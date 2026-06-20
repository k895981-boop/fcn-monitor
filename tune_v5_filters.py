"""
v5 進場過濾敏感度分析
在 v4.0 基礎（ATR>=P25 過濾）上，額外測試：
  VWAP : 突破方向需與 VWAP 位置一致
  TIME : 只接受 09:00~11:30 之間觸發的突破訊號
  PREV : 前一日方向偏多/偏空（只做同向）
"""
import pandas as pd
import numpy as np
import warnings
warnings.filterwarnings('ignore')
from datetime import time, date, timedelta, datetime

CSV_FILE        = 'txf_1min.csv'
ATR_PERIOD      = 14
ATR_SL_MULT     = 0.4
ATR_TP_MULT     = 0.8
TRAIL_TRIGGER   = 30
TRAIL_DISTANCE  = 20
ATR_FILTER_PCT  = 25        # v4.0 已有的 ATR 過濾
FIRST_BAR_START = time(8, 45)
DAY_END_NORMAL  = time(13, 40)
DAY_END_SETTLE  = time(13, 25)
POINT_VALUE     = 10
COMMISSION      = 30

# ── 進場時間窗口選項 ──
TIME_WINDOWS = [
    (time(8,59),  time(13,40), '不限'),
    (time(8,59),  time(11,30), '09:00~11:30'),
    (time(8,59),  time(12,00), '09:00~12:00'),
    (time(9,14),  time(11,30), '09:15~11:30'),
]

def is_settlement_day(d):
    if d.weekday() != 2: return False
    return sum(1 for x in range(1,d.day+1) if date(d.year,d.month,x).weekday()==2)==3

# ══ 載入資料 ══
print('載入資料...')
raw = pd.read_csv(CSV_FILE, encoding='utf-8-sig')
raw['DateTime'] = pd.to_datetime(raw['Date'].astype(str)+' '+raw['Time'].astype(str))
raw = raw.sort_values('DateTime').reset_index(drop=True)
raw_idx = raw.set_index('DateTime')

# 15分K
df15_all = raw_idx[['Open','High','Low','Close','Volume']].resample('15min',label='left').agg(
    {'Open':'first','High':'max','Low':'min','Close':'last','Volume':'sum'}
).dropna().reset_index()
df15_all['Date'] = df15_all['DateTime'].dt.date
df15_all['Time'] = df15_all['DateTime'].dt.time

# ATR
daily = raw_idx[['Open','High','Low','Close']].resample('1D').agg(
    {'Open':'first','High':'max','Low':'min','Close':'last'}).dropna()
daily['PC']  = daily['Close'].shift(1)
daily['TR']  = daily.apply(lambda r: max(
    r['High']-r['Low'],
    abs(r['High']-r['PC']) if pd.notna(r['PC']) else 0,
    abs(r['Low'] -r['PC']) if pd.notna(r['PC']) else 0), axis=1)
daily['ATR'] = daily['TR'].rolling(ATR_PERIOD).mean()
atr_map  = {d.date(): v for d,v in zip(daily.index, daily['ATR'])}

# VWAP（每日從 08:45 起算的累積 VWAP）
raw['_date'] = raw['DateTime'].dt.date
raw['_time'] = raw['DateTime'].dt.time
day_raw = raw[(raw['_time'] >= time(8,45)) & (raw['_time'] <= time(13,45))].copy()
day_raw['TP']  = (day_raw['High'] + day_raw['Low'] + day_raw['Close']) / 3
day_raw['TPV'] = day_raw['TP'] * day_raw['Volume']
day_raw['cumTPV'] = day_raw.groupby('_date')['TPV'].cumsum()
day_raw['cumVol'] = day_raw.groupby('_date')['Volume'].cumsum()
day_raw['VWAP']   = day_raw['cumTPV'] / day_raw['cumVol']
# 取每根15分K結束前的最後一筆1分K VWAP
vwap_idx = day_raw.set_index('DateTime')[['VWAP']]

def get_vwap_at(dt):
    """取某 datetime 之前（含）的最新 VWAP 值"""
    try:
        loc = vwap_idx.index.searchsorted(dt, side='right') - 1
        if loc < 0: return np.nan
        return float(vwap_idx.iloc[loc]['VWAP'])
    except:
        return np.nan

# 前一日漲跌方向
daily['PrevDir'] = np.sign(daily['Close'] - daily['Open'])   # +1 漲 / -1 跌 / 0 平
prev_dir_map = {d.date(): v for d,v in zip(daily.index, daily['PrevDir'].shift(1))}

# ATR 門檻（v4.0 既有）
valid_atrs = np.array([v for v in atr_map.values() if not np.isnan(v)])
atr_threshold = np.percentile(valid_atrs, ATR_FILTER_PCT)
print(f'ATR P{ATR_FILTER_PCT} 門檻：{atr_threshold:.1f}')

all_dates = sorted(df15_all['Date'].unique())
print(f'共 {len(all_dates)} 個交易日，開始分析...\n')

# ══ 核心回測（帶旗標參數）══
def run(use_vwap=False, entry_start=time(8,59), entry_end=time(13,40), use_prev=False):
    trades = []
    for trade_date, group in df15_all.groupby('Date'):
        atr = atr_map.get(trade_date, np.nan)
        if pd.isna(atr) or atr <= 0 or atr < atr_threshold:
            continue
        sl = max(1, round(atr * ATR_SL_MULT))
        tp = max(1, round(atr * ATR_TP_MULT))
        settle   = is_settlement_day(trade_date)
        day_end  = DAY_END_SETTLE if settle else DAY_END_NORMAL

        group = group.sort_values('Time').reset_index(drop=True)
        first = group[group['Time'] == FIRST_BAR_START]
        if first.empty: continue
        fh = first.iloc[0]['High']; fl = first.iloc[0]['Low']

        # 前日方向偏多/偏空
        prev_dir = prev_dir_map.get(trade_date, 0) if use_prev else 0

        subsequent = group[group['Time'] > FIRST_BAR_START]
        if subsequent.empty: continue

        direction = entry = ex_reason = None
        pnl = 0; peak = 0

        for _, bar in subsequent.iterrows():
            if bar['Time'] > day_end: break

            # 進場
            if direction is None:
                # 時間窗口過濾
                if bar['Time'] < entry_start or bar['Time'] > entry_end:
                    continue
                long_ok  = bar['High'] > fh and (prev_dir >= 0)  # 不偏空才做多
                short_ok = bar['Low']  < fl and (prev_dir <= 0)  # 不偏多才做空

                if long_ok or short_ok:
                    cand_dir = '多' if long_ok else '空'

                    # VWAP 過濾
                    if use_vwap:
                        bar_dt   = datetime.combine(trade_date, bar['Time'])
                        vwap_val = get_vwap_at(bar_dt)
                        if not np.isnan(vwap_val):
                            if cand_dir == '多' and bar['Close'] < vwap_val:
                                continue
                            if cand_dir == '空' and bar['Close'] > vwap_val:
                                continue

                    direction = cand_dir
                    entry     = fh if direction == '多' else fl

            # 出場
            if direction and not ex_reason:
                cp = (bar['High']-entry) if direction=='多' else (entry-bar['Low'])
                cl = (entry-bar['Low'])  if direction=='多' else (bar['High']-entry)
                peak = max(peak, cp)
                if cl >= sl:
                    pnl = -sl; ex_reason = '停損'; break
                if peak >= TRAIL_TRIGGER and peak-cp >= TRAIL_DISTANCE:
                    pnl = peak-TRAIL_DISTANCE; ex_reason = '移動停利'; break
                if cp >= tp:
                    pnl = tp; ex_reason = '停利'; break

        if direction and not ex_reason:
            last = subsequent[subsequent['Time'] <= day_end]
            if last.empty: continue
            ep  = last.iloc[-1]['Close']
            pnl = (ep-entry) if direction=='多' else (entry-ep)
            ex_reason = '尾盤出場'

        if direction:
            trades.append({'pnl': round(pnl,1),
                           'net': round(pnl*POINT_VALUE-COMMISSION)})

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
    months = max(((pd.to_datetime('2023-12-29')-pd.to_datetime('2011-01-20')).days)/30,1)
    return dict(n=n, wr=wr, pf=pf, aw=aw, al=al, net=net, mdd=mdd, monthly=net/months)

def row(label, r, base_n):
    keep = r['n']/base_n*100
    return (f"  {label:<22} {r['n']:>5}次  {r['wr']:>5.1f}%  {r['pf']:>5.2f}"
            f"  +{r['aw']:>5.1f}/{r['al']:>6.1f}  {r['net']:>10,.0f}元"
            f"  {r['mdd']:>8,.0f}元  {r['monthly']:>7,.0f}元  ({keep:.0f}%)")

HDR = f"  {'條件':<22} {'次數':>5}    {'勝率':>5}    {'PF':>5}  {'均獲/均虧':>12}  {'累積淨利':>10}  {'MDD':>8}  {'月均':>7}"

# ── 基準 ──
base = run()
print(HDR); print('-'*110)
print(row('v4.0 基準（ATR P25）', base, base['n']))

# ── F_VWAP 單獨 ──
print('\n── VWAP 方向過濾 ──')
print(HDR); print('-'*110)
r = run(use_vwap=True)
print(row('+ VWAP', r, base['n']))

# ── F_TIME 單獨 ──
print('\n── 進場時間窗口 ──')
print(HDR); print('-'*110)
for (es, ee, label) in TIME_WINDOWS:
    r = run(entry_start=es, entry_end=ee)
    print(row(f'時間 {label}', r, base['n']))

# ── F_PREV 單獨 ──
print('\n── 前日方向偏多/偏空 ──')
print(HDR); print('-'*110)
r = run(use_prev=True)
print(row('+ 前日方向過濾', r, base['n']))

# ── 最佳時間窗口（找出單獨最佳）──
best_time = max(TIME_WINDOWS,
    key=lambda x: run(entry_start=x[0], entry_end=x[1])['pf'])
best_es, best_ee, best_tl = best_time

# ── 組合測試 ──
print('\n── 組合測試 ──')
print(HDR); print('-'*110)
combos = [
    (True,  best_es, best_ee, False, f'VWAP + 時間{best_tl}'),
    (True,  time(8,59), time(13,40), True,  'VWAP + 前日方向'),
    (False, best_es, best_ee, True,  f'時間{best_tl} + 前日方向'),
    (True,  best_es, best_ee, True,  f'VWAP + 時間{best_tl} + 前日方向'),
]
combo_results = []
for vwap, es, ee, prev, label in combos:
    r = run(use_vwap=vwap, entry_start=es, entry_end=ee, use_prev=prev)
    if r:
        combo_results.append((label, r))
        print(row(label, r, base['n']))

# ── 最終結論 ──
all_r = [(label, r) for label, r in combo_results]
all_r.append(('v4.0 基準', base))

best_pf  = max(all_r, key=lambda x: x[1]['pf'])
best_net = max(all_r, key=lambda x: x[1]['net'])
best_mo  = max(all_r, key=lambda x: x[1]['monthly'])

print('\n' + '='*60)
print(f'最佳獲利因子 ：{best_pf[0]}  →  PF={best_pf[1]["pf"]:.2f}  月均={best_pf[1]["monthly"]:,.0f}元')
print(f'最佳累積淨利 ：{best_net[0]}  →  {best_net[1]["net"]:,.0f}元')
print(f'最佳月均損益 ：{best_mo[0]}  →  {best_mo[1]["monthly"]:,.0f}元')
print('='*60)
