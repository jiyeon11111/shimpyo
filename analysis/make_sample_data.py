"""실제 데이터가 오기 전에 전체 분석을 돌려보기 위한 가상 데이터 생성.

data/sample/에 data/README.md와 같은 형식으로 만든다. 값은 모두 가짜다.
실제 파일을 data/raw/에 넣으면 분석 코드는 자동으로 그쪽을 쓴다.
"""
import os

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "data", "sample")
os.makedirs(OUT, exist_ok=True)
rng = np.random.default_rng(42)

STATIONS = pd.DataFrame([
    (108, "서울", 37.57, 126.97, "서울", 0.6), (112, "인천", 37.48, 126.62, "인천", -0.4),
    (119, "수원", 37.27, 126.99, "경기", 0.4), (133, "대전", 36.37, 127.37, "대전", 0.5),
    (143, "대구", 35.88, 128.65, "대구", 1.4), (156, "광주", 35.17, 126.89, "광주", 1.0),
    (159, "부산", 35.10, 129.03, "부산", -0.2), (184, "제주", 33.51, 126.53, "제주", 0.0),
], columns=["지점", "지점명", "위도", "경도", "시도", "warm"])
STATIONS.drop(columns="warm").to_csv(os.path.join(OUT, "asos_stations.csv"), index=False, encoding="utf-8-sig")

YEARS = range(2016, 2027)
daily_rows, hourly_frames = [], []
for y in YEARS:
    days = pd.date_range(f"{y}-05-15", f"{y}-09-30", freq="D")
    doy = (days.dayofyear.to_numpy() - 135) / 138          # 0..1 over the season
    season = 21.5 + 8.5 * np.sin(np.pi * np.clip(doy * 1.05, 0, 1))
    # 더위 덩어리(폭염 기간) 몇 개
    wave = np.zeros(len(days))
    for _ in range(rng.integers(2, 5)):
        c, w, h = rng.integers(40, 100), rng.integers(4, 14), rng.uniform(2, 4.5)
        wave += h * np.exp(-0.5 * ((np.arange(len(days)) - c) / (w / 2)) ** 2)
    for _, s in STATIONS.iterrows():
        tmax = season + wave + s.warm + 0.08 * (y - 2016) + rng.normal(0, 1.2, len(days))
        rh_day = np.clip(72 - 0.9 * (tmax - 28) + rng.normal(0, 6, len(days)), 35, 95)
        hours = np.arange(24)
        diurnal = np.sin(np.pi * (hours - 6) / 18).clip(-0.3, 1)   # 15시 근처 최고
        ta = (tmax[:, None] - 7) + 7 * diurnal[None, :] + rng.normal(0, 0.4, (len(days), 24))
        rh = np.clip(rh_day[:, None] + 12 * (1 - diurnal[None, :]) + rng.normal(0, 3, (len(days), 24)), 20, 100)
        times = (days.to_numpy()[:, None] + pd.to_timedelta(hours, "h").to_numpy()[None, :]).ravel()
        hourly_frames.append(pd.DataFrame({"지점": s.지점, "지점명": s.지점명, "일시": pd.to_datetime(times).strftime("%Y-%m-%d %H:%M"),
                                           "기온(°C)": ta.ravel().round(1), "습도(%)": rh.ravel().round(0)}))
hourly = pd.concat(hourly_frames)
for y in YEARS:
    hourly[hourly["일시"].str.startswith(str(y))].to_csv(os.path.join(OUT, f"asos_hourly_{y}.csv"), index=False, encoding="utf-8-sig")

# 일 최고 체감온도(대략)로 온열질환, 특보 만들기
import sys  # noqa: E402
sys.path.insert(0, ROOT)
from engine.heat import apparent_temp_array  # noqa: E402

h = hourly.copy()
h["time"] = pd.to_datetime(h["일시"])
h["at"] = apparent_temp_array(h["기온(°C)"], h["습도(%)"])
h = h.merge(STATIONS[["지점", "시도"]], on="지점")
d = h.groupby(["시도", h["time"].dt.date])["at"].max().rename("atmax").reset_index().rename(columns={"time": "date"})
pop = {"서울": 9.4, "인천": 3.0, "경기": 13.6, "대전": 1.4, "대구": 2.4, "광주": 1.4, "부산": 3.3, "제주": 0.7}
lam = np.array([pop[s] for s in d["시도"]]) * 0.25 * np.exp(0.55 * np.clip(d["atmax"] - 32, -4, 8))
d["cases"] = rng.poisson(lam)
d.rename(columns={"date": "날짜", "시도": "시도", "cases": "환자수"})[["날짜", "시도", "환자수"]].to_csv(
    os.path.join(OUT, "heat_illness_daily.csv"), index=False, encoding="utf-8-sig")

warn = []
for sido, g in d.groupby("시도"):
    g = g.sort_values("date").reset_index(drop=True)
    for i in range(1, len(g)):
        a, b = g.loc[i - 1, "atmax"], g.loc[i, "atmax"]
        kind = "중대경보" if a >= 38 and b >= 38 else "경보" if a >= 35 and b >= 35 else "주의보" if a >= 33 and b >= 33 else None
        if kind:
            day = pd.Timestamp(g.loc[i, "date"])
            start = day + pd.Timedelta(hours=int(rng.integers(10, 15)))  # 오후에 발효되는 날도 섞음
            warn.append((sido, kind, start.strftime("%Y-%m-%d %H:%M"), (day + pd.Timedelta(hours=21)).strftime("%Y-%m-%d %H:%M")))
pd.DataFrame(warn, columns=["시도", "종류", "시작", "해제"]).to_csv(os.path.join(OUT, "heat_warnings.csv"), index=False, encoding="utf-8-sig")

# 배달 거래액 (월별, 2017-01 ~ 2026-09)
months = pd.period_range("2017-01", "2026-09", freq="M")
nat = h[h["시도"] == "서울"].groupby(h["time"].dt.to_period("M"))["at"].apply(lambda x: (x.groupby(x.index // 24).max() >= 33).sum() if len(x) else 0)
heatdays = np.array([nat.get(m, 0) for m in months])
t = np.arange(len(months))
sales = 600_000 * np.exp(0.016 * t - 0.004 * np.clip(t - 50, 0, None)) * (1 + 0.06 * np.sin(2 * np.pi * (months.month - 3) / 12)) * (1 + 0.004 * heatdays) * rng.normal(1, 0.02, len(months))
pd.DataFrame({"월": months.astype(str), "거래액": sales.round(0)}).to_csv(os.path.join(OUT, "food_delivery_monthly.csv"), index=False, encoding="utf-8-sig")

# 라이더 수 (시도별)
pd.DataFrame({"시도": list(pop), "라이더수": [int(p * 9000) for p in pop.values()]}).to_csv(
    os.path.join(OUT, "riders_by_region.csv"), index=False, encoding="utf-8-sig")

# S-DoT (서울 2026 여름, 도로 3대 + 공원 3대)
seoul = h[(h["시도"] == "서울") & (h["time"].dt.year == 2026)][["time", "기온(°C)", "습도(%)"]]
rows = []
for k, (zone, bump) in enumerate([("도로", 2.6), ("도로", 3.1), ("도로", 2.2), ("공원", -0.6), ("공원", -0.9), ("주거", 0.7)]):
    hr = seoul["time"].dt.hour
    sun = np.sin(np.pi * (hr - 6) / 14).clip(0, 1)
    ta = seoul["기온(°C)"] + bump * (0.3 + 0.7 * sun) + rng.normal(0, 0.5, len(seoul))
    rows.append(pd.DataFrame({"센서": f"S{k+1:02d}", "일시": seoul["time"].dt.strftime("%Y-%m-%d %H:%M"), "기온": ta.round(1),
                              "습도": (seoul["습도(%)"] - bump).clip(20, 100).round(0), "위도": 37.55 + k * 0.01, "경도": 126.92 + k * 0.01, "구역": zone}))
pd.concat(rows).to_csv(os.path.join(OUT, "sdot_hourly.csv"), index=False, encoding="utf-8-sig")
print("가상 데이터 생성 완료:", OUT)
