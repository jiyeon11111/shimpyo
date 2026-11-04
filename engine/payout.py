"""라이더 하루치 보전 계산.

받는 조건 (제안서 4장):
  1. 그날 그 격자에서 운행한 기록이 있을 것
  2. 지급 구간인 시간에 배차를 받지 않았을 것 (= 쉬었음)
  3. 하루 상한, 한 달 상한 안에서만 보전

시간당 단가와 상한은 초안 값이다. 단가 기준점은 제주 건설 일용직
기후보험의 시간당 1만7210원이며, 예산 시뮬레이션으로 조정한다.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .rules import judge_hour

HOURLY_RATE = 17_210      # 원, 초안
DAILY_CAP_HOURS = 4       # 초안
MONTHLY_CAP_HOURS = 40    # 초안


@dataclass
class RiderDay:
    rider_id: str
    date: str                                   # "2026-08-03"
    grid: tuple[int, int]                       # (nx, ny) 주 활동 격자
    worked_today: bool                          # 그날 이 격자 운행 기록 여부
    busy_hours: set[int] = field(default_factory=set)  # 배차를 받은 시각들


@dataclass
class DayResult:
    rider_id: str
    date: str
    paid_hours: list[int]
    amount: int
    alerts: dict[int, str]


def settle_day(
    day: RiderDay,
    hourly_temps: dict[int, float],
    used_this_month: float = 0,
    rate: int = HOURLY_RATE,
    daily_cap: int = DAILY_CAP_HOURS,
    monthly_cap: int = MONTHLY_CAP_HOURS,
) -> DayResult:
    """한 라이더의 하루를 시간 단위로 돌며 보전 시간과 금액을 계산한다.

    hourly_temps: {시각: 그 격자의 체감온도}
    used_this_month: 이번 달에 이미 보전받은 시간
    """
    alerts: dict[int, str] = {}
    paid: list[int] = []
    room = max(0, min(daily_cap, monthly_cap - used_this_month))

    for hour in sorted(hourly_temps):
        d = judge_hour(hourly_temps[hour], hour)
        if d.alert:
            alerts[hour] = d.alert
        if not (day.worked_today and d.pay_eligible):
            continue
        if hour in day.busy_hours:      # 그 시간에 일했으면 보전 없음
            continue
        if len(paid) >= room:
            break
        paid.append(hour)

    return DayResult(day.rider_id, day.date, paid, len(paid) * rate, alerts)


# ---------------------------------------------------------------------------
# 앱용: 쉼 한 번(시작~종료)을 분 단위로 정산한다.
# 판정은 시간 단위 규칙(judge_hour)을 그대로 쓰고, 보전은 쉰 분만큼 비례한다.
# 예: 14:40~16:10 쉼, 그 시간 내내 35도 이상 → 90분 보전.
# ---------------------------------------------------------------------------
from datetime import datetime, timedelta  # noqa: E402
from typing import Callable  # noqa: E402


@dataclass
class RestResult:
    rested_min: int
    paid_min: int
    amount: int


def settle_rest(
    start: datetime,
    end: datetime,
    temp_at: Callable[[datetime], float],
    paid_today_min: int = 0,
    paid_month_min: int = 0,
    rate: int = HOURLY_RATE,
    daily_cap: int = DAILY_CAP_HOURS,
    monthly_cap: int = MONTHLY_CAP_HOURS,
) -> RestResult:
    """쉼 한 번의 보전 분과 금액.

    temp_at: 시각 → 그 격자의 체감온도 (기상청 예보·실황에서 보간한 값)
    paid_today_min, paid_month_min: 이번 쉼 전에 이미 보전받은 분 (상한 계산용)
    """
    if end <= start:
        return RestResult(0, 0, 0)
    room = max(0, min(daily_cap * 60 - paid_today_min, monthly_cap * 60 - paid_month_min))
    paid = 0
    t = start.replace(second=0, microsecond=0)
    while t < end and paid < room:
        if judge_hour(temp_at(t), t.hour).pay_eligible:
            paid += 1
        t += timedelta(minutes=1)
    rested = int((end - start).total_seconds() // 60)
    return RestResult(rested, paid, round(paid / 60 * rate))
