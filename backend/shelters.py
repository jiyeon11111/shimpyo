"""쉼터 목록과 가까운 쉼터 찾기.

실제 파일: data/raw/shelters.csv (행정안전부 무더위쉼터 + 지자체 이동노동자 쉼터를 합친 것)
없으면 data/demo/shelters_sample.csv (가상 예시)를 쓴다. 열 이름이 다르면 COLUMNS만 고친다.
"""
from __future__ import annotations

import csv
import math
import os
from functools import lru_cache

from . import config

COLUMNS = {"name": "쉼터명", "kind": "구분", "addr": "주소", "lat": "위도", "lon": "경도", "hours": "운영시간", "note": "비고"}
WALK_M_PER_MIN = 75          # 걷는 속도 (분당 75m)
VERIFY_RADIUS_M = 150        # 이 거리 안에서 쉼을 시작하면 쉼터 휴식으로 바로 인정


def haversine_m(lat1, lon1, lat2, lon2) -> float:
    r = 6_371_000
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


@lru_cache(maxsize=1)
def _load() -> tuple[list[dict], bool]:
    real = os.path.join(config.RAW_DIR, "shelters.csv")
    path, virtual = (real, False) if os.path.exists(real) else (os.path.join(config.DEMO_DIR, "shelters_sample.csv"), True)
    for enc in ("utf-8-sig", "cp949"):
        try:
            with open(path, encoding=enc) as f:
                rows = list(csv.DictReader(f))
            break
        except UnicodeDecodeError:
            continue
    c = COLUMNS
    out = [{"name": r[c["name"]], "kind": r.get(c["kind"], "무더위쉼터"), "addr": r.get(c["addr"], ""),
            "lat": float(r[c["lat"]]), "lon": float(r[c["lon"]]), "hours": r.get(c["hours"], ""), "note": r.get(c["note"], "")}
           for r in rows if r.get(c["lat"]) and r.get(c["lon"])]
    for s in out:
        s["rider"] = is_rider_shelter(s["name"], s["kind"])
    return out, virtual


def is_virtual() -> bool:
    """지금 쓰는 목록이 가상 예시인지. 실제 목록(data/raw/shelters.csv)이 있으면 False."""
    return _load()[1]


def is_rider_shelter(name: str, kind: str) -> bool:
    """이동노동자(라이더) 쉼터인지. 구분 값이 파일마다 달라서(가상: '라이더 쉼터', 서울노동포털: '서울시 거점형'·'자치구' 등)
    이름과 구분을 함께 본다. 무더위쉼터(주민센터, 경로당 등)는 해당하지 않는다."""
    text = f"{name} {kind}"
    return "라이더" in text or "노동자" in text


@lru_cache(maxsize=1)
def count_by_dong() -> dict[str, int]:
    """행정동 코드 → 그 동 안의 쉼터 수. 지자체 화면에서 운행 시간이 많은 동에 쉼터가 몇 곳인지 보여줄 때 쓴다."""
    from . import gwanak
    out: dict[str, int] = {}
    for s in _load()[0]:
        code = gwanak.inside(s["lat"], s["lon"])
        if code:
            out[code] = out.get(code, 0) + 1
    return out


def nearest(lat: float, lon: float, kind: str | None = None, limit: int = 10) -> dict:
    rows, virtual = _load()
    items = []
    for s in rows:
        if kind == "rider" and not s["rider"]:
            continue
        d = haversine_m(lat, lon, s["lat"], s["lon"])
        items.append({**s, "distance_m": round(d), "walk_min": max(1, round(d / WALK_M_PER_MIN))})
    items.sort(key=lambda x: x["distance_m"])
    return {"virtual": virtual, "items": items[:limit]}


def near_shelter(lat: float, lon: float) -> bool:
    rows, _ = _load()
    return any(haversine_m(lat, lon, s["lat"], s["lon"]) <= VERIFY_RADIUS_M for s in rows)
