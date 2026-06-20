"""
敏感度分析：測試不同的第一段移動停利觸發點（TRAIL_L1）
固定：日盤only、ATR×0.4停損、ATR×0.8停利、夜盤關閉
"""
import pandas as pd
import numpy as np
import warnings, sys
warnings.filterwarnings('ignore')
from datetime import time, date, timedelta, datetime

CSV_FILE     = 'txf_all_sessions.csv'
ATR_PERIOD   = 14
ATR_SL_MULT  = 0.4
ATR_TP_MULT  = 0.8
TRAIL_D1     = 15
TRAIL_L2     = 60;  TRAIL_D2 = 25
TRAIL_L3     = 120; TRAIL_D3 = 45
DAY_FIRST_BAR  = time(8, 45)
DAY_END_NORMAL = time(13, 40)
DAY_END_SETTLE = time(13, 25)
POINT_VALUE  = 10
COMMISSION   = 30

def is_settlement_day(d):
    if d.weekday() != 2: return False
    return sum(1 for x in range(1, d.day+1) if date(d.year, d.month, x).weekday()==2) == 3

def calc_daily_atr(df):
    tmp = df.set_index('DateTime')
    daily = tmp[['Open','High','Low','Close']].resample('1D').agg(
        {'Open':'first','High':'max','Low':'min','Close':'last'}).dropna()
    daily['PC'] = daily['Close'].shift(1)
    daily['TR'] = daily.apply(lambda r: max(
        r['High']-r['Low'],
        abs(r['High']-r['PC']) if pd.notna(r['PC']) else 0,
        abs(r['Low'] -r['PC']) if pd.notna(r['PC']) else 0), axis=1)
    daily['ATR'] = daily['TR'].rolling(ATR_PERIOD).mean()
    return {d.date(): v for d,v in zip(daily.index, daily['ATR'])}

def run_one(df, atr_map, trail_l1):
    trades = []
    for trade_date, day_df in df.groupby('_date'):
        atr = atr_map.get(trade_date, np.nan)
        if pd.isna(atr) or atr <= 0: continue
        sl = max(1, round(atr * ATR_SL_MULT))
        tp = max(1, round(atr * ATR_TP_MULT))
        settle  = is_settlement_day(trade_date)
        day_end = DAY_END_SETTLE if settle else DAY_END_NORMAL

        bar_start = datetime.combine(trade_date, DAY_FIRST_BAR)
        bar_end   = bar_start + timedelta(minutes=15)
        day_end_dt= datetime.combine(trade_date, day_end)

        bar_rows = day_df[(day_df['DateTime'] >= bar_start) & (day_df['DateTime'] < bar_end)]
        if bar_rows.empty: continue
        fh = bar_rows['High'].max(); fl = bar_rows['Low'].min()

        after = day_df[(day_df['DateTime'] >= bar_end) & (day_df['DateTime'] <= day_end_dt)]
        if after.empty: continue

        direction = entry = ex_price = ex_reason = None
        pnl = 0; peak = 0

        for _, bar in after.iterrows():
            if bar['_time'] > day_end: break
            if direction is None:
                if bar['High'] > fh: direction, entry = '多', fh
                elif bar['Low'] < fl: direction, entry = '空', fl
            if direction and not ex_reason:
                cp = (bar['High']-entry) if direction=='多' else (entry-bar['Low'])
                cl = (entry-bar['Low'])  if direction=='多' else (bar['High']-entry)
                peak = max(peak, cp)
                if cl >= sl:
                    ex_price = entry-sl if direction=='多' else entry+sl
                    pnl = -sl; ex_reason = '停損'; break
                # 階梯移動停利
                if peak >= trail_l1:
                    td = TRAIL_D3 if peak>=TRAIL_L3 else (TRAIL_D2 if peak>=TRAIL_L2 else TRAIL_D1)
                    if peak - cp >= td:
                        locked = peak - td
                        ex_price = entry+locked if direction=='多' else entry-locked
                        pnl = locked; ex_reason = '移動停利'; break
                if cp >= tp:
                    ex_price = entry+tp if direction=='多' else entry-tp
                    pnl = tp; ex_reason = '停利'; break

        if direction and not ex_reason:
            last = after.iloc[-1]
            ex_price = last['Close']
            pnl = (ex_price-entry) if direction=='多' else (entry-ex_price)
            ex_reason = '強制平倉'

        if direction:
            trades.append({'pnl_pt': round(pnl,1), 'net': round(pnl*POINT_VALUE-COMMISSION), 'reason': ex_reason})

    if not trades: return None
    t = pd.DataFrame(trades)
    wins = t[t['pnl_pt']>0]; loss = t[t['pnl_pt']<0]
    wr  = len(wins)/len(t)*100
    pf  = wins['pnl_pt'].sum()/abs(loss['pnl_pt'].sum()) if len(loss) else 99
    net = t['net'].sum()
    eq  = t['net'].cumsum()
    mdd = (eq-eq.cummax()).min()
    months = max(((pd.to_datetime('2023-12-29')-pd.to_datetime('2011-01-20')).days)/30, 1)
    return {'trail_l1': trail_l1, 'trades': len(t), 'wr': wr, 'pf': pf,
            'net': net, 'mdd': mdd, 'monthly': net/months}

print('載入資料...')
df = pd.read_csv(CSV_FILE, encoding='utf-8-sig')
df['DateTime'] = pd.to_datetime(df['Date'].astype(str)+' '+df['Time'].astype(str))
df = df.sort_values('DateTime').reset_index(drop=True)
df['_date'] = df['DateTime'].dt.date
df['_time'] = df['DateTime'].dt.time
atr_map = calc_daily_atr(df)
print('ATR完成，開始掃描...\n')

print(f"{'TRAIL_L1':>10} {'交易數':>7} {'勝率':>7} {'獲利因子':>9} {'累積淨利':>12} {'最大回撤':>11} {'月均':>9}")
print('-'*70)

results = []
for l1 in [30, 35, 40, 45, 50, 55, 60, 65]:
    r = run_one(df, atr_map, l1)
    if r:
        results.append(r)
        print(f"  {r['trail_l1']:>8}  {r['trades']:>7}  {r['wr']:>6.1f}%  {r['pf']:>9.2f}  {r['net']:>11,.0f}元  {r['mdd']:>10,.0f}元  {r['monthly']:>8,.0f}元")

best = max(results, key=lambda x: x['net'])
print(f"\n最佳 TRAIL_L1 = {best['trail_l1']}  →  獲利因子 {best['pf']:.2f}  累積淨利 {best['net']:,.0f}元  月均 {best['monthly']:,.0f}元")
