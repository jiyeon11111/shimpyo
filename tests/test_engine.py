from datetime import datetime, timedelta

import pytest

from engine import Call, RiderBook, apparent_temp_summer, exposure_min, is_hot, judge_start, longest_dong, settle_rest, slot_of
from engine.payout import REST_PAY_CAP_WON, usual_hourly


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
    d = judge_start(34.0, 12, steady(), AT)
    assert d.pay_eligible and d.reasons == () and d.exposure_min >= 60


def test_32_boundary_and_no_time_window():
    assert is_hot(32.0) and not is_hot(31.9)
    night = datetime(2026, 8, 3, 21, 0)
    mv = [(night - timedelta(minutes=100), night - timedelta(minutes=5))]
    assert judge_start(32.0, 12, mv, night).pay_eligible      # 14~17시 제한 없음 (18~22시 시간대)


def test_31_96_is_not_hot_even_if_shown_as_32_0():
    # 판정은 반올림 전 값으로 한다. 31.96은 화면에 32.0으로 보여도 기준 미달이다.
    assert not is_hot(31.96) and round(31.96, 1) == 32.0
    d = judge_start(31.96, 12, steady(), AT)
    assert not d.pay_eligible and any("체감온도" in r for r in d.reasons)


def test_each_failed_condition_gives_reason():
    d = judge_start(31.0, 11, steady(15, 25), AT)
    assert not d.pay_eligible and len(d.reasons) == 3


def test_exposure_need_boundary():
    mv = [(AT - timedelta(minutes=60), AT)]
    assert judge_start(35.0, 12, mv, AT).pay_eligible
    assert not judge_start(35.0, 12, mv, AT, need_min=61).pay_eligible


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


def test_labor_needs_12_of_28_days():
    assert judge_start(35.0, 12, steady(), AT).pay_eligible
    d = judge_start(35.0, 11, steady(), AT)
    assert not d.pay_eligible and "12~15시" in d.reasons[0] and "11일" in d.reasons[0]


def test_slots_and_night_not_eligible():
    assert [slot_of(datetime(2026, 8, 3, h)) for h in (5, 6, 8, 9, 12, 15, 18, 21, 22)] == [None, 0, 0, 1, 2, 3, 4, 4, None]
    night = datetime(2026, 8, 3, 22, 30)
    mv = [(night - timedelta(minutes=90), night - timedelta(minutes=5))]
    d = judge_start(35.0, 28, mv, night)
    assert not d.pay_eligible and d.reasons == ("22시~6시는 적립 시간대가 아니에요",)


def test_no_dong_temperature_gives_reason():
    d = judge_start(None, 12, steady(), AT)
    assert not d.pay_eligible and "동" in d.reasons[0]


def test_longest_dong_splits_each_leg_in_half():
    a, b, c = "A", "B", "C"
    legs = [(AT - timedelta(minutes=50), AT - timedelta(minutes=30), a, b),    # 20분: A 10, B 10
            (AT - timedelta(minutes=25), AT - timedelta(minutes=5), b, c),     # 20분: B 10, C 10
            (AT - timedelta(minutes=90), AT - timedelta(minutes=70), c, c)]    # 1시간 밖: 세지 않음
    assert longest_dong(legs, AT) == b
    assert longest_dong([], AT) is None


def test_longest_dong_tie_goes_to_first_seen_dong():
    # 두 동이 같은 분이면 먼저 나온 동 (팀 analysis3.py와 같은 규칙). 코드 크기와 무관하다.
    z, a = "Z", "A"
    legs = [(AT - timedelta(minutes=40), AT - timedelta(minutes=20), z, a)]   # Z 10, A 10
    assert longest_dong(legs, AT) == z
    legs = [(AT - timedelta(minutes=40), AT - timedelta(minutes=20), a, z)]
    assert longest_dong(legs, AT) == a


def test_longest_dong_looks_at_last_13_legs_only():
    m = lambda k: AT - timedelta(minutes=k)  # noqa: E731
    old = [(m(59), m(45), "X", "X")]                                           # X 14분, 14번째 전 이동
    recent = [(m(44 - 3 * i), m(43 - 3 * i), "Y" if i % 2 else "W", "Y" if i % 2 else "W") for i in range(13)]
    assert longest_dong(old + recent, AT) != "X"
    assert longest_dong(old + recent, AT, last_n=None) == "X"


def test_rest_capped_at_10000_won():
    r = settle_rest(AT, AT + timedelta(minutes=30), True, 21_500)       # 30분치 10,750원 → 1만 원
    assert (r.paid_min, r.amount) == (30, REST_PAY_CAP_WON)
    assert settle_rest(AT, AT + timedelta(minutes=30), True, 19_000).amount == 9_500
    # 시간당 2만 원 상한을 먼저 건다: 25분 × 2만 원 = 8,333원 (30분치·1만 원 비교가 아니다)
    assert settle_rest(AT, AT + timedelta(minutes=25), True, 24_000).amount == 8_333


def test_no_usual_income_not_paid():
    r = settle_rest(AT, AT + timedelta(minutes=30), True, 0)
    assert r.amount == 0 and "평소 수입" in r.reason


# --- 운행 기록에서 판정 재료 뽑기 ------------------------------------

def _call(day, hh, mm, fee=4_000, dongs=("A", "B", "C")):
    t = datetime(2026, 8, day, hh, mm)
    return Call(t, t + timedelta(minutes=6), t + timedelta(minutes=10), t + timedelta(minutes=16), *dongs, fee)


def test_rider_book_worked_days_and_usual_income():
    # 7월 6일(월)부터 4주 동안 매일 13:00~14:16 운행(콜 4건, 20분 간격). 8월 3일(월) 13시 기준
    calls = []
    for i in range(28):
        d = datetime(2026, 7, 6) + timedelta(days=i)
        for hh, mm in ((13, 0), (13, 20), (13, 40), (14, 0)):
            t = d.replace(hour=hh, minute=mm)
            calls.append(Call(t, t + timedelta(minutes=6), t + timedelta(minutes=10), t + timedelta(minutes=16), "A", "B", "C", 4_000))
    book = RiderBook(calls)
    at = datetime(2026, 8, 3, 13, 50)
    assert book.worked_days(at) == 28 and book.worked_days(datetime(2026, 8, 3, 10, 0)) == 0
    # 같은 요일(월) 13시에 수락한 콜 3건 = 12,000원. 4주 평균도 12,000원
    assert book.usual_hourly(at) == usual_hourly([12_000] * 4) == 12_000
    assert book.worked_days(datetime(2026, 8, 3, 23, 0)) == 0


def test_worked_day_needs_60_minutes_in_slot():
    # 매일 13:00~13:36만 운행(36분)하면 그 시간대에 일한 날로 세지 않는다
    calls = [_call(d, 13, mm) for d in range(1, 29) for mm in (0, 20)]
    book = RiderBook(calls)
    assert book.worked_days(datetime(2026, 8, 29, 13, 0)) == 0


def test_rider_book_gap_over_30_splits_work_time():
    book = RiderBook([_call(3, 13, 0), _call(3, 13, 50)])   # 13:16 끝 → 13:50 시작: 34분 공백
    assert book.work_min[(datetime(2026, 8, 3).date(), 2)] == 32
    book = RiderBook([_call(3, 13, 0), _call(3, 13, 40)])   # 24분 공백은 이어 붙인다: 13:00~13:56
    assert book.work_min[(datetime(2026, 8, 3).date(), 2)] == 56


def test_usual_income_averages_only_worked_weeks():
    # 4주 중 2주만 같은 요일 13시에 일함 (4,000원, 8,000원) → 6,000원
    book = RiderBook([_call(13, 13, 0, fee=4_000), _call(20, 13, 0, fee=4_000), _call(20, 13, 30, fee=4_000)])
    assert book.usual_hourly(datetime(2026, 8, 27, 13, 40)) == 6_000


# --- 분석용 배열 판정이 엔진 판정과 같은지 ----------------------------

def test_vectorized_hot_hours_matches_engine():
    import pandas as pd
    from analysis.common import hot_hours
    temps = [30.0, 31.9, 32.0, 32.9, 33.0, 35.0, 38.0]
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
