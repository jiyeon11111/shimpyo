# %% [markdown]
# # 분석 3: 1년에 몇 시간이 지급 구간인가, 얼마가 드는가
# 질문: 지역별로 1년에 몇 시간이 보전 구간이고, 라이더 전체에 필요한 예산은 얼마인가?
# 데이터: D01·D02 ASOS, D08 시도별 라이더 수, 판정 규칙은 engine/rules.py 그대로
# 방법: 과거 각 연도 시간자료에 판정 규칙을 적용 → 시도별 연간 지급 구간 시간.
#       예산 = 라이더 수 × 지급 구간 시간 × 휴식 참여율 × 시간당 단가 (상한 적용 전, 보수적 상한값)
# 결과: outputs/a3_hours_by_region.png, outputs/a3_budget.csv

# %%
import numpy as np
import pandas as pd

from common import OUT, HEAT, INK, asos_hourly, load, payable, setup_plot, title
from engine.payout import HOURLY_RATE, MONTHLY_CAP_HOURS

plt = setup_plot()
PARTICIPATION = 0.5   # 지급 구간에 실제로 쉬는 비율 (가정, 시뮬레이션으로 조정)

h = asos_hourly()
h["pay"] = payable(h)
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
# 한 달 상한(시간)을 넘는 부분은 지급하지 않으므로, 여름 4.5개월 기준 연 상한으로 자른다
annual_cap = MONTHLY_CAP_HOURS * 4.5
for col, label in [("평균 해 (시간)", "평균 해 예산 (억원)"), ("더운 해, 상위 10% (시간)", "더운 해 예산 (억원)")]:
    per_rider = np.minimum(summary[col], annual_cap) * PARTICIPATION * HOURLY_RATE
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
ax.set_xlabel("연간 지급 구간 시간 (시간)")
ax.legend(frameon=False, loc="lower right")
ax.set_title(title("지역별 1년 중 보전 구간에 드는 시간", ["asos", "riders"]), loc="left", fontsize=12)
fig.tight_layout(); fig.savefig(f"{OUT}/a3_hours_by_region.png", dpi=160)
