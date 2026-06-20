"""
RSI 動能確認測試：在 v5.2 基礎上，要求突破時 RSI 站在 50 的多空分界線正確側
做多需 RSI > 50（動能偏多），做空需 RSI < 50（動能偏空）

測試不同 RSI 週期（9 / 14 / 21）與門檻值（45/50/55）組合
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

# 預先計算多個 RSI 週期
for period in [9, 14, 21]:
    delta = df15['Close'].diff()
    gain  = delta.clip(lower=0).ewm(com=period-1, adjust=False).mean()
    loss  = (-delta.clip(upper=0)).ewm(com=period-1, adjust=False).mean()
    rs    = gain / loss.replace(0, np.nan)
    df15[f'RSI{period}'] = 100 - (100 / (1 + rs))

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

def run(rsi_period=None, rsi_long=50, rsi_short=50):
    rsi_col = f'RSI{rsi_period}' if rsi_period else None
    trades = []
    for trade_date, group in df15.groupby('Date'):
        atr = atr_map.get(trade_date, np.nan)
        if pd.isna(atr) or atr <= 0 or atr < atr_thresh: continue
        sl = max(1, round(atr * ATR_SL_MULT))
        tp = max(1, round(atr * ATR_TP_MULT))
        settle  = is_settlement_day(trade_date)
        day_end = DAY_END_SETTLE if settle else DAY_END_NORMAL
        group = group.sort_values('Time').reset_index(drop=True)
        fb = group[group['Time'] == FIRST_BAR_START]
        if fb.empty: continue
        fh = fb.iloc[0]['High']; fl = fb.iloc[0]['Low']
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
                    # 量能過濾
                    bar_pos = df15.index[df15['DateTime'] == bar['DateTime']]
                    if len(bar_pos) == 0 or bar_pos[0] < VOL_LOOKBACK:
                        continue
                    pos = bar_pos[0]
                    avg_vol = df15.iloc[pos-VOL_LOOKBACK:pos]['Volume'].mean()
                    if avg_vol <= 0 or bar['Volume'] < avg_vol * VOL_MULT:
                        continue
                    # RSI 過濾
                    if rsi_col:
                        rsi_val = df15.loc[pos, rsi_col]
                        if pd.isna(rsi_val): continue
                        if cand == '多' and rsi_val < rsi_long: continue
                        if cand == '空' and rsi_val > rsi_short: continue
                    # VWAP 確認
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
            trades.append({'pnl': round(pnl,1), 'net': round(pnl * POINT_VALUE - COMMISSION)})

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
    months = max(((pd.to_datetime('2023-12-29') - pd.to_datetime('2011-01-20')).days) / 30, 1)
    return dict(n=n, wr=wr, pf=pf, rr=rr, aw=aw, al=al, net=net, mdd=mdd, monthly=net/months)

HDR = f"  {'設定':<30} {'次數':>5}  {'勝率':>6}  {'盈虧比':>6}  {'PF':>6}  {'月均':>8}  {'MDD':>9}"
SEP = '-' * 90

print('\n執行 RSI 動能確認測試...\n')
print(HDR); print(SEP)

base = run(rsi_period=None)
print(f"  {'v5.2 基準（無RSI過濾）':<30} {base['n']:>5}  {base['wr']:>5.1f}%  {base['rr']:>5.2f}:1  {base['pf']:>5.2f}  {base['monthly']:>7,.0f}元  {base['mdd']:>8,.0f}元")
print(SEP)

for period in [9, 14, 21]:
    print(f'\n── RSI{period} 週期 ──')
    for threshold in [45, 50, 55]:
        r = run(rsi_period=period, rsi_long=threshold, rsi_short=100-threshold)
        if r:
            flag = ' ★' if r['wr'] >= base['wr'] and r['rr'] >= base['rr'] and r['pf'] >= base['pf'] * 0.95 else ''
            label = f'RSI{period} 多>{100-threshold} / 空<{threshold}'
            print(f"  {label:<30} {r['n']:>5}  {r['wr']:>5.1f}%  {r['rr']:>5.2f}:1  {r['pf']:>5.2f}  {r['monthly']:>7,.0f}元  {r['mdd']:>8,.0f}元{flag}")

print(f'\n基準：次數{base["n"]}  勝率{base["wr"]:.1f}%  盈虧比{base["rr"]:.2f}:1  PF={base["pf"]:.2f}  月均{base["monthly"]:,.0f}元')
print('★ = 勝率、盈虧比均不低於基準 且 PF不差超過5%')
