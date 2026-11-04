# %% [markdown]
# # 분석 2: 지급 임계값 정하기
# 질문: 일 최고 체감온도 몇 도부터 온열질환이 급증하는가? 35도와 38도 기준이 맞는가?
# 데이터: D01·D02 ASOS, D09 온열질환 일별 신고 수 (D13 인구가 있으면 10만 명당으로 바꿔도 됨)
# 방법: 시도 × 일 단위로 일 최고 체감온도를 1도 구간으로 나누고, 구간별 하루 평균 환자 수를 비교한다.
#       전국 자료뿐이면 시도 칸이 '전국'이고, 체감온도는 관측지점 평균을 쓴다.
# 결과: outputs/a2_threshold.png, outputs/a2_by_bin.csv

# %%
import numpy as np
import pandas as pd

from common import OUT, INK, HEAT, asos_hourly, load, setup_plot, title

plt = setup_plot()

h = asos_hourly()
ill = load("illness", "heat_illness_daily.csv")
ill["date"] = pd.to_datetime(ill["date"]).dt.date

if set(ill["sido"]) == {"전국"}:
    atmax = h.groupby(["stn", h["time"].dt.date])["at"].max().groupby(level=1).mean().rename("atmax").reset_index()
    atmax = atmax.rename(columns={"time": "date"}).assign(sido="전국")
else:
    atmax = h.groupby(["sido", h["time"].dt.date])["at"].max().rename("atmax").reset_index().rename(columns={"time": "date"})

df = atmax.merge(ill, on=["sido", "date"], how="inner")
df["bin"] = np.floor(df["atmax"]).clip(26, 40).astype(int)
by = df.groupby("bin")["cases"].agg(["mean", "count"]).rename(columns={"mean": "하루 평균 환자수", "count": "날 수"})
by = by[by["날 수"] >= 10]
by["직전 구간 대비 배율"] = (by["하루 평균 환자수"] / by["하루 평균 환자수"].shift(1)).round(2)
by.to_csv(f"{OUT}/a2_by_bin.csv", encoding="utf-8-sig")
print(by)

# %% 그래프
fig, ax = plt.subplots(figsize=(9, 4.2))
colors = [HEAT["38"] if b >= 38 else HEAT["35"] if b >= 35 else HEAT["33"] if b >= 33 else HEAT["31"] if b >= 31 else "#d5dae0" for b in by.index]
ax.bar(by.index, by["하루 평균 환자수"], color=colors, width=0.8)
for b in (35, 38):
    ax.axvline(b - 0.5, color=INK, lw=1, ls="--")
    ax.text(b - 0.4, ax.get_ylim()[1] * 0.92, f"{b}도 기준", fontsize=9)
ax.set_xlabel("시도별 일 최고 체감온도 (도, 1도 구간)")
ax.set_ylabel("시도 하루 평균 온열질환자 (명)")
ax.set_title(title("체감온도 구간별 하루 평균 온열질환자", ["asos", "illness"]), loc="left", fontsize=12)
fig.tight_layout(); fig.savefig(f"{OUT}/a2_threshold.png", dpi=160)
