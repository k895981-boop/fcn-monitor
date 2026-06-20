"""
═══════════════════════════════════════════════════════════
  微台期｜開盤15分K突破策略【波段版 swing】
═══════════════════════════════════════════════════════════
  策略邏輯：
    - 每個交易日 08:45 第一根15分K定高低
    - 突破高點做多 / 跌破低點做空（同 v2）
    - 嚴格固定停損（ATR × SL_MULT），不移動
    - 停利目標放大（ATR × TP_MULT），讓利潤奔跑
    - 允許留倉過夜、跨日持有，最多 MAX_HOLD_DAYS 天
    - 整個持倉期間每分鐘掃描停損/停利
    - 到期強制平倉（最後一根K棒收盤價）
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
CSV_FILE       = 'txf_all_sessions.csv'

ATR_PERIOD     = 14
ATR_SL_MULT    = 1.0    # 停損 = ATR × 1.0（比當沖寬，給波段呼吸空間）
ATR_TP_MULT    = 3.0    # 停利 = ATR × 3.0（波段目標）

MAX_HOLD_DAYS  = 5      # 最多持倉天數（超過強制平倉）

POINT_VALUE    = 10     # 微台每點10元
COMMISSION     = 30     # 來回手續費

ENTRY_TIME     = time(8, 45)   # 第一根15分K開始時間

# ══════════════════════════════════════
# 讀取資料
# ══════════════════════════════════════
def load_data(filepath):
    print(f'讀取資料：{filepath}')
    df = pd.read_csv(filepath, encoding='utf-8-sig')
    df.columns = [c.strip() for c in df.columns]
    df['DateTime'] = pd.to_datetime(df['Date'].astype(str) + ' ' + df['Time'].astype(str))
    df = df.sort_values('DateTime').reset_index(drop=True)
    df['Date'] = df['DateTime'].dt.date
    df['Time'] = df['DateTime'].dt.time
    return df

# ══════════════════════════════════════
# 計算每日ATR（用日線）
# ══════════════════════════════════════
def calc_daily_atr(df):
    df2 = df.copy()
    df2 = df2.set_index('DateTime')
    daily = df2[['Open','High','Low','Close']].resample('1D').agg(
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
# 波段回測主邏輯
# ══════════════════════════════════════
def run_swing_backtest(df, atr_map):
    """
    逐分鐘掃描，允許跨日持倉。
    每個交易日只在 08:45 那根15分K（08:45~09:00 聚合）找突破訊號。
    """
    trades = []
    all_dates = sorted(df['Date'].unique())
    # 建立 datetime -> row 的快速索引
    df_idx = df.set_index('DateTime')

    i = 0
    while i < len(all_dates):
        entry_date = all_dates[i]

        # 聚合 08:45~09:00 的1分K成一根15分K（資料可能從08:46開始）
        bar_start = datetime.combine(entry_date, ENTRY_TIME)
        bar_end   = bar_start + timedelta(minutes=15)
        mask = (df['DateTime'] >= bar_start) & (df['DateTime'] < bar_end)
        bar_rows = df[mask]
        if bar_rows.empty:
            i += 1
            continue

        first_high = bar_rows['High'].max()
        first_low  = bar_rows['Low'].min()

        # 取得當日ATR
        atr = atr_map.get(entry_date, np.nan)
        if pd.isna(atr) or atr <= 0:
            i += 1
            continue
        stop_loss  = round(atr * ATR_SL_MULT)
        take_profit = round(atr * ATR_TP_MULT)

        # 從第一根15分K結束後開始掃描，最多 MAX_HOLD_DAYS 天
        scan_start_dt = bar_end
        max_date = all_dates[min(i + MAX_HOLD_DAYS, len(all_dates) - 1)]
        scan_end_dt = datetime.combine(max_date, time(23, 59))

        scan_df = df[(df['DateTime'] >= scan_start_dt) & (df['DateTime'] <= scan_end_dt)].copy()
        if scan_df.empty:
            i += 1
            continue

        direction = None
        entry_price = None
        entry_dt = None
        exit_price = None
        exit_dt = None
        exit_reason = None
        pnl_points = 0

        for _, row in scan_df.iterrows():
            # 進場：突破第一根15分K高低點
            if direction is None:
                if row['High'] > first_high:
                    direction = '多'
                    entry_price = first_high
                    entry_dt = row['DateTime']
                elif row['Low'] < first_low:
                    direction = '空'
                    entry_price = first_low
                    entry_dt = row['DateTime']

            if direction is not None and exit_reason is None:
                if direction == '多':
                    cur_loss   = entry_price - row['Low']
                    cur_profit = row['High'] - entry_price
                else:
                    cur_loss   = row['High'] - entry_price
                    cur_profit = entry_price - row['Low']

                # 停損（嚴格執行）
                if cur_loss >= stop_loss:
                    exit_price  = entry_price - stop_loss if direction == '多' else entry_price + stop_loss
                    pnl_points  = -stop_loss
                    exit_reason = '停損'
                    exit_dt     = row['DateTime']
                    break

                # 停利
                if cur_profit >= take_profit:
                    exit_price  = entry_price + take_profit if direction == '多' else entry_price - take_profit
                    pnl_points  = take_profit
                    exit_reason = '停利'
                    exit_dt     = row['DateTime']
                    break

        # 到期強制平倉
        if direction is not None and exit_reason is None:
            last_row   = scan_df.iloc[-1]
            exit_price = last_row['Close']
            pnl_points = (exit_price - entry_price) if direction == '多' else (entry_price - exit_price)
            exit_reason = '到期平倉'
            exit_dt     = last_row['DateTime']

        if direction is None:
            i += 1
            continue

        hold_days = (exit_dt.date() - entry_date).days if exit_dt else 0
        net_pnl = pnl_points * POINT_VALUE - COMMISSION

        trades.append({
            '進場日': str(entry_date),
            '出場日': str(exit_dt.date()) if exit_dt else '',
            '持倉天數': hold_days,
            '方向': direction,
            'ATR': round(atr),
            '停損點數': stop_loss,
            '停利點數': take_profit,
            '進場價': round(entry_price),
            '出場價': round(exit_price),
            '出場原因': exit_reason,
            '損益點數': round(pnl_points, 1),
            '淨損益(元)': round(net_pnl),
        })

        # 出場後跳到出場日的下一個交易日
        if exit_dt:
            exit_date = exit_dt.date()
            # 找出場日在 all_dates 中的位置，從下一天繼續
            try:
                idx = all_dates.index(exit_date)
                i = idx + 1
            except ValueError:
                i += 1
        else:
            i += 1

    return pd.DataFrame(trades)

# ══════════════════════════════════════
# 報表
# ══════════════════════════════════════
def print_report(trades_df):
    if trades_df.empty:
        print('無交易紀錄')
        return

    total = len(trades_df)
    wins   = trades_df[trades_df['損益點數'] > 0]
    losses = trades_df[trades_df['損益點數'] < 0]
    win_rate = len(wins) / total * 100
    avg_win  = wins['損益點數'].mean() if len(wins) else 0
    avg_loss = losses['損益點數'].mean() if len(losses) else 0
    total_net = trades_df['淨損益(元)'].sum()
    equity    = trades_df['淨損益(元)'].cumsum()
    max_dd    = (equity - equity.cummax()).min()
    pf        = (wins['損益點數'].sum() / abs(losses['損益點數'].sum())) if len(losses) else 99
    avg_hold  = trades_df['持倉天數'].mean()

    print('=' * 58)
    print('  微台期｜開盤15分K突破策略【波段版】回測報告')
    print('=' * 58)
    print(f'  回測期間  ：{trades_df["進場日"].min()} ~ {trades_df["進場日"].max()}')
    print(f'  停損模式  ：ATR × {ATR_SL_MULT}（嚴格執行，不移動）')
    print(f'  停利目標  ：ATR × {ATR_TP_MULT}')
    print(f'  最大持倉  ：{MAX_HOLD_DAYS} 天')
    print('-' * 58)
    print(f'  總交易次數：{total} 次')
    print(f'  勝     率：{win_rate:.1f}%')
    print(f'  平均獲利 ：+{avg_win:.1f} 點')
    print(f'  平均虧損 ：{avg_loss:.1f} 點')
    print(f'  獲利因子 ：{pf:.2f}')
    print(f'  平均持倉 ：{avg_hold:.1f} 天')
    print(f'  最大回撤 ：{max_dd:,.0f} 元')
    print(f'  累積淨利 ：{total_net:,.0f} 元')
    days = (pd.to_datetime(trades_df['進場日'].max()) - pd.to_datetime(trades_df['進場日'].min())).days
    months = max(days / 30, 1)
    print(f'  月均損益 ：{total_net/months:,.0f} 元')
    print('-' * 58)
    print('  出場原因分佈：')
    for reason, cnt in trades_df['出場原因'].value_counts().items():
        print(f'    {reason}：{cnt} 次（{cnt/total*100:.1f}%）')
    print('=' * 58)

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

    fig, axes = plt.subplots(3, 1, figsize=(13, 11))
    fig.patch.set_facecolor('#0f172a')
    for ax in axes:
        ax.set_facecolor('#1e293b')
        ax.tick_params(colors='#94a3b8')
        for s in ['top', 'right']: ax.spines[s].set_visible(False)
        for s in ['bottom', 'left']: ax.spines[s].set_color('#334155')

    equity = trades_df['淨損益(元)'].cumsum()
    color = '#22c55e' if equity.iloc[-1] >= 0 else '#ef4444'
    axes[0].plot(range(len(equity)), equity.values, color=color, linewidth=2)
    axes[0].fill_between(range(len(equity)), equity.values, 0, alpha=0.15, color=color)
    axes[0].axhline(0, color='#475569', ls='--', lw=1)
    axes[0].set_title('累積損益曲線（元）', color='#e2e8f0', fontsize=13, pad=10)

    colors = ['#22c55e' if p > 0 else '#ef4444' for p in trades_df['淨損益(元)']]
    axes[1].bar(range(len(trades_df)), trades_df['淨損益(元)'].values, color=colors, alpha=0.8)
    axes[1].axhline(0, color='#475569', ls='--', lw=1)
    axes[1].set_title('每筆交易損益（元）', color='#e2e8f0', fontsize=13, pad=10)

    counts = trades_df['出場原因'].value_counts()
    axes[2].pie(counts.values, labels=counts.index, autopct='%1.1f%%',
                colors=['#22c55e', '#ef4444', '#f59e0b', '#60a5fa'][:len(counts)],
                textprops={'color': '#e2e8f0'})
    axes[2].set_title('出場原因分佈', color='#e2e8f0', fontsize=13, pad=10)

    plt.tight_layout()
    out = 'swing_backtest_result.png'
    plt.savefig(out, dpi=150, bbox_inches='tight', facecolor='#0f172a')
    print(f'\n圖表已儲存：{out}')

# ══════════════════════════════════════
# 主程式
# ══════════════════════════════════════
if __name__ == '__main__':
    print('\n微台期 開盤15分K突破策略【波段版】啟動')
    print(f'  停損：ATR x {ATR_SL_MULT}  |  停利：ATR x {ATR_TP_MULT}  |  最大持倉：{MAX_HOLD_DAYS} 天\n')

    df = load_data(CSV_FILE)
    print(f'資料載入：{len(df):,} 筆')

    print('計算ATR...')
    atr_map = calc_daily_atr(df)

    print('執行波段回測（允許留倉過夜，請稍候）...')
    trades = run_swing_backtest(df, atr_map)
    print(f'回測完成：{len(trades)} 筆交易\n')

    print_report(trades)
    trades.to_csv('swing_trades_detail.csv', index=False, encoding='utf-8-sig')
    print('交易明細已儲存：swing_trades_detail.csv')
    plot_results(trades)
