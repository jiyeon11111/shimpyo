"""백엔드 로직 테스트 (시연 모드, 임시 DB)."""
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


def test_now_in_payable_window(svc):
    r = svc.now_status(LAT, LON, "15:00")
    assert r["grid"] == [59, 126] and r["temp"] >= 35 and r["pay_now"] is True


def test_now_before_window_not_payable(svc):
    assert svc.now_status(LAT, LON, "11:00")["pay_now"] is False


def test_rest_flow_and_history(svc):
    svc.rest_start(1, LAT, LON, "shelter", "14:00")
    mid = svc.rest_current(1, "15:00")
    assert mid["resting"] and mid["paid_min"] == 60
    with pytest.raises(svc.ServiceError):
        svc.rest_start(1, LAT, LON, "shelter", "15:00")   # 이미 쉬는 중
    done = svc.rest_stop(1, "16:00")
    assert done["paid_min"] == 120 and done["amount"] == round(120 / 60 * 17210)
    h = svc.history(1, "16:30")
    assert h["today_paid_min"] == 120 and h["today_left_min"] == 120
    assert h["week"][-1]["today"] and h["week"][-1]["rested"]


def test_daily_cap_across_rests(svc):
    svc.rest_start(1, LAT, LON, "shelter", "14:00"); svc.rest_stop(1, "17:00")
    svc.rest_start(1, LAT, LON, "shelter", "17:00"); r = svc.rest_stop(1, "18:00")
    assert r["paid_min"] == 0   # 17시 이후는 35도 구간 보전 없음


def test_shelters_sorted_and_virtual(svc):
    s = svc.shelter_list(LAT, LON)
    d = [x["distance_m"] for x in s["items"]]
    assert s["virtual"] and d == sorted(d)
    assert all("라이더" in x["kind"] for x in svc.shelter_list(LAT, LON, "rider")["items"])


def test_report_shape(svc):
    r = svc.report(LAT, LON, "15:30")
    assert len(r["grid"]) == 49 and sum(c["me"] for c in r["grid"]) == 1 and r["virtual"]


def test_demo_reset(svc):
    svc.rest_start(1, LAT, LON, "shelter", "14:00"); svc.rest_stop(1, "14:30")
    assert svc.demo_reset()["deleted"] == 1


def test_now_guidance_fields(svc):
    r = svc.now_status(LAT, LON, "15:00")
    assert r["pay_until"] and r["pay_until"] > 15 and r["next_pay"] is None
    assert r["shelter"]["inside"] is True          # 서교동 주민센터가 150m 안
    early = svc.now_status(LAT, LON, "11:00")
    assert early["pay_until"] is None and early["next_pay"] is not None and early["next_pay"] > 11


def test_rest_start_auto_place(svc):
    assert svc.rest_start(1, LAT, LON, "auto", "14:00")["place"] == "shelter"
    svc.rest_stop(1, "14:30")
    assert svc.rest_start(1, 37.60, 126.99, "auto", "15:00")["place"] == "street"   # 쉼터에서 먼 곳
