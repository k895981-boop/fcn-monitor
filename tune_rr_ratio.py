"""
盈虧比優化：在 v5.0 基礎上，測試不同的移動停利 / 停利參數組合
目標：維持高勝率的同時，把平均獲利拉大（提升盈虧比）
"""
import pandas as pd
import numpy as np
import warnings
warnings.filterwarnings('ignore')
from datetime import time, date, timedelta, datetime

CSV_FILE        = 'txf_1min.csv'
ATR_PERIOD      = 14
ATR_SL_MULT     = 0.4       # 停損固定不動
ATR_FILTER_PCT  = 25
ENTRY_EARLIEST  = time(9, 15)
FIRST_BAR_START = time(8, 45)
DAY_END_NORMAL  = time(13, 40)
DAY_END_SETTLE  = time(13, 25)
POINT_VALUE     = 10
COMMISSION      = 30

def is_settlement_day(d):
    if d.weekday() != 2: return False
    return sum(1 for x in range(1,d.day+1) if date(d.year,d.month,x).weekday()==2)==3

print('載入資料...')
raw = pd.read_csv(CSV_FILE, encoding='utf-8-sig')
raw['DateTime'] = pd.to_datetime(raw['Date'].astype(str)+' '+raw['Time'].astype(str))
raw = raw.sort_values('DateTime').reset_index(drop=True)
raw_idx = raw.set_index('DateTime')

df15 = raw_idx[['Open','High','Low','Close','Volume']].resample('15min',label='left').agg(
    {'Open':'first','High':'max','Low':'min','Close':'last','Volume':'sum'}
).dropna().reset_index()
df15['Date'] = df15['DateTime'].dt.date
df15['Time'] = df15['DateTime'].dt.time

daily = raw_idx[['Open','High','Low','Close']].resample('1D').agg(
    {'Open':'first','High':'max','Low':'min','Close':'last'}).dropna()
daily['PC']  = daily['Close'].shift(1)
daily['TR']  = daily.apply(lambda r: max(
    r['High']-r['Low'],
    abs(r['High']-r['PC']) if pd.notna(r['PC']) else 0,
    abs(r['Low'] -r['PC']) if pd.notna(r['PC']) else 0), axis=1)
daily['ATR'] = daily['TR'].rolling(ATR_PERIOD).mean()
atr_map = {d.date(): v for d,v in zip(daily.index, daily['ATR'])}

raw['_date'] = raw['DateTime'].dt.date
raw['_time'] = raw['DateTime'].dt.time
day_raw = raw[(raw['_time']>=time(8,45))&(raw['_time']<=time(13,45))].copy()
day_raw['TP']     = (day_raw['High']+day_raw['Low']+day_raw['Close'])/3
day_raw['TPV']    = day_raw['TP']*day_raw['Volume']
day_raw['cumTPV'] = day_raw.groupby('_date')['TPV'].cumsum()
day_raw['cumVol'] = day_raw.groupby('_date')['Volume'].cumsum()
day_raw['VWAP']   = day_raw['cumTPV']/day_raw['cumVol']
vwap_idx = day_raw.set_index('DateTime')[['VWAP']]

valid_atrs = np.array([v for v in atr_map.values() if not np.isnan(v)])
atr_thresh = np.percentile(valid_atrs, ATR_FILTER_PCT)

def get_vwap_at(dt):
    loc = vwap_idx.index.searchsorted(dt, side='right')-1
    return float(vwap_idx.iloc[loc]['VWAP']) if loc>=0 else np.nan

def run(trail_trigger, trail_dist, tp_mult, use_trailing=True):
    trades = []
    for trade_date, group in df15.groupby('Date'):
        atr = atr_map.get(trade_date, np.nan)
        if pd.isna(atr) or atr<=0 or atr<atr_thresh: continue
        sl = max(1, round(atr * ATR_SL_MULT))
        tp = max(1, round(atr * tp_mult)) if tp_mult else 99999

        settle  = is_settlement_day(trade_date)
        day_end = DAY_END_SETTLE if settle else DAY_END_NORMAL
        group = group.sort_values('Time').reset_index(drop=True)
        fb = group[group['Time']==FIRST_BAR_START]
        if fb.empty: continue
        fh = fb.iloc[0]['High']; fl = fb.iloc[0]['Low']
        subsequent = group[group['Time']>FIRST_BAR_START]
        if subsequent.empty: continue

        direction = entry = ex_reason = None
        pnl = 0; peak = 0

        for _, bar in subsequent.iterrows():
            if bar['Time'] > day_end: break
            if direction is None:
                if bar['Time'] < ENTRY_EARLIEST: continue
                cand = None
                if bar['High']>fh: cand='多'
                elif bar['Low']<fl: cand='空'
                if cand:
                    bdt = datetime.combine(trade_date, bar['Time'])
                    vv  = get_vwap_at(bdt)
                    if not np.isnan(vv):
                        if cand=='多' and bar['Close']<vv: continue
                        if cand=='空' and bar['Close']>vv: continue
                    direction=cand; entry=fh if cand=='多' else fl
            if direction and not ex_reason:
                cp = (bar['High']-entry) if direction=='多' else (entry-bar['Low'])
                cl = (entry-bar['Low'])  if direction=='多' else (bar['High']-entry)
                peak = max(peak, cp)
                if cl >= sl:
                    pnl=-sl; ex_reason='停損'; break
                if use_trailing and peak>=trail_trigger and peak-cp>=trail_dist:
                    pnl=peak-trail_dist; ex_reason='移動停利'; break
                if cp >= tp:
                    pnl=tp; ex_reason='停利'; break

        if direction and not ex_reason:
            last = subsequent[subsequent['Time']<=day_end]
            if last.empty: continue
            ep  = last.iloc[-1]['Close']
            pnl = (ep-entry) if direction=='多' else (entry-ep)
            ex_reason='尾盤出場'

        if direction:
            trades.append({'pnl':round(pnl,1),'net':round(pnl*POINT_VALUE-COMMISSION)})

    if not trades: return None
    t   = pd.DataFrame(trades)
    w   = t[t['pnl']>0]; l = t[t['pnl']<0]
    n   = len(t)
    wr  = len(w)/n*100
    pf  = w['pnl'].sum()/abs(l['pnl'].sum()) if len(l) else 99
    net = t['net'].sum()
    eq  = t['net'].cumsum()
    mdd = (eq-eq.cummax()).min()
    aw  = w['pnl'].mean() if len(w) else 0
    al  = l['pnl'].mean() if len(l) else 0
    rr  = abs(aw/al) if al!=0 else 99
    months = max(((pd.to_datetime('2023-12-29')-pd.to_datetime('2011-01-20')).days)/30,1)
    return dict(n=n, wr=wr, pf=pf, rr=rr, aw=aw, al=al, net=net, mdd=mdd, monthly=net/months)

HDR = f"  {'設定':<32} {'勝率':>6}  {'盈虧比':>6}  {'PF':>5}  {'均獲':>7}  {'均虧':>7}  {'月均':>8}  {'MDD':>9}"
SEP = '-'*100

# ── 基準 ──
base = run(30, 20, 0.8)
print(HDR); print(SEP)
print(f"  {'v5.0 基準 (T30/D20/TP0.8)':<32} {base['wr']:>5.1f}%  {base['rr']:>5.2f}:1  {base['pf']:>4.2f}  +{base['aw']:>5.1f}pt  {base['al']:>6.1f}pt  {base['monthly']:>7,.0f}元  {base['mdd']:>8,.0f}元")

# ── 方向A：調整移動停利觸發點 + 回撤距離 ──
print(f'\n── 方向A：拉高觸發點、拉寬回撤（讓獲利多跑一段）──')
print(HDR); print(SEP)
for trig, dist in [(30,25),(30,30),(40,25),(40,30),(50,25),(50,30),(50,35),(60,30),(60,35),(60,40)]:
    r = run(trig, dist, 0.8)
    if r:
        label = f'T{trig}/D{dist}/TP0.8'
        delta_rr = r['rr'] - base['rr']
        flag = ' ★' if r['rr'] > base['rr'] and r['wr'] >= base['wr']-1 else ''
        print(f"  {label:<32} {r['wr']:>5.1f}%  {r['rr']:>5.2f}:1  {r['pf']:>4.2f}  +{r['aw']:>5.1f}pt  {r['al']:>6.1f}pt  {r['monthly']:>7,.0f}元  {r['mdd']:>8,.0f}元{flag}")

# ── 方向B：取消移動停利，只用較大固定停利 ──
print(f'\n── 方向B：取消移動停利，改用更大固定停利倍數 ──')
print(HDR); print(SEP)
for tp_m in [1.0, 1.2, 1.5, 2.0, 2.5, 3.0]:
    r = run(30, 20, tp_m, use_trailing=False)
    if r:
        label = f'無移動停利 / TP×{tp_m}'
        flag = ' ★' if r['rr'] > base['rr'] and r['wr'] >= base['wr']-2 else ''
        print(f"  {label:<32} {r['wr']:>5.1f}%  {r['rr']:>5.2f}:1  {r['pf']:>4.2f}  +{r['aw']:>5.1f}pt  {r['al']:>6.1f}pt  {r['monthly']:>7,.0f}元  {r['mdd']:>8,.0f}元{flag}")

# ── 方向C：移動停利 + 更大固定停利 ──
print(f'\n── 方向C：保留移動停利，但把固定停利目標拉遠 ──')
print(HDR); print(SEP)
for trig, dist, tp_m in [(30,20,1.2),(30,20,1.5),(40,30,1.2),(40,30,1.5),(50,30,1.5),(50,35,1.5),(50,35,2.0)]:
    r = run(trig, dist, tp_m)
    if r:
        label = f'T{trig}/D{dist}/TP×{tp_m}'
        flag = ' ★' if r['rr'] > base['rr'] and r['wr'] >= base['wr']-1 else ''
        print(f"  {label:<32} {r['wr']:>5.1f}%  {r['rr']:>5.2f}:1  {r['pf']:>4.2f}  +{r['aw']:>5.1f}pt  {r['al']:>6.1f}pt  {r['monthly']:>7,.0f}元  {r['mdd']:>8,.0f}元{flag}")

print(f'\n基準：勝率{base["wr"]:.1f}%  盈虧比{base["rr"]:.2f}:1  PF={base["pf"]:.2f}  月均{base["monthly"]:,.0f}元')
print('★ = 盈虧比優於基準且勝率不差超過1%')
