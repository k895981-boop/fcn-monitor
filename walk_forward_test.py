"""
走步式驗證（Walk-Forward Validation）
目的：確認 v5.1 策略是真實有效，還是對歷史資料過度擬合

測試方式：
  樣本內（In-Sample）  ：2011～2016（用這段資料訂出 ATR P25 門檻）
  樣本外（Out-of-Sample）：2017～2023（用全新的資料測試，模擬真實未來）

如果策略有真實邏輯基礎，樣本外的表現應該接近樣本內。
如果差距很大，代表過度擬合，上線需要更謹慎。
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
ENTRY_EARLIEST  = time(9, 15)
FIRST_BAR_START = time(8, 45)
DAY_END_NORMAL  = time(13, 40)
DAY_END_SETTLE  = time(13, 25)
POINT_VALUE     = 10
COMMISSION      = 30

IN_SAMPLE_END   = '2016-12-31'
OOS_START       = '2017-01-01'

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

# ATR P25 門檻：只用樣本內資料計算
is_end = pd.Timestamp(IN_SAMPLE_END)
in_sample_atrs = [v for d, v in atr_map.items()
                  if pd.Timestamp(d) <= is_end and not np.isnan(v)]
atr_thresh_insample = np.percentile(in_sample_atrs, ATR_FILTER_PCT)

# 全資料的 ATR P25（作為對照）
all_atrs = [v for v in atr_map.values() if not np.isnan(v)]
atr_thresh_full = np.percentile(all_atrs, ATR_FILTER_PCT)

print(f'ATR P25 門檻（樣本內 2011-2016）：{atr_thresh_insample:.1f} 點')
print(f'ATR P25 門檻（全資料 2011-2023）：{atr_thresh_full:.1f} 點')

def get_vwap_at(dt):
    loc = vwap_idx.index.searchsorted(dt, side='right') - 1
    return float(vwap_idx.iloc[loc]['VWAP']) if loc >= 0 else np.nan

def run_period(label, date_start, date_end, atr_thresh):
    trades = []
    ds = pd.Timestamp(date_start).date() if date_start else None
    de = pd.Timestamp(date_end).date() if date_end else None

    for trade_date, group in df15.groupby('Date'):
        if ds and trade_date < ds: continue
        if de and trade_date > de: continue

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
        subsequent = group[group['Time'] > FIRST_BAR_START]
        if subsequent.empty: continue

        direction = entry = ex_reason = None
        pnl = 0; peak = 0

        for _, bar in subsequent.iterrows():
            if bar['Time'] > day_end: break
            if direction is None:
                if bar['Time'] < ENTRY_EARLIEST: continue
                cand = None
                if bar['High'] > fh: cand = '多'
                elif bar['Low'] < fl: cand = '空'
                if cand:
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
            trades.append({
                'date': trade_date,
                'pnl': round(pnl, 1),
                'net': round(pnl * POINT_VALUE - COMMISSION),
                'reason': ex_reason
            })

    if not trades:
        return None
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
    # 計算月數
    t['month'] = pd.to_datetime(t['date']).dt.to_period('M')
    monthly = t.groupby('month')['net'].sum()
    lose_months = (monthly < 0).sum()
    total_months = len(monthly)
    months_f = total_months
    return dict(label=label, n=n, wr=wr, pf=pf, rr=rr, aw=aw, al=al,
                net=net, mdd=mdd, monthly=net/months_f if months_f else 0,
                total_months=total_months, lose_months=lose_months,
                trades=t)

print('\n執行走步式驗證...\n')

r_in  = run_period('樣本內  2011～2016', '2011-01-01', IN_SAMPLE_END,  atr_thresh_insample)
r_oos = run_period('樣本外  2017～2023', OOS_START,    '2023-12-31',   atr_thresh_insample)
r_all = run_period('全資料  2011～2023', '2011-01-01', '2023-12-31',   atr_thresh_full)

SEP = '=' * 68
print(SEP)
print('  走步式驗證結果（v5.1 策略）')
print(SEP)

for r in [r_in, r_oos, r_all]:
    print(f"\n  【{r['label']}】")
    print(f"  交易次數  ：{r['n']} 次")
    print(f"  勝    率  ：{r['wr']:.1f}%")
    print(f"  盈 虧 比  ：{r['rr']:.2f}：1  （均獲 +{r['aw']:.1f}pt / 均虧 {r['al']:.1f}pt）")
    print(f"  獲利因子  ：{r['pf']:.2f}")
    print(f"  月均損益  ：{r['monthly']:,.0f} 元")
    print(f"  最大回撤  ：{r['mdd']:,.0f} 元")
    print(f"  虧損月比  ：{r['lose_months']}/{r['total_months']} 個月（{r['lose_months']/r['total_months']*100:.1f}%）")

print(f'\n{SEP}')
print('  逐年明細（樣本外 2017～2023）')
print(f'{SEP}')
print(f"  {'年份':>5}  {'次數':>5}  {'勝率':>7}  {'PF':>6}  {'月均':>9}  {'年淨利':>11}  {'MDD':>9}")
print('  ' + '-'*62)
oos_trades = r_oos['trades']
oos_trades['year'] = pd.to_datetime(oos_trades['date']).dt.year
for yr, g in oos_trades.groupby('year'):
    gw = g[g['pnl'] > 0]; gl = g[g['pnl'] < 0]
    yr_n   = len(g)
    yr_wr  = len(gw) / yr_n * 100
    yr_pf  = gw['pnl'].sum() / abs(gl['pnl'].sum()) if len(gl) else 99
    yr_net = g['net'].sum()
    eq     = g['net'].cumsum()
    yr_mdd = (eq - eq.cummax()).min()
    g['month'] = pd.to_datetime(g['date']).dt.to_period('M')
    yr_months = len(g.groupby('month'))
    yr_monthly = yr_net / yr_months if yr_months else 0
    print(f"  {yr}  {yr_n:>5}  {yr_wr:>6.1f}%  {yr_pf:>5.2f}  {yr_monthly:>8,.0f}元  {yr_net:>10,.0f}元  {yr_mdd:>8,.0f}元")

print(f'\n{SEP}')
print('  判讀標準')
print(f'{SEP}')
ratio_pf  = r_oos['pf']  / r_in['pf']
ratio_wr  = r_oos['wr']  / r_in['wr']
ratio_mon = r_oos['monthly'] / r_in['monthly']
print(f"  獲利因子  樣本外/樣本內 = {r_oos['pf']:.2f} / {r_in['pf']:.2f} = {ratio_pf:.2f}")
print(f"  勝    率  樣本外/樣本內 = {r_oos['wr']:.1f}% / {r_in['wr']:.1f}% = {ratio_wr:.2f}")
print(f"  月均損益  樣本外/樣本內 = {r_oos['monthly']:,.0f} / {r_in['monthly']:,.0f} = {ratio_mon:.2f}")
print()
if ratio_pf >= 0.7 and r_oos['pf'] >= 1.5 and r_oos['wr'] >= 60:
    print('  結論：樣本外表現合格，策略具備真實邏輯基礎，過度擬合風險較低。')
elif ratio_pf >= 0.5 and r_oos['pf'] >= 1.2:
    print('  結論：樣本外有獲利但明顯衰退，策略有部分過度擬合，上線需謹慎。')
else:
    print('  結論：樣本外表現大幅衰退，策略可能嚴重過度擬合，不建議直接上線。')
print(SEP)
