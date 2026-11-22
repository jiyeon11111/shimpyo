"""2차 보완: 활동일 기준(12/10/8일) 변경 시 지급 대상·지급액 + 라이더 유형별 지급 예시.
규칙과 simulate()는 run_final.py와 같다 (모델 체감 32℃, N 60분, 쉼 30분, 하루 4회, 금액 = 평소시급 x 30/60).
사용: python run_k.py <opps_2026_model.csv.gz> <riders.csv>
"""
import sys
import numpy as np, pandas as pd

REST = 30; CAP_DAY = 4
SCALE = {'하한': 2.5, '중간': 4.7, '상한': 7.2}   # 관악구 라이더 수(천 명), 발표 10번 슬라이드와 같음


def simulate(O, line, K, N, P, seed=1):
    rng = np.random.default_rng(seed); draws = rng.random(len(O))
    elig = (O['모델체감'].values >= line) & (O['활동일'].values >= K)
    expo, cum, mins = O['노출분'].values, O['누적이동'].values, O['분'].values
    key = (O['라이더ID'].astype(str) + O['날짜'].astype(str)).values
    rest = np.zeros(len(O), bool); last = None
    for i in range(len(O)):
        if key[i] != last: last, reset, rend, n = key[i], None, -1e9, 0
        if not elig[i] or mins[i] < rend or n >= CAP_DAY: continue
        e = expo[i] if reset is None else min(expo[i], cum[i] - reset)
        if e >= N and draws[i] < P:
            rest[i] = True; rend = mins[i] + REST; reset = cum[i]; n += 1
    return rest


O = pd.read_csv(sys.argv[1], encoding='utf-8-sig', compression='gzip')
O = O.sort_values(['라이더ID', '날짜', '분']).reset_index(drop=True)
R = pd.read_csv(sys.argv[2], encoding='utf-8-sig')[['라이더ID', '유형']]
types = ['전업', '저녁부업', '점심주말']
ntype = R['유형'].value_counts()
print('rows', len(O), '| riders', O['라이더ID'].nunique(), '| types', ntype.to_dict(), flush=True)

rows, trows, ex = [], [], {}
for K in (12, 10, 8):
    for P in (1.0, 0.5):
        rest = simulate(O, 32, K, 60, P)
        X = O[rest].copy(); X['지급액'] = X['평소시급'] * REST / 60
        per = X.groupby('라이더ID')['지급액'].agg(['sum', 'size'])
        tot = X['지급액'].sum()
        r = dict(활동일K=K, 쉼확률=P, 지급횟수=len(X), 받은라이더=len(per), 총액_억_1000명=tot / 1e8,
                 받은라이더1인평균_만원=per['sum'].mean() / 1e4)
        for k, v in SCALE.items(): r[f'관악_{k}_억'] = tot / 1e8 * v
        rows.append(r)
        per = per.join(R.set_index('라이더ID'))
        for t in types:
            g = per[per['유형'] == t]
            trows.append(dict(활동일K=K, 쉼확률=P, 유형=t, 유형인원=int(ntype[t]), 받은라이더=len(g),
                              받은비율=len(g) / ntype[t], 총액_만원=g['sum'].sum() / 1e4,
                              받은1인_평균_만원=g['sum'].mean() / 1e4, 받은1인_중앙_만원=g['sum'].median() / 1e4,
                              받은1인_평균횟수=g['size'].mean(),
                              등록1인_평균_만원=g['sum'].sum() / ntype[t] / 1e4))
        if (K, P) == (12, 0.5):
            X = X.merge(R, on='라이더ID')
            X['시'] = X['분'] // 60
            for t in types:
                g = X[X['유형'] == t]
                s = g.groupby('라이더ID')['지급액'].sum()
                rid = (s - s.median()).abs().idxmin()          # 중앙값에 가장 가까운 라이더
                gr = g[g['라이더ID'] == rid]
                ex[t] = dict(라이더ID=rid, 여름총액=int(round(s[rid])), 횟수=len(gr),
                             받은날=gr['날짜'].nunique(), 한번평균=int(round(gr['지급액'].mean())),
                             평소시급_중앙=int(round(gr['평소시급'].median())),
                             주시간대=f"{int(gr['시'].quantile(.25))}–{int(gr['시'].quantile(.75)) + 1}시",
                             한번_중앙=int(round(g['지급액'].median())))
        print(K, P, 'done', flush=True)

T = pd.DataFrame(rows); TT = pd.DataFrame(trows); E = pd.DataFrame(ex).T
T.to_csv('활동일_변경_지급.csv', index=False, encoding='utf-8-sig')
TT.to_csv('활동일_변경_유형별.csv', index=False, encoding='utf-8-sig')
E.to_csv('유형별_지급예시_K12_P05.csv', encoding='utf-8-sig')
pd.set_option('display.width', 250)
print(T.round(3).to_string(index=False)); print(TT.round(3).to_string(index=False)); print(E.to_string())
