# %% [markdown]
# # 분석 5: 도로 위 실제 더위는 공식 값보다 몇 도 높은가
# 질문: 서울 도로변 센서의 체감온도는 같은 시각 기상청 관측 체감온도보다 몇 도 높은가?
# 데이터: D16 S-DoT 환경정보(서울), D01·D02 ASOS 서울(108) 지점
# 방법: 같은 시각끼리 맞대어 체감온도 차이(센서 - ASOS)를 구역별, 시각별로 비교한다.
#       결과는 알림 보정폭으로만 쓰고, 지급 판정은 공식 체감온도를 유지한다.
# 결과: outputs/a5_road_heat.png, outputs/a5_offset.csv

# %%
import pandas as pd

from common import OUT, HEAT, INK, asos_hourly, load, setup_plot, title
from engine.heat import apparent_temp_array

plt = setup_plot()
SEOUL_STN = 108

s = load("sdot", "sdot_hourly.csv")
s["time"] = pd.to_datetime(s["time"]).dt.floor("h")
s["at"] = apparent_temp_array(s["ta"], s["rh"])
a = asos_hourly()
a = a[a["stn"] == SEOUL_STN][["time", "at"]].rename(columns={"at": "at_asos"})
df = s.merge(a, on="time", how="inner")
df["diff"] = df["at"] - df["at_asos"]
df["zone_type"] = df["zone"].where(df["zone"].str.contains("도로"), "그 외")
df.loc[df["zone"].str.contains("도로"), "zone_type"] = "도로"
df["hour"] = df["time"].dt.hour

by_zone = df.groupby("zone_type")["diff"].describe()[["count", "mean", "50%", "75%"]].round(2)
by_zone.columns = ["시간 수", "평균 차이 (도)", "중앙값 (도)", "상위 25% (도)"]
afternoon = df[df["hour"].between(14, 16)].groupby("zone_type")["diff"].mean().round(2).rename("14~17시 평균 차이 (도)")
out = by_zone.join(afternoon)
out.to_csv(f"{OUT}/a5_offset.csv", encoding="utf-8-sig")
print(out)

# %% 그래프: 시각별 평균 차이
prof = df.groupby(["zone_type", "hour"])["diff"].mean().unstack(0)
fig, ax = plt.subplots(figsize=(9, 4))
if "도로" in prof:
    ax.plot(prof.index, prof["도로"], color=HEAT["38"], lw=2.2, label="도로 구역 센서")
if "그 외" in prof:
    ax.plot(prof.index, prof["그 외"], color=INK, lw=1.5, alpha=0.6, label="그 외 센서")
ax.axhline(0, color=INK, lw=0.8)
ax.axvspan(14, 17, color=HEAT["31"], alpha=0.5, lw=0)
ax.set_xlabel("시각 (시)"); ax.set_ylabel("체감온도 차이 (도, 센서 - 기상청)")
ax.legend(frameon=False)
road = out.loc["도로", "14~17시 평균 차이 (도)"] if "도로" in out.index else float("nan")
ax.set_title(title(f"도로 위는 오후 보전 시간대에 공식 값보다 {road:+.1f}도", ["sdot", "asos"]), loc="left", fontsize=12)
fig.tight_layout(); fig.savefig(f"{OUT}/a5_road_heat.png", dpi=160)
