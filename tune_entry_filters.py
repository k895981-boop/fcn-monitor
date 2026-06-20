"""
進場過濾條件敏感度分析（基於 v2 策略）
測試三種過濾條件的最佳組合：
  F1: 開盤15分K振幅 / ATR  < threshold → 跳過
  F2: ATR < 歷史ATR的第N百分位 → 跳過
  F3: 開盤15分K成交量 < 20日均量 × ratio → 跳過
"""
import pandas as pd
import numpy as np
import warnings
warnings.filterwarnings('ignore')
from datetime import time, date, timedelta, datetime
import itertools

CSV_FILE       = 'txf_1min.csv'   # 日盤資料
ATR_PERIOD     = 14
ATR_SL_MULT    = 0.4
ATR_TP_MULT    = 0.8
USE_TRAILING   = True
TRAIL_TRIGGER  = 30
TRAIL_DISTANCE = 20
FIRST_BAR_START= time(8, 45)
DAY_END_NORMAL = time(13, 40)
DAY_END_SETTLE = time(13, 25)
POINT_VALUE    = 10
COMMISSION     = 30

def is_settlement_day(d):
    if d.weekday() != 2: return False
    return sum(1 for x in range(1, d.day+1) if date(d.year,d.month,x).weekday()==2) == 3

# ── 載入資料並準備 ──
print('載入資料...')
raw = pd.read_csv(CSV_FILE, encoding='utf-8-sig')
raw['DateTime'] = pd.to_datetime(raw['Date'].astype(str)+' '+raw['Time'].astype(str))
raw = raw.sort_values('DateTime').reset_index(drop=True)
raw_idx = raw.set_index('DateTime')

# 15分K
df15_all = raw_idx[['Open','High','Low','Close','Volume']].resample('15min', label='left').agg(
    {'Open':'first','High':'max','Low':'min','Close':'last','Volume':'sum'}
).dropna().reset_index()
df15_all['Date'] = df15_all['DateTime'].dt.date
df15_all['Time'] = df15_all['DateTime'].dt.time

# 每日ATR
daily = raw_idx[['Open','High','Low','Close']].resample('1D').agg(
    {'Open':'first','High':'max','Low':'min','Close':'last'}).dropna()
daily['PC'] = daily['Close'].shift(1)
daily['TR'] = daily.apply(lambda r: max(
    r['High']-r['Low'],
    abs(r['High']-r['PC']) if pd.notna(r['PC']) else 0,
    abs(r['Low']-r['PC'])  if pd.notna(r['PC']) else 0), axis=1)
daily['ATR'] = daily['TR'].rolling(ATR_PERIOD).mean()
atr_map = {d.date(): v for d,v in zip(daily.index, daily['ATR'])}

# 20日均量（第一根15分K）
first_bars = df15_all[df15_all['Time'] == FIRST_BAR_START].copy()
first_bars = first_bars.sort_values('Date').set_index('Date')
first_bars['AvgVol20'] = first_bars['Volume'].rolling(20).mean()
avg_vol_map = {d: v for d, v in zip(first_bars.index, first_bars['AvgVol20'])}
# 開盤振幅 map
open_range_map = {d: (r['High']-r['Low']) for d, r in first_bars.iterrows()}
open_vol_map   = {d: r['Volume'] for d, r in first_bars.iterrows()}

# ATR百分位（全期）
all_atrs = np.array([v for v in atr_map.values() if not np.isnan(v)])

print(f'資料準備完成，共 {len(df15_all["Date"].unique())} 個交易日\n')

# ── 回測核心（帶過濾條件）──
def run_with_filters(f1_ratio=0.0, f2_pct=0, f3_ratio=0.0):
    """
    f1_ratio: 開盤振幅 / ATR 最低門檻（0=不過濾）
    f2_pct:   ATR 百分位下限（0=不過濾）
    f3_ratio: 開盤量 / 20日均量 最低比例（0=不過濾）
    """
    atr_threshold = np.percentile(all_atrs, f2_pct) if f2_pct > 0 else 0
    trades = []

    for trade_date, group in df15_all.groupby('Date'):
        atr = atr_map.get(trade_date, np.nan)
        if pd.isna(atr) or atr <= 0: continue

        # ── 過濾條件 ──
        # F1: 開盤振幅
        if f1_ratio > 0:
            orng = open_range_map.get(trade_date, 0)
            if orng < atr * f1_ratio: continue

        # F2: ATR 百分位
        if f2_pct > 0 and atr < atr_threshold: continue

        # F3: 量能
        if f3_ratio > 0:
            ovol = open_vol_map.get(trade_date, 0)
            avgv = avg_vol_map.get(trade_date, np.nan)
            if pd.isna(avgv) or avgv <= 0 or ovol < avgv * f3_ratio: continue

        sl = max(1, round(atr * ATR_SL_MULT))
        tp = max(1, round(atr * ATR_TP_MULT))
        settle  = is_settlement_day(trade_date)
        day_end = DAY_END_SETTLE if settle else DAY_END_NORMAL

        group = group.sort_values('Time').reset_index(drop=True)
        first = group[group['Time'] == FIRST_BAR_START]
        if first.empty: continue
        fh = first.iloc[0]['High']; fl = first.iloc[0]['Low']

        subsequent = group[group['Time'] > FIRST_BAR_START]
        if subsequent.empty: continue

        direction = entry = ex_price = ex_reason = None
        pnl = 0; peak = 0

        for _, bar in subsequent.iterrows():
            if bar['Time'] > day_end: break
            if direction is None:
                if bar['High'] > fh: direction, entry = '多', fh
                elif bar['Low'] < fl: direction, entry = '空', fl
            if direction and not ex_reason:
                cp = (bar['High']-entry) if direction=='多' else (entry-bar['Low'])
                cl = (entry-bar['Low'])  if direction=='多' else (bar['High']-entry)
                peak = max(peak, cp)
                if cl >= sl:
                    pnl = -sl; ex_reason = '停損'; break
                if USE_TRAILING and peak >= TRAIL_TRIGGER:
                    if peak - cp >= TRAIL_DISTANCE:
                        pnl = peak - TRAIL_DISTANCE; ex_reason = '移動停利'; break
                if cp >= tp:
                    pnl = tp; ex_reason = '停利'; break

        if direction and not ex_reason:
            last = subsequent.iloc[-1]
            ep = last['Close']
            pnl = (ep-entry) if direction=='多' else (entry-ep)
            ex_reason = '尾盤出場'

        if direction:
            trades.append({'pnl': round(pnl,1), 'net': round(pnl*POINT_VALUE-COMMISSION)})

    if not trades: return None
    t  = pd.DataFrame(trades)
    w  = t[t['pnl']>0]; l = t[t['pnl']<0]
    n  = len(t)
    wr = len(w)/n*100
    pf = w['pnl'].sum()/abs(l['pnl'].sum()) if len(l) else 99
    net= t['net'].sum()
    eq = t['net'].cumsum()
    mdd= (eq-eq.cummax()).min()
    months = max(((pd.to_datetime('2023-12-29')-pd.to_datetime('2011-01-03')).days)/30, 1)
    return {'n': n, 'wr': wr, 'pf': pf, 'net': net, 'mdd': mdd, 'monthly': net/months}

# ── 基準（無過濾）──
base = run_with_filters(0, 0, 0)
print('基準（無過濾）：')
print(f"  {base['n']}次  勝率{base['wr']:.1f}%  PF={base['pf']:.2f}  淨利={base['net']:,.0f}元  MDD={base['mdd']:,.0f}元  月均={base['monthly']:,.0f}元\n")

# ── F1：開盤振幅過濾 ──
print('─ F1：開盤15分K振幅 / ATR 門檻 ─')
print(f"{'門檻':>6} {'次數':>6} {'勝率':>7} {'PF':>6} {'累積淨利':>12} {'MDD':>11} {'月均':>9} {'留存率':>7}")
print('-'*68)
f1_results = []
for thr in [0.0, 0.10, 0.15, 0.20, 0.25, 0.30, 0.35]:
    r = run_with_filters(f1_ratio=thr, f2_pct=0, f3_ratio=0)
    if r:
        pct = r['n']/base['n']*100
        f1_results.append((thr, r))
        print(f"  {thr:.2f}  {r['n']:>6}  {r['wr']:>6.1f}%  {r['pf']:>5.2f}  {r['net']:>11,.0f}元  {r['mdd']:>10,.0f}元  {r['monthly']:>8,.0f}元  {pct:>6.1f}%")

# ── F2：ATR百分位過濾 ──
print('\n─ F2：ATR 百分位下限 ─')
print(f"{'百分位':>7} {'次數':>6} {'勝率':>7} {'PF':>6} {'累積淨利':>12} {'MDD':>11} {'月均':>9} {'留存率':>7}")
print('-'*68)
f2_results = []
for pct in [0, 10, 20, 25, 30, 40]:
    r = run_with_filters(f1_ratio=0, f2_pct=pct, f3_ratio=0)
    if r:
        keep = r['n']/base['n']*100
        f2_results.append((pct, r))
        print(f"  P{pct:>2}    {r['n']:>6}  {r['wr']:>6.1f}%  {r['pf']:>5.2f}  {r['net']:>11,.0f}元  {r['mdd']:>10,.0f}元  {r['monthly']:>8,.0f}元  {keep:>6.1f}%")

# ── F3：量能過濾 ──
print('\n─ F3：開盤量 / 20日均量 ─')
print(f"{'比例':>6} {'次數':>6} {'勝率':>7} {'PF':>6} {'累積淨利':>12} {'MDD':>11} {'月均':>9} {'留存率':>7}")
print('-'*68)
f3_results = []
for ratio in [0.0, 0.5, 0.7, 0.8, 1.0, 1.2]:
    r = run_with_filters(f1_ratio=0, f2_pct=0, f3_ratio=ratio)
    if r:
        keep = r['n']/base['n']*100
        f3_results.append((ratio, r))
        print(f"  {ratio:.1f}   {r['n']:>6}  {r['wr']:>6.1f}%  {r['pf']:>5.2f}  {r['net']:>11,.0f}元  {r['mdd']:>10,.0f}元  {r['monthly']:>8,.0f}元  {keep:>6.1f}%")

# ── 最佳單因子 → 組合測試 ──
best_f1 = max(f1_results, key=lambda x: x[1]['pf'])[0]
best_f2 = max(f2_results, key=lambda x: x[1]['pf'])[0]
best_f3 = max(f3_results, key=lambda x: x[1]['pf'])[0]

print(f'\n最佳單因子：F1={best_f1}  F2=P{best_f2}  F3={best_f3}')
print('\n─ 組合測試（F1 + F2 + F3）─')
print(f"{'F1':>5} {'F2':>5} {'F3':>5} {'次數':>6} {'勝率':>7} {'PF':>6} {'累積淨利':>12} {'MDD':>11} {'月均':>9} {'留存率':>7}")
print('-'*76)

combo_results = []
for f1 in [0.0, best_f1]:
    for f2 in [0, best_f2]:
        for f3 in [0.0, best_f3]:
            if f1==0 and f2==0 and f3==0: continue  # 基準已印
            r = run_with_filters(f1, f2, f3)
            if r:
                keep = r['n']/base['n']*100
                combo_results.append((f1, f2, f3, r))
                print(f"  {f1:.2f}  P{f2:>2}  {f3:.1f}  {r['n']:>6}  {r['wr']:>6.1f}%  {r['pf']:>5.2f}  {r['net']:>11,.0f}元  {r['mdd']:>10,.0f}元  {r['monthly']:>8,.0f}元  {keep:>6.1f}%")

if combo_results:
    best = max(combo_results, key=lambda x: x[3]['pf'])
    print(f"\n最佳組合：F1={best[0]}  F2=P{best[1]}  F3={best[2]}")
    print(f"  次數={best[3]['n']}  勝率={best[3]['wr']:.1f}%  PF={best[3]['pf']:.2f}  累積淨利={best[3]['net']:,.0f}元  月均={best[3]['monthly']:,.0f}元")
