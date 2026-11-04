"""체감온도 계산.

기상청 여름철 체감온도 산출식(2022.6.2 적용)을 그대로 구현한다.
출처: 기상자료개방포털 체감온도 안내
    체감온도 = -0.2442 + 0.55399*Tw + 0.45535*Ta - 0.0022*Tw^2 + 0.00278*Tw*Ta + 3.0
    Tw(습구온도)는 Stull(2011) 추정식으로 기온(Ta)과 상대습도(RH)에서 계산한다.

과거 ASOS 자료에는 체감온도 값이 따로 없으므로, 분석과 실시간 판정이
같은 공식을 쓰도록 이 함수 하나만 사용한다.
"""
from __future__ import annotations

import math


def wet_bulb_stull(ta: float, rh: float) -> float:
    """기온(섭씨)과 상대습도(%)로 습구온도(섭씨)를 추정한다 (Stull, 2011)."""
    if not 0 <= rh <= 100:
        raise ValueError(f"상대습도는 0~100% 범위여야 합니다: {rh}")
    return (
        ta * math.atan(0.151977 * math.sqrt(rh + 8.313659))
        + math.atan(ta + rh)
        - math.atan(rh - 1.67633)
        + 0.00391838 * rh ** 1.5 * math.atan(0.023101 * rh)
        - 4.686035
    )


def apparent_temp_summer(ta: float, rh: float) -> float:
    """기상청 여름철 체감온도(섭씨). 소수 첫째 자리로 반올림한다."""
    tw = wet_bulb_stull(ta, rh)
    value = (
        -0.2442
        + 0.55399 * tw
        + 0.45535 * ta
        - 0.0022 * tw ** 2
        + 0.00278 * tw * ta
        + 3.0
    )
    return round(value, 1)


def apparent_temp_array(ta, rh):
    """apparent_temp_summer와 같은 식을 배열(numpy, pandas)에 한 번에 적용한다. 분석용."""
    import numpy as np
    ta = np.asarray(ta, dtype=float)
    rh = np.clip(np.asarray(rh, dtype=float), 0, 100)
    tw = (ta * np.arctan(0.151977 * np.sqrt(rh + 8.313659)) + np.arctan(ta + rh)
          - np.arctan(rh - 1.67633) + 0.00391838 * rh ** 1.5 * np.arctan(0.023101 * rh) - 4.686035)
    return np.round(-0.2442 + 0.55399 * tw + 0.45535 * ta - 0.0022 * tw ** 2 + 0.00278 * tw * ta + 3.0, 1)
