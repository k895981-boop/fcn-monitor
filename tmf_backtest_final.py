"""
═══════════════════════════════════════════════════════════
  微台期｜開盤15分K突破策略【最終優化版 v4.0】
═══════════════════════════════════════════════════════════
  基於 v2 策略 + 進場過濾最佳化：
    ✅ ATR 動態停損（× 0.4，嚴格不移動）
    ✅ 移動停利（獲利30點觸發，回撤20點出場）
    ✅ 固定停利（ATR × 0.8）
    ✅ 每日單次交易，尾盤強制平倉
    ✅ 進場過濾：只做 ATR ≥ 歷史第25百分位的日子
       （排除市場最安靜的25%交易日，避免盤整洗出）
═══════════════════════════════════════════════════════════
"""
import pandas as pd
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import warnings
warnings.filterwarnings('ignore')
from datetime import time, date, timedelta

CSV_FILE        = 'txf_1min.csv'

ATR_PERIOD      = 14
ATR_SL_MULT     = 0.4
ATR_TP_MULT     = 0.8

USE_TRAILING    = True
TRAIL_TRIGGER   = 30
TRAIL_DISTANCE  = 20

# ── 進場過濾 ──
ATR_FILTER_PCT  = 25    # 只做 ATR ≥ 歷史第25百分位的日子

FIRST_BAR_START = time(8, 45)
TRADE_END       = time(13, 40)
SETTLE_DAY_END  = time(13, 25)

POINT_VALUE     = 10
COMMISSION      = 30

# ══════════════════════════════════════
def is_settlement_day(d):
    if d.weekday() != 2: return False
    return sum(1 for x in range(1, d.day+1) if date(d.year,d.month,x).weekday()==2) == 3

def load_and_prepare(filepath):
    df = pd.read_csv(filepath, encoding='utf-8-sig')
    df.columns = [c.strip() for c in df.columns]
    df['DateTime'] = pd.to_datetime(df['Date'].astype(str)+' '+df['Time'].astype(str))
    df = df.sort_values('DateTime').reset_index(drop=True)
    idx = df.set_index('DateTime')

    df15 = idx[['Open','High','Low','Close','Volume']].resample('15min', label='left').agg(
        {'Open':'first','High':'max','Low':'min','Close':'last','Volume':'sum'}
    ).dropna().reset_index()
    df15['Date'] = df15['DateTime'].dt.date
    df15['Time'] = df15['DateTime'].dt.time

    daily = idx[['Open','High','Low','Close']].resample('1D').agg(
        {'Open':'first','High':'max','Low':'min','Close':'last'}).dropna()
    daily['PC']  = daily['Close'].shift(1)
    daily['TR']  = daily.apply(lambda r: max(
        r['High']-r['Low'],
        abs(r['High']-r['PC']) if pd.notna(r['PC']) else 0,
        abs(r['Low'] -r['PC']) if pd.notna(r['PC']) else 0), axis=1)
    daily['ATR'] = daily['TR'].rolling(ATR_PERIOD).mean()
    atr_map = {d.date(): v for d,v in zip(daily.index, daily['ATR'])}

    return df15, atr_map

def run_backtest(df15, atr_map):
    # ATR 過濾門檻（全期ATR的第25百分位）
    valid_atrs = np.array([v for v in atr_map.values() if not np.isnan(v)])
    atr_threshold = np.percentile(valid_atrs, ATR_FILTER_PCT)
    print(f'ATR 過濾門檻（P{ATR_FILTER_PCT}）：{atr_threshold:.1f} 點')

    trades = []
    skipped = 0

    for trade_date, group in df15.groupby('Date'):
        atr = atr_map.get(trade_date, np.nan)
        if pd.isna(atr) or atr <= 0: continue

        # 進場過濾
        if atr < atr_threshold:
            skipped += 1
            continue

        sl = max(1, round(atr * ATR_SL_MULT))
        tp = max(1, round(atr * ATR_TP_MULT))
        settle  = is_settlement_day(trade_date)
        day_end = SETTLE_DAY_END if settle else TRADE_END

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
                if USE_TRAILING and peak >= TRAIL_TRIGGER and peak-cp >= TRAIL_DISTANCE:
                    pnl = peak - TRAIL_DISTANCE; ex_reason = '移動停利'; break
                if cp >= tp:
                    pnl = tp; ex_reason = '停利'; break

        if direction and not ex_reason:
            last = subsequent.iloc[-1]
            ep = last['Close']
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

    print(f'過濾掉低ATR日：{skipped} 天（占 {skipped/(skipped+len(trades))*100:.1f}%）')
    return pd.DataFrame(trades)

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

    print('\n'+'='*60)
    print('  微台期｜開盤15分K突破策略 v4.0（最終優化版）')
    print('='*60)
    print(f'  回測期間  ：{t["日期"].min()} ~ {t["日期"].max()}')
    print(f'  進場過濾  ：ATR ≥ 歷史第{ATR_FILTER_PCT}百分位')
    print(f'  停損模式  ：ATR × {ATR_SL_MULT}（嚴格不動）')
    print(f'  移動停利  ：觸發{TRAIL_TRIGGER}點 / 回撤{TRAIL_DISTANCE}點')
    print('-'*60)
    print(f'  總交易次數：{n} 次')
    print(f'  勝     率：{wr:.1f}%')
    print(f'  平均獲利 ：+{aw:.1f} 點')
    print(f'  平均虧損 ：{al:.1f} 點')
    print(f'  獲利因子 ：{pf:.2f}')
    print(f'  最大回撤 ：{mdd:,.0f} 元')
    print(f'  累積淨利 ：{net:,.0f} 元')
    print(f'  月均損益 ：{net/mo:,.0f} 元')
    print('-'*60)
    print('  出場原因分佈：')
    for reason, cnt in t['出場原因'].value_counts().items():
        print(f'    {reason}：{cnt}次（{cnt/n*100:.1f}%）')
    print('='*60)

    # 與基準版(v2)比較
    print('\n  ── vs v2 基準版對比 ──')
    base = {'勝率':62.0, 'PF':1.87, '月均':2260, '累積':357240, 'MDD':-7770}
    now  = {'勝率':wr,   'PF':pf,   '月均':net/mo,'累積':net,   'MDD':mdd}
    for k in ['勝率','PF','月均','累積','MDD']:
        diff = now[k]-base[k]
        sign = '+' if diff>=0 else ''
        print(f'  {k}：{base[k]:>10} → {now[k]:>10.1f}  ({sign}{diff:.1f})')

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

    # ATR分佈（已交易 vs 已過濾）
    axes[1,1].set_title('月損益走勢', color='#e2e8f0', fontsize=13)
    t['月份'] = pd.to_datetime(t['日期']).dt.to_period('M')
    monthly = t.groupby('月份')['淨損益(元)'].sum()
    bar_colors = ['#22c55e' if v>=0 else '#ef4444' for v in monthly.values]
    axes[1,1].bar(range(len(monthly)), monthly.values, color=bar_colors, alpha=0.8)
    axes[1,1].axhline(0, color='#475569', ls='--', lw=1)
    axes[1,1].set_xlabel('月份（依序）', color='#94a3b8', fontsize=10)

    plt.tight_layout()
    plt.savefig('backtest_v4_result.png', dpi=150, bbox_inches='tight', facecolor='#0f172a')
    print('圖表已儲存：backtest_v4_result.png')

if __name__ == '__main__':
    print('微台期 開盤15分K突破策略 v4.0 啟動')
    df15, atr_map = load_and_prepare(CSV_FILE)
    print(f'資料載入完成，共 {len(df15["Date"].unique())} 個交易日')
    trades = run_backtest(df15, atr_map)
    print(f'回測完成：{len(trades)} 筆交易\n')
    print_report(trades)
    trades.to_csv('trades_v4_detail.csv', index=False, encoding='utf-8-sig')
    print('交易明細已儲存：trades_v4_detail.csv')
    plot_results(trades)
