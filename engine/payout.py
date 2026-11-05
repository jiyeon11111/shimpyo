"""쉼 한 번의 정산 (팀 합의안, 2026-11-05).

- 쉼을 시작할 때 rules.judge_start로 지급 대상이었어야 한다.
- 쉼 버튼을 누르면 콜이 꺼진다. 20분 이상 쉬어야 인정한다 (법의 "2시간마다 20분").
- 금액은 그 라이더가 평소 그 시간대에 벌던 수입(최근 4주 시간당 평균)에 쉰 분을 비례해 준다.
  체감온도가 더 높다고 금액이 늘지 않는다. 더 뜨거운 동을 일부러 찾아갈 이유를 없앤다.
- 상한: 한 번에 최대 30분치, 하루 4번까지. 초안 값이며 분석 3·4로 확정한다.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

REST_MIN = 20              # 이보다 짧으면 인정하지 않는다
REST_PAY_CAP_MIN = 30      # 한 번에 최대 30분치
DAILY_PAID_RESTS = 4       # 하루 최대 4번


@dataclass
class RestResult:
    rested_min: int
    paid_min: int
    amount: int
    reason: str | None = None   # 돈이 안 나온 이유 (나왔으면 None)


def settle_rest(start: datetime, end: datetime, eligible: bool, usual_hourly_won: int,
                paid_rests_today: int = 0, ineligible_reason: str | None = None) -> RestResult:
    """쉼 한 번의 지급 분과 금액.

    eligible: 쉼을 시작할 때 judge_start가 지급 대상이라고 했는가
    usual_hourly_won: 쉼을 시작한 시간대의 평소 시간당 수입
    paid_rests_today: 이번 쉼 전에 오늘 이미 돈을 받은 쉼 횟수
    """
    rested = max(0, int((end - start).total_seconds() // 60))
    if not eligible:
        return RestResult(rested, 0, 0, ineligible_reason or "쉬기 시작할 때 적립 조건이 맞지 않았어요")
    if paid_rests_today >= DAILY_PAID_RESTS:
        return RestResult(rested, 0, 0, f"오늘 {DAILY_PAID_RESTS}번을 다 받았어요")
    if rested < REST_MIN:
        return RestResult(rested, 0, 0, f"{REST_MIN}분보다 짧게 쉬었어요")
    paid = min(rested, REST_PAY_CAP_MIN)
    return RestResult(rested, paid, round(paid / 60 * usual_hourly_won))
