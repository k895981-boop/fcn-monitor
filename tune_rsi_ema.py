"""
RSI + 200 EMA 過濾測試（在 v5.2 基礎上）

方向二：RSI(14) 動能確認
  - 做多時 RSI > 50，做空時 RSI < 50（計算突破棒當下的 15分K RSI）

方向三：200 日 EMA 大方向過濾
  - 只在收盤價 > 200日EMA 時做多
  - 只在收盤價 < 200日EMA 時做空

測試組合：
  A) v5.2 基準
  B) v5.2 + RSI
  C) v5.2 + 200EMA
  D) v5.2 + RSI + 200EMA（交集）
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
EMA_PERIOD      = 200
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

# 15分K
df15 = raw_idx[['Open','High','Low','Close','Volume']].resample('15min', label='left').agg(
    {'Open':'first','High':'max','Low':'min','Close':'last','Volume':'sum'}
).dropna().reset_index()
df15['Date'] = df15['DateTime'].dt.date
df15['Time'] = df15['DateTime'].dt.time
df15 = df15.sort_values('DateTime').reset_index(drop=True)

# RSI(14) 計算在 15分K 上
delta = df15['Close'].diff()
gain  = delta.clip(lower=0)
loss  = (-delta).clip(lower=0)
avg_gain = gain.ewm(com=RSI_PERIOD-1, min_periods=RSI_PERIOD).mean()
avg_loss = loss.ewm(com=RSI_PERIOD-1, min_periods=RSI_PERIOD).mean()
rs = avg_gain / avg_loss.replace(0, np.nan)
df15['RSI'] = 100 - (100 / (1 + rs))

# 日ATR
daily = raw_idx[['Open','High','Low','Close']].resample('1D').agg(
    {'Open':'first','High':'max','Low':'min','Close':'last'}).dropna()
daily['PC']  = daily['Close'].shift(1)
daily['TR']  = daily.apply(lambda r: max(
    r['High']-r['Low'],
    abs(r['High']-r['PC']) if pd.notna(r['PC']) else 0,
    abs(r['Low'] -r['PC']) if pd.notna(r['PC']) else 0), axis=1)
daily['ATR'] = daily['TR'].rolling(ATR_PERIOD).mean()

# 200日EMA
daily['EMA200'] = daily['Close'].ewm(span=EMA_PERIOD, min_periods=EMA_PERIOD).mean()
atr_map   = {d.date(): v for d, v in zip(daily.index, daily['ATR'])}
ema200_map = {d.date(): v for d, v in zip(daily.index, daily['EMA200'])}
close_map  = {d.date(): v for d, v in zip(daily.index, daily['Close'])}

# VWAP
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

def run(use_rsi=False, use_ema=False):
    trades = []
    for trade_date, group in df15.groupby('Date'):
        atr = atr_map.get(trade_date, np.nan)
        if pd.isna(atr) or atr <= 0 or atr < atr_thresh: continue

        # 200 EMA 前日收盤方向
        if use_ema:
            prev_close = close_map.get(trade_date, np.nan)
            ema200     = ema200_map.get(trade_date, np.nan)
            if pd.isna(prev_close) or pd.isna(ema200): continue
            ema_bull = prev_close > ema200   # True=多頭市場
            ema_bear = prev_close < ema200   # True=空頭市場

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
                    # EMA200 大方向過濾
                    if use_ema:
                        if cand == '多' and not ema_bull: continue
                        if cand == '空' and not ema_bear: continue

                    # 量能過濾（v5.2 固定條件）
                    bar_pos = df15.index[df15['DateTime'] == bar['DateTime']]
                    if len(bar_pos) == 0 or bar_pos[0] < VOL_LOOKBACK:
                        continue
                    pos = bar_pos[0]
                    avg_vol = df15.iloc[pos-VOL_LOOKBACK:pos]['Volume'].mean()
                    if avg_vol <= 0 or bar['Volume'] < avg_vol * VOL_MULT:
                        continue

                    # RSI 動能過濾
                    if use_rsi:
                        rsi_val = df15.loc[pos, 'RSI']
                        if pd.isna(rsi_val): continue
                        if cand == '多' and rsi_val <= 50: continue
                        if cand == '空' and rsi_val >= 50: continue

                    # VWAP 方向確認
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
                mdd=mdd, monthly=net/total_mo, lose_mo=lose_mo,
                total_mo=total_mo, trades=t)

print('\n執行測試...\n')

scenarios = [
    ('v5.2 基準',              False, False),
    ('v5.2 + RSI>50/<50',     True,  False),
    ('v5.2 + 200日EMA方向',    False, True),
    ('v5.2 + RSI + 200EMA',   True,  True),
]

HDR = f"  {'設定':<28} {'次數':>5}  {'勝率':>6}  {'盈虧比':>6}  {'PF':>6}  {'均獲':>7}  {'均虧':>7}  {'月均':>8}  {'MDD':>9}  {'虧月':>5}"
SEP = '-' * 112
print(HDR); print(SEP)

results = {}
for label, use_rsi, use_ema in scenarios:
    r = run(use_rsi=use_rsi, use_ema=use_ema)
    if r:
        results[label] = r
        base = results.get('v5.2 基準')
        flag = ''
        if base and label != 'v5.2 基準':
            if r['wr'] >= base['wr'] and r['rr'] > base['rr'] and r['pf'] >= base['pf'] * 0.95:
                flag = ' ★'
        print(f"  {label:<28} {r['n']:>5}  {r['wr']:>5.1f}%  {r['rr']:>5.2f}:1  {r['pf']:>5.2f}  +{r['aw']:>5.1f}pt  {r['al']:>6.1f}pt  {r['monthly']:>7,.0f}元  {r['mdd']:>8,.0f}元  {r['lose_mo']}/{r['total_mo']}{flag}")

# 走步式驗證（最佳組合）
print('\n\n── 走步式驗證：v5.2 + RSI + 200EMA ──\n')

def run_period(date_start, date_end, use_rsi, use_ema):
    # 樣本內 ATR P25
    is_end = pd.Timestamp('2016-12-31')
    in_atrs = [v for d, v in atr_map.items() if pd.Timestamp(d) <= is_end and not np.isnan(v)]
    thresh = np.percentile(in_atrs, ATR_FILTER_PCT)

    trades = []
    ds = pd.Timestamp(date_start).date()
    de = pd.Timestamp(date_end).date()

    for trade_date, group in df15.groupby('Date'):
        if trade_date < ds or trade_date > de: continue
        atr = atr_map.get(trade_date, np.nan)
        if pd.isna(atr) or atr <= 0 or atr < thresh: continue

        if use_ema:
            prev_close = close_map.get(trade_date, np.nan)
            ema200     = ema200_map.get(trade_date, np.nan)
            if pd.isna(prev_close) or pd.isna(ema200): continue
            ema_bull = prev_close > ema200
            ema_bear = prev_close < ema200

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
                    if use_ema:
                        if cand == '多' and not ema_bull: continue
                        if cand == '空' and not ema_bear: continue
                    bar_pos = df15.index[df15['DateTime'] == bar['DateTime']]
                    if len(bar_pos) == 0 or bar_pos[0] < VOL_LOOKBACK: continue
                    pos = bar_pos[0]
                    avg_vol = df15.iloc[pos-VOL_LOOKBACK:pos]['Volume'].mean()
                    if avg_vol <= 0 or bar['Volume'] < avg_vol * VOL_MULT: continue
                    if use_rsi:
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
    n   = len(t); wr = len(w)/n*100
    pf  = w['pnl'].sum()/abs(l['pnl'].sum()) if len(l) else 99
    net = t['net'].sum(); eq = t['net'].cumsum()
    mdd = (eq-eq.cummax()).min()
    aw  = w['pnl'].mean() if len(w) else 0
    al  = l['pnl'].mean() if len(l) else 0
    rr  = abs(aw/al) if al != 0 else 99
    t['month'] = pd.to_datetime(t['date']).dt.to_period('M')
    monthly = t.groupby('month')['net'].sum()
    lose_mo = (monthly<0).sum(); total_mo = len(monthly)
    return dict(n=n, wr=wr, pf=pf, rr=rr, net=net, mdd=mdd,
                monthly=net/total_mo, lose_mo=lose_mo, total_mo=total_mo, trades=t)

for label, use_rsi, use_ema in [('v5.2 基準', False, False), ('v5.2 + RSI + 200EMA', True, True)]:
    r_in  = run_period('2011-01-01', '2016-12-31', use_rsi, use_ema)
    r_oos = run_period('2017-01-01', '2023-12-31', use_rsi, use_ema)
    ratio_pf = r_oos['pf'] / r_in['pf']
    if ratio_pf >= 0.7 and r_oos['pf'] >= 1.5: verdict = '合格'
    elif ratio_pf >= 0.5 and r_oos['pf'] >= 1.2: verdict = '尚可（有衰退）'
    else: verdict = '不合格'

    print(f'  ┌─ {label}')
    print(f'  │              {"樣本內 2011-2016":>20}  {"樣本外 2017-2023":>20}  {"樣外/樣內":>8}')
    print(f'  │  次數        {r_in["n"]:>20}  {r_oos["n"]:>20}')
    print(f'  │  勝率        {r_in["wr"]:>19.1f}%  {r_oos["wr"]:>19.1f}%  {r_oos["wr"]/r_in["wr"]:>7.2f}')
    print(f'  │  盈虧比      {r_in["rr"]:>18.2f}:1  {r_oos["rr"]:>18.2f}:1')
    print(f'  │  PF          {r_in["pf"]:>20.2f}  {r_oos["pf"]:>20.2f}  {ratio_pf:>7.2f}')
    print(f'  │  月均        {r_in["monthly"]:>18,.0f}元  {r_oos["monthly"]:>18,.0f}元')
    print(f'  │  MDD         {r_in["mdd"]:>18,.0f}元  {r_oos["mdd"]:>18,.0f}元')
    print(f'  │  虧損月      {r_in["lose_mo"]}/{r_in["total_mo"]}個月{"":14}  {r_oos["lose_mo"]}/{r_oos["total_mo"]}個月')
    print(f'  └─ 結論：{verdict}\n')

    if label == 'v5.2 + RSI + 200EMA':
        print(f'  樣本外逐年（{label}）')
        print(f"  {'年份':>5}  {'次數':>5}  {'勝率':>7}  {'PF':>6}  {'月均':>9}  {'年淨利':>10}")
        print('  ' + '-'*52)
        oos = r_oos['trades']
        oos['year'] = pd.to_datetime(oos['date']).dt.year
        for yr, g in oos.groupby('year'):
            gw = g[g['pnl']>0]; gl = g[g['pnl']<0]
            yp = gw['pnl'].sum()/abs(gl['pnl'].sum()) if len(gl) else 99
            g['month'] = pd.to_datetime(g['date']).dt.to_period('M')
            ym = g['net'].sum() / len(g.groupby('month'))
            print(f"  {yr}  {len(g):>5}  {len(gw)/len(g)*100:>6.1f}%  {yp:>5.2f}  {ym:>8,.0f}元  {g['net'].sum():>9,.0f}元")
