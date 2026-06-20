"""
═══════════════════════════════════════════════════════════
  微台期｜開盤15分K突破策略【v3.0 日夜盤雙時段】
═══════════════════════════════════════════════════════════
  v3 新增：
    ✅ 日盤 + 夜盤各自獨立操作，各自強制平倉
    ✅ 階梯式移動停利：
         獲利 < TRAIL_L1       → 固定停利保護
         TRAIL_L1 ~ TRAIL_L2  → 回撤 TRAIL_D1（緊）
         TRAIL_L2 ~ TRAIL_L3  → 回撤 TRAIL_D2（中）
         獲利 > TRAIL_L3      → 回撤 TRAIL_D3（寬，讓趨勢跑）
    ✅ 嚴格ATR停損，不移動
    ✅ 每時段只做第一個訊號
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
import os

# ══════════════════════════════════════
# 參數設定
# ══════════════════════════════════════
CSV_FILE        = 'txf_all_sessions.csv'

# ── ATR 停損/停利 ──
ATR_PERIOD      = 14
ATR_SL_MULT     = 0.4    # 停損 = ATR × 0.4（嚴格不動）
ATR_TP_MULT     = 0.8    # 固定停利 = ATR × 0.8

# ── 階梯式移動停利 ──
USE_TRAILING    = True
TRAIL_L1        = 30     # 獲利達此點啟動第一段保護
TRAIL_D1        = 15     # 第一段：回撤15點出場（緊）
TRAIL_L2        = 60     # 獲利達此點進入第二段
TRAIL_D2        = 25     # 第二段：回撤25點（中）
TRAIL_L3        = 120    # 獲利達此點進入第三段（大趨勢）
TRAIL_D3        = 45     # 第三段：回撤45點（寬，讓趨勢跑）

# ── 交易時段控制 ──
TRADE_DAY       = True   # 做日盤
TRADE_NIGHT     = True   # 做夜盤

# ── 日盤時段 ──
DAY_FIRST_BAR   = time(8, 45)
DAY_END_NORMAL  = time(13, 40)   # 一般日強制出場
DAY_END_SETTLE  = time(13, 25)   # 結算日強制出場

# ── 夜盤時段 ──
NIGHT_FIRST_BAR = time(15, 0)
NIGHT_END       = time(4, 55)    # 次日 04:55 強制出場

# ── 商品成本 ──
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
    df['_date'] = df['DateTime'].dt.date
    df['_time'] = df['DateTime'].dt.time
    return df

# ══════════════════════════════════════
# 計算每日ATR
# ══════════════════════════════════════
def calc_daily_atr(df):
    tmp = df.set_index('DateTime')
    daily = tmp[['Open','High','Low','Close']].resample('1D').agg(
        {'Open':'first','High':'max','Low':'min','Close':'last'}
    ).dropna()
    daily['PrevClose'] = daily['Close'].shift(1)
    daily['TR'] = daily.apply(lambda r: max(
        r['High'] - r['Low'],
        abs(r['High'] - r['PrevClose']) if pd.notna(r['PrevClose']) else 0,
        abs(r['Low']  - r['PrevClose']) if pd.notna(r['PrevClose']) else 0,
    ), axis=1)
    daily['ATR'] = daily['TR'].rolling(ATR_PERIOD).mean()
    return {d.date(): atr for d, atr in zip(daily.index, daily['ATR'])}

# ══════════════════════════════════════
# 結算日判斷
# ══════════════════════════════════════
def is_settlement_day(d):
    if d.weekday() != 2:
        return False
    count = sum(1 for day in range(1, d.day + 1) if date(d.year, d.month, day).weekday() == 2)
    return count == 3

# ══════════════════════════════════════
# 階梯式移動停利邏輯
# ══════════════════════════════════════
def check_trailing(peak_profit, cur_profit):
    """回傳是否應出場、以及鎖定的獲利點數"""
    if not USE_TRAILING:
        return False, 0
    if peak_profit < TRAIL_L1:
        return False, 0
    # 決定目前適用的回撤距離
    if peak_profit >= TRAIL_L3:
        trail_dist = TRAIL_D3
    elif peak_profit >= TRAIL_L2:
        trail_dist = TRAIL_D2
    else:
        trail_dist = TRAIL_D1
    drawdown = peak_profit - cur_profit
    if drawdown >= trail_dist:
        locked = peak_profit - trail_dist
        return True, locked
    return False, 0

# ══════════════════════════════════════
# 單筆時段回測（日盤 or 夜盤）
# ══════════════════════════════════════
def backtest_session(session_df, first_bar_start, first_bar_end_dt, trade_end_time,
                     stop_loss, take_profit, session_label, atr_val, trade_date, is_settle):
    """
    session_df   : 該時段的分鐘K（已過濾好時段範圍）
    first_bar_*  : 第一根15分K的起迄 datetime
    trade_end_time: 強制出場的 time 物件
    """
    # 取第一根15分K
    bar_rows = session_df[(session_df['DateTime'] >= first_bar_start) &
                          (session_df['DateTime'] < first_bar_end_dt)]
    if bar_rows.empty:
        return None

    first_high = bar_rows['High'].max()
    first_low  = bar_rows['Low'].min()

    # 第一根15分K結束後開始掃描
    after_df = session_df[session_df['DateTime'] >= first_bar_end_dt].copy()
    if after_df.empty:
        return None

    direction = entry_price = exit_price = exit_reason = None
    pnl_points = 0
    peak_profit = 0

    for _, bar in after_df.iterrows():
        # 強制出場時間判斷
        bar_time = bar['DateTime'].time()
        # 夜盤跨日：04:55 以前要出場，所以 bar_time > NIGHT_END 才算超時
        # 日盤：bar_time > trade_end_time
        if trade_end_time == NIGHT_END:
            # 夜盤：從15:00跑到次日04:55，只要 bar_time > 04:55 就強制出場
            # 但要排除15:00~23:59這段（time比較會有問題）
            # 用 DateTime 直接比較比較準確
            pass  # 在下面用 limit_dt 處理
        else:
            if bar_time > trade_end_time:
                break

        if direction is None:
            if bar['High'] > first_high:
                direction, entry_price = '多', first_high
            elif bar['Low'] < first_low:
                direction, entry_price = '空', first_low

        if direction is not None and exit_reason is None:
            if direction == '多':
                cur_profit = bar['High'] - entry_price
                cur_loss   = entry_price - bar['Low']
            else:
                cur_profit = entry_price - bar['Low']
                cur_loss   = bar['High'] - entry_price

            peak_profit = max(peak_profit, cur_profit)

            # ① 嚴格停損
            if cur_loss >= stop_loss:
                exit_price  = entry_price - stop_loss if direction == '多' else entry_price + stop_loss
                pnl_points  = -stop_loss
                exit_reason = '停損'
                break

            # ② 階梯移動停利
            triggered, locked = check_trailing(peak_profit, cur_profit)
            if triggered:
                exit_price  = entry_price + locked if direction == '多' else entry_price - locked
                pnl_points  = locked
                exit_reason = '移動停利'
                break

            # ③ 固定停利
            if cur_profit >= take_profit:
                exit_price  = entry_price + take_profit if direction == '多' else entry_price - take_profit
                pnl_points  = take_profit
                exit_reason = '停利'
                break

    # 強制出場（尾盤 / 夜盤收盤）
    if direction is not None and exit_reason is None:
        last = after_df.iloc[-1]
        exit_price  = last['Close']
        pnl_points  = (exit_price - entry_price) if direction == '多' else (entry_price - exit_price)
        exit_reason = '強制平倉'

    if direction is None:
        return None

    net_pnl = pnl_points * POINT_VALUE - COMMISSION
    return {
        '日期': str(trade_date),
        '時段': session_label,
        '結算日': '是' if is_settle else '',
        '方向': direction,
        'ATR': atr_val,
        '停損': stop_loss,
        '停利': take_profit,
        '進場價': round(entry_price),
        '出場價': round(exit_price),
        '出場原因': exit_reason,
        '損益點數': round(pnl_points, 1),
        '淨損益(元)': round(net_pnl),
    }

# ══════════════════════════════════════
# 主回測
# ══════════════════════════════════════
def run_backtest(df, atr_map):
    trades = []
    all_dates = sorted(df['_date'].unique())

    for trade_date in all_dates:
        atr = atr_map.get(trade_date, np.nan)
        if pd.isna(atr) or atr <= 0:
            continue
        stop_loss   = max(1, round(atr * ATR_SL_MULT))
        take_profit = max(1, round(atr * ATR_TP_MULT))
        atr_val     = round(atr)
        is_settle   = is_settlement_day(trade_date)

        # ── 日盤 ──
        if TRADE_DAY:
            day_end = DAY_END_SETTLE if is_settle else DAY_END_NORMAL
            day_end_dt = datetime.combine(trade_date, day_end)
            bar_start  = datetime.combine(trade_date, DAY_FIRST_BAR)
            bar_end    = bar_start + timedelta(minutes=15)
            # 日盤資料：08:45 ~ day_end
            day_df = df[(df['_date'] == trade_date) &
                        (df['DateTime'] >= bar_start) &
                        (df['DateTime'] <= day_end_dt)].copy()
            result = backtest_session(day_df, bar_start, bar_end, day_end,
                                      stop_loss, take_profit, '日盤', atr_val, trade_date, is_settle)
            if result:
                trades.append(result)

        # ── 夜盤（當天 15:00 開始到次日 05:00）──
        if TRADE_NIGHT:
            night_start_dt = datetime.combine(trade_date, NIGHT_FIRST_BAR)
            night_bar_end  = night_start_dt + timedelta(minutes=15)
            next_day       = trade_date + timedelta(days=1)
            night_end_dt   = datetime.combine(next_day, time(5, 0))
            # 夜盤資料：當天15:00 ~ 次日05:00
            night_df = df[(df['DateTime'] >= night_start_dt) &
                          (df['DateTime'] <= night_end_dt)].copy()
            if not night_df.empty:
                # 強制出場時間用 limit_dt 篩掉，而不是靠 time 比較
                # 這裡直接在傳入 session_df 前把超時的行砍掉
                limit_dt = datetime.combine(next_day, NIGHT_END)
                night_df = night_df[night_df['DateTime'] <= limit_dt]
                result = backtest_session(night_df, night_start_dt, night_bar_end, NIGHT_END,
                                          stop_loss, take_profit, '夜盤', atr_val, trade_date, is_settle)
                if result:
                    trades.append(result)

    return pd.DataFrame(trades)

# ══════════════════════════════════════
# 報表
# ══════════════════════════════════════
def print_report(trades_df):
    if trades_df.empty:
        print('無交易紀錄')
        return

    def stats(df, label):
        total = len(df)
        if total == 0:
            print(f'\n  [{label}] 無交易')
            return
        wins   = df[df['損益點數'] > 0]
        losses = df[df['損益點數'] < 0]
        wr  = len(wins) / total * 100
        aw  = wins['損益點數'].mean() if len(wins) else 0
        al  = losses['損益點數'].mean() if len(losses) else 0
        net = df['淨損益(元)'].sum()
        eq  = df['淨損益(元)'].cumsum()
        mdd = (eq - eq.cummax()).min()
        pf  = wins['損益點數'].sum() / abs(losses['損益點數'].sum()) if len(losses) else 99
        days = (pd.to_datetime(df['日期'].max()) - pd.to_datetime(df['日期'].min())).days
        months = max(days / 30, 1)
        print(f'\n  ── {label}（{total} 次）──')
        print(f'  勝率 {wr:.1f}%  |  獲利因子 {pf:.2f}')
        print(f'  平均獲利 +{aw:.1f} 點  |  平均虧損 {al:.1f} 點')
        print(f'  最大回撤 {mdd:,.0f} 元  |  累積淨利 {net:,.0f} 元  |  月均 {net/months:,.0f} 元')
        for reason, cnt in df['出場原因'].value_counts().items():
            print(f'    {reason}：{cnt}次（{cnt/total*100:.1f}%）')

    total = len(trades_df)
    wins  = trades_df[trades_df['損益點數'] > 0]
    losses= trades_df[trades_df['損益點數'] < 0]
    net   = trades_df['淨損益(元)'].sum()
    eq    = trades_df['淨損益(元)'].cumsum()
    mdd   = (eq - eq.cummax()).min()
    pf    = wins['損益點數'].sum() / abs(losses['損益點數'].sum()) if len(losses) else 99
    wr    = len(wins) / total * 100
    aw    = wins['損益點數'].mean() if len(wins) else 0
    al    = losses['損益點數'].mean() if len(losses) else 0
    days  = (pd.to_datetime(trades_df['日期'].max()) - pd.to_datetime(trades_df['日期'].min())).days
    months = max(days / 30, 1)

    print('=' * 60)
    print('  微台期｜開盤15分K突破策略 v3.0｜日夜盤回測報告')
    print('=' * 60)
    print(f'  回測期間   ：{trades_df["日期"].min()} ~ {trades_df["日期"].max()}')
    print(f'  停損模式   ：ATR × {ATR_SL_MULT}（嚴格不動）')
    print(f'  移動停利   ：階梯式（{TRAIL_L1}點啟動/{TRAIL_D1}回撤 → {TRAIL_L2}點/{TRAIL_D2}回撤 → {TRAIL_L3}點/{TRAIL_D3}回撤）')
    print(f'  日盤       ：{"開啟" if TRADE_DAY else "關閉"}  |  夜盤：{"開啟" if TRADE_NIGHT else "關閉"}')
    print('-' * 60)
    print(f'  總交易次數 ：{total} 次')
    print(f'  整體勝率   ：{wr:.1f}%')
    print(f'  平均獲利   ：+{aw:.1f} 點')
    print(f'  平均虧損   ：{al:.1f} 點')
    print(f'  獲利因子   ：{pf:.2f}')
    print(f'  最大回撤   ：{mdd:,.0f} 元')
    print(f'  累積淨利   ：{net:,.0f} 元')
    print(f'  月均損益   ：{net/months:,.0f} 元')
    print('-' * 60)
    print('  出場原因分佈（整體）：')
    for reason, cnt in trades_df['出場原因'].value_counts().items():
        print(f'    {reason}：{cnt}次（{cnt/total*100:.1f}%）')

    # 分時段統計
    if TRADE_DAY and TRADE_NIGHT:
        stats(trades_df[trades_df['時段'] == '日盤'], '日盤')
        stats(trades_df[trades_df['時段'] == '夜盤'], '夜盤')
    print('=' * 60)

# ══════════════════════════════════════
# 繪圖
# ══════════════════════════════════════
def plot_results(trades_df):
    if trades_df.empty:
        return
    for font in ['Microsoft JhengHei', 'Microsoft YaHei', 'Arial Unicode MS']:
        try:
            plt.rcParams['font.family'] = font
            break
        except:
            pass
    plt.rcParams['axes.unicode_minus'] = False

    fig, axes = plt.subplots(2, 2, figsize=(14, 10))
    fig.patch.set_facecolor('#0f172a')
    for ax in axes.flat:
        ax.set_facecolor('#1e293b')
        ax.tick_params(colors='#94a3b8')
        for s in ['top', 'right']: ax.spines[s].set_visible(False)
        for s in ['bottom', 'left']: ax.spines[s].set_color('#334155')

    # 累積損益
    eq = trades_df['淨損益(元)'].cumsum()
    color = '#22c55e' if eq.iloc[-1] >= 0 else '#ef4444'
    axes[0,0].plot(range(len(eq)), eq.values, color=color, lw=2)
    axes[0,0].fill_between(range(len(eq)), eq.values, 0, alpha=0.15, color=color)
    axes[0,0].axhline(0, color='#475569', ls='--', lw=1)
    axes[0,0].set_title('累積損益曲線（元）', color='#e2e8f0', fontsize=12)

    # 每筆損益
    colors = ['#22c55e' if p > 0 else '#ef4444' for p in trades_df['淨損益(元)']]
    axes[0,1].bar(range(len(trades_df)), trades_df['淨損益(元)'].values, color=colors, alpha=0.8)
    axes[0,1].axhline(0, color='#475569', ls='--', lw=1)
    axes[0,1].set_title('每筆交易損益（元）', color='#e2e8f0', fontsize=12)

    # 出場原因
    counts = trades_df['出場原因'].value_counts()
    axes[1,0].pie(counts.values, labels=counts.index, autopct='%1.1f%%',
                  colors=['#22c55e','#ef4444','#f59e0b','#60a5fa'][:len(counts)],
                  textprops={'color':'#e2e8f0'})
    axes[1,0].set_title('出場原因分佈', color='#e2e8f0', fontsize=12)

    # 日夜盤累積損益對比
    if TRADE_DAY and TRADE_NIGHT:
        for session, color in [('日盤', '#60a5fa'), ('夜盤', '#f59e0b')]:
            s_df = trades_df[trades_df['時段'] == session]
            if not s_df.empty:
                eq_s = s_df['淨損益(元)'].cumsum().reset_index(drop=True)
                axes[1,1].plot(range(len(eq_s)), eq_s.values, color=color, lw=2, label=session)
        axes[1,1].axhline(0, color='#475569', ls='--', lw=1)
        axes[1,1].legend(facecolor='#1e293b', labelcolor='#e2e8f0')
        axes[1,1].set_title('日盤 vs 夜盤 累積損益', color='#e2e8f0', fontsize=12)
    else:
        axes[1,1].axis('off')

    plt.tight_layout()
    out = 'backtest_v3_result.png'
    plt.savefig(out, dpi=150, bbox_inches='tight', facecolor='#0f172a')
    print(f'\n圖表已儲存：{out}')

# ══════════════════════════════════════
# 主程式
# ══════════════════════════════════════
if __name__ == '__main__':
    print('\n微台期 開盤15分K突破策略 v3.0 啟動')
    print(f'  日盤：{"開啟" if TRADE_DAY else "關閉"}  |  夜盤：{"開啟" if TRADE_NIGHT else "關閉"}')
    print(f'  停損：ATR×{ATR_SL_MULT}  |  停利：ATR×{ATR_TP_MULT}')
    print(f'  階梯停利：{TRAIL_L1}pt/{TRAIL_D1}回 → {TRAIL_L2}pt/{TRAIL_D2}回 → {TRAIL_L3}pt/{TRAIL_D3}回\n')

    df = load_data(CSV_FILE)
    print(f'資料載入：{len(df):,} 筆')

    atr_map = calc_daily_atr(df)
    print('ATR計算完成\n')

    trades = run_backtest(df, atr_map)
    print(f'回測完成：{len(trades)} 筆交易\n')

    print_report(trades)
    trades.to_csv('trades_v3_detail.csv', index=False, encoding='utf-8-sig')
    print('交易明細已儲存：trades_v3_detail.csv')
    plot_results(trades)
