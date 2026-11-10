# %% [markdown]
# # 분석 4: 기존 방식과 비교 (보장 공백)
# 질문: 특보 기준(제주 방식: 오후 1시 이전 폭염경보 발효 시 보전)이었다면 놓치는 위험 시간은 얼마인가?
# 데이터: D01·D02 ASOS, D05 폭염특보 이력
# 방법: 같은 시간자료에 두 기준을 적용한다.
#   - 쉼표 기준: engine/rules.py의 체감온도 기준 (32도 이상, 시간대 제한 없음).
#     자격·노출 조건은 라이더 자료가 있어야 해서 여기서는 기온 조건만 비교한다.
#   - 특보 기준: 그 시도에 폭염경보 이상이 오후 1시 이전 발효된 날의 14~17시
#   쉼표 기준으로는 위험한데 특보 기준으로는 보전받지 못하는 시간을 '보장 공백'으로 센다.
# 결과: outputs/a4_gap.png, outputs/a4_gap.csv

# %%
import pandas as pd

from common import OUT, HEAT, INK, asos_hourly, hot_hours, load, setup_plot, title

plt = setup_plot()

h = asos_hourly()
h["ours"] = hot_hours(h)
h["date"] = h["time"].dt.date

w = load("warnings", "heat_warnings.csv")
w["start"] = pd.to_datetime(w["start"])
w = w[w["kind"].isin(["경보", "중대경보"]) & (w["start"].dt.hour < 13)]
warn_days = set(zip(w["sido"], w["start"].dt.date))
h["alert_rule"] = pd.Series([(s, d) in warn_days for s, d in zip(h["sido"], h["date"])], index=h.index) & h["time"].dt.hour.between(14, 16)
h["gap"] = h["ours"] & ~h["alert_rule"]

h["year"] = h["time"].dt.year
g = h.groupby(["sido", "year", "stn"]).agg(ours=("ours", "sum"), alert=("alert_rule", "sum"), gap=("gap", "sum"))
res = g.groupby("sido").mean().round(1)
res.columns = ["쉼표 기준 위험 시간", "특보 기준 보전 시간", "특보 기준이 놓친 시간"]
res["놓친 비율 (%)"] = (res["특보 기준이 놓친 시간"] / res["쉼표 기준 위험 시간"] * 100).round(1)
res.to_csv(f"{OUT}/a4_gap.csv", encoding="utf-8-sig")
print(res)

# %% 그래프
r = res.sort_values("쉼표 기준 위험 시간")
fig, ax = plt.subplots(figsize=(9, 4.2))
ax.barh(r.index, r["쉼표 기준 위험 시간"] - r["특보 기준이 놓친 시간"], color=INK, alpha=0.75, label="특보 기준으로도 보전")
ax.barh(r.index, r["특보 기준이 놓친 시간"], left=r["쉼표 기준 위험 시간"] - r["특보 기준이 놓친 시간"], color=HEAT["38"], label="특보 기준이 놓친 시간")
ax.set_xlabel("연평균 시간 (시간, 관측지점 평균)")
ax.legend(frameon=False, loc="lower right")
total = res["특보 기준이 놓친 시간"].sum() / res["쉼표 기준 위험 시간"].sum() * 100
ax.set_title(title(f"특보 기준은 위험 시간의 {total:.0f}%를 놓친다", ["asos", "warnings"]), loc="left", fontsize=12)
fig.tight_layout(); fig.savefig(f"{OUT}/a4_gap.png", dpi=160)
