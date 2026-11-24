"""앱의 실제 동작. FastAPI(main.py)와 기본 서버(serve_stdlib.py)가 똑같이 이 함수들을 부른다.

모든 함수는 JSON으로 바꿀 수 있는 dict를 돌려준다. 오류는 ServiceError(메시지, 상태코드).
"""
from __future__ import annotations

import csv
import json
import os
import random
from collections import defaultdict
from datetime import datetime, timedelta
from functools import lru_cache

from engine.grid import locate
from engine.payout import (DAILY_PAID_RESTS, DEFAULT_STAGE, NEED_SETTLEMENT, REST_MIN, REST_PAY_CAP_MIN, REST_PAY_CAP_WON,
                           STAGE_NAMES, STAGES, pay_hourly, settle_rest)
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
            "labor_need_days": LABOR_NEED_DAYS, "labor_window_days": LABOR_WINDOW_DAYS, "slots": [list(x) for x in SLOTS],
            "stages": [{"stage": s, "name": STAGE_NAMES[s], "pays": s != "A"} for s in STAGES],
            "real_shelters": not shelters.is_virtual()}


# ----------------------------- 데이터 연동 단계 -----------------------------
SETTLE_NAMES = {"pending": "대조 대기", "verified": "확인 완료", "mismatch": "불일치"}


def _rider_row(c, rider_id: int):
    row = c.execute("SELECT * FROM riders WHERE id=?", (rider_id,)).fetchone()
    if not row:
        raise ServiceError("없는 라이더입니다.", 404)
    return row


def _link(row, usual_hourly: int | None = None) -> dict:
    """라이더의 연동 단계와 지급 기준. usual_hourly를 주면 지금 적용될 시급도 함께."""
    stage = row["stage"] or DEFAULT_STAGE
    hourly, basis = pay_hourly(stage, usual_hourly or 0)
    return {"stage": stage, "name": STAGE_NAMES[stage], "basis": basis, "pay_hourly": hourly, "pays": stage != "A",
            "rider_name": row["name"], "consent": bool(row["consent_at"]), "consent_at": row["consent_at"],
            "settle_status": row["settle_status"], "settle_file": row["settle_file"],
            "settle_name": SETTLE_NAMES.get(row["settle_status"] or ""), "can_upload": stage == "A"}


def rider_info(rider_id: int = 1) -> dict:
    with db.conn() as c:
        return _link(_rider_row(c, rider_id))


def consent(rider_id: int = 1, at: str | None = None) -> dict:
    """위치 사용 동의를 기록한다. 좌표는 저장하지 않고 쉼 기록에 격자와 행정동만 남긴다."""
    t = config.now(at)
    with db.conn() as c:
        _rider_row(c, rider_id)
        c.execute("UPDATE riders SET consent_at=COALESCE(consent_at, ?) WHERE id=?", (_fmt(t), rider_id))
        return _link(_rider_row(c, rider_id))


def settlement_upload(rider_id: int = 1, filename: str | None = None, at: str | None = None) -> dict:
    """정산 내역을 등록한다(가입할 때 한 번). A단계 → B단계가 되어 그때부터 평소 수입 기준으로 지급한다. '대조 대기'로 남긴다.

    MVP는 파일 이름만 기록한다. 이미지 판독과 GPS 기록 대조는 하지 않는다(월 1회 사후 대조를 가정).
    """
    t = config.now(at)
    name = (filename or "").strip()[:120]
    if not name:
        raise ServiceError("정산 내역 파일을 골라 주세요.")
    with db.conn() as c:
        row = _rider_row(c, rider_id)
        if (row["stage"] or DEFAULT_STAGE) != "A":
            raise ServiceError("정산 내역이 이미 등록돼 있어요.", 409)
        c.execute("UPDATE riders SET stage='B', settle_status='pending', settle_at=?, settle_file=? WHERE id=?", (_fmt(t), name, rider_id))
        return _link(_rider_row(c, rider_id))


def settlement_summary(rider_id: int = 1, at: str | None = None) -> dict:
    """등록한 정산 내역에서 읽은 평소 시간당 수입: 오늘 요일의 시간대별 값 (최근 4주 같은 요일·같은 1시간 평균).

    시연 모드는 가상 라이더 콜 기록으로 만든 가상 정산 내역이다. 실제 모드는 판독을 구현하지 않아 빈 목록을 준다.
    """
    t = config.now(at)
    with db.conn() as c:
        row = _rider_row(c, rider_id)
    hours = []
    if config.DEMO_MODE:
        book = riders.demo_book()
        for h in range(SLOTS[0][0], SLOTS[-1][1]):
            hours.append({"h": h, "usual_hourly": book.usual_hourly(t.replace(hour=h, minute=0))})
    now_usual = next((x["usual_hourly"] for x in hours if x["h"] == t.hour), 0)
    return {"registered": (row["stage"] or DEFAULT_STAGE) != "A", "file": row["settle_file"], "status": row["settle_status"],
            "status_name": SETTLE_NAMES.get(row["settle_status"] or ""), "weekday": t.weekday(), "hour": t.hour,
            "hours": hours, "usual_hourly": now_usual, "per_rest": min(round(now_usual * REST_PAY_CAP_MIN / 60), REST_PAY_CAP_WON),
            "weeks": 4, "virtual": config.DEMO_MODE}


def demo_stage(rider_id: int = 1, stage: str = DEFAULT_STAGE) -> dict:
    """시연 모드: 연동 단계를 바로 바꾼다. A로 돌리면 정산 내역 기록도 지운다."""
    if not config.DEMO_MODE:
        raise ServiceError("시연 모드에서만 쓸 수 있습니다.", 403)
    if stage not in STAGES:
        raise ServiceError("stage는 A, B, C 중 하나입니다.")
    with db.conn() as c:
        _rider_row(c, rider_id)
        if _open_rest(c, rider_id):
            raise ServiceError("쉬는 중에는 단계를 바꿀 수 없어요. 먼저 쉼을 끝내세요.", 409)
        status = {"A": None, "B": "verified", "C": None}[stage]
        c.execute("UPDATE riders SET stage=?, settle_status=?, settle_at=CASE WHEN ?='A' THEN NULL ELSE settle_at END, "
                  "settle_file=CASE WHEN ?='A' THEN NULL ELSE settle_file END WHERE id=?", (stage, status, stage, stage, rider_id))
        return _link(_rider_row(c, rider_id))


@lru_cache(maxsize=1)
def _virtual_stages() -> dict:
    """가상 라이더의 연동 단계와 B단계 정산 내역 대조 상태. 고정 시드라 늘 같다. 지어낸 값이다.

    가상 라이더는 모두 지급 대상이라 정산 내역 등록(B) 70%, 플랫폼 연동(C) 30%로 나눈다. B와 C는 금액 기준이 같다.
    """
    path = os.path.join(gwanak.DIR, "가상라이더_관악_라이더.csv")
    if not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8-sig", newline="") as f:
        ids = sorted(r["라이더ID"] for r in csv.DictReader(f))
    rng, out = random.Random(1), {}
    for rid in ids:
        x, y = rng.random(), rng.random()
        stage = "B" if x < 0.7 else "C"
        out[rid] = (stage, ("verified" if y < 0.85 else "pending" if y < 0.97 else "mismatch") if stage == "B" else None)
    return out


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
    with db.conn() as c:
        link = _link(_rider_row(c, rider_id), j["usual_hourly"])
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
            "shelter": shelter, "virtual_weather": config.DEMO_MODE, "virtual_rider": j["has_record"] and config.DEMO_MODE,
            "link": link}


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
        # 지급 기준은 쉼을 시작할 때의 연동 단계로 정해 기록한다 (쉬는 중 단계가 바뀌어도 이번 쉼은 그대로).
        stage = _rider_row(c, rider_id)["stage"] or DEFAULT_STAGE
        hourly, basis = pay_hourly(stage, j["usual_hourly"] or 0)
        mock = j["pay_now"]                      # 조건만 본 판정 (A단계에서는 모의 판정)
        if basis == "none":                      # 정산 내역 등록 전: 기록만 남기고 돈은 주지 않는다
            j["reasons"] = ([NEED_SETTLEMENT] if j["pay_now"] else []) + j["reasons"]
            j["pay_now"] = False
        cur = c.execute("""INSERT INTO rests (rider_id, start, place, verified, nx, ny, sido, sgg, emd,
                           eligible, reason, temp, exposure_min, usual_hourly, stage, basis, pay_hourly)
                           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                        (rider_id, _fmt(t), place, verified, cell.nx, cell.ny, sido, sgg, emd,
                         int(j["pay_now"]), j["reasons"][0] if j["reasons"] else None, temp, j["exposure_min"], j["usual_hourly"],
                         stage, basis, hourly))
        rid = cur.lastrowid
    return {"rest_id": rid, "start": _fmt(t), "grid": [cell.nx, cell.ny], "place": place, "verified": bool(verified),
            "eligible": j["pay_now"], "reasons": j["reasons"], "stage": stage, "basis": basis, "pay_hourly": hourly,
            "mock_eligible": mock}


def _settle(c, row, t: datetime):
    start = datetime.fromisoformat(row["start"])
    return settle_rest(start, t, bool(row["eligible"]), _row_hourly(row),
                       _paid_rests_before(c, row["rider_id"], start), row["reason"])


def _row_hourly(row) -> int:
    """쉼 기록에 적용할 시급. 단계 기록이 없는 예전 기록은 평소 시간당 수입."""
    return (row["pay_hourly"] if row["pay_hourly"] is not None else row["usual_hourly"]) or 0


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
            "eligible": bool(row["eligible"]), "reason": r.reason, "usual_hourly": row["usual_hourly"] or 0,
            "stage": row["stage"], "basis": row["basis"] or "usual", "pay_hourly": _row_hourly(row)}


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
            "amount": r.amount, "reason": r.reason, "stage": row["stage"], "basis": row["basis"] or "usual", "pay_hourly": _row_hourly(row)}


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
    # 여름 합계를 연동 단계별로 나눈다 (B·C 모두 집계 파일의 지급액, 평소 수입 기준)
    vs, staged = _virtual_stages(), {s: {"rests": 0, "amount": 0} for s in STAGES}
    for rows in rests.values():
        for r in rows:
            st = vs.get(r["라이더ID"], ("C", None))[0]
            staged[st]["rests"] += 1
            staged[st]["amount"] += int(r["지급액"])
    return {"rests": rests, "hot": hot, "summary": summary, "staged": staged}


def dong_geo() -> dict:
    """지도용 관악구 행정동 경계와 중심 좌표."""
    ds = gwanak.dongs()
    return {"gu": gwanak.GU, "features": [
        {"code": f["properties"]["code"], "name": f["properties"]["name"], "geometry": f["geometry"],
         "center": [ds[f["properties"]["code"]]["lon"], ds[f["properties"]["code"]]["lat"]] if f["properties"]["code"] in ds else None}
        for f in gwanak.geo()["features"]]}


def report(lat: float, lon: float, at: str | None = None) -> dict:
    """지자체·보험사 화면: 관악구 21개 동 체감온도 지도, 지금 쉬는 라이더, 오늘 보전 시간·지급 예정, 폭염 속 운행 시간.

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

    dash = _dash() if config.DEMO_MODE else {"rests": {}, "hot": {}, "summary": None, "staged": None}
    vs = _virtual_stages() if config.DEMO_MODE else {}
    by_stage = {s: {"stage": s, "name": STAGE_NAMES[s], "basis": pay_hourly(s, 0)[1], "riders": 0, "paid_riders": set(),
                    "rests": 0, "paid_min": 0, "amount": 0} for s in STAGES}
    verify = {"pending": 0, "verified": 0, "mismatch": 0}
    for rid, (st, status) in vs.items():
        if rid == riders.DEMO_RIDER_CODE:
            continue   # 앱에서 직접 누르는 라이더는 아래에서 DB 값으로 센다
        by_stage[st]["riders"] += 1
        if status:
            verify[status] += 1

    def add_stage(st, who, paid_min, amount):
        b = by_stage.get(st or "C")
        if b is None or paid_min <= 0:
            return
        b["paid_riders"].add(who)
        b["rests"] += 1
        b["paid_min"] += paid_min
        b["amount"] += amount

    for r in dash["rests"].get(day, []):
        if r["라이더ID"] == riders.DEMO_RIDER_CODE:
            continue   # 앱에서 직접 누르는 라이더
        s_ = int(r["시작"][:2]) * 60 + int(r["시작"][3:])
        e_ = int(r["끝"][:2]) * 60 + int(r["끝"][3:])
        if s_ > mm:
            continue
        start = t.replace(hour=s_ // 60, minute=s_ % 60)
        st = vs.get(r["라이더ID"], ("C", None))[0]
        res = settle_rest(start, start + timedelta(minutes=min(e_, mm) - s_), True, pay_hourly(st, int(r["평소시급"]))[0], int(r["앞선지급"]))
        add(r["판정동코드"], int(s_ <= mm < e_), res.paid_min, res.amount)
        add_stage(st, r["라이더ID"], res.paid_min, res.amount)
    for r in dash["hot"].get(day, []):
        h = int(r["시"])
        frac = 1.0 if (h + 1) * 60 <= mm else max(0.0, (mm - h * 60) / 60)
        if r["동코드"] in per:
            per[r["동코드"]]["missed_min"] += float(r["더위근무분"]) * frac

    with db.conn() as c:
        rows = c.execute("SELECT * FROM rests WHERE substr(start,1,10)=? AND virtual=0", (day,)).fetchall()
        for rd in c.execute("SELECT * FROM riders").fetchall():
            by_stage[rd["stage"] or DEFAULT_STAGE]["riders"] += 1
            if rd["settle_status"] in verify:
                verify[rd["settle_status"]] += 1
    for row in rows:
        if row["end"]:
            add_stage(row["stage"], f"app-{row['rider_id']}", row["paid_min"] or 0, row["amount"] or 0)
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
            "virtual": config.DEMO_MODE, "virtual_riders": (dash["summary"] or {}).get("riders", 0) if config.DEMO_MODE else 0,
            "stages": [{**{k: v for k, v in b.items() if k not in ("paid_riders", "paid_min")}, "paid_riders": len(b["paid_riders"]),
                        "paid_hours": round(b["paid_min"] / 60, 1),
                        "season": (dash.get("staged") or {}).get(b["stage"])} for b in by_stage.values()],
            "verify": verify}


def demo_reset() -> dict:
    """시연 모드에서 오늘(시연 날짜) 실제로 눌러 만든 쉼 기록을 지운다. 가상 기록은 남긴다."""
    if not config.DEMO_MODE:
        raise ServiceError("시연 모드에서만 쓸 수 있습니다.", 403)
    with db.conn() as c:
        n = c.execute("DELETE FROM rests WHERE virtual=0 AND substr(start,1,10)=?", (config.DEMO_DATE,)).rowcount
    return {"deleted": n}
