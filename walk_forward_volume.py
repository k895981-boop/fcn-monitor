"""
成交量過濾的走步式驗證
樣本內：2011～2016（找出量能條件）
樣本外：2017～2023（用全新資料驗證）

測試最有潛力的兩個組合：
  A) 量>均量×1.5 / 前5根
  B) 量>均量×1.8 / 前10根
對照組：v5.1 基準（無量能過濾）
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
df15 = df15.sort_values('DateTime').reset_index(drop=True)

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

# ATR P25 門檻：只用樣本內資料
is_end = pd.Timestamp(IN_SAMPLE_END)
in_atrs = [v for d, v in atr_map.items() if pd.Timestamp(d) <= is_end and not np.isnan(v)]
atr_thresh = np.percentile(in_atrs, ATR_FILTER_PCT)

def get_vwap_at(dt):
    loc = vwap_idx.index.searchsorted(dt, side='right') - 1
    return float(vwap_idx.iloc[loc]['VWAP']) if loc >= 0 else np.nan

def run(date_start, date_end, vol_mult=None, vol_lookback=5):
    trades = []
    ds = pd.Timestamp(date_start).date()
    de = pd.Timestamp(date_end).date()

    for trade_date, group in df15.groupby('Date'):
        if trade_date < ds or trade_date > de: continue
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
                if cand and vol_mult is not None:
                    bar_pos = df15.index[df15['DateTime'] == bar['DateTime']]
                    if len(bar_pos) == 0 or bar_pos[0] < vol_lookback:
                        cand = None
                    else:
                        pos = bar_pos[0]
                        avg_vol = df15.iloc[pos-vol_lookback:pos]['Volume'].mean()
                        if avg_vol <= 0 or bar['Volume'] < avg_vol * vol_mult:
                            cand = None
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

scenarios = [
    ('v5.1 基準（無量能過濾）',   None,  5),
    ('量×1.5 / 前5根',          1.5,   5),
    ('量×1.8 / 前10根',         1.8,  10),
]

SEP = '=' * 72
print(f'\n{SEP}')
print('  走步式驗證：成交量過濾')
print(SEP)

for label, vm, vl in scenarios:
    r_in  = run(IN_SAMPLE_END.replace('2016','2011'), IN_SAMPLE_END, vm, vl)
    r_oos = run(OOS_START, '2023-12-31', vm, vl)

    ratio_pf  = r_oos['pf']  / r_in['pf']
    ratio_wr  = r_oos['wr']  / r_in['wr']
    ratio_mon = r_oos['monthly'] / r_in['monthly']

    if ratio_pf >= 0.7 and r_oos['pf'] >= 1.5 and r_oos['wr'] >= 60:
        verdict = '合格'
    elif ratio_pf >= 0.5 and r_oos['pf'] >= 1.2:
        verdict = '尚可（有衰退）'
    else:
        verdict = '不合格（過度擬合風險高）'

    print(f'\n  ┌─ {label}')
    print(f'  │          {"":10} {"樣本內 2011-2016":>18}  {"樣本外 2017-2023":>18}  {"樣外/樣內":>8}')
    print(f'  │  交易次數  {"":10} {r_in["n"]:>18}  {r_oos["n"]:>18}')
    print(f'  │  勝    率  {"":10} {r_in["wr"]:>17.1f}%  {r_oos["wr"]:>17.1f}%  {ratio_wr:>7.2f}')
    print(f'  │  盈 虧 比  {"":10} {r_in["rr"]:>16.2f}:1  {r_oos["rr"]:>16.2f}:1')
    print(f'  │  獲利因子  {"":10} {r_in["pf"]:>18.2f}  {r_oos["pf"]:>18.2f}  {ratio_pf:>7.2f}')
    print(f'  │  月均損益  {"":10} {r_in["monthly"]:>16,.0f}元  {r_oos["monthly"]:>16,.0f}元  {ratio_mon:>7.2f}')
    print(f'  │  最大回撤  {"":10} {r_in["mdd"]:>16,.0f}元  {r_oos["mdd"]:>16,.0f}元')
    print(f'  │  虧損月數  {"":10} {r_in["lose_mo"]}/{r_in["total_mo"]}個月{"":9}  {r_oos["lose_mo"]}/{r_oos["total_mo"]}個月')
    print(f'  └─ 結論：{verdict}')

    # 樣本外逐年
    print(f'\n  樣本外逐年（{label}）')
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
    print()

print(SEP)
