"""백엔드 로직 테스트 (시연 모드, 임시 DB, 가상 라이더 민수).

민수는 가상라이더_관악 콜 파일의 전업 라이더 R0297이다(가상). 2026-08-03(월)에는 10:31에 첫 콜을 받는다.
그래서 11시에는 최근 2시간 이동이 60분에 못 미치고, 14시에는 넘는다. 7시대(06~09시)에는 일한 적이 없다.
쉼이 20분을 넘으면 노출 누적이 0으로 돌아간다.
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
