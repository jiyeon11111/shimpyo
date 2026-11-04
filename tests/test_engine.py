import pytest

from engine import RiderDay, apparent_temp_summer, judge_hour, settle_day


# --- 체감온도 ---------------------------------------------------------

def test_humid_day_feels_hotter_than_dry_day():
    assert apparent_temp_summer(33, 80) > apparent_temp_summer(33, 30)


def test_hotter_air_feels_hotter():
    assert apparent_temp_summer(36, 60) > apparent_temp_summer(32, 60)


def test_invalid_humidity_rejected():
    with pytest.raises(ValueError):
        apparent_temp_summer(30, 120)


# --- 판정 규칙 --------------------------------------------------------

def test_below_31_nothing():
    d = judge_hour(30.0, 15)
    assert d.level is None and not d.pay_eligible and d.alert is None


def test_33_alert_only():
    d = judge_hour(33.5, 15)
    assert d.level == "33+" and not d.pay_eligible and d.alert == "휴식 권고"


def test_35_pays_only_14_to_17():
    assert judge_hour(35.2, 14).pay_eligible
    assert judge_hour(35.2, 16).pay_eligible
    assert not judge_hour(35.2, 17).pay_eligible
    assert not judge_hour(35.2, 11).pay_eligible


def test_38_pays_any_hour():
    assert judge_hour(38.1, 10).pay_eligible
    assert judge_hour(38.1, 20).alert == "강한 휴식 알림"


# --- 하루 정산 --------------------------------------------------------

TEMPS = {11: 34.0, 12: 34.8, 13: 35.4, 14: 36.1, 15: 36.5, 16: 35.9, 17: 35.0, 18: 33.2}


def test_rest_in_window_gets_paid():
    day = RiderDay("r1", "2026-08-03", (60, 127), worked_today=True)
    r = settle_day(day, TEMPS)
    assert r.paid_hours == [14, 15, 16]
    assert r.amount == 3 * 17_210


def test_no_work_record_no_pay():
    day = RiderDay("r2", "2026-08-03", (60, 127), worked_today=False)
    assert settle_day(day, TEMPS).amount == 0


def test_hour_with_delivery_not_paid():
    day = RiderDay("r3", "2026-08-03", (60, 127), worked_today=True, busy_hours={15})
    assert settle_day(day, TEMPS).paid_hours == [14, 16]


def test_monthly_cap_limits_payout():
    day = RiderDay("r4", "2026-08-03", (60, 127), worked_today=True)
    r = settle_day(day, TEMPS, used_this_month=39)
    assert r.paid_hours == [14]


# --- 분석용 배열 판정이 엔진 판정과 같은지 ----------------------------

def test_vectorized_payable_matches_engine():
    import pandas as pd
    from analysis.common import payable
    rows = [(t, h) for t in (30.0, 33.0, 34.9, 35.0, 36.5, 37.9, 38.0, 39.2) for h in range(24)]
    df = pd.DataFrame({"at": [t for t, _ in rows],
                       "time": pd.to_datetime([f"2026-08-03 {h:02d}:00" for _, h in rows])})
    assert payable(df).tolist() == [judge_hour(t, h).pay_eligible for t, h in rows]


def test_array_formula_matches_scalar():
    from engine.heat import apparent_temp_array
    pairs = [(28, 90), (31.5, 70), (33, 50), (35, 60), (38, 40)]
    assert list(apparent_temp_array([a for a, _ in pairs], [b for _, b in pairs])) == [apparent_temp_summer(a, b) for a, b in pairs]


# --- 분 단위 정산 (앱용) ------------------------------------------------

from datetime import datetime  # noqa: E402

from engine.payout import settle_rest  # noqa: E402


def _hot(t):  # 하루 종일 36도
    return 36.0


def test_rest_paid_by_minute_inside_window():
    r = settle_rest(datetime(2026, 8, 3, 14, 40), datetime(2026, 8, 3, 16, 10), _hot)
    assert (r.rested_min, r.paid_min, r.amount) == (90, 90, round(90 / 60 * 17_210))


def test_rest_outside_window_not_paid():
    r = settle_rest(datetime(2026, 8, 3, 16, 30), datetime(2026, 8, 3, 17, 30), _hot)
    assert r.paid_min == 30  # 17시 이후는 35도 구간 보전 없음


def test_rest_respects_daily_cap():
    r = settle_rest(datetime(2026, 8, 3, 14, 0), datetime(2026, 8, 3, 17, 0), _hot, paid_today_min=200)
    assert r.paid_min == 40


# --- 격자 변환 ---------------------------------------------------------

from engine.grid import latlon_to_grid  # noqa: E402


def test_grid_known_points():
    assert latlon_to_grid(37.5665, 126.9780) == (60, 127)   # 서울시청
    assert latlon_to_grid(35.1796, 129.0756) == (98, 76)    # 부산시청
    assert latlon_to_grid(33.4996, 126.5312) == (53, 38)    # 제주시청
