"""위경도 → 기상청 단기예보 격자(nx, ny).

1순위: 기상청 활용가이드에 들어있는 격자 좌표표(data/raw/kma_grid.csv)에서 가장 가까운 읍면동을 찾는다.
       읍면동 이름까지 함께 나오므로 집계·정산(행정구역)에 그대로 쓸 수 있다.
2순위: 표가 없으면 기상청이 공개한 람베르트 정각원추도법 변환식으로 계산한다.
       (지도 투영 상수는 활용가이드 부록과 같은 값. tests에서 서울·부산·제주 격자로 검증)

격자표 열 이름: 1단계(시도), 2단계(시군구), 3단계(읍면동), 격자 X, 격자 Y, 위도(초/100), 경도(초/100)
활용가이드 엑셀을 CSV로 저장하면 이 열 이름 그대로다. 다르면 TABLE_COLUMNS만 고친다.
"""
from __future__ import annotations

import csv
import math
import os
from dataclasses import dataclass
from functools import lru_cache

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TABLE = os.path.join(ROOT, "data", "raw", "kma_grid.csv")
TABLE_COLUMNS = {"sido": "1단계", "sgg": "2단계", "emd": "3단계", "nx": "격자 X", "ny": "격자 Y",
                 "lat": "위도(초/100)", "lon": "경도(초/100)"}

# 기상청 단기예보 격자 상수
RE, GRID = 6371.00877, 5.0
SLAT1, SLAT2, OLON, OLAT = 30.0, 60.0, 126.0, 38.0
XO, YO = 43, 136


@dataclass(frozen=True)
class Cell:
    nx: int
    ny: int
    sido: str = ""
    sgg: str = ""
    emd: str = ""


def latlon_to_grid(lat: float, lon: float) -> tuple[int, int]:
    """기상청 변환식. 위도·경도(도) → (nx, ny)."""
    d = math.pi / 180.0
    re = RE / GRID
    s1, s2, olon, olat = SLAT1 * d, SLAT2 * d, OLON * d, OLAT * d
    sn = math.log(math.cos(s1) / math.cos(s2)) / math.log(math.tan(math.pi * 0.25 + s2 * 0.5) / math.tan(math.pi * 0.25 + s1 * 0.5))
    sf = math.tan(math.pi * 0.25 + s1 * 0.5) ** sn * math.cos(s1) / sn
    ro = re * sf / math.tan(math.pi * 0.25 + olat * 0.5) ** sn
    ra = re * sf / math.tan(math.pi * 0.25 + lat * d * 0.5) ** sn
    theta = lon * d - olon
    theta = (theta + math.pi) % (2 * math.pi) - math.pi
    theta *= sn
    return int(ra * math.sin(theta) + XO + 0.5), int(ro - ra * math.cos(theta) + YO + 0.5)


@lru_cache(maxsize=1)
def _table() -> list[dict]:
    if not os.path.exists(TABLE):
        return []
    for enc in ("utf-8-sig", "cp949"):
        try:
            with open(TABLE, encoding=enc) as f:
                rows = list(csv.DictReader(f))
            break
        except UnicodeDecodeError:
            continue
    c = TABLE_COLUMNS
    out = []
    for r in rows:
        if not r.get(c["emd"]):
            continue  # 시도·시군구 대표 행은 건너뛴다
        out.append({"nx": int(r[c["nx"]]), "ny": int(r[c["ny"]]), "lat": float(r[c["lat"]]), "lon": float(r[c["lon"]]),
                    "sido": r[c["sido"]], "sgg": r[c["sgg"]], "emd": r[c["emd"]]})
    return out


def locate(lat: float, lon: float) -> Cell:
    """위치의 격자와 (표가 있으면) 읍면동."""
    rows = _table()
    if rows:
        best = min(rows, key=lambda r: (r["lat"] - lat) ** 2 + ((r["lon"] - lon) * math.cos(math.radians(lat))) ** 2)
        return Cell(best["nx"], best["ny"], best["sido"], best["sgg"], best["emd"])
    nx, ny = latlon_to_grid(lat, lon)
    return Cell(nx, ny)
