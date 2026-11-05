"""라이더 운행 기록 공급. 판정에 필요한 세 가지를 준다.

  - 최근 4주 동안 이 시간대에 일했는가
  - 이 시간대 평소 시간당 수입 (최근 4주 평균)
  - 오늘의 실제 배달 이동 구간 (콜 수락 → 음식점 → 고객)

실제로는 배달 플랫폼 운행 기록에서 와야 한다. 아직 협약 전이라:
  - 시연 모드: 아래 가상 라이더(민수) 프로필을 쓴다. 모두 지어낸 값이다.
  - 실제 모드: 기록이 없으므로 None을 돌려주고, 서비스는 지급 판정을 하지 않는다.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from . import config

# 가상 라이더 민수: 최근 4주 평일 10~18시에 배달. 시간대별 평소 시간당 수입(원). 지어낸 값.
DEMO_WORK_HOURS = range(10, 18)
DEMO_USUAL_HOURLY = {10: 13_800, 11: 17_200, 12: 21_500, 13: 18_900, 14: 14_600, 15: 13_900, 16: 15_200, 17: 19_800}
# 가상 하루: 10시부터 35분마다 25분 이동, 10분은 음식점·고객 앞 대기
DEMO_CYCLE_MIN, DEMO_MOVE_MIN = 35, 25


def _demo_moves(day: datetime, rests: list[tuple[datetime, datetime]]) -> list[tuple[datetime, datetime]]:
    """가상 이동 구간. 쉬는 동안(콜 꺼짐)에는 배달하지 않으므로 쉼과 겹치는 부분을 잘라낸다."""
    out = []
    t, stop = day.replace(hour=10, minute=0), day.replace(hour=20, minute=0)
    while t < stop:
        pieces = [(t, t + timedelta(minutes=DEMO_MOVE_MIN))]
        for rs, re_ in rests:
            pieces = [p for s, e in pieces for p in ((s, min(e, rs)), (max(s, re_), e)) if p[1] > p[0]]
        out += pieces
        t += timedelta(minutes=DEMO_CYCLE_MIN)
    return out


def profile(rider_id: int, t: datetime, rests: list[tuple[datetime, datetime]]) -> dict | None:
    """t 시각의 판정 재료. rests: 오늘 쉼 구간들 (진행 중이면 끝을 t로). 기록이 없으면 None."""
    if not config.DEMO_MODE:
        return None   # 플랫폼 연동 전
    return {"worked_slot": t.hour in DEMO_WORK_HOURS,
            "usual_hourly": DEMO_USUAL_HOURLY.get(t.hour, 0),
            "moves": _demo_moves(t, rests),
            "virtual": True}
