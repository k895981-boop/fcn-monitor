"""
═══════════════════════════════════════════════════════════
  微台期｜開盤15分K突破策略【v3b：15分K出場 + 階梯移動停利】
═══════════════════════════════════════════════════════════
  v3b 修正重點：
    - 進出場判斷全部基於15分K（與v2相同）
    - 升級為階梯式移動停利：
        獲利 < L1          → 不啟動
        L1 ~ L2            → 回撤 D1（緊，保護小獲利）
        L2 ~ L3            → 回撤 D2（中）
        > L3               → 回撤 D3（寬，讓大趨勢跑）
    - 嚴格ATR停損，不移動
    - 每日只做第一個訊號，日盤收盤前強制平倉
    - 支援日盤 + 夜盤各自獨立操作
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

# ══════════════════════════════════════
# 參數設定
# ══════════════════════════════════════
CSV_FILE        = 'txf_all_sessions.csv'

ATR_PERIOD      = 14
ATR_SL_MULT     = 0.4
ATR_TP_MULT     = 0.8

# 階梯移動停利（基於15分K獲利點數）
USE_TRAILING    = True
TRAIL_L1        = 30    # 達此點啟動第一段
TRAIL_D1        = 20    # 回撤20點出場（與v2原始相同）
TRAIL_L2        = 60    # 達此點進入第二段
TRAIL_D2        = 30    # 回撤30點（稍放寬）
TRAIL_L3        = 120   # 達此點進入第三段（大趨勢）
TRAIL_D3        = 50    # 回撤50點（讓趨勢跑）

# 時段控制
TRADE_DAY       = True
TRADE_NIGHT     = False   # 夜盤預設關閉（可改True）

# 日盤
DAY_FIRST_BAR   = time(8, 45)
DAY_END_NORMAL  = time(13, 40)
DAY_END_SETTLE  = time(13, 25)

# 夜盤
NIGHT_FIRST_BAR = time(15, 0)
NIGHT_END       = time(4, 55)

POINT_VALUE     = 10
COMMISSION      = 30

# ══════════════════════════════════════
# 讀取資料
# ══════════════════════════════════════
def load_data(filepath):
    df = pd.read_csv(filepath, encoding='utf-8-sig')
    df.columns = [c.strip() for c in df.columns]
    df['DateTime'] = pd.to_datetime(df['Date'].astype(str) + ' ' + df['Time'].astype(str))
    df = df.sort_values('DateTime').reset_index(drop=True)
    return df

# ══════════════════════════════════════
# 聚合15分K（指定時間範圍）
# ══════════════════════════════════════
def resample_15min(df, start_dt, end_dt):
    mask = (df['DateTime'] >= start_dt) & (df['DateTime'] <= end_dt)
    seg = df[mask].copy().set_index('DateTime')
    if seg.empty:
        return pd.DataFrame()
    df15 = seg[['Open','High','Low','Close','Volume']].resample('15min', label='left').agg(
        {'Open':'first','High':'max','Low':'min','Close':'last','Volume':'sum'}
    ).dropna()
    df15['Time'] = df15.index.time
    return df15.reset_index()

# ══════════════════════════════════════
# 每日ATR
# ══════════════════════════════════════
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

# ══════════════════════════════════════
# 結算日
# ══════════════════════════════════════
def is_settlement_day(d):
    if d.weekday() != 2: return False
    return sum(1 for x in range(1, d.day+1) if date(d.year,d.month,x).weekday()==2) == 3

# ══════════════════════════════════════
# 階梯移動停利
# ══════════════════════════════════════
def check_trailing(peak_profit, cur_profit):
    if not USE_TRAILING or peak_profit < TRAIL_L1:
        return False, 0
    trail_dist = TRAIL_D3 if peak_profit >= TRAIL_L3 else \
                 TRAIL_D2 if peak_profit >= TRAIL_L2 else TRAIL_D1
    if peak_profit - cur_profit >= trail_dist:
        return True, peak_profit - trail_dist
    return False, 0

# ══════════════════════════════════════
# 單時段回測（基於15分K）
# ══════════════════════════════════════
def backtest_session(df15, first_bar_time, trade_end_time,
                     stop_loss, take_profit, label, atr_val, trade_date, is_settle):
    # 第一根15分K
    first_bars = df15[df15['Time'] == first_bar_time]
    if first_bars.empty:
        return None
    fb = first_bars.iloc[0]
    first_high, first_low = fb['High'], fb['Low']

    subsequent = df15[df15['Time'] > first_bar_time]
    if subsequent.empty:
        return None

    direction = entry = ex_price = ex_reason = None
    pnl = 0; peak = 0

    for _, bar in subsequent.iterrows():
        if bar['Time'] > trade_end_time:
            break
        # 進場
        if direction is None:
            if bar['High'] > first_high:
                direction, entry = '多', first_high
            elif bar['Low'] < first_low:
                direction, entry = '空', first_low
        # 出場
        if direction and not ex_reason:
            cp = (bar['High']-entry) if direction=='多' else (entry-bar['Low'])
            cl = (entry-bar['Low'])  if direction=='多' else (bar['High']-entry)
            peak = max(peak, cp)

            # ① 嚴格停損
            if cl >= stop_loss:
                ex_price = entry-stop_loss if direction=='多' else entry+stop_loss
                pnl = -stop_loss; ex_reason = '停損'; break

            # ② 階梯移動停利
            triggered, locked = check_trailing(peak, cp)
            if triggered:
                ex_price = entry+locked if direction=='多' else entry-locked
                pnl = locked; ex_reason = '移動停利'; break

            # ③ 固定停利
            if cp >= take_profit:
                ex_price = entry+take_profit if direction=='多' else entry-take_profit
                pnl = take_profit; ex_reason = '停利'; break

    # 強制平倉
    if direction and not ex_reason:
        # 找 trade_end_time 之前的最後一根K
        valid = df15[df15['Time'] <= trade_end_time]
        if valid.empty:
            return None
        last = valid.iloc[-1]
        ex_price = last['Close']
        pnl = (ex_price-entry) if direction=='多' else (entry-ex_price)
        ex_reason = '強制平倉'

    if direction is None:
        return None

    return {
        '日期': str(trade_date),
        '時段': label,
        '結算日': '是' if is_settle else '',
        '方向': direction,
        'ATR': atr_val,
        '停損': stop_loss,
        '停利': take_profit,
        '進場價': round(entry),
        '出場價': round(ex_price),
        '出場原因': ex_reason,
        '損益點數': round(pnl, 1),
        '淨損益(元)': round(pnl * POINT_VALUE - COMMISSION),
    }

# ══════════════════════════════════════
# 主回測
# ══════════════════════════════════════
def run_backtest(df, atr_map):
    trades = []
    all_dates = sorted(df['DateTime'].dt.date.unique())

    for trade_date in all_dates:
        atr = atr_map.get(trade_date, np.nan)
        if pd.isna(atr) or atr <= 0:
            continue
        sl  = max(1, round(atr * ATR_SL_MULT))
        tp  = max(1, round(atr * ATR_TP_MULT))
        av  = round(atr)
        settle = is_settlement_day(trade_date)

        # ── 日盤 ──
        if TRADE_DAY:
            day_end = DAY_END_SETTLE if settle else DAY_END_NORMAL
            s = datetime.combine(trade_date, DAY_FIRST_BAR)
            e = datetime.combine(trade_date, day_end)
            df15 = resample_15min(df, s, e)
            if not df15.empty:
                r = backtest_session(df15, DAY_FIRST_BAR, day_end,
                                     sl, tp, '日盤', av, trade_date, settle)
                if r:
                    trades.append(r)

        # ── 夜盤 ──
        if TRADE_NIGHT:
            next_day = trade_date + timedelta(days=1)
            s = datetime.combine(trade_date, NIGHT_FIRST_BAR)
            e = datetime.combine(next_day, NIGHT_END)
            df15 = resample_15min(df, s, e)
            if not df15.empty:
                r = backtest_session(df15, NIGHT_FIRST_BAR, NIGHT_END,
                                     sl, tp, '夜盤', av, trade_date, False)
                if r:
                    trades.append(r)

    return pd.DataFrame(trades)

# ══════════════════════════════════════
# 報表
# ══════════════════════════════════════
def print_report(trades_df):
    if trades_df.empty:
        print('無交易紀錄'); return

    def section(df, label):
        n = len(df)
        if n == 0: return
        w = df[df['損益點數']>0]; l = df[df['損益點數']<0]
        wr  = len(w)/n*100
        pf  = w['損益點數'].sum()/abs(l['損益點數'].sum()) if len(l) else 99
        aw  = w['損益點數'].mean() if len(w) else 0
        al  = l['損益點數'].mean() if len(l) else 0
        net = df['淨損益(元)'].sum()
        eq  = df['淨損益(元)'].cumsum()
        mdd = (eq-eq.cummax()).min()
        days= (pd.to_datetime(df['日期'].max())-pd.to_datetime(df['日期'].min())).days
        mo  = max(days/30,1)
        print(f'\n  ── {label}（{n} 次）──')
        print(f'  勝率 {wr:.1f}%  |  獲利因子 {pf:.2f}')
        print(f'  平均獲利 +{aw:.1f} 點  |  平均虧損 {al:.1f} 點')
        print(f'  最大回撤 {mdd:,.0f} 元  |  累積淨利 {net:,.0f} 元  |  月均 {net/mo:,.0f} 元')
        for reason, cnt in df['出場原因'].value_counts().items():
            print(f'    {reason}：{cnt}次（{cnt/n*100:.1f}%）')

    t = trades_df
    n = len(t)
    w = t[t['損益點數']>0]; l = t[t['損益點數']<0]
    wr  = len(w)/n*100
    pf  = w['損益點數'].sum()/abs(l['損益點數'].sum()) if len(l) else 99
    aw  = w['損益點數'].mean() if len(w) else 0
    al  = l['損益點數'].mean() if len(l) else 0
    net = t['淨損益(元)'].sum()
    eq  = t['淨損益(元)'].cumsum()
    mdd = (eq-eq.cummax()).min()
    days= (pd.to_datetime(t['日期'].max())-pd.to_datetime(t['日期'].min())).days
    mo  = max(days/30,1)

    trail_info = f'階梯式 {TRAIL_L1}pt/{TRAIL_D1}回→{TRAIL_L2}pt/{TRAIL_D2}回→{TRAIL_L3}pt/{TRAIL_D3}回'

    print('='*62)
    print('  微台期｜開盤15分K突破策略 v3b｜日夜盤回測報告')
    print('='*62)
    print(f'  回測期間 ：{t["日期"].min()} ~ {t["日期"].max()}')
    print(f'  停損模式 ：ATR × {ATR_SL_MULT}（嚴格不動）')
    print(f'  移動停利 ：{trail_info}')
    print(f'  日盤{"開啟" if TRADE_DAY else "關閉"}  |  夜盤{"開啟" if TRADE_NIGHT else "關閉"}')
    print('-'*62)
    print(f'  總交易次數：{n} 次')
    print(f'  整體勝率  ：{wr:.1f}%')
    print(f'  平均獲利  ：+{aw:.1f} 點')
    print(f'  平均虧損  ：{al:.1f} 點')
    print(f'  獲利因子  ：{pf:.2f}')
    print(f'  最大回撤  ：{mdd:,.0f} 元')
    print(f'  累積淨利  ：{net:,.0f} 元')
    print(f'  月均損益  ：{net/mo:,.0f} 元')
    print('-'*62)
    print('  出場原因分佈（整體）：')
    for reason, cnt in t['出場原因'].value_counts().items():
        print(f'    {reason}：{cnt}次（{cnt/n*100:.1f}%）')

    if TRADE_DAY and TRADE_NIGHT:
        section(t[t['時段']=='日盤'], '日盤')
        section(t[t['時段']=='夜盤'], '夜盤')
    print('='*62)

# ══════════════════════════════════════
# 繪圖
# ══════════════════════════════════════
def plot_results(trades_df):
    if trades_df.empty: return
    for font in ['Microsoft JhengHei','Microsoft YaHei','Arial Unicode MS']:
        try: plt.rcParams['font.family'] = font; break
        except: pass
    plt.rcParams['axes.unicode_minus'] = False

    ncols = 2 if (TRADE_DAY and TRADE_NIGHT) else 1
    fig, axes = plt.subplots(2, 2, figsize=(14, 10))
    fig.patch.set_facecolor('#0f172a')
    for ax in axes.flat:
        ax.set_facecolor('#1e293b')
        ax.tick_params(colors='#94a3b8')
        for s in ['top','right']: ax.spines[s].set_visible(False)
        for s in ['bottom','left']: ax.spines[s].set_color('#334155')

    eq = trades_df['淨損益(元)'].cumsum()
    col = '#22c55e' if eq.iloc[-1]>=0 else '#ef4444'
    axes[0,0].plot(range(len(eq)), eq.values, color=col, lw=2)
    axes[0,0].fill_between(range(len(eq)), eq.values, 0, alpha=0.15, color=col)
    axes[0,0].axhline(0, color='#475569', ls='--', lw=1)
    axes[0,0].set_title('累積損益曲線（元）', color='#e2e8f0', fontsize=12)

    cols = ['#22c55e' if p>0 else '#ef4444' for p in trades_df['淨損益(元)']]
    axes[0,1].bar(range(len(trades_df)), trades_df['淨損益(元)'].values, color=cols, alpha=0.8)
    axes[0,1].axhline(0, color='#475569', ls='--', lw=1)
    axes[0,1].set_title('每筆交易損益（元）', color='#e2e8f0', fontsize=12)

    counts = trades_df['出場原因'].value_counts()
    axes[1,0].pie(counts.values, labels=counts.index, autopct='%1.1f%%',
                  colors=['#22c55e','#ef4444','#f59e0b','#60a5fa'][:len(counts)],
                  textprops={'color':'#e2e8f0'})
    axes[1,0].set_title('出場原因分佈', color='#e2e8f0', fontsize=12)

    if TRADE_DAY and TRADE_NIGHT:
        for session, color in [('日盤','#60a5fa'),('夜盤','#f59e0b')]:
            s_df = trades_df[trades_df['時段']==session]
            if not s_df.empty:
                eq_s = s_df['淨損益(元)'].cumsum().reset_index(drop=True)
                axes[1,1].plot(range(len(eq_s)), eq_s.values, color=color, lw=2, label=session)
        axes[1,1].axhline(0, color='#475569', ls='--', lw=1)
        axes[1,1].legend(facecolor='#1e293b', labelcolor='#e2e8f0')
        axes[1,1].set_title('日盤 vs 夜盤', color='#e2e8f0', fontsize=12)
    else:
        axes[1,1].axis('off')

    plt.tight_layout()
    out = 'backtest_v3b_result.png'
    plt.savefig(out, dpi=150, bbox_inches='tight', facecolor='#0f172a')
    print(f'\n圖表已儲存：{out}')

# ══════════════════════════════════════
# 主程式
# ══════════════════════════════════════
if __name__ == '__main__':
    print('\n微台期 開盤15分K突破策略 v3b 啟動')
    print(f'  日盤：{"開啟" if TRADE_DAY else "關閉"}  |  夜盤：{"開啟" if TRADE_NIGHT else "關閉"}')
    print(f'  停損：ATR×{ATR_SL_MULT}  |  固定停利：ATR×{ATR_TP_MULT}')
    print(f'  階梯停利：{TRAIL_L1}pt/{TRAIL_D1}回 → {TRAIL_L2}pt/{TRAIL_D2}回 → {TRAIL_L3}pt/{TRAIL_D3}回\n')

    df = load_data(CSV_FILE)
    print(f'資料載入：{len(df):,} 筆')
    atr_map = calc_daily_atr(df)
    print('ATR計算完成，開始回測...\n')

    trades = run_backtest(df, atr_map)
    print(f'回測完成：{len(trades)} 筆交易\n')

    print_report(trades)
    trades.to_csv('trades_v3b_detail.csv', index=False, encoding='utf-8-sig')
    print('交易明細已儲存：trades_v3b_detail.csv')
    plot_results(trades)
