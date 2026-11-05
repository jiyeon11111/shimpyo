"""앱의 실제 동작. FastAPI(main.py)와 기본 서버(serve_stdlib.py)가 똑같이 이 함수들을 부른다.

모든 함수는 JSON으로 바꿀 수 있는 dict를 돌려준다. 오류는 ServiceError(메시지, 상태코드).
"""
from __future__ import annotations

import math
import random
from datetime import datetime, timedelta

from engine.grid import locate
from engine.payout import DAILY_PAID_RESTS, REST_MIN, REST_PAY_CAP_MIN, settle_rest
from engine.rules import EXPOSURE_NEED_MIN, HEAT_MIN_C, is_hot, judge_start

from . import config, db, riders, shelters, weather

NO_RECORD = "배달 플랫폼 운행 기록과 아직 연결되지 않아 적립 여부를 판정할 수 없어요"


class ServiceError(Exception):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


def _stage(t: float) -> dict:
    for lo, name, key in ((38, "매우 위험", "38"), (35, "위험", "35"), (33, "주의", "33"), (31, "관심", "31")):
        if t >= lo:
            return {"name": name, "key": key}
    return {"name": "보통", "key": "0"}


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
            "pay_cap_min": REST_PAY_CAP_MIN, "daily_rests": DAILY_PAID_RESTS}


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


def _judge(rider_id: int, temp: float, t: datetime) -> dict:
    """지금 쉬기 시작하면 지급 대상인지. 운행 기록이 없으면(실제 모드) 판정하지 않는다."""
    with db.conn() as c:
        p = riders.profile(rider_id, t, _rests_today(c, rider_id, t))
    if p is None:
        return {"pay_now": False, "reasons": [NO_RECORD], "exposure_min": None, "usual_hourly": None,
                "worked_slot": None, "alert": None, "has_record": False}
    d = judge_start(temp, p["worked_slot"], p["moves"], t)
    return {"pay_now": d.pay_eligible, "reasons": list(d.reasons), "exposure_min": d.exposure_min,
            "usual_hourly": p["usual_hourly"], "worked_slot": p["worked_slot"], "alert": d.alert, "has_record": True}


def now_status(lat: float, lon: float, at: str | None = None, rider_id: int = 1) -> dict:
    """홈: 지금 이 위치 격자의 체감온도, 단계, 지금 쉬면 적립되는지와 안 되는 이유."""
    t = config.now(at)
    cell = locate(lat, lon)
    f = _temp_fn(cell.nx, cell.ny, t)
    temp = round(f(t), 1)
    j = _judge(rider_id, temp, t)
    hourly = {int(h): round(v, 1) for h, v in weather.hourly(cell.nx, cell.ny, t).items()}
    near = shelters.nearest(lat, lon, None, 1)["items"]
    shelter = None
    if near:
        s0 = near[0]
        shelter = {"name": s0["name"], "kind": s0["kind"], "walk_min": s0["walk_min"], "distance_m": s0["distance_m"],
                   "inside": s0["distance_m"] <= shelters.VERIFY_RADIUS_M}
    return {"time": _fmt(t), "grid": [cell.nx, cell.ny], "place": " ".join(x for x in (cell.sgg, cell.emd) if x) or ("마포구 서교동" if config.DEMO_MODE else "현재 위치"),
            "temp": temp, "stage": _stage(temp), "hot": is_hot(temp), **j,
            "exposure_need_min": EXPOSURE_NEED_MIN, "hourly": hourly,
            "hours": [{"h": h, "temp": v, "hot": is_hot(v)} for h, v in sorted(hourly.items())],
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
    cell = locate(lat, lon)
    verified = 1 if (place == "shelter" and shelters.near_shelter(lat, lon)) or config.DEMO_MODE else 0
    with db.conn() as c:
        if _open_rest(c, rider_id):
            raise ServiceError("이미 쉬는 중입니다. 먼저 쉼을 종료하세요.", 409)
    # 판정은 쉼을 시작한 순간, 시작한 격자 기준. 근거를 기록에 남긴다.
    temp = round(_temp_fn(cell.nx, cell.ny, t)(t), 1)
    j = _judge(rider_id, temp, t)
    with db.conn() as c:
        cur = c.execute("""INSERT INTO rests (rider_id, start, place, verified, nx, ny, sido, sgg, emd,
                           eligible, reason, temp, exposure_min, usual_hourly) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                        (rider_id, _fmt(t), place, verified, cell.nx, cell.ny, cell.sido, cell.sgg, cell.emd,
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
def _virtual_riders(center, n=300, seed=7):
    rnd = random.Random(seed)
    out = []
    for _ in range(n):
        out.append({"nx": center[0] + rnd.randint(-3, 3), "ny": center[1] + rnd.randint(-3, 3), "join": rnd.random() < 0.62,
                    "st": 840 + rnd.randint(0, 99), "du": 10 + rnd.randint(0, 50), "usual": rnd.randint(12, 22) * 1000})
    return out


def report(lat: float, lon: float, at: str | None = None) -> dict:
    """지자체·보험사 화면: 주변 7×7 격자 위험도, 쉬는 라이더, 보전 시간, 쉬지 못한 위험 시간.

    시연 모드에서는 가상 라이더 300명의 하루를 함께 계산한다 (virtual=true).
    가상 라이더는 자격(평소 근무)과 노출(배달 이동 N분)을 채웠다고 가정하고, 쉼 조건(20분 이상,
    한 번에 30분치)과 시작 격자의 33도 기준만 적용한다.
    실제 모드에서는 DB의 실제 쉼 기록만 집계한다.
    """
    t = config.now(at)
    me = locate(lat, lon)
    grid, fns = [], {}
    for dy in range(-3, 4):
        for dx in range(-3, 4):
            nx, ny = me.nx + dx, me.ny - dy
            fns[(nx, ny)] = _temp_fn(nx, ny, t)
            grid.append({"nx": nx, "ny": ny, "temp": round(fns[(nx, ny)](t), 1), "me": dx == 0 and dy == 0})
    resting = paid = missed = amount = 0
    day0 = t.replace(hour=0, minute=0)
    mm = t.hour * 60 + t.minute
    if config.DEMO_MODE:
        # 33도 여부는 격자·분마다 한 번만 계산한다 (라이더 300명이 같은 49칸을 나눠 쓴다)
        minutes = range(840, min(mm, 1200))
        hot = {k: {m for m in minutes if is_hot(f(day0 + timedelta(minutes=m)))} for k, f in fns.items()}
        for r in _virtual_riders((me.nx, me.ny)):
            hot_here = hot[(r["nx"], r["ny"])]
            rest = range(r["st"], r["st"] + r["du"]) if r["join"] else range(0)
            missed += sum(1 for m in hot_here if m not in rest)
            done = min(r["du"], mm - r["st"])            # 지금까지 쉰 분
            if r["join"] and done >= REST_MIN and r["st"] in hot_here:
                p = min(done, REST_PAY_CAP_MIN)
                paid += p
                amount += round(p / 60 * r["usual"])
            resting += r["join"] and r["st"] <= mm < r["st"] + r["du"]
    with db.conn() as c:
        rows = c.execute("SELECT * FROM rests WHERE substr(start,1,10)=? AND virtual=0", (t.strftime("%Y-%m-%d"),)).fetchall()
    for row in rows:
        if row["end"]:
            paid += row["paid_min"] or 0
            amount += row["amount"] or 0
        else:
            resting += 1
    return {"time": _fmt(t), "grid": grid, "resting": resting, "paid_hours": round(paid / 60, 1),
            "missed_hours": round(missed / 60), "amount": amount,
            "virtual": config.DEMO_MODE, "virtual_riders": 300 if config.DEMO_MODE else 0}


def demo_reset() -> dict:
    """시연 모드에서 오늘(시연 날짜) 실제로 눌러 만든 쉼 기록을 지운다. 가상 기록은 남긴다."""
    if not config.DEMO_MODE:
        raise ServiceError("시연 모드에서만 쓸 수 있습니다.", 403)
    with db.conn() as c:
        n = c.execute("DELETE FROM rests WHERE virtual=0 AND substr(start,1,10)=?", (config.DEMO_DATE,)).rowcount
    return {"deleted": n}
