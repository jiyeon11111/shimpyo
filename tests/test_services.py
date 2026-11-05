"""백엔드 로직 테스트 (시연 모드, 임시 DB, 가상 라이더 민수).

민수는 10시부터 35분마다 25분 배달 이동한다(가상). 그래서 11시에는 최근 2시간 이동이 80분에 못 미치고,
14시에는 넘는다. 쉼이 20분을 넘으면 노출 누적이 0으로 돌아간다.
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


LAT, LON = 37.5552, 126.9222


def test_now_eligible_after_two_hours_of_delivery(svc):
    r = svc.now_status(LAT, LON, "14:00")
    assert r["grid"] == [59, 126] and r["hot"] and r["pay_now"] is True
    assert r["exposure_min"] >= r["exposure_need_min"] and r["usual_hourly"] == 14_600 and r["virtual_rider"]


def test_now_not_enough_exposure_gives_reason(svc):
    r = svc.now_status(LAT, LON, "11:00")
    assert r["pay_now"] is False and any("배달 이동" in x for x in r["reasons"])


def test_now_outside_usual_hours(svc):
    r = svc.now_status(LAT, LON, "18:30")
    assert r["pay_now"] is False and any("4주" in x for x in r["reasons"])


def test_rest_flow_and_history(svc):
    s = svc.rest_start(1, LAT, LON, "shelter", "14:00")
    assert s["eligible"]
    early = svc.rest_current(1, "14:15")
    assert early["resting"] and early["paid_min"] == 0 and "20분" in early["reason"]
    with pytest.raises(svc.ServiceError):
        svc.rest_start(1, LAT, LON, "shelter", "14:20")   # 이미 쉬는 중
    done = svc.rest_stop(1, "14:55")
    assert (done["rested_min"], done["paid_min"], done["amount"]) == (55, 30, 7_300)
    h = svc.history(1, "15:00")
    assert h["today_paid_rests"] == 1 and h["today_left_rests"] == 3 and h["today_amount"] == 7_300
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
    j = svc._judge(1, 36.0, config.now("2026-08-03T14:00"))
    assert j["pay_now"] is False and j["has_record"] is False and j["reasons"] == [svc.NO_RECORD]


def test_shelters_sorted_and_virtual(svc):
    s = svc.shelter_list(LAT, LON)
    d = [x["distance_m"] for x in s["items"]]
    assert s["virtual"] and d == sorted(d)
    assert all("라이더" in x["kind"] for x in svc.shelter_list(LAT, LON, "rider")["items"])


def test_report_shape(svc):
    r = svc.report(LAT, LON, "15:30")
    assert len(r["grid"]) == 49 and sum(c["me"] for c in r["grid"]) == 1 and r["virtual"]
    assert r["amount"] > 0 and r["paid_hours"] > 0


def test_demo_reset(svc):
    svc.rest_start(1, LAT, LON, "shelter", "14:00"); svc.rest_stop(1, "14:30")
    assert svc.demo_reset()["deleted"] == 1


def test_config_has_agreed_numbers(svc):
    c = svc.app_config()
    assert (c["heat_min"], c["exposure_need_min"], c["rest_min"], c["pay_cap_min"], c["daily_rests"]) == (33.0, 80, 20, 30, 4)


def test_rest_start_auto_place(svc):
    assert svc.rest_start(1, LAT, LON, "auto", "14:00")["place"] == "shelter"
    svc.rest_stop(1, "14:30")
    assert svc.rest_start(1, 37.60, 126.99, "auto", "15:00")["place"] == "street"   # 쉼터에서 먼 곳
