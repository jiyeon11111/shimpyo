"""쉼 시작 시점의 지급 자격 판정 (팀 확정안, 2026-11-09).

지급하려면 쉼을 시작하는 순간 세 가지가 모두 맞아야 한다.
  1. 평소 일하던 시간 (노동 확인): 하루를 다섯 시간대(06-09, 09-12, 12-15, 15-18, 18-22)로 나눈다.
     쉼을 시작한 시각이 속한 시간대에, 최근 28일 중 12일 이상 일했어야 한다 (무임승차 방지).
     "일한 날" = 그 시간대에 60분 이상 운행한 날. 운행 시간은 콜 수락~배달 완료를 이어 붙이되
     30분 넘게 비면 끊는다 (팀 분석 activity.py와 같은 정의).
     22~06시는 어느 시간대에도 속하지 않으므로 지급 대상이 아니다.
  2. 뜨거운 동: 쉼 시작 전 1시간 동안 가장 오래 달린 행정동의 체감온도가 32도 이상이다. 시간대 제한은 없다.
     온도는 행정동 체감온도 모델 값이다. 32도는 모델 값 전용 판정선이다(33도 − 모델 불확도).
     센서 실측끼리 판정할 때는 33도를 쓴다(SENSOR_HEAT_MIN_C).
     달린 분은 이동 구간마다 양 끝 동에 반씩 나눈다:
       이동 1(콜 수락 → 음식점 도착)은 출발동·음식점동에, 이동 2(픽업 → 배달 완료)는 음식점동·고객동에.
  3. 실제 노출: 최근 2시간 동안 실제 배달 이동(이동 1 + 이동 2)이 누적 N분 이상이다.
     콜을 켠 채 카페에서 기다린 시간은 세지 않고, 20분 넘는 공백이 있으면 누적을 0으로 되돌린다.
쉼 자체의 조건(20분 이상)과 금액은 payout.py가 계산한다.

숫자는 팀 확정안(2026-11-09)이다. 32도, N=60분, 28일 중 12일. 숫자만 고치면 앱 전체에 반영된다.
한계: 직사광선 아래에서 기다린 시간은 노출로 세지 못한다.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

HEAT_MIN_C = 32.0          # 모델 체감온도 기준 32도(33도 − 모델 불확도)
SENSOR_HEAT_MIN_C = 33.0   # 센서 실측끼리 판정할 때 (산업안전보건기준규칙 2시간마다 20분 휴식 기준)
EXPOSURE_WINDOW_MIN = 120  # 최근 2시간
EXPOSURE_NEED_MIN = 60     # 팀 확정안 N
RESET_GAP_MIN = 20         # 이보다 긴 공백(쉼, 콜 켠 대기 포함)이면 노출 누적을 0으로
DONG_WINDOW_MIN = 60       # "그 시간 가장 오래 달린 동": 쉼 시작 전 1시간

SLOTS = ((6, 9), (9, 12), (12, 15), (15, 18), (18, 22))   # 노동 확인·평소 수입 시간대 (시작 이상, 끝 미만)
LABOR_WINDOW_DAYS = 28     # 최근 28일 (쉼 시작 전날까지)
LABOR_NEED_DAYS = 12       # 그중 이 시간대에 일한 날
WORKED_SLOT_MIN = 60       # 그 시간대에 이만큼 운행해야 "일한 날"
WORK_JOIN_GAP_MIN = 30     # 운행 시간: 다음 콜 수락까지 이보다 길게 비면 끊는다 (식사·휴식)

Move = tuple[datetime, datetime]              # 실제 배달 이동 한 구간 (시작, 끝)
Leg = tuple[datetime, datetime, str, str]     # 이동 구간 + 양 끝 동 코드 (달린 분을 반씩 나눈다)

NIGHT_REASON = "22시~6시는 적립 시간대가 아니에요"


@dataclass(frozen=True)
class Decision:
    pay_eligible: bool          # 지금 쉬기 시작하면 지급 대상인가
    exposure_min: int           # 최근 2시간 실제 배달 이동 누적 (분)
    reasons: tuple[str, ...]    # 지급 대상이 아닌 이유 (라이더에게 보여줄 문장)
    alert: str | None           # 체감온도 알림


def is_hot(apparent_temp: float) -> bool:
    return apparent_temp >= HEAT_MIN_C


def alert_for(apparent_temp: float | None) -> str | None:
    if apparent_temp is None:
        return None
    if apparent_temp >= 38:
        return "강한 휴식 알림"
    return "휴식 권고" if is_hot(apparent_temp) else None


def slot_of(t: datetime) -> int | None:
    """t가 속한 시간대 번호(0~4). 22~06시면 None."""
    for i, (a, b) in enumerate(SLOTS):
        if a <= t.hour < b:
            return i
    return None


def slot_label(i: int) -> str:
    a, b = SLOTS[i]
    return f"{a}~{b}시"


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


def dong_minutes(legs: list[Leg], at: datetime, window_min: int = DONG_WINDOW_MIN) -> dict[str, float]:
    """at 전 window_min분 동안 동별로 달린 분. 이동 구간마다 양 끝 동에 반씩 더한다."""
    lo = at - timedelta(minutes=window_min)
    out: dict[str, float] = {}
    for s, e, a, b in legs:
        m = (min(e, at) - max(s, lo)).total_seconds() / 60
        if m > 0:
            out[a] = out.get(a, 0.0) + m / 2
            out[b] = out.get(b, 0.0) + m / 2
    return out


def longest_dong(legs: list[Leg], at: datetime, window_min: int = DONG_WINDOW_MIN) -> str | None:
    """쉼 시작 전 1시간 동안 가장 오래 달린 동 코드. 달린 기록이 없으면 None. 같으면 코드가 작은 동."""
    mins = dong_minutes(legs, at, window_min)
    return min(mins, key=lambda k: (-round(mins[k], 6), k)) if mins else None


def judge_start(apparent_temp: float | None, worked_days: int, moves: list[Move], at: datetime,
                need_min: int = EXPOSURE_NEED_MIN) -> Decision:
    """지금 쉬기 시작하면 지급 대상인지. 이유는 맞지 않는 조건마다 하나씩.

    apparent_temp: 가장 오래 달린 동의 모델 체감온도. 달린 동이 없으면 None.
    worked_days: 쉼 시작 시각이 속한 시간대에 최근 28일 중 일한 날 수.
    """
    exp = exposure_min(moves, at)
    reasons = []
    slot = slot_of(at)
    if slot is None:
        reasons.append(NIGHT_REASON)
    elif worked_days < LABOR_NEED_DAYS:
        reasons.append(f"최근 4주 동안 이 시간대({slot_label(slot)})에 일한 날이 {worked_days}일이에요. "
                       f"{LABOR_NEED_DAYS}일이 필요해요")
    if apparent_temp is None:
        reasons.append("최근 1시간 동안 달린 동이 없어 체감온도를 정할 수 없어요")
    elif not is_hot(apparent_temp):
        reasons.append(f"체감온도가 {HEAT_MIN_C:.0f}도보다 낮아요")
    if exp < need_min:
        reasons.append(f"최근 2시간 배달 이동이 {exp}분이에요. {need_min}분이 필요해요")
    return Decision(not reasons, exp, tuple(reasons), alert_for(apparent_temp))
