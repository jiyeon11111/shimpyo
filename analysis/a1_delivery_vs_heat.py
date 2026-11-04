# %% [markdown]
# # 분석 1: 폭염과 배달 수요
# 질문: 폭염일이 하루 늘 때 음식서비스 거래액은 몇 % 늘어나는가?
# 데이터: D07 음식서비스 거래액(월별), D01·D02 ASOS(월별 폭염일수 계산용)
# 방법: log(거래액) ~ 장기 추세 + 월별 계절 효과 + 폭염일수. 추세와 계절을 빼야
#       "원래 여름에 많이 시킨다"와 "더워서 더 시킨다"가 구분된다.
# 결과: outputs/a1_delivery_vs_heat.png, outputs/a1_result.csv

# %%
import numpy as np
import pandas as pd

from common import OUT, INK, HEAT, asos_hourly, load, setup_plot, title

plt = setup_plot()

# %% 월별 전국 폭염일수: 관측지점별 일 최고 체감온도 33도 이상인 날의 지점 평균
h = asos_hourly()
daily = h.groupby(["stn", h["time"].dt.date])["at"].max().reset_index()
daily["month"] = pd.to_datetime(daily["time"]).dt.to_period("M")
heat_days = daily.assign(hot=daily["at"] >= 33).groupby(["month", "stn"])["hot"].sum().groupby("month").mean()

sales = load("delivery", "food_delivery_monthly.csv")
sales["month"] = pd.PeriodIndex(sales["month"], freq="M")
df = sales.set_index("month").join(heat_days.rename("heat_days")).fillna({"heat_days": 0})
df = df[df.index >= pd.Period("2017-01", "M")]

# %% 회귀: numpy 최소제곱 (추가 패키지 없이)
t = np.arange(len(df))
X = np.column_stack([np.ones(len(df)), t, t ** 2] + [(df.index.month == m).astype(float) for m in range(2, 13)] + [df["heat_days"]])
y = np.log(df["sales"].to_numpy())
beta, *_ = np.linalg.lstsq(X, y, rcond=None)
resid = y - X @ beta
sigma2 = resid @ resid / (len(y) - X.shape[1])
se = np.sqrt(np.diag(sigma2 * np.linalg.inv(X.T @ X)))
effect, effect_se = beta[-1], se[-1]
pct = (np.exp(effect) - 1) * 100
lo, hi = (np.exp(effect - 1.96 * effect_se) - 1) * 100, (np.exp(effect + 1.96 * effect_se) - 1) * 100
pd.DataFrame([{"폭염일 1일당 거래액 변화(%)": round(pct, 2), "95% 하한": round(lo, 2), "95% 상한": round(hi, 2), "표본(개월)": len(df)}]).to_csv(
    f"{OUT}/a1_result.csv", index=False, encoding="utf-8-sig")
print(f"폭염일 하루당 음식서비스 거래액 {pct:+.2f}% (95% 구간 {lo:+.2f}% ~ {hi:+.2f}%), {len(df)}개월")

# %% 그래프: 거래액(선)과 폭염일수(막대)
fig, ax = plt.subplots(figsize=(11, 4.2))
x = df.index.to_timestamp()
ax2 = ax.twinx()
ax2.bar(x, df["heat_days"], width=22, color=HEAT["35"], alpha=0.55, label="월 폭염일수")
ax.plot(x, df["sales"] / 1e6, color=INK, lw=2, label="음식서비스 거래액")
ax.set_ylabel("거래액 (조원)")
ax2.set_ylabel("폭염일수 (일, 체감 33도 이상)")
ax2.spines["right"].set_visible(True)
ax.set_zorder(ax2.get_zorder() + 1); ax.patch.set_visible(False)
ax.set_title(title(f"더운 달에 배달이 더 늘어난다: 폭염일 하루당 거래액 {pct:+.2f}%", ["delivery", "asos"]), loc="left", fontsize=12)
fig.tight_layout(); fig.savefig(f"{OUT}/a1_delivery_vs_heat.png", dpi=160)
