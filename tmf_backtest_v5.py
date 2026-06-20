"""
═══════════════════════════════════════════════════════════
  微台期｜開盤15分K突破策略【v5.0 最佳化版】
═══════════════════════════════════════════════════════════
  策略規則：
    1. 只做 ATR ≥ 歷史第25百分位的日子（排除盤整日）
    2. 只接受 09:15 之後觸發的突破（排除開盤假突破）
    3. 突破方向需與當日 VWAP 一致（多頭在均價上方、空頭在下方）
    4. 嚴格 ATR×0.4 停損，不移動
    5. 移動停利：獲利30點觸發，回撤20點出場
    6. 固定停利：ATR×0.8
    7. 每日只做第一個訊號，尾盤強制平倉
═══════════════════════════════════════════════════════════
"""
import pandas as pd
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import warnings
warnings.filterwarnings('ignore')
from datetime import time, date, timedelta, datetime

CSV_FILE        = 'txf_1min.csv'
ATR_PERIOD      = 14
ATR_SL_MULT     = 0.4
ATR_TP_MULT     = 0.8
TRAIL_TRIGGER   = 30
TRAIL_DISTANCE  = 20
ATR_FILTER_PCT  = 25
ENTRY_EARLIEST  = time(9, 15)   # 不接受 09:00 那根的假突破
FIRST_BAR_START = time(8, 45)
DAY_END_NORMAL  = time(13, 40)
DAY_END_SETTLE  = time(13, 25)
POINT_VALUE     = 10
COMMISSION      = 30

def is_settlement_day(d):
    if d.weekday() != 2: return False
    return sum(1 for x in range(1, d.day+1) if date(d.year,d.month,x).weekday()==2) == 3

# ══ 載入並準備資料 ══
def load_and_prepare(filepath):
    raw = pd.read_csv(filepath, encoding='utf-8-sig')
    raw['DateTime'] = pd.to_datetime(raw['Date'].astype(str)+' '+raw['Time'].astype(str))
    raw = raw.sort_values('DateTime').reset_index(drop=True)
    raw_idx = raw.set_index('DateTime')

    # 15分K
    df15 = raw_idx[['Open','High','Low','Close','Volume']].resample('15min',label='left').agg(
        {'Open':'first','High':'max','Low':'min','Close':'last','Volume':'sum'}
    ).dropna().reset_index()
    df15['Date'] = df15['DateTime'].dt.date
    df15['Time'] = df15['DateTime'].dt.time

    # 日ATR
    daily = raw_idx[['Open','High','Low','Close']].resample('1D').agg(
        {'Open':'first','High':'max','Low':'min','Close':'last'}).dropna()
    daily['PC']  = daily['Close'].shift(1)
    daily['TR']  = daily.apply(lambda r: max(
        r['High']-r['Low'],
        abs(r['High']-r['PC']) if pd.notna(r['PC']) else 0,
        abs(r['Low'] -r['PC']) if pd.notna(r['PC']) else 0), axis=1)
    daily['ATR'] = daily['TR'].rolling(ATR_PERIOD).mean()
    atr_map = {d.date(): v for d,v in zip(daily.index, daily['ATR'])}

    # 日內 VWAP（從 08:45 起算）
    raw['_date'] = raw['DateTime'].dt.date
    raw['_time'] = raw['DateTime'].dt.time
    day_raw = raw[(raw['_time'] >= time(8,45)) & (raw['_time'] <= time(13,45))].copy()
    day_raw['TP']     = (day_raw['High']+day_raw['Low']+day_raw['Close'])/3
    day_raw['TPV']    = day_raw['TP'] * day_raw['Volume']
    day_raw['cumTPV'] = day_raw.groupby('_date')['TPV'].cumsum()
    day_raw['cumVol'] = day_raw.groupby('_date')['Volume'].cumsum()
    day_raw['VWAP']   = day_raw['cumTPV'] / day_raw['cumVol']
    vwap_idx = day_raw.set_index('DateTime')[['VWAP']]

    return df15, atr_map, vwap_idx

def get_vwap_at(vwap_idx, dt):
    loc = vwap_idx.index.searchsorted(dt, side='right') - 1
    if loc < 0: return np.nan
    return float(vwap_idx.iloc[loc]['VWAP'])

# ══ 回測 ══
def run_backtest(df15, atr_map, vwap_idx):
    valid_atrs = np.array([v for v in atr_map.values() if not np.isnan(v)])
    atr_thresh = np.percentile(valid_atrs, ATR_FILTER_PCT)
    print(f'ATR 過濾門檻（P{ATR_FILTER_PCT}）：{atr_thresh:.1f} 點')

    trades = []
    for trade_date, group in df15.groupby('Date'):
        atr = atr_map.get(trade_date, np.nan)
        if pd.isna(atr) or atr <= 0 or atr < atr_thresh: continue

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

        direction = entry = ex_reason = None
        pnl = 0; peak = 0

        for _, bar in subsequent.iterrows():
            if bar['Time'] > day_end: break

            # 進場
            if direction is None:
                if bar['Time'] < ENTRY_EARLIEST: continue  # 等 09:15
                cand = None
                if bar['High'] > fh: cand = '多'
                elif bar['Low'] < fl: cand = '空'
                if cand:
                    # VWAP 確認
                    bar_dt   = datetime.combine(trade_date, bar['Time'])
                    vwap_val = get_vwap_at(vwap_idx, bar_dt)
                    if not np.isnan(vwap_val):
                        if cand == '多' and bar['Close'] < vwap_val: continue
                        if cand == '空' and bar['Close'] > vwap_val: continue
                    direction = cand
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
            trades.append({
                '日期': str(trade_date), '方向': direction,
                '結算日': '是' if settle else '',
                'ATR': round(atr), '停損': sl, '停利': tp,
                '進場價': round(entry), '出場原因': ex_reason,
                '損益點數': round(pnl,1),
                '淨損益(元)': round(pnl*POINT_VALUE-COMMISSION),
            })

    return pd.DataFrame(trades)

# ══ 報表 ══
def print_report(t):
    if t.empty: return
    n   = len(t)
    w   = t[t['損益點數']>0]; l = t[t['損益點數']<0]
    wr  = len(w)/n*100
    pf  = w['損益點數'].sum()/abs(l['損益點數'].sum()) if len(l) else 99
    aw  = w['損益點數'].mean() if len(w) else 0
    al  = l['損益點數'].mean() if len(l) else 0
    net = t['淨損益(元)'].sum()
    eq  = t['淨損益(元)'].cumsum()
    mdd = (eq-eq.cummax()).min()
    days= (pd.to_datetime(t['日期'].max())-pd.to_datetime(t['日期'].min())).days
    mo  = max(days/30,1)

    print('\n'+'='*62)
    print('  微台期｜開盤15分K突破策略 v5.0（最佳化版）')
    print('='*62)
    print(f'  回測期間  ：{t["日期"].min()} ~ {t["日期"].max()}')
    print(f'  進場條件  ：ATR≥P25 + 09:15後進場 + VWAP方向一致')
    print(f'  停損模式  ：ATR × {ATR_SL_MULT}（嚴格不動）')
    print(f'  移動停利  ：觸發{TRAIL_TRIGGER}點 / 回撤{TRAIL_DISTANCE}點')
    print('-'*62)
    print(f'  總交易次數：{n} 次')
    print(f'  勝     率：{wr:.1f}%')
    print(f'  平均獲利 ：+{aw:.1f} 點')
    print(f'  平均虧損 ：{al:.1f} 點')
    print(f'  獲利因子 ：{pf:.2f}')
    print(f'  最大回撤 ：{mdd:,.0f} 元')
    print(f'  累積淨利 ：{net:,.0f} 元')
    print(f'  月均損益 ：{net/mo:,.0f} 元')
    print('-'*62)
    print('  出場原因分佈：')
    for reason, cnt in t['出場原因'].value_counts().items():
        print(f'    {reason}：{cnt}次（{cnt/n*100:.1f}%）')
    print('='*62)

    # 逐年統計
    print('\n  ── 逐年損益（驗證穩定性）──')
    print(f"  {'年份':>5}  {'次數':>5}  {'勝率':>7}  {'PF':>6}  {'淨利':>10}  {'MDD':>9}")
    print('  ' + '-'*52)
    t['年份'] = pd.to_datetime(t['日期']).dt.year
    for yr, g in t.groupby('年份'):
        gw = g[g['損益點數']>0]; gl = g[g['損益點數']<0]
        y_wr  = len(gw)/len(g)*100
        y_pf  = gw['損益點數'].sum()/abs(gl['損益點數'].sum()) if len(gl) else 99
        y_net = g['淨損益(元)'].sum()
        y_eq  = g['淨損益(元)'].cumsum()
        y_mdd = (y_eq-y_eq.cummax()).min()
        print(f'  {yr}  {len(g):>5}  {y_wr:>6.1f}%  {y_pf:>5.2f}  {y_net:>9,.0f}元  {y_mdd:>8,.0f}元')

    # 與 v4.0 比較
    print('\n  ── vs v4.0 基準版對比 ──')
    v4 = {'勝率':65.1,'PF':1.97,'月均':2167,'累積':341400,'MDD':-8510}
    v5 = {'勝率':wr,  'PF':pf,  '月均':net/mo,'累積':net,'MDD':mdd}
    for k in ['勝率','PF','月均','累積','MDD']:
        diff = v5[k]-v4[k]
        sign = '+' if diff>=0 else ''
        print(f'  {k}：{v4[k]:>10} → {v5[k]:>12.1f}  ({sign}{diff:.1f})')

# ══ 繪圖 ══
def plot_results(t):
    if t.empty: return
    for font in ['Microsoft JhengHei','Microsoft YaHei','Arial Unicode MS']:
        try: plt.rcParams['font.family'] = font; break
        except: pass
    plt.rcParams['axes.unicode_minus'] = False

    fig, axes = plt.subplots(2, 2, figsize=(14, 10))
    fig.patch.set_facecolor('#0f172a')
    for ax in axes.flat:
        ax.set_facecolor('#1e293b'); ax.tick_params(colors='#94a3b8')
        for s in ['top','right']: ax.spines[s].set_visible(False)
        for s in ['bottom','left']: ax.spines[s].set_color('#334155')

    eq = t['淨損益(元)'].cumsum()
    col = '#22c55e' if eq.iloc[-1]>=0 else '#ef4444'
    axes[0,0].plot(range(len(eq)), eq.values, color=col, lw=2)
    axes[0,0].fill_between(range(len(eq)), eq.values, 0, alpha=0.15, color=col)
    axes[0,0].axhline(0, color='#475569', ls='--', lw=1)
    axes[0,0].set_title('累積損益曲線（元）', color='#e2e8f0', fontsize=13)

    cols = ['#22c55e' if p>0 else '#ef4444' for p in t['淨損益(元)']]
    axes[0,1].bar(range(len(t)), t['淨損益(元)'].values, color=cols, alpha=0.8)
    axes[0,1].axhline(0, color='#475569', ls='--', lw=1)
    axes[0,1].set_title('每筆交易損益（元）', color='#e2e8f0', fontsize=13)

    counts = t['出場原因'].value_counts()
    axes[1,0].pie(counts.values, labels=counts.index, autopct='%1.1f%%',
                  colors=['#22c55e','#ef4444','#f59e0b','#60a5fa'][:len(counts)],
                  textprops={'color':'#e2e8f0'})
    axes[1,0].set_title('出場原因分佈', color='#e2e8f0', fontsize=13)

    t['月份'] = pd.to_datetime(t['日期']).dt.to_period('M')
    monthly = t.groupby('月份')['淨損益(元)'].sum()
    bar_colors = ['#22c55e' if v>=0 else '#ef4444' for v in monthly.values]
    axes[1,1].bar(range(len(monthly)), monthly.values, color=bar_colors, alpha=0.8)
    axes[1,1].axhline(0, color='#475569', ls='--', lw=1)
    axes[1,1].set_title('月損益走勢（13年）', color='#e2e8f0', fontsize=13)
    axes[1,1].set_xlabel('月份（依序）', color='#94a3b8', fontsize=10)

    plt.tight_layout()
    plt.savefig('backtest_v5_result.png', dpi=150, bbox_inches='tight', facecolor='#0f172a')
    print('\n圖表已儲存：backtest_v5_result.png')

if __name__ == '__main__':
    print('微台期 開盤15分K突破策略 v5.0 啟動')
    print('進場條件：ATR≥P25 + 09:15後進場 + VWAP方向確認\n')
    df15, atr_map, vwap_idx = load_and_prepare(CSV_FILE)
    print(f'資料載入完成，共 {len(df15["Date"].unique())} 個交易日')
    trades = run_backtest(df15, atr_map, vwap_idx)
    print(f'回測完成：{len(trades)} 筆交易\n')
    print_report(trades)
    trades.to_csv('trades_v5_detail.csv', index=False, encoding='utf-8-sig')
    print('交易明細已儲存：trades_v5_detail.csv')
    plot_results(trades)
