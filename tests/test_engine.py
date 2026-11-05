from datetime import datetime, timedelta

import pytest

from engine import apparent_temp_summer, exposure_min, is_hot, judge_start, settle_rest


# --- 체감온도 ---------------------------------------------------------

def test_humid_day_feels_hotter_than_dry_day():
    assert apparent_temp_summer(33, 80) > apparent_temp_summer(33, 30)


def test_hotter_air_feels_hotter():
    assert apparent_temp_summer(36, 60) > apparent_temp_summer(32, 60)


def test_invalid_humidity_rejected():
    with pytest.raises(ValueError):
        apparent_temp_summer(30, 120)


# --- 노출: 최근 2시간 실제 배달 이동 ----------------------------------

AT = datetime(2026, 8, 3, 14, 0)


def m(h1, m1, h2, m2):
    return (datetime(2026, 8, 3, h1, m1), datetime(2026, 8, 3, h2, m2))


def steady(each=25, gap=10, start=AT - timedelta(hours=2)):
    """start부터 AT까지 each분 이동, gap분 대기 반복."""
    out, t = [], start
    while t < AT:
        out.append((t, t + timedelta(minutes=each)))
        t += timedelta(minutes=each + gap)
    return out


def test_exposure_counts_only_last_two_hours():
    assert exposure_min([m(11, 0, 11, 55), m(11, 58, 12, 30), m(12, 35, 13, 55)], AT) == 30 + 80


def test_cafe_gap_over_20_resets():
    assert exposure_min([m(12, 0, 13, 0), m(13, 21, 13, 50)], AT) == 29   # 21분 공백 → 앞의 60분은 버림


def test_gap_of_exactly_20_does_not_reset():
    assert exposure_min([m(12, 0, 13, 0), m(13, 20, 13, 50)], AT) == 90


def test_idle_over_20_before_now_is_zero():
    assert exposure_min([m(12, 0, 13, 30)], AT) == 0   # 마지막 이동 뒤 30분째 대기


def test_move_in_progress_clipped_at_now():
    assert exposure_min([m(12, 30, 14, 30)], AT) == 90


# --- 쉼 시작 판정 ------------------------------------------------------

def test_all_three_conditions_pay():
    d = judge_start(34.0, True, steady(), AT)
    assert d.pay_eligible and d.reasons == () and d.exposure_min >= 80


def test_33_boundary_and_no_time_window():
    assert is_hot(33.0) and not is_hot(32.9)
    night = datetime(2026, 8, 3, 21, 0)
    mv = [(night - timedelta(minutes=100), night - timedelta(minutes=5))]
    assert judge_start(33.0, True, mv, night).pay_eligible      # 14~17시 제한 없음


def test_each_failed_condition_gives_reason():
    d = judge_start(32.0, False, steady(15, 25), AT)
    assert not d.pay_eligible and len(d.reasons) == 3


def test_exposure_need_boundary():
    mv = [(AT - timedelta(minutes=80), AT)]
    assert judge_start(35.0, True, mv, AT).pay_eligible
    assert not judge_start(35.0, True, mv, AT, need_min=81).pay_eligible


def test_hotter_does_not_change_amount():
    a = settle_rest(AT, AT + timedelta(minutes=30), True, 15_000)
    b = settle_rest(AT, AT + timedelta(minutes=30), True, 15_000)
    assert a.amount == b.amount == 7_500   # 금액에 체감온도가 들어가지 않는다


# --- 쉼 정산 -----------------------------------------------------------

def test_rest_under_20_not_paid():
    r = settle_rest(AT, AT + timedelta(minutes=19), True, 15_000)
    assert (r.paid_min, r.amount) == (0, 0) and r.reason


def test_rest_20_paid_by_usual_income():
    r = settle_rest(AT, AT + timedelta(minutes=20), True, 15_000)
    assert (r.paid_min, r.amount, r.reason) == (20, 5_000, None)


def test_rest_capped_at_30_min():
    r = settle_rest(AT, AT + timedelta(minutes=55), True, 14_600)
    assert (r.rested_min, r.paid_min, r.amount) == (55, 30, 7_300)


def test_fifth_rest_of_day_not_paid():
    assert settle_rest(AT, AT + timedelta(minutes=30), True, 15_000, paid_rests_today=3).amount > 0
    assert settle_rest(AT, AT + timedelta(minutes=30), True, 15_000, paid_rests_today=4).amount == 0


def test_ineligible_start_never_paid():
    r = settle_rest(AT, AT + timedelta(minutes=40), False, 15_000, 0, "이유")
    assert r.amount == 0 and r.reason == "이유"


# --- 분석용 배열 판정이 엔진 판정과 같은지 ----------------------------

def test_vectorized_hot_hours_matches_engine():
    import pandas as pd
    from analysis.common import hot_hours
    temps = [30.0, 32.9, 33.0, 34.9, 35.0, 38.0]
    df = pd.DataFrame({"at": temps})
    assert hot_hours(df).tolist() == [is_hot(t) for t in temps]


def test_array_formula_matches_scalar():
    from engine.heat import apparent_temp_array
    pairs = [(28, 90), (31.5, 70), (33, 50), (35, 60), (38, 40)]
    assert list(apparent_temp_array([a for a, _ in pairs], [b for _, b in pairs])) == [apparent_temp_summer(a, b) for a, b in pairs]


# --- 격자 변환 ---------------------------------------------------------

from engine.grid import latlon_to_grid  # noqa: E402


def test_grid_known_points():
    assert latlon_to_grid(37.5665, 126.9780) == (60, 127)   # 서울시청
    assert latlon_to_grid(35.1796, 129.0756) == (98, 76)    # 부산시청
    assert latlon_to_grid(33.4996, 126.5312) == (53, 38)    # 제주시청
