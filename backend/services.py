"""앱의 실제 동작. FastAPI(main.py)와 기본 서버(serve_stdlib.py)가 똑같이 이 함수들을 부른다.

모든 함수는 JSON으로 바꿀 수 있는 dict를 돌려준다. 오류는 ServiceError(메시지, 상태코드).
"""
from __future__ import annotations

import csv
import json
import os
from collections import defaultdict
from datetime import datetime, timedelta
from functools import lru_cache

from engine.grid import locate
from engine.payout import DAILY_PAID_RESTS, REST_MIN, REST_PAY_CAP_MIN, REST_PAY_CAP_WON, settle_rest
from engine.rules import (EXPOSURE_NEED_MIN, HEAT_MIN_C, LABOR_NEED_DAYS, LABOR_WINDOW_DAYS, SLOTS, is_hot,
                          judge_start, longest_dong)

from . import config, db, gwanak, riders, shelters, weather

NO_RECORD = "배달 플랫폼 운행 기록과 아직 연결되지 않아 적립 여부를 판정할 수 없어요"


class ServiceError(Exception):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


def _stage(t: float) -> dict:
    for lo, name, key in ((38, "매우 위험", "38"), (35, "위험", "35"), (32, "주의", "32"), (31, "관심", "31")):
        if t >= lo:
            return {"name": name, "key": key}
    return {"name": "보통", "key": "0"}


def _r1(v: float | None) -> float | None:
    """화면에 보여줄 체감온도: 소수 첫째 자리. 판정에는 쓰지 않는다 (판정은 반올림 전 값)."""
    return None if v is None else round(v, 1)


def _fmt(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M")


def _temp_fn(nx, ny, dt):
    try:
        return weather.temp_fn(nx, ny, dt)
    except weather.WeatherError as e:
        raise ServiceError(str(e), 503) from e


def app_config() -> dict:
    return {"demo": config.DEMO_MODE, "demo_date": config.DEMO_DATE, "demo_start": config.DEMO_START,
            "demo_lat": config.DEMO_LAT, "demo_lon": config.DEMO_LON,
            "heat_min": HEAT_MIN_C, "exposure_need_min": EXPOSURE_NEED_MIN, "rest_min": REST_MIN,
            "pay_cap_min": REST_PAY_CAP_MIN, "pay_cap_won": REST_PAY_CAP_WON, "daily_rests": DAILY_PAID_RESTS,
            "labor_need_days": LABOR_NEED_DAYS, "labor_window_days": LABOR_WINDOW_DAYS, "slots": [list(x) for x in SLOTS]}


def _rests_today(c, rider_id: int, t: datetime) -> list[tuple[datetime, datetime]]:
    """오늘 쉼 구간 (진행 중이면 끝을 t로). 가상 이동 구간에서 쉰 시간을 빼는 데 쓴다."""
    rows = c.execute("SELECT start, end FROM rests WHERE rider_id=? AND virtual=0 AND substr(start,1,10)=?",
                     (rider_id, t.strftime("%Y-%m-%d"))).fetchall()
    out = []
    for r in rows:
        s = datetime.fromisoformat(r["start"])
        if s <= t:
            out.append((s, min(datetime.fromisoformat(r["end"]), t) if r["end"] else t))
    return out


def _judge(rider_id: int, t: datetime) -> dict:
    """지금 쉬기 시작하면 지급 대상인지. 운행 기록이 없으면(실제 모드) 판정하지 않는다.

    판정 온도는 쉼 시작 전 1시간 동안 가장 오래 달린 행정동의 모델 체감온도다.
    """
    with db.conn() as c:
        p = riders.profile(rider_id, t, _rests_today(c, rider_id, t))
    if p is None:
        return {"pay_now": False, "reasons": [NO_RECORD], "exposure_min": None, "usual_hourly": None,
                "worked_days": None, "judge_dong": None, "judge_temp": None, "alert": None, "has_record": False}
    code = longest_dong(p["legs"], t)
    temp = gwanak.temp(code, t)
    d = judge_start(temp, p["worked_days"], p["moves"], t)
    return {"pay_now": d.pay_eligible, "reasons": list(d.reasons), "exposure_min": d.exposure_min,
            "usual_hourly": p["usual_hourly"], "worked_days": p["worked_days"],
            "judge_dong": {"code": code, "name": gwanak.name(code)} if code else None, "judge_temp": _r1(temp),
            "judge_temp_raw": temp, "alert": d.alert, "has_record": True}


def _place(lat: float, lon: float):
    """위치 표시와 집계용 행정구역. 시연 모드는 관악구 동 경계로, 실제 모드는 기상청 격자 표로."""
    cell = locate(lat, lon)
    code = gwanak.locate(lat, lon) if config.DEMO_MODE else None
    if code:
        return cell, code, "서울특별시", gwanak.GU, gwanak.name(code)
    return cell, None, cell.sido, cell.sgg, cell.emd


def now_status(lat: float, lon: float, at: str | None = None, rider_id: int = 1) -> dict:
    """홈: 판정 체감온도, 단계, 지금 쉬면 적립되는지와 안 되는 이유.

    시연 모드: 체감온도는 행정동 모델 값. 가장 오래 달린 동이 있으면 그 동, 없으면 지금 있는 동.
    실제 모드: 모델이 없어(2026 여름만) 이 위치 기상청 격자 예보로 보여준다.
    """
    t = config.now(at)
    cell, code, _, sgg, emd = _place(lat, lon)
    j = _judge(rider_id, t)
    temp_code = (j["judge_dong"] or {}).get("code") or code
    # temp·hourly는 반올림 전 값. 단계·hot 판정은 이 값으로 하고, 내보낼 때만 반올림한다.
    if config.DEMO_MODE and gwanak.temp(temp_code, t) is not None:
        temp = gwanak.temp(temp_code, t)
        hourly = gwanak.hourly(temp_code, t.date())
    else:
        temp = _temp_fn(cell.nx, cell.ny, t)(t)
        hourly = {int(h): v for h, v in weather.hourly(cell.nx, cell.ny, t).items()}
    j.pop("judge_temp_raw")
    near = shelters.nearest(lat, lon, None, 1)["items"]
    shelter = None
    if near:
        s0 = near[0]
        shelter = {"name": s0["name"], "kind": s0["kind"], "walk_min": s0["walk_min"], "distance_m": s0["distance_m"],
                   "inside": s0["distance_m"] <= shelters.VERIFY_RADIUS_M}
    return {"time": _fmt(t), "grid": [cell.nx, cell.ny], "place": " ".join(x for x in (sgg, emd) if x) or "현재 위치",
            "dong": code, "temp_dong": gwanak.name(temp_code) if temp_code else None, "temp": _r1(temp), "stage": _stage(temp), "hot": is_hot(temp), **j,
            "exposure_need_min": EXPOSURE_NEED_MIN, "hourly": {h: _r1(v) for h, v in hourly.items()},
            "hours": [{"h": h, "temp": _r1(v), "hot": is_hot(v)} for h, v in sorted(hourly.items())],
            "shelter": shelter, "virtual_weather": config.DEMO_MODE, "virtual_rider": j["has_record"] and config.DEMO_MODE}


def _paid_rests_before(c, rider_id: int, t: datetime) -> int:
    """오늘 이미 돈을 받은 쉼 횟수 (하루 4번 상한용)."""
    return c.execute("SELECT COUNT(*) FROM rests WHERE rider_id=? AND end IS NOT NULL AND paid_min>0 AND substr(start,1,10)=?",
                     (rider_id, t.strftime("%Y-%m-%d"))).fetchone()[0]


def _open_rest(c, rider_id):
    return c.execute("SELECT * FROM rests WHERE rider_id=? AND end IS NULL ORDER BY id DESC LIMIT 1", (rider_id,)).fetchone()


def rest_start(rider_id: int, lat: float, lon: float, place: str, at: str | None = None) -> dict:
    if place not in ("shelter", "street", "auto"):
        raise ServiceError("place는 shelter, street, auto 중 하나입니다.")
    if place == "auto":   # 앱 기본값: 쉼터 150m 안이면 쉼터, 아니면 그 밖의 곳
        place = "shelter" if shelters.near_shelter(lat, lon) else "street"
    t = config.now(at)
    cell, _, sido, sgg, emd = _place(lat, lon)
    verified = 1 if (place == "shelter" and shelters.near_shelter(lat, lon)) or config.DEMO_MODE else 0
    with db.conn() as c:
        if _open_rest(c, rider_id):
            raise ServiceError("이미 쉬는 중입니다. 먼저 쉼을 종료하세요.", 409)
    # 판정은 쉼을 시작한 순간 기준: 직전 1시간 가장 오래 달린 동의 모델 체감온도. 근거를 기록에 남긴다.
    j = _judge(rider_id, t)
    temp = j.pop("judge_temp_raw")   # 근거 기록은 판정에 쓴 원래 값
    with db.conn() as c:
        cur = c.execute("""INSERT INTO rests (rider_id, start, place, verified, nx, ny, sido, sgg, emd,
                           eligible, reason, temp, exposure_min, usual_hourly) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                        (rider_id, _fmt(t), place, verified, cell.nx, cell.ny, sido, sgg, emd,
                         int(j["pay_now"]), j["reasons"][0] if j["reasons"] else None, temp, j["exposure_min"], j["usual_hourly"]))
        rid = cur.lastrowid
    return {"rest_id": rid, "start": _fmt(t), "grid": [cell.nx, cell.ny], "place": place, "verified": bool(verified),
            "eligible": j["pay_now"], "reasons": j["reasons"]}


def _settle(c, row, t: datetime):
    start = datetime.fromisoformat(row["start"])
    return settle_rest(start, t, bool(row["eligible"]), row["usual_hourly"] or 0,
                       _paid_rests_before(c, row["rider_id"], start), row["reason"])


def rest_current(rider_id: int, at: str | None = None) -> dict:
    """쉬는 중이면 지금까지의 잠정 보전."""
    t = config.now(at)
    with db.conn() as c:
        row = _open_rest(c, rider_id)
        if not row:
            return {"resting": False}
        r = _settle(c, row, t)
    return {"resting": True, "rest_id": row["id"], "start": row["start"], "place": row["place"], "verified": bool(row["verified"]),
            "rested_min": r.rested_min, "paid_min": r.paid_min, "amount": r.amount,
            "eligible": bool(row["eligible"]), "reason": r.reason, "usual_hourly": row["usual_hourly"] or 0}


def rest_stop(rider_id: int, at: str | None = None) -> dict:
    t = config.now(at)
    with db.conn() as c:
        row = _open_rest(c, rider_id)
        if not row:
            raise ServiceError("쉬는 중이 아닙니다.", 409)
        if t <= datetime.fromisoformat(row["start"]):
            raise ServiceError("종료 시각이 시작 시각보다 빠릅니다.")
        r = _settle(c, row, t)
        c.execute("UPDATE rests SET end=?, rested_min=?, paid_min=?, amount=? WHERE id=?", (_fmt(t), r.rested_min, r.paid_min, r.amount, row["id"]))
    return {"rest_id": row["id"], "start": row["start"], "end": _fmt(t), "rested_min": r.rested_min, "paid_min": r.paid_min,
            "amount": r.amount, "reason": r.reason}


def history(rider_id: int, at: str | None = None) -> dict:
    """내역: 오늘 쉼 기록, 이번 달 합계, 오늘 남은 횟수, 최근 7일 쉰 날."""
    t = config.now(at)
    day, month = t.strftime("%Y-%m-%d"), t.strftime("%Y-%m")
    week_days = [(t - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(6, -1, -1)]
    with db.conn() as c:
        rows = [dict(r) for r in c.execute(
            "SELECT * FROM rests WHERE rider_id=? AND end IS NOT NULL AND (substr(start,1,7)=? OR substr(start,1,10)>=?) ORDER BY start DESC",
            (rider_id, month, week_days[0]))]
    in_month = [r for r in rows if r["start"][:7] == month]
    today = [r for r in rows if r["start"][:10] == day]
    rested_days = {r["start"][:10] for r in rows if r["paid_min"]}
    paid_rests = sum(1 for r in today if r["paid_min"])
    return {"today": today,
            "month": {"count": len(in_month), "paid_min": sum(r["paid_min"] for r in in_month), "amount": sum(r["amount"] for r in in_month)},
            "today_paid_rests": paid_rests, "today_left_rests": max(0, DAILY_PAID_RESTS - paid_rests),
            "today_amount": sum(r["amount"] for r in today),
            "week": [{"date": d, "rested": d in rested_days, "today": d == day} for d in week_days],
            "has_virtual": any(r["virtual"] for r in rows)}


def shelter_list(lat: float, lon: float, kind: str | None = None) -> dict:
    return shelters.nearest(lat, lon, kind)


# ----------------------------- 리포트 -----------------------------
@lru_cache(maxsize=1)
def _dash() -> dict:
    """대시보드 집계 결과 (python -m analysis.gwanak_summer 가 만든 파일). 날짜별로 묶어 둔다."""
    rests, hot = defaultdict(list), defaultdict(list)
    for name, out in (("dashboard_rests_2026.csv", rests), ("dashboard_hot_2026.csv", hot)):
        path = os.path.join(gwanak.DIR, name)
        if os.path.exists(path):
            with open(path, encoding="utf-8-sig", newline="") as f:
                for r in csv.DictReader(f):
                    out[r["날짜"]].append(r)
    path = os.path.join(gwanak.DIR, "dashboard_summary_2026.json")
    summary = json.load(open(path, encoding="utf-8-sig")) if os.path.exists(path) else None
    return {"rests": rests, "hot": hot, "summary": summary}


def dong_geo() -> dict:
    """지도용 관악구 행정동 경계와 중심 좌표."""
    ds = gwanak.dongs()
    return {"gu": gwanak.GU, "features": [
        {"code": f["properties"]["code"], "name": f["properties"]["name"], "geometry": f["geometry"],
         "center": [ds[f["properties"]["code"]]["lon"], ds[f["properties"]["code"]]["lat"]] if f["properties"]["code"] in ds else None}
        for f in gwanak.geo()["features"]]}


def report(lat: float, lon: float, at: str | None = None) -> dict:
    """지자체·보험사 화면: 관악구 21개 동 체감온도 지도, 지금 쉬는 라이더, 오늘 보전 시간·지급 예정, 못 쉰 위험 시간.

    시연 모드: 가상 라이더 1,000명의 2026 여름 콜 기록에 팀 분석 4와 같은 쉼 가정(조건이 될 때 절반이 30분 쉼)을 얹어 판정·정산한 결과
    (data/gwanak/dashboard_*.csv)에서 그날 그 시각까지를 센다. 앱에서 민수로 직접 누르는 라이더(R0297)는
    그날 기록에서 빼고 DB의 실제 쉼 기록으로 더한다. 여름 합계(5/15~9/30)도 함께 준다.
    실제 모드: DB의 실제 쉼 기록만 집계한다. 체감온도는 동 중심의 기상청 격자 예보다.
    """
    t = config.now(at)
    me = gwanak.locate(lat, lon)
    day, mm = t.strftime("%Y-%m-%d"), t.hour * 60 + t.minute
    per = {c: {"code": c, "name": d["name"], "resting": 0, "paid_min": 0, "amount": 0, "missed_min": 0.0, "me": c == me}
           for c, d in gwanak.dongs().items()}
    for c, d in gwanak.dongs().items():
        v = gwanak.temp(c, t) if config.DEMO_MODE else None
        if v is None and not config.DEMO_MODE:
            cell = locate(d["lat"], d["lon"])
            v = _temp_fn(cell.nx, cell.ny, t)(t)
        per[c]["temp"] = v   # 반올림 전. hot·stage를 정한 뒤 내보낼 때 반올림한다

    def add(code, resting, paid_min, amount):
        x = per.get(code)
        if x is None:
            return
        x["resting"] += resting
        x["paid_min"] += paid_min
        x["amount"] += amount

    dash = _dash() if config.DEMO_MODE else {"rests": {}, "hot": {}, "summary": None}
    for r in dash["rests"].get(day, []):
        if r["라이더ID"] == riders.DEMO_RIDER_CODE:
            continue   # 앱에서 직접 누르는 라이더
        s_ = int(r["시작"][:2]) * 60 + int(r["시작"][3:])
        e_ = int(r["끝"][:2]) * 60 + int(r["끝"][3:])
        if s_ > mm:
            continue
        start = t.replace(hour=s_ // 60, minute=s_ % 60)
        res = settle_rest(start, start + timedelta(minutes=min(e_, mm) - s_), True, int(r["평소시급"]), int(r["앞선지급"]))
        add(r["판정동코드"], int(s_ <= mm < e_), res.paid_min, res.amount)
    for r in dash["hot"].get(day, []):
        h = int(r["시"])
        frac = 1.0 if (h + 1) * 60 <= mm else max(0.0, (mm - h * 60) / 60)
        if r["동코드"] in per:
            per[r["동코드"]]["missed_min"] += float(r["더위근무분"]) * frac

    with db.conn() as c:
        rows = c.execute("SELECT * FROM rests WHERE substr(start,1,10)=? AND virtual=0", (day,)).fetchall()
    codes = {d["name"]: k for k, d in gwanak.dongs().items()}
    out = {"resting": 0, "paid_min": 0, "amount": 0}     # 관악구 밖 실제 쉼 기록 (지도에는 없고 합계에만)
    for row in rows:
        r3 = (0, row["paid_min"] or 0, row["amount"] or 0) if row["end"] else (1, 0, 0)
        if (row["emd"] or "") in codes and row["sgg"] == gwanak.GU:
            add(codes[row["emd"]], *r3)
        else:
            out = {"resting": out["resting"] + r3[0], "paid_min": out["paid_min"] + r3[1], "amount": out["amount"] + r3[2]}

    dongs = sorted(per.values(), key=lambda x: x["code"])
    total_paid_min = sum(x["paid_min"] for x in dongs) + out["paid_min"]
    for x in dongs:
        x["paid_hours"], x["missed_hours"] = round(x.pop("paid_min") / 60, 1), round(x.pop("missed_min") / 60, 1)
        x["stage"] = _stage(x["temp"])["name"] if x["temp"] is not None else None
        x["hot"] = x["temp"] is not None and is_hot(x["temp"])
        x["temp"] = _r1(x["temp"])
    return {"time": _fmt(t), "me": me, "dongs": dongs, "heat_min": HEAT_MIN_C,
            "resting": sum(x["resting"] for x in dongs) + out["resting"],
            "paid_hours": round(total_paid_min / 60, 1),
            "amount": sum(x["amount"] for x in dongs) + out["amount"],
            "missed_hours": round(sum(x["missed_hours"] for x in dongs)),
            "season": dash["summary"] and {k: dash["summary"][k] for k in
                                          ("season", "riders", "paid_riders", "paid_rests", "paid_hours", "amount", "missed_hours", "rest_p", "scenarios")},
            "virtual": config.DEMO_MODE, "virtual_riders": (dash["summary"] or {}).get("riders", 0) if config.DEMO_MODE else 0}


def demo_reset() -> dict:
    """시연 모드에서 오늘(시연 날짜) 실제로 눌러 만든 쉼 기록을 지운다. 가상 기록은 남긴다."""
    if not config.DEMO_MODE:
        raise ServiceError("시연 모드에서만 쓸 수 있습니다.", 403)
    with db.conn() as c:
        n = c.execute("DELETE FROM rests WHERE virtual=0 AND substr(start,1,10)=?", (config.DEMO_DATE,)).rowcount
    return {"deleted": n}
