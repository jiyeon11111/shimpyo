"""회의록 11/7 기준 분석 3·4 (모델 체감온도, 판정선 32℃)"""
import pandas as pd, numpy as np
BANDS=['아침','오전','낮','오후','밤']; LIM=[(6,9),(9,12),(12,15),(15,18),(18,22)]
R=pd.read_csv('/home/claude/sim/out/가상라이더_관악_라이더.csv')[['라이더ID','유형']]
REST=30; CAP_DAY=4

def prep(y):
    O=pd.read_pickle(f'opps_{y}.pkl')
    if '활동일' not in O:
        A=pd.read_pickle(f'active_{y}.pkl')
        days=pd.date_range(f'{y}-04-17',f'{y}-09-30'); di={d:i for i,d in enumerate(days)}
        rid=sorted(R['라이더ID']); ri={r:i for i,r in enumerate(rid)}
        M=np.zeros((len(rid),len(days),5),np.int16)
        M[A['라이더ID'].map(ri).values,A['날짜'].map(di).values]=A[BANDS].values.astype(np.int16)
        cs=np.concatenate([np.zeros((len(rid),1,5),np.int32),np.cumsum(M,axis=1)],axis=1)
        t=O['날짜'].map(di).values; r=O['라이더ID'].map(ri).values; h=O['분'].values/60
        b=np.full(len(O),-1)
        for k,(lo,hi) in enumerate(LIM): b[(h>=lo)&(h<hi)]=k
        ok=b>=0; cnt=np.full(len(O),-1)
        cnt[ok]=cs[r[ok],t[ok],b[ok]]-cs[r[ok],np.maximum(t[ok]-28,0),b[ok]]
        O['활동일']=cnt
    Mo=pd.read_csv(f'관악_동별체감온도_모델_{y}.csv.gz',dtype={'행정동코드':str})
    Mo['시각']=pd.to_datetime(Mo['시각'])
    key=dict(zip(zip(Mo['행정동코드'],Mo['시각']),Mo['체감온도']))
    stamp=O['날짜']+pd.to_timedelta((O['분']//60+1).astype(int),unit='h')
    O['모델체감']=[key.get((d,s),np.nan) for d,s in zip(O['동'],stamp)]
    return O.sort_values(['라이더ID','날짜','분']).reset_index(drop=True)

def simulate(O,line,K,N,P,seed=1):
    rng=np.random.default_rng(seed); draws=rng.random(len(O))
    elig=(O['모델체감'].values>=line)&(O['활동일'].values>=K)
    expo,cum,mins=O['노출분'].values,O['누적이동'].values,O['분'].values
    key=(O['라이더ID'].astype(str)+O['날짜'].astype(str)).values
    rest=np.zeros(len(O),bool); last=None
    for i in range(len(O)):
        if key[i]!=last: last,reset,rend,n=key[i],None,-1e9,0
        if not elig[i] or mins[i]<rend or n>=CAP_DAY: continue
        e=expo[i] if reset is None else min(expo[i],cum[i]-reset)
        if e>=N and draws[i]<P:
            rest[i]=True; rend=mins[i]+REST; reset=cum[i]; n+=1
    return rest

rows=[]; detail={}
for y in (2025,2026):
    O=prep(y); O.to_pickle(f'opps_{y}_model.pkl')
    print(y,'모델 32↑ 순간',round((O['모델체감']>=32).mean()*100,1),'% | 33↑',round((O['모델체감']>=33).mean()*100,1),'% | 결측',O['모델체감'].isna().sum(),flush=True)
    combos=[(32,12,N,P) for N in (50,60) for P in (1.0,0.5,0.25)]
    if y==2025: combos+=[(33,12,60,1.0)]+[(32,K,60,1.0) for K in (8,16,21)]
    for line,K,N,P in combos:
        rest=simulate(O,line,K,N,P)
        X=O[rest]
        for ratio in (1.0,1.1):
            pay=X['평소시급'].values*ratio*REST/60
            per=pd.Series(pay).groupby(X['라이더ID'].values).sum()
            rows.append(dict(연도=y,판정선=line,활동일K=K,N분=N,쉼확률=P,금액비율=ratio,지급횟수=len(X),
                받은라이더=X['라이더ID'].nunique(),총액_억_1000명=pay.sum()/1e8,라이더1인평균_만원=pay.sum()/1000/1e4,
                한번_중앙=np.median(pay),한번_99=np.percentile(pay,99),하루평균횟수=len(X)/max(1,X.groupby(['라이더ID','날짜']).ngroups)))
        if (y,line,K,N,P)==(2026,32,12,60,1.0): detail['hourly']=X['평소시급']
T=pd.DataFrame(rows); T.to_csv('최종_분석34_모델32.csv',index=False,encoding='utf-8-sig')
pd.set_option('display.width',250)
print(T.round(2).to_string(index=False))
print('2026 지급된 쉼의 평소시급 분위 50/90/99:',np.percentile(detail['hourly'],[50,90,99]).round(0))
