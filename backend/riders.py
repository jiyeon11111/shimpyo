"""라이더 운행 기록 공급. 판정에 필요한 재료를 준다.

  - 쉼 시작 시각이 속한 시간대에 최근 28일 중 일한 날 수 (노동 확인)
  - 같은 요일·같은 시간대의 평소 시간당 수입 (최근 4주 배달료 합 ÷ 일한 시간)
  - 오늘의 실제 배달 이동 구간과 양 끝 동 (노출, 가장 오래 달린 동)

실제로는 배달 플랫폼 운행 기록에서 와야 한다. 아직 협약 전이라:
  - 시연 모드: 가상 라이더 콜 파일(data/gwanak)의 라이더 한 명(DEMO_RIDER_CODE)을 민수로 쓴다. 지어낸 값이다.
    콜 원본은 git에 안 올리므로 그 라이더의 콜만 data/gwanak/demo_rider_calls.csv로 뽑아 둔다.
  - 실제 모드: 기록이 없으므로 None을 돌려주고, 서비스는 지급 판정을 하지 않는다.
"""
from __future__ import annotations

import csv
import os
from datetime import datetime
from functools import lru_cache

from engine.records import Call, RiderBook
from engine.rules import Leg

from . import config, gwanak

DEMO_RIDER_CODE = "R0297"    # 가상라이더_관악의 전업 라이더. 앱에서는 '민수'(id 1)로 보인다
DEMO_CALLS = os.path.join(gwanak.DIR, "demo_rider_calls.csv")


def _dt(s: str) -> datetime:
    return datetime.fromisoformat(s)


def call_from_row(r: dict) -> Call:
    return Call(_dt(r["수락시각"]), _dt(r["음식점도착"]), _dt(r["픽업시각"]), _dt(r["배달완료"]),
                r["출발동코드"], r["음식점동코드"], r["고객동코드"], int(float(r["배달료"])))


@lru_cache(maxsize=1)
def demo_book() -> RiderBook:
    with open(DEMO_CALLS, encoding="utf-8-sig", newline="") as f:
        return RiderBook([call_from_row(r) for r in csv.DictReader(f)])


def _cut(legs: list[Leg], rests: list[tuple[datetime, datetime]]) -> list[Leg]:
    """쉬는 동안(콜 꺼짐)에는 배달하지 않으므로 쉼과 겹치는 부분을 잘라낸다."""
    for rs, re_ in rests:
        legs = [p for s, e, a, b in legs for p in ((s, min(e, rs), a, b), (max(s, re_), e, a, b)) if p[1] > p[0]]
    return legs


def profile(rider_id: int, t: datetime, rests: list[tuple[datetime, datetime]]) -> dict | None:
    """t 시각의 판정 재료. rests: 오늘 쉼 구간들 (진행 중이면 끝을 t로). 기록이 없으면 None."""
    if not config.DEMO_MODE:
        return None   # 플랫폼 연동 전
    book = demo_book()
    legs = _cut([leg for leg in book.legs_on(t.date()) if leg[0] < t], rests)
    return {"worked_days": book.worked_days(t), "usual_hourly": book.usual_hourly(t),
            "legs": legs, "moves": [(s, e) for s, e, _, _ in legs], "virtual": True}
