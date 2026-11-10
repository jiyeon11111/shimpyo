"""관악구 2026 여름 대시보드 집계: 가상 라이더 1,000명 콜 기록 × 행정동 체감온도 모델 × 팀 확정안.

    python -m analysis.gwanak_summer        # 프로젝트 폴더에서. 2~3분 걸린다

입력 (data/gwanak, 모두 BOM 있는 CSV, 행정동코드는 문자열)
  - 가상라이더_관악_콜_2026.csv.gz   콜 한 건이 한 행. 용량이 커서 git에 안 올린다 (드라이브에서 받기)
  - 관악_동별체감온도_모델_2026.csv.gz
  - data/raw/dong_seoul.geojson      (있으면) 관악구 경계를 gwanak_dong.geojson으로 다시 뽑는다

출력 (git에 올리는 결과만)
  - dashboard_rests_2026.csv    적립 대상으로 판정된 쉼 한 건이 한 행 (지급액 0인 경우 포함)
  - dashboard_hot_2026.csv      날짜·시·동별 "32도 이상에서 일한 라이더 분" (못 쉰 위험 시간)
  - dashboard_summary_2026.json 여름 합계, 판정 이유별 건수, 동별·월별 합계

가정 (콜 기록에는 쉼 버튼 기록이 없다) — 팀 분석 4(김아현, team_scripts/run_final.py)와 같은 방식
  - 콜 로그는 "쉼표가 없을 때 평소처럼 일한 기록"이다. 쉬기 버튼을 누를 수 있는 순간은 배달을 마친 직후다.
  - 배달을 마칠 때마다, 자격(가장 오래 달린 동 모델 32도 이상 + 그 시간대 28일 중 12일 이상 일함)이 되고
    노출이 60분 이상이면 확률 P로 30분 쉰다고 본다. 쉬는 30분 동안은 다시 쉬지 않고, 쉰 뒤에는 그 뒤 이동만
    노출로 센다. 하루 최대 4번. 난수 seed=1, 순서는 라이더·날짜·시각 (팀 코드와 같다).
  - P 기본값은 0.5(기획서 "자격자의 절반이 쉼"). 1.0과 0.25 결과도 summary의 scenarios에 넣는다.
  - 금액 = min(평소 시간당 수입, 2만 원) × 30 ÷ 60 (engine.payout.settle_rest). 팀 분석은 2만 원 상한 없이 계산했다.
  - 노출·가장 오래 달린 동은 engine/rules.py, 일한 날·평소 수입은 engine/records.py 정의를 따른다.
  - 집계 기간은 2026-05-15~09-30. 그 전(04-18~05-14) 기록은 노동 확인과 평소 수입 계산에만 쓴다.
  - 못 쉰 위험 시간: 일한 구간(콜을 20분 이내 공백으로 이은 것)의 분을 시각(정시~정시)별로 나눠,
    그 1시간 동안 가장 오래 달린 동의 모델 체감온도가 32도 이상이면 센다.
"""
from __future__ import annotations

import json
import os
import sys
import time
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from backend import gwanak  # noqa: E402
from engine.payout import DAILY_PAID_RESTS, REST_PAY_CAP_MIN, REST_PAY_CAP_WON, settle_rest  # noqa: E402
from engine.records import Call, RiderBook  # noqa: E402
from engine.rules import (EXPOSURE_NEED_MIN, EXPOSURE_WINDOW_MIN, LABOR_NEED_DAYS, RESET_GAP_MIN, is_hot,  # noqa: E402
                          longest_dong, slot_label, slot_of)

D = gwanak.DIR
SEASON = (date(2026, 5, 15), date(2026, 9, 30))
REST_P = 0.5                       # 기본: 자격자의 절반이 쉼
SCENARIOS = (1.0, 0.5, 0.25)
SEED = 1
CALLS = os.path.join(D, "가상라이더_관악_콜_2026.csv.gz")
RAW_GEO = os.path.join(ROOT, "data", "raw", "dong_seoul.geojson")


def build_geo() -> None:
    """data/raw/dong_seoul.geojson에서 관악구(11620) 동만 좌표 5자리로 뽑는다."""
    if not os.path.exists(RAW_GEO):
        return
    with open(RAW_GEO, encoding="utf-8-sig") as f:
        g = json.load(f)

    def rnd(x):
        return [rnd(y) for y in x] if isinstance(x[0], list) else [round(x[0], 5), round(x[1], 5)]
    fs = [{"type": "Feature", "properties": {"code": f["properties"]["adm_cd2"], "name": f["properties"]["adm_nm"].split()[-1]},
           "geometry": {"type": f["geometry"]["type"], "coordinates": rnd(f["geometry"]["coordinates"])}}
          for f in g["features"] if f["properties"]["adm_cd2"].startswith("11620")]
    fs.sort(key=lambda f: f["properties"]["code"])
    with open(os.path.join(D, "gwanak_dong.geojson"), "w", encoding="utf-8") as f:
        json.dump({"type": "FeatureCollection", "features": fs}, f, ensure_ascii=False, separators=(",", ":"))


def in_season(d: date) -> bool:
    return SEASON[0] <= d <= SEASON[1]


def rider_season(book: RiderBook, rid: str, opps: list, hot: dict) -> None:
    """배달 완료 순간(쉼 기회)마다 판정 재료를 opps에 쌓고, 못 쉰 위험 시간을 hot에 더한다."""
    gap = timedelta(minutes=RESET_GAP_MIN)
    for day in sorted(book.by_day):
        if not in_season(day):
            continue
        cs = book.by_day[day]
        legs_all = book.legs_on(day)
        base = datetime.combine(day, datetime.min.time())
        mins = lambda t: (t - base).total_seconds() / 60  # noqa: E731
        sx = np.array([mins(leg[0]) for leg in legs_all]); ex = np.array([mins(leg[1]) for leg in legs_all])
        g = np.r_[np.inf, sx[1:] - ex[:-1]]                     # 앞 이동과의 공백
        cum = np.r_[0, np.cumsum(ex - sx)]                      # 누적 이동 분
        for j, c in enumerate(cs):
            mi = 2 * j + 1; at = ex[mi]
            seg0 = mi - int(np.argmax(g[mi::-1] > RESET_GAP_MIN))   # 20분 넘는 공백 뒤부터
            lo = at - EXPOSURE_WINDOW_MIN
            expo = float(np.clip(np.minimum(ex[seg0:mi + 1], at) - np.maximum(sx[seg0:mi + 1], lo), 0, None).sum())
            code = longest_dong(legs_all[:mi + 1], c.done)
            temp = gwanak.temp(code, c.done)
            opps.append((rid, day, at, c.done, expo, float(cum[mi + 1]), code, temp,
                         book.worked_days(c.done), book.usual_hourly(c.done)))
        # 못 쉰 위험 시간: 일한 구간(20분 이내 공백으로 이은 콜)을 시각별로 나눠 그 시각 가장 오래 달린 동이 32도 이상이면 센다
        s, e = cs[0].accept, cs[0].done
        for c in cs[1:] + [None]:
            if c is not None and c.accept - e <= gap:
                e = max(e, c.done)
                continue
            h = s.replace(minute=0, second=0, microsecond=0)
            while h < e:
                h1 = h + timedelta(hours=1)
                m = (min(e, h1) - max(s, h)).total_seconds() / 60
                if m > 0:
                    code = longest_dong([leg for leg in legs_all if leg[0] < h1], h1, 60)
                    t = gwanak.temp(code, h)
                    if t is not None and is_hot(t):
                        hot[(day.isoformat(), h.hour, code)] += m
                h = h1
            if c is not None:
                s, e = c.accept, c.done


def simulate(o: pd.DataFrame, p: float, seed: int = SEED) -> np.ndarray:
    """팀 run_final.simulate와 같은 규칙. 쉼 기회마다 확률 p로 30분 쉰다."""
    draws = np.random.default_rng(seed).random(len(o))
    elig = o["자격"].to_numpy()
    expo, cum, at = o["노출분"].to_numpy(), o["누적이동"].to_numpy(), o["분"].to_numpy()
    key = (o["라이더ID"] + o["날짜"].astype(str)).to_numpy()
    rest = np.zeros(len(o), bool); last = None
    for i in range(len(o)):
        if key[i] != last:
            last, reset, rend, n = key[i], None, -1e9, 0
        if not elig[i] or at[i] < rend or n >= DAILY_PAID_RESTS:
            continue
        e = expo[i] if reset is None else min(expo[i], cum[i] - reset)
        if e >= EXPOSURE_NEED_MIN and draws[i] < p:
            rest[i] = True; rend = at[i] + REST_PAY_CAP_MIN; reset = cum[i]; n += 1
    return rest


def rests_table(o: pd.DataFrame, rest: np.ndarray) -> pd.DataFrame:
    x = o[rest].copy()
    x["앞선지급"] = x.groupby(["라이더ID", "날짜"]).cumcount()
    rows = []
    for r in x.itertuples(index=False):
        s = r.완료
        res = settle_rest(s, s + timedelta(minutes=REST_PAY_CAP_MIN), True, int(r.평소시급), int(r.앞선지급))
        rows.append({"라이더ID": r.라이더ID, "날짜": r.날짜.isoformat(), "시작": s.strftime("%H:%M"),
                     "끝": (s + timedelta(minutes=REST_PAY_CAP_MIN)).strftime("%H:%M"), "판정동코드": r.동, "체감온도": round(r.체감온도, 2),
                     "시간대": slot_label(slot_of(s)), "평소시급": int(r.평소시급), "앞선지급": int(r.앞선지급),
                     "쉰분": res.rested_min, "지급분": res.paid_min, "지급액": res.amount,
                     "상한전지급액": round(r.평소시급 * REST_PAY_CAP_MIN / 60)})
    return pd.DataFrame(rows)


def scenario(r: pd.DataFrame, p: float) -> dict:
    """팀 결과표(최종_분석34_모델32)와 같은 칸 + 2만 원 상한을 건 금액."""
    per_day = r.groupby(["라이더ID", "날짜"]).size()
    return {"p": p, "rests": int(len(r)), "riders": int(r["라이더ID"].nunique()),
            "amount_uncapped": int(r["상한전지급액"].sum()), "amount": int(r["지급액"].sum()),
            "median_uncapped": float(r["상한전지급액"].median()), "p99_uncapped": float(np.percentile(r["상한전지급액"], 99)),
            "per_day": round(float(per_day.mean()), 3), "capped": int((r["상한전지급액"] > REST_PAY_CAP_WON).sum()),
            "zero_usual": int((r["평소시급"] == 0).sum())}


def _reason_key(r: str) -> str:
    for k in ("22시~6시", "평소 수입", "최근 4주", "체감온도", "달린 동", "배달 이동", "번을 다 받았어요"):
        if k in r:
            return k
    return r


def main() -> None:
    t0 = time.time()
    build_geo()
    calls = pd.read_csv(CALLS, encoding="utf-8-sig",
                        dtype={"라이더ID": str, "출발동코드": str, "음식점동코드": str, "고객동코드": str})
    for col in ("수락시각", "음식점도착", "픽업시각", "배달완료"):
        calls[col] = pd.to_datetime(calls[col])
    print(f"콜 {len(calls):,}건, 라이더 {calls['라이더ID'].nunique():,}명 ({time.time() - t0:.0f}초)")

    opps, hot = [], defaultdict(float)
    for i, (rid, g) in enumerate(calls.groupby("라이더ID", sort=True)):
        book = RiderBook([Call(a.to_pydatetime(), b.to_pydatetime(), p.to_pydatetime(), d.to_pydatetime(), x, y, z, int(f))
                          for a, b, p, d, x, y, z, f in zip(g["수락시각"], g["음식점도착"], g["픽업시각"], g["배달완료"],
                                                            g["출발동코드"], g["음식점동코드"], g["고객동코드"], g["배달료"])])
        rider_season(book, rid, opps, hot)
        if (i + 1) % 200 == 0:
            print(f"  라이더 {i + 1:,}명 ({time.time() - t0:.0f}초)")
    o = pd.DataFrame(opps, columns=["라이더ID", "날짜", "분", "완료", "노출분", "누적이동", "동", "체감온도", "활동일", "평소시급"])
    o = o.sort_values(["라이더ID", "날짜", "분"], kind="stable").reset_index(drop=True)
    o["자격"] = o["체감온도"].fillna(-99).map(is_hot) & (o["활동일"] >= LABOR_NEED_DAYS) & o["완료"].map(lambda t: slot_of(t) is not None)
    print(f"쉼 기회 {len(o):,}건, 자격 {int(o['자격'].sum()):,}건 ({time.time() - t0:.0f}초)")

    scen, r = {}, None
    for p in SCENARIOS:
        rp = rests_table(o, simulate(o, p))
        scen[str(p)] = scenario(rp, p)
        if p == REST_P:
            r = rp
    r.to_csv(os.path.join(D, "dashboard_rests_2026.csv"), index=False, encoding="utf-8-sig")
    h = pd.DataFrame([{"날짜": k[0], "시": k[1], "동코드": k[2], "더위근무분": round(v, 1)} for k, v in sorted(hot.items())])
    h.to_csv(os.path.join(D, "dashboard_hot_2026.csv"), index=False, encoding="utf-8-sig")
    reasons = Counter({"쉼 기회(배달 완료)": len(o), "자격": int(o["자격"].sum()),
                       "체감온도 32도 미만": int((~o["체감온도"].fillna(-99).map(is_hot)).sum()),
                       "일한 날 12일 미만": int((o["활동일"] < LABOR_NEED_DAYS).sum()),
                       "22시~6시": int((~o["완료"].map(lambda t: slot_of(t) is not None)).sum())})

    paid = r[r["지급액"] > 0]
    names = {c: gwanak.name(c) for c in gwanak.dongs()}
    by_dong = {c: {"name": names[c], "riders": int(g["라이더ID"].nunique()), "paid_hours": round(g["지급분"].sum() / 60, 1),
                   "amount": int(g["지급액"].sum())} for c, g in paid.groupby("판정동코드")}
    for c, g in h.groupby("동코드"):
        by_dong.setdefault(c, {"name": names[c], "riders": 0, "paid_hours": 0, "amount": 0})["missed_hours"] = round(g["더위근무분"].sum() / 60, 1)
    paid_m = paid.assign(m=paid["날짜"].str[:7])
    summary = {
        "season": [SEASON[0].isoformat(), SEASON[1].isoformat()],
        "riders": int(calls["라이더ID"].nunique()),
        "paid_riders": int(paid["라이더ID"].nunique()),
        "paid_rests": int(len(paid)),
        "paid_hours": round(paid["지급분"].sum() / 60, 1),
        "amount": int(paid["지급액"].sum()),
        "rest_p": REST_P,
        "capped_10000": int((r["상한전지급액"] > REST_PAY_CAP_WON).sum()),
        "scenarios": scen,
        "missed_hours": round(h["더위근무분"].sum() / 60, 1) if len(h) else 0,
        "opportunities": dict(reasons),
        "by_month": {m: {"riders": int(g["라이더ID"].nunique()), "paid_hours": round(g["지급분"].sum() / 60, 1),
                         "amount": int(g["지급액"].sum())} for m, g in paid_m.groupby("m")},
        "by_dong": dict(sorted(by_dong.items())),
    }
    with open(os.path.join(D, "dashboard_summary_2026.json"), "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=1)
    print(json.dumps({k: v for k, v in summary.items() if k not in ("by_dong", "by_month")}, ensure_ascii=False, indent=1))
    print(f"끝 ({time.time() - t0:.0f}초)")


if __name__ == "__main__":
    main()
