"""
開盤區間寬度過濾測試（在 v5.3 基礎上）

邏輯：09:00 那根 15 分K（08:45~09:00）的高低差 >= 當日 ATR × 比例門檻
      開盤區間太窄 → 假突破機率高，不值得交易
      開盤區間夠寬 → 市場有方向性，突破後走勢更乾淨

測試：比例門檻從 0.10 到 0.50，找出最佳甜蜜點
"""
import pandas as pd
import numpy as np
import warnings
warnings.filterwarnings('ignore')
from datetime import time, date, datetime

CSV_FILE        = 'txf_1min.csv'
ATR_PERIOD      = 14
ATR_SL_MULT     = 0.4
ATR_TP_MULT     = 1.5
TRAIL_TRIGGER   = 30
TRAIL_DISTANCE  = 20
ATR_FILTER_PCT  = 25
VOL_MULT        = 1.5
VOL_LOOKBACK    = 5
RSI_PERIOD      = 14
ENTRY_EARLIEST  = time(9, 15)
FIRST_BAR_START = time(8, 45)
DAY_END_NORMAL  = time(13, 40)
DAY_END_SETTLE  = time(13, 25)
POINT_VALUE     = 10
COMMISSION      = 30

def is_settlement_day(d):
    if d.weekday() != 2: return False
    return sum(1 for x in range(1, d.day+1) if date(d.year, d.month, x).weekday()==2) == 3

print('載入資料...')
raw = pd.read_csv(CSV_FILE, encoding='utf-8-sig')
raw['DateTime'] = pd.to_datetime(raw['Date'].astype(str) + ' ' + raw['Time'].astype(str))
raw = raw.sort_values('DateTime').reset_index(drop=True)
raw_idx = raw.set_index('DateTime')

df15 = raw_idx[['Open','High','Low','Close','Volume']].resample('15min', label='left').agg(
    {'Open':'first','High':'max','Low':'min','Close':'last','Volume':'sum'}
).dropna().reset_index()
df15['Date'] = df15['DateTime'].dt.date
df15['Time'] = df15['DateTime'].dt.time
df15 = df15.sort_values('DateTime').reset_index(drop=True)

delta    = df15['Close'].diff()
gain     = delta.clip(lower=0)
loss     = (-delta).clip(lower=0)
avg_gain = gain.ewm(com=RSI_PERIOD-1, min_periods=RSI_PERIOD).mean()
avg_loss = loss.ewm(com=RSI_PERIOD-1, min_periods=RSI_PERIOD).mean()
rs       = avg_gain / avg_loss.replace(0, np.nan)
df15['RSI'] = 100 - (100 / (1 + rs))

daily = raw_idx[['Open','High','Low','Close']].resample('1D').agg(
    {'Open':'first','High':'max','Low':'min','Close':'last'}).dropna()
daily['PC']  = daily['Close'].shift(1)
daily['TR']  = daily.apply(lambda r: max(
    r['High']-r['Low'],
    abs(r['High']-r['PC']) if pd.notna(r['PC']) else 0,
    abs(r['Low'] -r['PC']) if pd.notna(r['PC']) else 0), axis=1)
daily['ATR'] = daily['TR'].rolling(ATR_PERIOD).mean()
atr_map = {d.date(): v for d, v in zip(daily.index, daily['ATR'])}

raw['_date'] = raw['DateTime'].dt.date
raw['_time'] = raw['DateTime'].dt.time
day_raw = raw[(raw['_time'] >= time(8,45)) & (raw['_time'] <= time(13,45))].copy()
day_raw['TP']     = (day_raw['High'] + day_raw['Low'] + day_raw['Close']) / 3
day_raw['TPV']    = day_raw['TP'] * day_raw['Volume']
day_raw['cumTPV'] = day_raw.groupby('_date')['TPV'].cumsum()
day_raw['cumVol'] = day_raw.groupby('_date')['Volume'].cumsum()
day_raw['VWAP']   = day_raw['cumTPV'] / day_raw['cumVol']
vwap_idx = day_raw.set_index('DateTime')[['VWAP']]

valid_atrs = [v for v in atr_map.values() if not np.isnan(v)]
atr_thresh = np.percentile(valid_atrs, ATR_FILTER_PCT)

def get_vwap_at(dt):
    loc = vwap_idx.index.searchsorted(dt, side='right') - 1
    return float(vwap_idx.iloc[loc]['VWAP']) if loc >= 0 else np.nan

def run(range_ratio=None):
    trades = []
    for trade_date, group in df15.groupby('Date'):
        atr = atr_map.get(trade_date, np.nan)
        if pd.isna(atr) or atr <= 0 or atr < atr_thresh: continue

        group = group.sort_values('Time').reset_index(drop=True)
        fb = group[group['Time'] == FIRST_BAR_START]
        if fb.empty: continue
        fh = fb.iloc[0]['High']; fl = fb.iloc[0]['Low']

        # 開盤區間寬度過濾
        if range_ratio is not None:
            opening_range = fh - fl
            if opening_range < atr * range_ratio:
                continue

        sl = max(1, round(atr * ATR_SL_MULT))
        tp = max(1, round(atr * ATR_TP_MULT))
        settle  = is_settlement_day(trade_date)
        day_end = DAY_END_SETTLE if settle else DAY_END_NORMAL

        subsequent = group[group['Time'] > FIRST_BAR_START].reset_index(drop=True)
        if subsequent.empty: continue

        direction = entry = ex_reason = None
        pnl = 0; peak = 0

        for i, bar in subsequent.iterrows():
            if bar['Time'] > day_end: break
            if direction is None:
                if bar['Time'] < ENTRY_EARLIEST: continue
                cand = None
                if bar['High'] > fh: cand = '多'
                elif bar['Low'] < fl: cand = '空'
                if cand:
                    bar_pos = df15.index[df15['DateTime'] == bar['DateTime']]
                    if len(bar_pos) == 0 or bar_pos[0] < VOL_LOOKBACK: continue
                    pos = bar_pos[0]
                    avg_vol = df15.iloc[pos-VOL_LOOKBACK:pos]['Volume'].mean()
                    if avg_vol <= 0 or bar['Volume'] < avg_vol * VOL_MULT: continue
                    rsi_val = df15.loc[pos, 'RSI']
                    if pd.isna(rsi_val): continue
                    if cand == '多' and rsi_val <= 50: continue
                    if cand == '空' and rsi_val >= 50: continue
                    bdt = datetime.combine(trade_date, bar['Time'])
                    vv  = get_vwap_at(bdt)
                    if not np.isnan(vv):
                        if cand == '多' and bar['Close'] < vv: continue
                        if cand == '空' and bar['Close'] > vv: continue
                    direction = cand
                    entry = fh if cand == '多' else fl

            if direction and not ex_reason:
                cp = (bar['High'] - entry) if direction == '多' else (entry - bar['Low'])
                cl = (entry - bar['Low']) if direction == '多' else (bar['High'] - entry)
                peak = max(peak, cp)
                if cl >= sl:
                    pnl = -sl; ex_reason = '停損'; break
                if peak >= TRAIL_TRIGGER and peak - cp >= TRAIL_DISTANCE:
                    pnl = peak - TRAIL_DISTANCE; ex_reason = '移動停利'; break
                if cp >= tp:
                    pnl = tp; ex_reason = '停利'; break

        if direction and not ex_reason:
            last = subsequent[subsequent['Time'] <= day_end]
            if last.empty: continue
            ep  = last.iloc[-1]['Close']
            pnl = (ep - entry) if direction == '多' else (entry - ep)
            ex_reason = '尾盤出場'

        if direction:
            trades.append({'date': trade_date, 'pnl': round(pnl,1),
                           'net': round(pnl * POINT_VALUE - COMMISSION)})

    if not trades: return None
    t   = pd.DataFrame(trades)
    w   = t[t['pnl'] > 0]; l = t[t['pnl'] < 0]
    n   = len(t)
    wr  = len(w) / n * 100
    pf  = w['pnl'].sum() / abs(l['pnl'].sum()) if len(l) else 99
    net = t['net'].sum()
    eq  = t['net'].cumsum()
    mdd = (eq - eq.cummax()).min()
    aw  = w['pnl'].mean() if len(w) else 0
    al  = l['pnl'].mean() if len(l) else 0
    rr  = abs(aw / al) if al != 0 else 99
    t['month'] = pd.to_datetime(t['date']).dt.to_period('M')
    monthly = t.groupby('month')['net'].sum()
    lose_mo = (monthly < 0).sum()
    total_mo = len(monthly)
    return dict(n=n, wr=wr, pf=pf, rr=rr, aw=aw, al=al, net=net,
                mdd=mdd, monthly=net/total_mo, lose_mo=lose_mo, total_mo=total_mo)

print('\n執行開盤區間寬度過濾測試...\n')
HDR = f"  {'設定':<28} {'次數':>5}  {'勝率':>6}  {'盈虧比':>6}  {'PF':>6}  {'均獲':>7}  {'均虧':>7}  {'月均':>8}  {'MDD':>9}  {'虧月':>5}"
SEP = '-' * 112
print(HDR); print(SEP)

base = run(range_ratio=None)
print(f"  {'v5.3 基準（無區間寬度過濾）':<28} {base['n']:>5}  {base['wr']:>5.1f}%  {base['rr']:>5.2f}:1  {base['pf']:>5.2f}  +{base['aw']:>5.1f}pt  {base['al']:>6.1f}pt  {base['monthly']:>7,.0f}元  {base['mdd']:>8,.0f}元  {base['lose_mo']}/{base['total_mo']}")
print(SEP)

for ratio in [0.10, 0.15, 0.20, 0.25, 0.30, 0.35, 0.40, 0.45, 0.50]:
    r = run(range_ratio=ratio)
    if r:
        flag = ' ★' if (r['wr'] >= base['wr'] and r['rr'] > base['rr']
                        and r['monthly'] >= base['monthly'] * 0.90) else ''
        label = f'開盤區間 ≥ ATR×{ratio}'
        print(f"  {label:<28} {r['n']:>5}  {r['wr']:>5.1f}%  {r['rr']:>5.2f}:1  {r['pf']:>5.2f}  +{r['aw']:>5.1f}pt  {r['al']:>6.1f}pt  {r['monthly']:>7,.0f}元  {r['mdd']:>8,.0f}元  {r['lose_mo']}/{r['total_mo']}{flag}")

print(f'\n基準：次數{base["n"]}  勝率{base["wr"]:.1f}%  盈虧比{base["rr"]:.2f}:1  PF={base["pf"]:.2f}  月均{base["monthly"]:,.0f}元')
print('★ = 勝率不低於基準 且 盈虧比更高 且 月均不低於基準的90%')
