"""분석 공통 도구: 데이터 불러오기, 체감온도 계산, 그래프 설정.

열 이름이 원본과 다르면 COLUMNS만 고친다.
"""
from __future__ import annotations

import glob
import os
import sys

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from engine.heat import apparent_temp_array  # noqa: E402
from engine.rules import HEAT_MIN_C  # noqa: E402

RAW = os.path.join(ROOT, "data", "raw")
SAMPLE = os.path.join(ROOT, "data", "sample")
OUT = os.path.join(ROOT, "outputs")
os.makedirs(OUT, exist_ok=True)

# 원본 열 이름 → 분석에서 쓰는 이름
COLUMNS = {
    "asos": {"지점": "stn", "일시": "time", "기온(°C)": "ta", "습도(%)": "rh"},
    "stations": {"지점": "stn", "지점명": "name", "위도": "lat", "경도": "lon", "시도": "sido"},
    "warnings": {"시도": "sido", "종류": "kind", "시작": "start", "해제": "end"},
    "delivery": {"월": "month", "거래액": "sales"},
    "riders": {"시도": "sido", "라이더수": "riders"},
    "illness": {"날짜": "date", "시도": "sido", "환자수": "cases"},
    "sdot": {"센서": "sensor", "일시": "time", "기온": "ta", "습도": "rh", "위도": "lat", "경도": "lon", "구역": "zone"},
}

SUMMER = (5, 15, 9, 30)  # 온열질환 감시 기간과 같게: 5/15 ~ 9/30
USING_SAMPLE: set[str] = set()


def _read_csv(path: str) -> pd.DataFrame:
    for enc in ("utf-8-sig", "cp949", "euc-kr"):
        try:
            return pd.read_csv(path, encoding=enc)
        except UnicodeDecodeError:
            continue
    raise ValueError(f"인코딩을 알 수 없는 파일: {path}")


def load(kind: str, pattern: str) -> pd.DataFrame:
    """data/raw에서 찾고, 없으면 data/sample에서 불러온다."""
    files = sorted(glob.glob(os.path.join(RAW, pattern)))
    if not files:
        files = sorted(glob.glob(os.path.join(SAMPLE, pattern)))
        if files:
            USING_SAMPLE.add(kind)
    if not files:
        raise FileNotFoundError(f"{pattern} 파일이 data/raw에도 data/sample에도 없습니다.")
    df = pd.concat([_read_csv(f) for f in files], ignore_index=True)
    df = df.rename(columns=COLUMNS[kind])
    missing = set(COLUMNS[kind].values()) - set(df.columns)
    if missing:
        raise KeyError(f"{pattern}에 필요한 열이 없습니다: {missing}. common.py의 COLUMNS를 확인하세요.")
    return df


def in_summer(ts: pd.Series) -> pd.Series:
    m, d = ts.dt.month, ts.dt.day
    start = (m > SUMMER[0]) | ((m == SUMMER[0]) & (d >= SUMMER[1]))
    end = (m < SUMMER[2]) | ((m == SUMMER[2]) & (d <= SUMMER[3]))
    return start & end


def asos_hourly() -> pd.DataFrame:
    """ASOS 시간자료 + 체감온도 + 시도. 여름 감시 기간만."""
    df = load("asos", "asos_hourly_*.csv")
    df["time"] = pd.to_datetime(df["time"])
    df = df[in_summer(df["time"])].dropna(subset=["ta", "rh"]).copy()
    df["rh"] = df["rh"].clip(0, 100)
    df["at"] = apparent_temp_array(df["ta"], df["rh"])
    st = load("stations", "asos_stations.csv")[["stn", "sido"]]
    return df.merge(st, on="stn", how="left")


def hot_hours(df: pd.DataFrame) -> pd.Series:
    """시간 자료 한 줄마다 체감온도 기준(33도 이상, engine.rules.is_hot과 같음)을 넘었는지 표시.

    지급 가능한 시간의 상한일 뿐이다. 실제 지급은 라이더의 자격(평소 근무)·노출(배달 이동 N분)·
    쉼(20분 이상)을 함께 봐야 하므로 기상 자료만으로는 지급 시간을 셀 수 없다.
    """
    return pd.Series(df["at"].to_numpy() >= HEAT_MIN_C, index=df.index)


def title(text: str, kinds: list[str]) -> str:
    return text + ("  [가상 데이터]" if USING_SAMPLE.intersection(kinds) else "")


def setup_plot():
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib import font_manager
    for name in ("Malgun Gothic", "AppleGothic", "NanumGothic", "Noto Sans CJK KR", "Noto Sans KR"):
        if any(name in f.name for f in font_manager.fontManager.ttflist):
            plt.rcParams["font.family"] = name
            break
    plt.rcParams["axes.unicode_minus"] = False
    plt.rcParams["axes.spines.top"] = False
    plt.rcParams["axes.spines.right"] = False
    return plt


HEAT = {"31": "#f6e7b0", "33": "#f2c14e", "35": "#ec8a2f", "38": "#d4442a"}
INK = "#1d2530"
