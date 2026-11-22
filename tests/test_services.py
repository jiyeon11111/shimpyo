"""백엔드 로직 테스트 (시연 모드, 임시 DB, 가상 라이더 민수).

민수는 가상라이더_관악 콜 파일의 전업 라이더 R0297이다(가상). 2026-08-03(월)에는 10:31에 첫 콜을 받는다.
그래서 11시에는 최근 2시간 이동이 60분에 못 미치고, 14시에는 넘는다. 7시대(06~09시)에는 일한 적이 없다.
쉼이 20분을 넘으면 노출 누적이 0으로 돌아간다.

연동 단계: svc는 C단계(플랫폼 연동, 평소 수입 기준)로 맞춰 둔다. 가입 직후 기본값인 A단계(정액)는 svc_a로 따로 본다.
"""
import os
import tempfile

import pytest


@pytest.fixture()
def svc(monkeypatch):
    from backend import config, db, services
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False).name
    monkeypatch.setattr(config, "DB_PATH", tmp)
    monkeypatch.setattr(config, "DEMO_MODE", True)
    db.init()
    services.demo_stage(1, "C")
    yield services
    os.remove(tmp)


@pytest.fixture()
def svc_a(monkeypatch):
    """가입 직후 그대로: A단계(앱 단독, 정액)."""
    from backend import config, db, services
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False).name
    monkeypatch.setattr(config, "DB_PATH", tmp)
    monkeypatch.setattr(config, "DEMO_MODE", True)
    db.init()
    yield services
    os.remove(tmp)


LAT, LON = 37.4781, 126.9515   # 관악구청 (청룡동)


def test_now_eligible_after_two_hours_of_delivery(svc):
    r = svc.now_status(LAT, LON, "14:00")
    assert r["grid"] == [59, 125] and r["place"] == "관악구 청룡동" and r["hot"] and r["pay_now"] is True
    assert r["exposure_min"] >= r["exposure_need_min"] and r["usual_hourly"] == 7_988 and r["virtual_rider"]
    assert r["worked_days"] >= 12 and r["judge_dong"]["name"] and r["temp"] == r["judge_temp"] >= 32


def test_now_not_enough_exposure_gives_reason(svc):
    r = svc.now_status(LAT, LON, "11:00")
    assert r["pay_now"] is False and any("배달 이동" in x for x in r["reasons"])


def test_now_outside_usual_hours(svc):
    r = svc.now_status(LAT, LON, "07:00")
    assert r["pay_now"] is False and any("4주" in x and "6~9시" in x for x in r["reasons"])


def test_night_not_a_paid_slot(svc):
    r = svc.now_status(LAT, LON, "22:30")
    assert r["pay_now"] is False and "22시~6시는 적립 시간대가 아니에요" in r["reasons"]


def test_rest_flow_and_history(svc):
    s = svc.rest_start(1, LAT, LON, "shelter", "14:00")
    assert s["eligible"]
    early = svc.rest_current(1, "14:15")
    assert early["resting"] and early["paid_min"] == 0 and "20분" in early["reason"]
    with pytest.raises(svc.ServiceError):
        svc.rest_start(1, LAT, LON, "shelter", "14:20")   # 이미 쉬는 중
    done = svc.rest_stop(1, "14:55")
    assert (done["rested_min"], done["paid_min"], done["amount"]) == (55, 30, round(30 / 60 * 7_988))
    h = svc.history(1, "15:00")
    assert h["today_paid_rests"] == 1 and h["today_left_rests"] == 3 and h["today_amount"] == done["amount"]
    assert h["week"][-1]["today"] and h["week"][-1]["rested"]


def test_rest_resets_exposure(svc):
    svc.rest_start(1, LAT, LON, "shelter", "14:00"); svc.rest_stop(1, "14:40")
    again = svc.rest_start(1, LAT, LON, "shelter", "14:40")
    assert again["eligible"] is False
    assert svc.rest_stop(1, "15:10")["amount"] == 0
    assert svc.now_status(LAT, LON, "17:10")["pay_now"] is True   # 다시 2시간 배달하면 받을 수 있다


def test_real_mode_does_not_judge(svc, monkeypatch):
    from backend import config
    monkeypatch.setattr(config, "DEMO_MODE", False)
    j = svc._judge(1, config.now("2026-08-03T14:00"))
    assert j["pay_now"] is False and j["has_record"] is False and j["reasons"] == [svc.NO_RECORD]


def test_shelters_sorted_and_virtual(svc):
    s = svc.shelter_list(LAT, LON)
    d = [x["distance_m"] for x in s["items"]]
    assert s["virtual"] and d == sorted(d)
    assert all("라이더" in x["kind"] for x in svc.shelter_list(LAT, LON, "rider")["items"])


def test_report_gwanak_dongs(svc):
    r = svc.report(LAT, LON, "15:30")
    assert len(r["dongs"]) == 21 and [d["name"] for d in r["dongs"] if d["me"]] == ["청룡동"] and r["virtual"]
    assert all(d["temp"] is not None for d in r["dongs"]) and r["virtual_riders"] == 1000
    assert r["amount"] > 0 and r["paid_hours"] > 0 and r["season"]["paid_riders"] > 0


def test_report_counts_only_until_now_and_adds_app_rests(svc):
    early, late = svc.report(LAT, LON, "10:00"), svc.report(LAT, LON, "18:00")
    assert early["amount"] < late["amount"] and early["missed_hours"] <= late["missed_hours"]
    before = svc.report(LAT, LON, "14:10")["resting"]
    svc.rest_start(1, LAT, LON, "auto", "14:00")
    assert svc.report(LAT, LON, "14:10")["resting"] == before + 1     # 앱에서 누른 쉼이 더해진다
    done = svc.rest_stop(1, "14:40")
    after = svc.report(LAT, LON, "14:40")
    cheong = [d for d in after["dongs"] if d["me"]][0]
    assert done["amount"] > 0 and cheong["amount"] >= done["amount"]


def test_dong_geo(svc):
    g = svc.dong_geo()
    assert len(g["features"]) == 21 and all(f["code"].startswith("11620") and f["center"] for f in g["features"])


def test_demo_reset(svc):
    svc.rest_start(1, LAT, LON, "shelter", "14:00"); svc.rest_stop(1, "14:30")
    assert svc.demo_reset()["deleted"] == 1


def test_config_has_agreed_numbers(svc):
    c = svc.app_config()
    assert (c["heat_min"], c["exposure_need_min"], c["rest_min"], c["pay_cap_min"], c["pay_cap_won"], c["daily_rests"]) == (32.0, 60, 20, 30, 10_000, 4)
    assert (c["labor_need_days"], c["labor_window_days"], len(c["slots"])) == (12, 28, 5)


def test_rest_start_auto_place(svc):
    assert svc.rest_start(1, LAT, LON, "auto", "14:00")["place"] == "shelter"
    svc.rest_stop(1, "14:30")
    assert svc.rest_start(1, 37.60, 126.99, "auto", "15:00")["place"] == "street"   # 쉼터에서 먼 곳


def test_model_31_96_shows_32_0_but_is_not_paid(svc, monkeypatch):
    """모델 값 31.96: 화면에는 32.0으로 보이지만 판정은 원래 값이라 지급 대상이 아니다."""
    from backend import gwanak
    monkeypatch.setattr(gwanak, "temp", lambda code, t: 31.96 if code else None)
    r = svc.now_status(LAT, LON, "14:00")
    assert r["temp"] == 32.0 and r["judge_temp"] == 32.0
    assert r["hot"] is False and r["pay_now"] is False and any("체감온도" in x for x in r["reasons"])
    assert all(h["temp"] == 32.0 and h["hot"] is False for h in r["hours"])
    s = svc.rest_start(1, LAT, LON, "auto", "14:00")
    assert s["eligible"] is False
    rep = svc.report(LAT, LON, "14:00")
    assert all(d["temp"] == 32.0 and d["hot"] is False for d in rep["dongs"])


# ----------------------------- 데이터 연동 단계 (지급은 정산 내역 기반) -----------------------------
def test_new_rider_is_app_only_and_not_paid(svc_a):
    """가입 직후(A): 조건은 그대로 판정해 보여주지만(모의 판정) 돈은 주지 않는다."""
    r = svc_a.now_status(LAT, LON, "14:00")
    assert r["pay_now"] is True and r["usual_hourly"] == 7_988       # 조건 판정은 단계와 상관없이 같다
    assert (r["link"]["stage"], r["link"]["basis"], r["link"]["pays"], r["link"]["can_upload"]) == ("A", "none", False, True)
    s = svc_a.rest_start(1, LAT, LON, "auto", "14:00")
    assert s["eligible"] is False and s["mock_eligible"] is True and s["reasons"][0] == "정산 내역을 등록하면 받을 수 있어요"
    cur = svc_a.rest_current(1, "14:25")
    assert cur["amount"] == 0 and cur["eligible"] is False and "정산 내역" in cur["reason"]
    done = svc_a.rest_stop(1, "14:55")
    assert (done["paid_min"], done["amount"], done["basis"]) == (0, 0, "none")
    h = svc_a.history(1, "15:00")
    assert h["today_amount"] == 0 and h["today_left_rests"] == 4       # 못 받은 쉼은 하루 횟수에 안 든다


def test_settlement_register_then_paid_usual_income(svc_a):
    with pytest.raises(svc_a.ServiceError):
        svc_a.settlement_upload(1, "  ", "14:00")              # 파일 없음
    up = svc_a.settlement_upload(1, "가상_정산내역_민수.csv", "14:00")
    assert (up["stage"], up["basis"], up["pays"], up["settle_status"], up["settle_name"], up["can_upload"]) == ("B", "usual", True, "pending", "대조 대기", False)
    with pytest.raises(svc_a.ServiceError) as e:
        svc_a.settlement_upload(1, "again.png", "14:01")
    assert e.value.status == 409
    s = svc_a.rest_start(1, LAT, LON, "auto", "14:05")
    assert s["eligible"] is True and (s["basis"], s["pay_hourly"]) == ("usual", 7_988)
    assert svc_a.rest_stop(1, "14:35")["amount"] == round(30 / 60 * 7_988)
    assert svc_a.report(LAT, LON, "15:00")["verify"]["pending"] >= 1


def test_settlement_summary_reads_usual_income(svc_a):
    before = svc_a.settlement_summary(1, "14:00")
    assert before["registered"] is False and before["virtual"] is True
    svc_a.settlement_upload(1, "가상_정산내역_민수.csv", "14:00")
    sm = svc_a.settlement_summary(1, "14:00")
    assert sm["registered"] and sm["file"] == "가상_정산내역_민수.csv" and sm["status_name"] == "대조 대기"
    assert [x["h"] for x in sm["hours"]] == list(range(6, 22))
    assert (sm["usual_hourly"], sm["per_rest"]) == (7_988, 3_994)
    assert sm["usual_hourly"] == svc_a.now_status(LAT, LON, "14:00")["usual_hourly"]   # 판정에 쓰는 값과 같다


def test_stage_is_fixed_when_rest_starts(svc_a):
    svc_a.rest_start(1, LAT, LON, "auto", "14:00")
    with pytest.raises(svc_a.ServiceError) as e:
        svc_a.demo_stage(1, "C")                                # 쉬는 중에는 못 바꾼다
    assert e.value.status == 409
    svc_a.settlement_upload(1, "a.png", "14:10")                # 쉬는 중 등록해도 이번 쉼은 시작할 때 기준(지급 없음)
    assert svc_a.rest_stop(1, "14:30")["amount"] == 0
    assert svc_a.rider_info(1)["stage"] == "B"


def test_consent_recorded_once(svc_a):
    assert svc_a.consent(1, "14:00")["consent"] is True
    from backend import db
    with db.conn() as c:
        first = c.execute("SELECT consent_at FROM riders WHERE id=1").fetchone()[0]
    svc_a.consent(1, "15:00")
    with db.conn() as c:
        assert c.execute("SELECT consent_at FROM riders WHERE id=1").fetchone()[0] == first


def test_demo_stage_validates(svc):
    assert svc.demo_stage(1, "A")["pays"] is False and svc.demo_stage(1, "B")["settle_status"] == "verified"
    with pytest.raises(svc.ServiceError):
        svc.demo_stage(1, "D")


def test_report_stage_breakdown_keeps_plan_numbers(svc):
    r = svc.report(LAT, LON, "15:30")
    st = {s["stage"]: s for s in r["stages"]}
    assert sum(s["riders"] for s in r["stages"]) == 1000 and set(st) == {"A", "B", "C"}
    assert sum(s["amount"] for s in r["stages"]) == r["amount"]              # 단계별 합 = 오늘 지급 예정
    assert (st["A"]["basis"], st["A"]["riders"], st["A"]["amount"]) == ("none", 0, 0)   # 가상 라이더는 모두 등록한 것으로 본다
    assert st["B"]["basis"] == st["C"]["basis"] == "usual" and st["B"]["riders"] > st["C"]["riders"] > 0
    # 정액이 없으니 여름 합계는 기획서 숫자(가상 1,000명, 절반이 쉼) 그대로다
    assert sum(s["season"]["amount"] for s in r["stages"]) == r["season"]["amount"] == 114_185_957
    assert r["verify"]["verified"] > r["verify"]["pending"] > r["verify"]["mismatch"] > 0


def test_config_has_stages(svc):
    c = svc.app_config()
    assert [(s["stage"], s["pays"]) for s in c["stages"]] == [("A", False), ("B", True), ("C", True)] and "flat_hourly" not in c
