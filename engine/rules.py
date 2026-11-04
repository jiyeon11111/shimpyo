"""체감온도 단계별 판정 규칙.

규칙 값은 코드에 박지 않고 RULES 설정으로 둔다. 분석 2에서 임계값이
바뀌면 이 표의 숫자만 고치면 된다. 단계는 산업안전보건기준규칙의
체감온도 기준(31, 33, 35, 38도)에 맞춘 초안이다.

위에서부터 순서대로 확인하고, 처음 맞는 규칙 하나만 적용한다.
"""
from __future__ import annotations

from dataclasses import dataclass

# 초안 값. 분석 결과로 확정한다.
RULES: list[dict] = [
    {"level": "38+", "min_temp": 38.0, "hours": range(0, 24),  "pay": True,  "alert": "강한 휴식 알림"},
    {"level": "35+", "min_temp": 35.0, "hours": range(14, 17), "pay": True,  "alert": "휴식 알림"},
    {"level": "35+", "min_temp": 35.0, "hours": range(0, 24),  "pay": False, "alert": "휴식 권고"},
    {"level": "33+", "min_temp": 33.0, "hours": range(0, 24),  "pay": False, "alert": "휴식 권고"},
    {"level": "31+", "min_temp": 31.0, "hours": range(0, 24),  "pay": False, "alert": None},
]


@dataclass(frozen=True)
class Decision:
    level: str | None       # 해당 단계, 31도 미만이면 None
    pay_eligible: bool      # 이 시간에 쉬면 보전 대상인가
    alert: str | None       # 라이더에게 보낼 알림 종류


def judge_hour(apparent_temp: float, hour: int, rules: list[dict] = RULES) -> Decision:
    """한 격자, 한 시간의 체감온도로 지급 구간 여부를 판정한다.

    hour는 0~23 (해당 시각부터 1시간). 예: 14는 14시~15시.
    """
    if not 0 <= hour <= 23:
        raise ValueError(f"hour는 0~23이어야 합니다: {hour}")
    for rule in rules:
        if apparent_temp >= rule["min_temp"] and hour in rule["hours"]:
            return Decision(rule["level"], rule["pay"], rule["alert"])
    return Decision(None, False, None)
