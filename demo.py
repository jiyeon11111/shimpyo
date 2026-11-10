"""엔진 동작 확인용 예시. 가상의 폭염일 14시, 라이더 네 명이 쉬기 시작한다. 모두 지어낸 값."""
from datetime import datetime, timedelta

from engine import apparent_temp_summer, judge_start, settle_rest

at = datetime(2026, 8, 3, 14, 0)
temp = apparent_temp_summer(35.6, 55)     # 가상 기온 35.6도, 습도 55% (실제 판정은 행정동 모델 값)
print(f"14시 체감온도 {temp:.1f}도\n")


def moves(minutes_each, gap):
    """12시부터 14시까지 minutes_each분 이동, gap분 대기를 반복."""
    out, t = [], at - timedelta(hours=2)
    while t < at:
        out.append((t, t + timedelta(minutes=minutes_each)))
        t += timedelta(minutes=minutes_each + gap)
    return out


riders = [
    ("A 평소 이 시간 배달, 꾸준히 이동", 20, moves(25, 10), 25, 15_200),
    ("B 카페에서 25분씩 대기", 20, moves(15, 25), 25, 15_200),   # 20분 넘는 공백으로 노출이 계속 리셋
    ("C 최근 4주 중 이 시간대 5일만 일함", 5, moves(25, 10), 25, 0),
    ("D 15분만 쉼", 20, moves(25, 10), 15, 15_200),
]
for name, worked_days, mv, rest_min, usual in riders:
    d = judge_start(temp, worked_days, mv, at)
    r = settle_rest(at, at + timedelta(minutes=rest_min), d.pay_eligible, usual, 0, d.reasons[0] if d.reasons else None)
    print(f"{name}: 노출 {d.exposure_min}분, {rest_min}분 쉼 → {r.amount:,}원" + (f" ({r.reason})" if r.reason else ""))
