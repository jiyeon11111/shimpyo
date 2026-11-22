"""쉼 한 번의 정산 (팀 확정안, 2026-11-09).

- 쉼을 시작할 때 rules.judge_start로 지급 대상이었어야 한다.
- 쉼 버튼을 누르면 콜이 꺼진다. 20분 이상 쉬어야 인정한다 (법의 "2시간마다 20분").
- 금액 = min(평소 시간당 수입, 2만 원) × min(쉰 분, 30) ÷ 60 (기획서 지급 규칙).
  평소 시간당 수입 = 최근 4주 같은 요일·같은 1시간(예: 월요일 14시)의 배달료 합을, 그 시간에 일한 주만 평균 (records.py,
  팀 분석 analysis3.py와 같은 정의).
  체감온도가 더 높다고 금액이 늘지 않는다. 더 뜨거운 동을 일부러 찾아갈 이유를 없앤다.
- 상한: 시간당 2만 원 × 30분 = 한 번 최대 1만 원, 하루 4번까지.

데이터 연동 단계 (2차 보완, 팀 결론 2026-11-22). 판정 규칙(rules.py)은 단계와 상관없이 같다. 지급은 정산 내역 기반이다.
  - A 앱만 사용: 정산 내역 등록 전. 돈은 주지 않는다. 폭염 알림, 쉼터 안내, 모의 판정(조건이 맞는지)만 한다.
  - B 정산 내역 등록: 라이더가 가입할 때 배달 앱 정산 내역을 한 번 올린다. 평소 시간당 수입으로 준다. 플랫폼 협조 없이 시작하는 단계.
  - C 플랫폼 연동: 플랫폼 운행 기록이 자동으로 들어온다. 금액 기준은 B와 같고, 등록·대조가 필요 없다.
  정액(최저임금) 지급은 두지 않는다: 쉬는 동안 못 번 돈을 보전하는 것이라 잃은 만큼만 준다.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

REST_MIN = 20              # 이보다 짧으면 인정하지 않는다
REST_PAY_CAP_MIN = 30      # 한 번에 최대 30분치
HOURLY_CAP_WON = 20_000    # 평소 시간당 수입 상한
REST_PAY_CAP_WON = HOURLY_CAP_WON * REST_PAY_CAP_MIN // 60   # 한 번 최대 1만 원 (= 2만 원 × 30분)
DAILY_PAID_RESTS = 4       # 하루 최대 4번
USUAL_WEEKS = 4            # 평소 수입: 최근 4주 같은 요일
STAGES = ("A", "B", "C")
STAGE_NAMES = {"A": "앱만 사용", "B": "정산 내역 등록", "C": "플랫폼 연동"}
DEFAULT_STAGE = "A"        # 가입 직후: 정산 내역 등록 전
NEED_SETTLEMENT = "정산 내역을 등록하면 받을 수 있어요"


@dataclass
class RestResult:
    rested_min: int
    paid_min: int
    amount: int
    reason: str | None = None   # 돈이 안 나온 이유 (나왔으면 None)


def usual_hourly(hour_fees: list[float]) -> int:
    """평소 시간당 수입 = 같은 요일·같은 1시간의 배달료 합을, 그 시간에 일한 주만 평균. 일한 주가 없으면 0."""
    return round(sum(hour_fees) / len(hour_fees)) if hour_fees else 0


def pay_hourly(stage: str, usual_hourly_won: int) -> tuple[int, str]:
    """연동 단계에 따른 지급 기준 시급과 기준 이름. A는 지급 없음(0, "none"), B·C는 평소 시간당 수입("usual")."""
    if stage not in STAGES:
        raise ValueError(f"연동 단계는 {', '.join(STAGES)} 중 하나입니다: {stage!r}")
    return (0, "none") if stage == "A" else (usual_hourly_won, "usual")


def settle_rest(start: datetime, end: datetime, eligible: bool, usual_hourly_won: int,
                paid_rests_today: int = 0, ineligible_reason: str | None = None) -> RestResult:
    """쉼 한 번의 지급 분과 금액.

    eligible: 쉼을 시작할 때 judge_start가 지급 대상이라고 했는가
    usual_hourly_won: 쉼을 시작한 요일·시간대의 평소 시간당 수입 (정산 내역 등록 전인 A단계는 서비스가 지급 대상에서 뺀다)
    paid_rests_today: 이번 쉼 전에 오늘 이미 돈을 받은 쉼 횟수
    """
    rested = max(0, int((end - start).total_seconds() // 60))
    if not eligible:
        return RestResult(rested, 0, 0, ineligible_reason or "쉬기 시작할 때 적립 조건이 맞지 않았어요")
    if paid_rests_today >= DAILY_PAID_RESTS:
        return RestResult(rested, 0, 0, f"오늘 {DAILY_PAID_RESTS}번을 다 받았어요")
    if rested < REST_MIN:
        return RestResult(rested, 0, 0, f"{REST_MIN}분보다 짧게 쉬었어요")
    if usual_hourly_won <= 0:
        return RestResult(rested, 0, 0, "최근 4주 같은 요일 이 시간대에 일한 기록이 없어 평소 수입을 정할 수 없어요")
    paid = min(rested, REST_PAY_CAP_MIN)
    return RestResult(rested, paid, round(min(usual_hourly_won, HOURLY_CAP_WON) * paid / 60))
