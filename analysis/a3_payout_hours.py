# %% [markdown]
# # 분석 3: 1년에 몇 시간이 33도를 넘는가, 얼마가 드는가
# 질문: 지역별로 1년에 체감 33도 이상인 시간이 얼마이고, 라이더 전체에 필요한 예산은 얼마인가?
# 데이터: D01·D02 ASOS, D08 시도별 라이더 수, 기준은 engine/rules.py·payout.py 그대로
# 방법: 과거 각 연도 시간자료에서 33도 이상인 시간을 센다 → 시도별 연간 시간.
#       법 기준 "2시간마다 20분"에 맞춰 33도 이상 2시간마다 쉼 한 번으로 본다 (하루 4번 상한은 근사).
#       예산 = 라이더 수 × 쉼 횟수 × 참여율 × 한 번 지급(30분치 × 평소 시간당 수입 가정)
#       자격·노출 조건으로 실제 지급은 이보다 적다 → 보수적 상한값
# 결과: outputs/a3_hours_by_region.png, outputs/a3_budget.csv

# %%
import numpy as np
import pandas as pd

from common import OUT, HEAT, INK, asos_hourly, hot_hours, load, setup_plot, title
from engine.payout import DAILY_PAID_RESTS, REST_PAY_CAP_MIN

plt = setup_plot()
PARTICIPATION = 0.5          # 33도 이상에 실제로 쉬는 비율 (가정, 시뮬레이션으로 조정)
USUAL_HOURLY_WON = 15_000    # 평소 시간당 수입 (가정, 라이더 실태조사로 교체)

h = asos_hourly()
h["pay"] = hot_hours(h)
h["year"] = h["time"].dt.year
# 시도에 지점이 여럿이면 지점 평균
hours = h.groupby(["sido", "year", "stn"])["pay"].sum().groupby(["sido", "year"]).mean().unstack("year")
summary = pd.DataFrame({
    "평균 해 (시간)": hours.mean(axis=1).round(1),
    "더운 해, 상위 10% (시간)": hours.quantile(0.9, axis=1).round(1),
    "최근 해 (시간)": hours[hours.columns.max()].round(1),
})

riders = load("riders", "riders_by_region.csv").set_index("sido")["riders"]
summary["라이더 수"] = riders.reindex(summary.index)
# ponytail: 하루 4번 상한은 연간 시간에 바로 못 붙여서 "여름 4.5개월 × 하루 4번"으로 연 상한을 자른다. 일별 집계로 바꾸면 정확해짐
annual_cap_rests = DAILY_PAID_RESTS * 30 * 4.5
per_rest_won = REST_PAY_CAP_MIN / 60 * USUAL_HOURLY_WON
for col, label in [("평균 해 (시간)", "평균 해 예산 (억원)"), ("더운 해, 상위 10% (시간)", "더운 해 예산 (억원)")]:
    per_rider = np.minimum(summary[col] / 2, annual_cap_rests) * PARTICIPATION * per_rest_won
    summary[label] = (per_rider * summary["라이더 수"] / 1e8).round(1)
summary.loc["합계", ["라이더 수", "평균 해 예산 (억원)", "더운 해 예산 (억원)"]] = summary[["라이더 수", "평균 해 예산 (억원)", "더운 해 예산 (억원)"]].sum()
summary.to_csv(f"{OUT}/a3_budget.csv", encoding="utf-8-sig")
print(summary)

# %% 그래프: 시도별 평균 해와 더운 해의 지급 구간 시간
s = summary.drop(index="합계").sort_values("평균 해 (시간)")
fig, ax = plt.subplots(figsize=(9, 4.2))
y = np.arange(len(s))
ax.barh(y, s["더운 해, 상위 10% (시간)"], color=HEAT["35"], alpha=0.35, label="더운 해 (상위 10%)")
ax.barh(y, s["평균 해 (시간)"], color=HEAT["35"], label="평균 해")
ax.set_yticks(y, s.index)
ax.set_xlabel("연간 체감 33도 이상 시간 (시간)")
ax.legend(frameon=False, loc="lower right")
ax.set_title(title("지역별 1년 중 체감 33도를 넘는 시간", ["asos", "riders"]), loc="left", fontsize=12)
fig.tight_layout(); fig.savefig(f"{OUT}/a3_hours_by_region.png", dpi=160)
