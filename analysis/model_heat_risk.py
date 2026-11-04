# %% [markdown]
# # 모델: 온열질환 위험 예측 (유일한 학습형 모델)
# 무엇: 시도 × 일 단위 온열질환 신고 수를 예측한다.
# 왜: 지급 기준(35도, 38도)을 감이 아니라 데이터로 정당화하기 위해. 분석 2의 단순 비교를
#     연속 폭염, 열대야 같은 다른 요인을 함께 고려해 보강한다.
# 방법: 포아송 회귀(기준선) vs 그래디언트 부스팅(포아송 손실). 둘 다 scikit-learn만 쓴다.
#       LightGBM이 설치돼 있으면 함께 비교한다.
# 검증: 연도 단위 분할. 앞선 해로 학습, 2025년 검증, 2026년 테스트. 미래 정보가 학습에 섞이지 않게.
# 평가: 일별 오차(MAE)와 환자가 몰린 날(상위 10%)을 놓치지 않았는지(재현율).
# 해석: 부분의존도로 체감온도별 위험 곡선 → 31도 대비 위험이 2배·5배·10배가 되는 온도를 지급 기준 근거로 쓴다.
# 결과: outputs/model_scores.csv, outputs/model_risk_curve.png

# %%
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.inspection import partial_dependence
from sklearn.linear_model import PoissonRegressor
from sklearn.metrics import mean_absolute_error
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from common import OUT, HEAT, INK, asos_hourly, load, setup_plot, title

plt = setup_plot()

# %% 피처 만들기
h = asos_hourly()
key = "sido"
ill = load("illness", "heat_illness_daily.csv")
ill["date"] = pd.to_datetime(ill["date"])
national = set(ill["sido"]) == {"전국"}
if national:
    h["sido"] = "전국"

d = h.groupby([key, h["time"].dt.normalize()]).agg(
    atmax=("at", "max"), atmin=("at", "min"), hot_hours=("at", lambda x: (x >= 33).sum())).reset_index().rename(columns={"time": "date"})
d = d.sort_values([key, "date"])
g = d.groupby(key)
d["atmax_prev"] = g["atmax"].shift(1)
d["tropical_night"] = (d["atmin"] >= 25).astype(int)
# 연속 폭염일수: 체감 33도 이상이 며칠째 이어지는가
d["hot"] = (d["atmax"] >= 33).astype(int)
d["streak"] = g["hot"].transform(lambda s: s.groupby((s != s.shift()).cumsum()).cumsum() * s)
d["month"] = d["date"].dt.month
d["dow"] = d["date"].dt.dayofweek
d["year"] = d["date"].dt.year
d = d.merge(ill, on=[key, "date"], how="inner").dropna()
d = pd.get_dummies(d, columns=[key], prefix="r", dtype=float) if not national else d
FEATS = ["atmax", "atmax_prev", "hot_hours", "tropical_night", "streak", "month", "dow"] + [c for c in d.columns if c.startswith("r_")]

# %% 연도 단위 분할
test_year, val_year = d["year"].max(), d["year"].max() - 1
tr, va, te = d[d["year"] < val_year], d[d["year"] == val_year], d[d["year"] == test_year]
print(f"학습 {tr['year'].min()}~{tr['year'].max()} ({len(tr)}일), 검증 {val_year} ({len(va)}일), 테스트 {test_year} ({len(te)}일)")

models = {
    "포아송 회귀 (기준선)": make_pipeline(StandardScaler(), PoissonRegressor(alpha=1e-3, max_iter=1000)),
    # 더울수록 위험이 줄어드는 이상한 모양이 나오지 않게, 더위 관련 피처에 '증가만' 제약을 건다
    "그래디언트 부스팅 (포아송)": HistGradientBoostingRegressor(
        loss="poisson", max_iter=300, learning_rate=0.05, random_state=0,
        monotonic_cst=[1 if f in ("atmax", "atmax_prev", "hot_hours", "streak") else 0 for f in FEATS]),
}
try:
    import lightgbm as lgb
    models["LightGBM (포아송)"] = lgb.LGBMRegressor(objective="poisson", n_estimators=400, learning_rate=0.03, verbose=-1)
except ImportError:
    pass

def recall_top(y_true, y_pred, q=0.9):
    thr = np.quantile(y_true, q)
    hi = y_true >= thr
    return (y_pred[hi] >= np.quantile(y_pred, q)).mean()

rows, fitted = [], {}
for name, m in models.items():
    m.fit(tr[FEATS], tr["cases"])
    fitted[name] = m
    for split, part in [("검증", va), ("테스트", te)]:
        p = m.predict(part[FEATS])
        rows.append({"모델": name, "구분": split, "MAE (명/일)": round(mean_absolute_error(part["cases"], p), 2),
                     "고위험일 재현율": round(recall_top(part["cases"].to_numpy(), p), 2)})
scores = pd.DataFrame(rows)
scores.to_csv(f"{OUT}/model_scores.csv", index=False, encoding="utf-8-sig")
print(scores)

# %% 해석: 검증 성적이 가장 좋은 모델의 체감온도별 위험 곡선
best = scores[scores["구분"] == "검증"].sort_values("MAE (명/일)").iloc[0]["모델"]
pdp = partial_dependence(fitted[best], d[FEATS], ["atmax"], grid_resolution=50, percentiles=(0.01, 0.995))
grid, curve = pdp["grid_values"][0], pdp["average"][0]
rel = curve / np.interp(31, grid, curve)  # 31도 대비 배수
# 위험이 31도의 2배, 5배, 10배가 되는 체감온도: 지급 기준 후보를 설명하는 숫자
marks = {}
for k in (2, 5, 10):
    above = np.where(rel >= k)[0]
    marks[k] = float(grid[above[0]]) if len(above) else float("nan")
pd.DataFrame({"체감온도": grid.round(1), "31도 대비 위험 배수": rel.round(2)}).to_csv(f"{OUT}/model_risk_curve.csv", index=False, encoding="utf-8-sig")
print(f"최적 모델: {best}. 31도 대비 위험 2배: {marks[2]:.1f}도, 5배: {marks[5]:.1f}도, 10배: {marks[10]:.1f}도")

fig, ax = plt.subplots(figsize=(9, 4.2))
ax.plot(grid, rel, color=INK, lw=2.2)
for b, c in ((33, HEAT["33"]), (35, HEAT["35"]), (38, HEAT["38"])):
    ax.axvline(b, color=c, lw=2, alpha=0.8)
    ax.text(b + 0.1, rel.max() * 0.95, f"{b}도", fontsize=9, color=INK)
for k, t in marks.items():
    if not np.isnan(t):
        yk = float(np.interp(t, grid, rel))
        ax.plot([t], [yk], "o", color=INK, ms=4)
        ax.annotate(f"{k}배 · {t:.1f}도", (t, yk), textcoords="offset points", xytext=(-58, 6), fontsize=9)
ax.set_xlabel("일 최고 체감온도 (도)"); ax.set_ylabel("온열질환 위험 (31도 대비 배수)")
ax.set_title(title(f"체감온도별 온열질환 위험 곡선 ({best})", ["asos", "illness"]), loc="left", fontsize=12)
fig.tight_layout(); fig.savefig(f"{OUT}/model_risk_curve.png", dpi=160)
