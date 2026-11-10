"""운행 기록(콜)에서 판정 재료를 뽑는다. 앱(backend/riders.py)과 대시보드 집계(analysis/gwanak_summer.py)가 같이 쓴다.

콜 한 건: 수락 → 음식점 도착 (이동 1) → 픽업 (음식점 대기) → 배달 완료 (이동 2).
  - 노출과 "가장 오래 달린 동"은 이동 1·2만 센다. 음식점 대기는 세지 않는다.
  - 운행 시간: 콜 구간(수락 → 배달 완료)을 이어 붙이되, 30분(rules.WORK_JOIN_GAP_MIN) 넘는 공백은 식사·휴식으로 보고 끊는다.
    이어 붙인 구간을 시간대별로 잘라 분을 센다.
  - 일한 날: 그 시간대 운행 시간이 60분(rules.WORKED_SLOT_MIN) 이상인 날 (팀 분석 activity.py와 같다).
  - 평소 시간당 수입: 배달료를 수락 시각의 1시간(날짜, 시)에 넣고, 최근 4주 같은 요일 같은 시의 합을
    그 시에 일한 주만 평균한다 (팀 분석 analysis3.py와 같다).
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from .payout import USUAL_WEEKS, usual_hourly
from .rules import LABOR_WINDOW_DAYS, SLOTS, WORK_JOIN_GAP_MIN, WORKED_SLOT_MIN, Leg, slot_of


@dataclass(frozen=True)
class Call:
    accept: datetime
    arrive: datetime     # 음식점 도착
    pickup: datetime
    done: datetime       # 배달 완료
    dep: str             # 출발동 코드
    shop: str            # 음식점동 코드
    cust: str            # 고객동 코드
    fee: int             # 배달료 (원)

    def legs(self) -> list[Leg]:
        return [(self.accept, self.arrive, self.dep, self.shop), (self.pickup, self.done, self.shop, self.cust)]


def _slot_minutes(s: datetime, e: datetime) -> dict[int, float]:
    """구간 [s, e)를 시간대별로 잘라 분을 센다 (하루 안 구간만 들어온다)."""
    out: dict[int, float] = {}
    day = s.replace(hour=0, minute=0, second=0, microsecond=0)
    for i, (a, b) in enumerate(SLOTS):
        m = (min(e, day + timedelta(hours=b)) - max(s, day + timedelta(hours=a))).total_seconds() / 60
        if m > 0:
            out[i] = m
    return out


class RiderBook:
    """한 라이더의 콜 기록과 날짜·시간대별 색인."""

    def __init__(self, calls: list[Call]):
        self.calls = sorted(calls, key=lambda c: c.accept)
        self.by_day: dict[date, list[Call]] = defaultdict(list)
        for c in self.calls:
            self.by_day[c.accept.date()].append(c)
        self.worked: dict[date, set[int]] = defaultdict(set)              # 날짜 → 일한 시간대
        self.hour_fee: dict[tuple[date, int], float] = defaultdict(float)  # (날짜, 시) → 배달료 합 (수락 시각 기준)
        self.work_min: dict[tuple[date, int], float] = defaultdict(float)  # (날짜, 시간대) → 운행 분
        gap = timedelta(minutes=WORK_JOIN_GAP_MIN)
        for d, cs in self.by_day.items():
            for c in cs:
                self.hour_fee[(d, c.accept.hour)] += c.fee
            s, e = cs[0].accept, cs[0].done
            for c in cs[1:] + [None]:
                if c is not None and c.accept - e <= gap:
                    e = max(e, c.done)
                    continue
                for k, m in _slot_minutes(s, e).items():
                    self.work_min[(d, k)] += m
                if c is not None:
                    s, e = c.accept, c.done
            for k in range(len(SLOTS)):
                if self.work_min.get((d, k), 0) >= WORKED_SLOT_MIN:
                    self.worked[d].add(k)

    def worked_days(self, at: datetime) -> int:
        """at이 속한 시간대에 최근 28일(전날까지) 중 일한 날 수. 22~06시면 0."""
        k = slot_of(at)
        if k is None:
            return 0
        d0 = at.date()
        return sum(1 for i in range(1, LABOR_WINDOW_DAYS + 1) if k in self.worked.get(d0 - timedelta(days=i), ()))

    def usual_hourly(self, at: datetime) -> int:
        """최근 4주 같은 요일·같은 시(at.hour)의 배달료 합을, 그 시에 일한 주만 평균."""
        days = [at.date() - timedelta(weeks=w) for w in range(1, USUAL_WEEKS + 1)]
        return usual_hourly([self.hour_fee[(d, at.hour)] for d in days if (d, at.hour) in self.hour_fee])

    def legs_on(self, day: date) -> list[Leg]:
        return [leg for c in self.by_day.get(day, []) for leg in c.legs()]
