"""격자별 시간 체감온도.

시연 모드: data/demo/weather_<날짜>.json (가상 값)을 쓴다. 주변 격자는 기준 격자에서
           정해진 편차를 더해 만든다. 발표장에서 인터넷이 없어도 동작한다.
실제 모드: 기상청 단기예보 조회서비스(getVilageFcst)에서 TMP(기온), REH(습도)를 받아
           기상청 공식 체감온도 산출식(engine.heat)으로 계산한다. 결과는 30분 캐시.
"""
from __future__ import annotations

import json
import math
import os
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta

from engine.heat import apparent_temp_summer

from . import config

KMA_URL = "https://apis.data.go.kr/1360000/VilageFcstInfoService_2.0/getVilageFcst"
BASE_TIMES = ["0200", "0500", "0800", "1100", "1400", "1700", "2000", "2300"]
_cache: dict = {}


class WeatherError(RuntimeError):
    pass


# ----------------------------- 시연 모드 -----------------------------
def _demo_file(day: str) -> dict:
    path = os.path.join(config.DEMO_DIR, f"weather_{day}.json")
    if not os.path.exists(path):
        raise WeatherError(f"시연 기상 파일이 없습니다: {path}")
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _demo_offset(nx: int, ny: int, center: tuple[int, int]) -> float:
    """기준 격자에서 멀어질수록 조금씩 시원해지는 가상 편차 (도)."""
    d = math.hypot(nx - center[0], ny - center[1])
    return round(1.3 - 0.62 * d + 0.4 * math.sin(nx * 1.7 + ny * 0.9), 2)


def _demo_hourly(nx: int, ny: int, day: str) -> dict[int, float]:
    w = _demo_file(day)
    off = _demo_offset(nx, ny, tuple(w["center"]))
    return {int(h): apparent_temp_summer(ta, rh) + off for h, (ta, rh) in w["hours"].items()}


# ----------------------------- 기상청 API -----------------------------
def _base(dt: datetime) -> tuple[str, str]:
    """dt 기준 가장 최근 단기예보 발표 시각 (발표 10분 뒤부터 조회 가능)."""
    t = dt - timedelta(minutes=10)
    hhmm = t.strftime("%H%M")
    past = [b for b in BASE_TIMES if b <= hhmm]
    if past:
        return t.strftime("%Y%m%d"), past[-1]
    return (t - timedelta(days=1)).strftime("%Y%m%d"), "2300"


def _kma_hourly(nx: int, ny: int, dt: datetime) -> dict[int, float]:
    if not config.KMA_KEY:
        raise WeatherError("KMA_SERVICE_KEY가 설정되지 않았습니다.")
    base_date, base_time = _base(dt)
    key = (nx, ny, base_date, base_time)
    hit = _cache.get(key)
    if hit and time.time() - hit[0] < 1800:
        return hit[1]
    q = urllib.parse.urlencode({"serviceKey": config.KMA_KEY, "pageNo": 1, "numOfRows": 1000, "dataType": "JSON",
                                "base_date": base_date, "base_time": base_time, "nx": nx, "ny": ny})
    try:
        with urllib.request.urlopen(f"{KMA_URL}?{q}", timeout=8) as r:
            body = json.load(r)
        items = body["response"]["body"]["items"]["item"]
    except Exception as e:  # 네트워크, 키 오류, 응답 형식 오류
        raise WeatherError(f"기상청 API 호출 실패: {e}") from e
    ta, rh = {}, {}
    today = dt.strftime("%Y%m%d")
    for it in items:
        if it["fcstDate"] != today:
            continue
        h = int(it["fcstTime"][:2])
        if it["category"] == "TMP":
            ta[h] = float(it["fcstValue"])
        elif it["category"] == "REH":
            rh[h] = float(it["fcstValue"])
    out = {h: apparent_temp_summer(ta[h], rh[h]) for h in ta if h in rh}
    if not out:
        raise WeatherError("기상청 응답에 오늘 기온·습도 예보가 없습니다.")
    _cache[key] = (time.time(), out)
    return out


# ----------------------------- 공통 -----------------------------
def hourly(nx: int, ny: int, dt: datetime) -> dict[int, float]:
    if config.DEMO_MODE:
        return _demo_hourly(nx, ny, dt.strftime("%Y-%m-%d"))
    return _kma_hourly(nx, ny, dt)


def temp_fn(nx: int, ny: int, day: datetime):
    """시각 → 체감온도. 시간값 사이는 선형 보간."""
    hrs = hourly(nx, ny, day)
    keys = sorted(hrs)

    def at(t: datetime) -> float:
        x = t.hour + t.minute / 60
        if x <= keys[0]:
            return hrs[keys[0]]
        if x >= keys[-1]:
            return hrs[keys[-1]]
        lo = max(k for k in keys if k <= x)
        hi = min(k for k in keys if k > x)
        return hrs[lo] + (hrs[hi] - hrs[lo]) * (x - lo) / (hi - lo)
    return at
