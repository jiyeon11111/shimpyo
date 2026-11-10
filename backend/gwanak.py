"""관악구 팀 데이터 읽기 (기본 라이브러리만). 시연 모드의 체감온도·지도·대시보드가 여기서 온다.

  data/gwanak/관악_동별체감온도_모델_2026.csv.gz  행정동 체감온도 모델(정현). 21개 동 × 1시간, 2026-05-15~09-30
                                                  "H시" 값 = H-1시~H시 평균
  data/gwanak/가상라이더_관악_동정보.csv          21개 동 이름·중심 좌표
  data/gwanak/gwanak_dong.geojson                 관악구 행정동 경계 (data/raw/dong_seoul.geojson에서 11620만)
  data/gwanak/demo_rider_calls.csv                앱 시연 라이더(민수)의 콜 기록 (가상라이더 콜 파일에서 한 명)
  data/gwanak/dashboard_*.csv, .json              대시보드 집계 결과 (python -m analysis.gwanak_summer)

모든 CSV는 BOM이 있어 utf-8-sig로 읽고, 행정동코드는 문자열로 다룬다.
"""
from __future__ import annotations

import csv
import gzip
import json
import math
import os
from datetime import date, datetime, timedelta
from functools import lru_cache

from . import config

DIR = os.path.join(config.ROOT, "data", "gwanak")
MODEL_FILE = os.path.join(DIR, "관악_동별체감온도_모델_2026.csv.gz")
GU = "관악구"


def _csv(name: str) -> list[dict]:
    path = os.path.join(DIR, name)
    opener = gzip.open if name.endswith(".gz") else open
    with opener(path, "rt", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


@lru_cache(maxsize=1)
def dongs() -> dict[str, dict]:
    """동 코드 → {name, lat, lon}."""
    return {r["동코드"]: {"name": r["동"], "lat": float(r["위도"]), "lon": float(r["경도"])}
            for r in _csv("가상라이더_관악_동정보.csv")}


def name(code: str | None) -> str | None:
    d = dongs().get(code or "")
    return d["name"] if d else None


@lru_cache(maxsize=1)
def geo() -> dict:
    with open(os.path.join(DIR, "gwanak_dong.geojson"), encoding="utf-8-sig") as f:
        return json.load(f)


def has_model() -> bool:
    return os.path.exists(MODEL_FILE)


@lru_cache(maxsize=1)
def _model() -> dict[str, dict[str, float]]:
    out: dict[str, dict[str, float]] = {}
    for r in _csv(os.path.basename(MODEL_FILE)):
        out.setdefault(r["행정동코드"], {})[r["시각"][:13]] = float(r["체감온도"])
    return out


def key(t: datetime) -> str:
    """분 t가 속한 1시간 값의 키. 'H시' 값이 H-1시~H시 평균이라 t를 내림한 정시 + 1시간."""
    return (t.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)).strftime("%Y-%m-%d %H")


def temp(code: str | None, t: datetime) -> float | None:
    """동의 t 시점 모델 체감온도. 동이 없거나 모델 기간 밖이면 None."""
    if not code:
        return None
    v = _model().get(code, {}).get(key(t))
    return None if v is None else round(v, 1)


def hourly(code: str, day: date, hours=range(6, 22)) -> dict[int, float]:
    """막대 그래프용: h시~h+1시 값 (모델의 'h+1시')."""
    out = {}
    for h in hours:
        v = temp(code, datetime(day.year, day.month, day.day, h, 30))
        if v is not None:
            out[h] = v
    return out


def _inside(lon: float, lat: float, ring: list) -> bool:
    hit = False
    for (x1, y1), (x2, y2) in zip(ring, ring[1:] + ring[:1]):
        if (y1 > lat) != (y2 > lat) and lon < (x2 - x1) * (lat - y1) / (y2 - y1) + x1:
            hit = not hit
    return hit


def locate(lat: float, lon: float) -> str | None:
    """위치가 속한 관악구 동 코드. 경계 밖이면 1.5km 안의 가장 가까운 동 중심, 그것도 없으면 None."""
    for f in geo()["features"]:
        g = f["geometry"]
        polys = g["coordinates"] if g["type"] == "MultiPolygon" else [g["coordinates"]]
        for poly in polys:
            if _inside(lon, lat, poly[0]) and not any(_inside(lon, lat, hole) for hole in poly[1:]):
                return f["properties"]["code"]
    best = min(dongs().items(), key=lambda kv: (kv[1]["lat"] - lat) ** 2 + ((kv[1]["lon"] - lon) * math.cos(math.radians(lat))) ** 2)
    d = best[1]
    km = math.hypot(d["lat"] - lat, (d["lon"] - lon) * math.cos(math.radians(lat))) * 111
    return best[0] if km <= 1.5 else None
