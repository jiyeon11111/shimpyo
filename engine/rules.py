"""쉼 시작 시점의 지급 자격 판정 (팀 합의안, 2026-11-05).

지급하려면 쉼을 시작하는 순간 세 가지가 모두 맞아야 한다.
  1. 평소 일하던 시간: 최근 4주 동안 이 시간대에 운행한 기록이 있다 (무임승차 방지).
  2. 뜨거운 동: 그 시간 가장 오래 달린 행정동의 체감온도가 33도 이상이다. 시간대 제한은 없다.
     MVP는 행정동 체감온도 모델이 아직 없어서 쉼을 시작한 격자의 체감온도로 대신한다.
  3. 실제 노출: 최근 2시간 동안 실제 배달 이동(콜 수락 → 음식점 → 고객)이 누적 N분 이상이다.
     콜을 켠 채 카페에서 기다린 시간은 세지 않고, 20분 넘는 공백이 있으면 누적을 0으로 되돌린다.
쉼 자체의 조건(20분 이상)과 금액은 payout.py가 계산한다.

숫자는 초안이다. N=80분은 설명용 값이고 분석 3·4로 확정한다. 숫자만 고치면 앱 전체에 반영된다.
한계: 직사광선 아래에서 기다린 시간은 노출로 세지 못한다.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

HEAT_MIN_C = 33.0          # 산업안전보건기준규칙 제560조: 체감 33도 이상이면 2시간마다 20분 휴식
EXPOSURE_WINDOW_MIN = 120  # 최근 2시간
EXPOSURE_NEED_MIN = 80     # 초안 N. 분석 3·4로 확정
RESET_GAP_MIN = 20         # 이보다 긴 공백(쉼, 콜 켠 대기 포함)이면 노출 누적을 0으로

Move = tuple[datetime, datetime]   # 실제 배달 이동 한 구간 (시작, 끝)


@dataclass(frozen=True)
class Decision:
    pay_eligible: bool          # 지금 쉬기 시작하면 지급 대상인가
    exposure_min: int           # 최근 2시간 실제 배달 이동 누적 (분)
    reasons: tuple[str, ...]    # 지급 대상이 아닌 이유 (라이더에게 보여줄 문장)
    alert: str | None           # 체감온도 알림


def is_hot(apparent_temp: float) -> bool:
    return apparent_temp >= HEAT_MIN_C


def alert_for(apparent_temp: float) -> str | None:
    if apparent_temp >= 38:
        return "강한 휴식 알림"
    return "휴식 권고" if is_hot(apparent_temp) else None


def exposure_min(moves: list[Move], at: datetime) -> int:
    """at 기준 최근 2시간의 실제 배달 이동 누적 분. 20분 넘는 공백 뒤부터만 센다."""
    window_start = at - timedelta(minutes=EXPOSURE_WINDOW_MIN)
    gap = timedelta(minutes=RESET_GAP_MIN)
    total, last_end = 0.0, None
    for s, e in sorted(m for m in moves if m[0] < at):
        e = min(e, at)
        if last_end is not None and s - last_end > gap:
            total = 0.0
        lo = max(s, window_start)
        if e > lo:
            total += (e - lo).total_seconds() / 60
        last_end = e if last_end is None else max(last_end, e)
    if last_end is None or at - last_end > gap:
        return 0
    return int(total)


def judge_start(apparent_temp: float, worked_this_slot: bool, moves: list[Move], at: datetime,
                need_min: int = EXPOSURE_NEED_MIN) -> Decision:
    """지금 쉬기 시작하면 지급 대상인지. 이유는 맞지 않는 조건마다 하나씩."""
    exp = exposure_min(moves, at)
    reasons = []
    if not worked_this_slot:
        reasons.append("최근 4주 동안 이 시간대에 일한 기록이 없어요")
    if not is_hot(apparent_temp):
        reasons.append(f"체감온도가 {HEAT_MIN_C:.0f}도보다 낮아요")
    if exp < need_min:
        reasons.append(f"최근 2시간 배달 이동이 {exp}분이에요. {need_min}분이 필요해요")
    return Decision(not reasons, exp, tuple(reasons), alert_for(apparent_temp))
