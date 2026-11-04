"""엔진 동작 확인용 예시. 가상의 폭염일 하루, 라이더 세 명."""
from engine import RiderDay, apparent_temp_summer, settle_day

# 가상의 한 격자 시간별 기온(섭씨)과 습도(%)
weather = {11: (32.5, 62), 12: (33.4, 60), 13: (34.2, 58), 14: (35.0, 57),
           15: (35.6, 55), 16: (35.1, 56), 17: (34.0, 58), 18: (32.6, 62)}
temps = {h: apparent_temp_summer(ta, rh) for h, (ta, rh) in weather.items()}

print("시각  기온  습도  체감온도")
for h, (ta, rh) in weather.items():
    print(f"{h:>3}시  {ta:4.1f}  {rh:3d}%   {temps[h]:4.1f}")

riders = [
    RiderDay("A", "2026-08-03", (60, 127), worked_today=True),                    # 폭염 시간에 쉼
    RiderDay("B", "2026-08-03", (60, 127), worked_today=True, busy_hours={14, 15}),  # 일부 시간 배달
    RiderDay("C", "2026-08-03", (60, 127), worked_today=False),                   # 운행 기록 없음
]
print()
for rd in riders:
    r = settle_day(rd, temps)
    print(f"라이더 {r.rider_id}: 보전 시각 {r.paid_hours or '-'}, 금액 {r.amount:,}원")
