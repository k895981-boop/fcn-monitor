"""
═══════════════════════════════════════════════════════════
  微台期｜開盤15分K突破策略【升級版 v2.0】
═══════════════════════════════════════════════════════════

  本版新增（依據與 Claude 討論的內容）：
    ✅ ATR 動態停損   — 隨市場波動自動調整，不被固定點數洗出場
    ✅ 移動停利        — 鎖住獲利，讓利潤奔跑
    ✅ 每日單次交易    — 細水長流，當天只做第一個訊號
    ✅ 尾盤強制出場    — 不留倉過夜
    ✅ 敏感度分析      — 自動找最佳參數組合

  資料來源（免費）：
    量化通 https://quantpass.org/txf/  下載台指期1分K CSV
    欄位：Date, Time, Open, High, Low, Close, Volume

  使用方式：
    1. pip install pandas matplotlib numpy
    2. 將CSV放到同資料夾，改下方 CSV_FILE 路徑
    3. python tmf_backtest_v2.py

  ── 給 Claude Code 的提示 ──
  裝好 Claude Code 後，在此檔案資料夾輸入 claude，
  可以直接說：「幫我執行這個程式並調整參數找出最佳組合」
═══════════════════════════════════════════════════════════
"""

import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import os
from datetime import time, date, timedelta, datetime

# ══════════════════════════════════════
# ▌ 參數設定區（可自行調整）
# ══════════════════════════════════════

CSV_FILE        = "txf_1min.csv"   # CSV檔案路徑

# ── ATR 動態停損設定 ──
ATR_PERIOD      = 14               # ATR計算天數
ATR_SL_MULT     = 0.4              # 停損 = ATR × 0.4
ATR_TP_MULT     = 0.8             # 停利 = ATR × 0.8
USE_FIXED       = False            # True=用固定點數, False=用ATR動態

# ── 固定點數（USE_FIXED=True 時生效）──
FIXED_SL        = 40               # 固定停損點數
FIXED_TP        = 80               # 固定停利點數

# ── 移動停利設定 ──
USE_TRAILING    = True             # 是否啟用移動停利
TRAIL_TRIGGER   = 30               # 獲利達此點數後啟動移動停利
TRAIL_DISTANCE  = 20               # 從最高點回撤此點數出場

# ── 風控設定 ──
ONE_TRADE_DAY   = True             # 每天只做第一個訊號（細水長流）

# ── 商品與成本 ──
POINT_VALUE     = 10               # 微台每點10元
COMMISSION      = 30               # 來回手續費（元）

# ── 交易時段 ──
FIRST_BAR_START = time(8, 45)      # 第一根15分K開始
TRADE_END       = time(13, 40)     # 一般日盤強制出場（13:45收盤前5分鐘）
SETTLE_DAY_END  = time(13, 25)     # 結算日強制出場（當月合約13:30收盤前5分鐘）
NIGHT_END       = time(4, 55)      # 夜盤強制出場（隔日05:00收盤前5分鐘）絕不留倉

# ══════════════════════════════════════
# ▌ 讀取資料
# ══════════════════════════════════════

def load_data(filepath):
    if not os.path.exists(filepath):
        print(f"\n⚠️  找不到 {filepath}，改用內建模擬資料示範...")
        print("   真實資料請至 https://quantpass.org/txf/ 下載\n")
        return generate_demo_data()

    df = pd.read_csv(filepath)
    df.columns = [c.strip() for c in df.columns]

    col_map = {}
    for col in df.columns:
        c = col.lower().strip()
        if c in ["date", "日期"]:       col_map[col] = "Date"
        elif c in ["time", "時間"]:     col_map[col] = "Time"
        elif c in ["open", "開盤"]:     col_map[col] = "Open"
        elif c in ["high", "最高"]:     col_map[col] = "High"
        elif c in ["low", "最低"]:      col_map[col] = "Low"
        elif c in ["close", "收盤"]:    col_map[col] = "Close"
        elif c in ["volume", "成交量"]: col_map[col] = "Volume"
    df = df.rename(columns=col_map)

    df["DateTime"] = pd.to_datetime(df["Date"].astype(str) + " " + df["Time"].astype(str))
    df = df.sort_values("DateTime").reset_index(drop=True)
    df["Date"] = df["DateTime"].dt.date
    df["Time"] = df["DateTime"].dt.time
    return df

def generate_demo_data():
    np.random.seed(42)
    rows = []
    price = 22000.0
    d = date(2023, 1, 3)
    end = date(2024, 12, 31)

    while d <= end:
        if d.weekday() >= 5:
            d += timedelta(days=1)
            continue
        t = datetime(d.year, d.month, d.day, 8, 45)
        open_p = price + np.random.randn() * 40
        # 隨機決定當天波動程度（模擬不同市場狀況）
        daily_vol = np.random.choice([6, 10, 16], p=[0.4, 0.4, 0.2])
        for _ in range(300):
            change = np.random.randn() * daily_vol
            high = open_p + abs(np.random.randn() * daily_vol * 1.5)
            low = open_p - abs(np.random.randn() * daily_vol * 1.5)
            close = open_p + change
            rows.append({
                "DateTime": t, "Date": d, "Time": t.time(),
                "Open": round(open_p), "High": round(high),
                "Low": round(low), "Close": round(close),
                "Volume": int(abs(np.random.randn() * 500 + 1000))
            })
            open_p = close
            t += pd.Timedelta(minutes=1)
        price = rows[-1]["Close"]
        d += timedelta(days=1)
    return pd.DataFrame(rows)

# ══════════════════════════════════════
# ▌ 結算日判斷（每月第三個星期三）
# ══════════════════════════════════════

def is_settlement_day(d):
    """判斷是否為台指期結算日：每月第三個星期三"""
    if d.weekday() != 2:          # 星期三 weekday()==2
        return False
    # 計算這天是當月第幾個星期三
    count = 0
    for day in range(1, d.day + 1):
        check = date(d.year, d.month, day)
        if check.weekday() == 2:
            count += 1
    return count == 3              # 第三個星期三

def get_trade_end(d, is_night=False):
    """依日期取得當天的強制出場時間"""
    if is_night:
        return NIGHT_END           # 夜盤一律 04:55 出場
    if is_settlement_day(d):
        return SETTLE_DAY_END       # 結算日 13:25 出場
    return TRADE_END                # 一般日 13:40 出場

# ══════════════════════════════════════
# ▌ 聚合15分K + 計算每日ATR
# ══════════════════════════════════════

def prepare_data(df):
    df = df.copy()
    df["DateTime"] = pd.to_datetime(df["Date"].astype(str) + " " + df["Time"].astype(str))
    df = df.set_index("DateTime")

    # 聚合成15分K
    df_15 = df[["Open","High","Low","Close","Volume"]].resample("15min", label="left").agg({
        "Open": "first", "High": "max", "Low": "min",
        "Close": "last", "Volume": "sum"
    }).dropna()
    df_15["Date"] = df_15.index.date
    df_15["Time"] = df_15.index.time

    # 計算每日OHLC（用來算ATR）
    daily = df.resample("1D").agg({
        "Open": "first", "High": "max", "Low": "min", "Close": "last"
    }).dropna()

    # True Range
    daily["PrevClose"] = daily["Close"].shift(1)
    daily["TR"] = daily.apply(lambda r: max(
        r["High"] - r["Low"],
        abs(r["High"] - r["PrevClose"]) if pd.notna(r["PrevClose"]) else 0,
        abs(r["Low"] - r["PrevClose"]) if pd.notna(r["PrevClose"]) else 0
    ), axis=1)
    daily["ATR"] = daily["TR"].rolling(ATR_PERIOD).mean()
    atr_map = {d.date(): atr for d, atr in zip(daily.index, daily["ATR"])}

    return df_15.reset_index(), atr_map

# ══════════════════════════════════════
# ▌ 回測主邏輯
# ══════════════════════════════════════

def run_backtest(df_15, atr_map, params=None):
    if params:
        sl_mult = params.get("sl_mult", ATR_SL_MULT)
        tp_mult = params.get("tp_mult", ATR_TP_MULT)
        use_fixed = params.get("use_fixed", USE_FIXED)
        fixed_sl = params.get("fixed_sl", FIXED_SL)
        fixed_tp = params.get("fixed_tp", FIXED_TP)
    else:
        sl_mult, tp_mult = ATR_SL_MULT, ATR_TP_MULT
        use_fixed, fixed_sl, fixed_tp = USE_FIXED, FIXED_SL, FIXED_TP

    trades = []

    for trade_date, group in df_15.groupby("Date"):
        group = group.sort_values("Time").reset_index(drop=True)
        first_bars = group[group["Time"] == FIRST_BAR_START]
        if first_bars.empty:
            continue
        first_bar = first_bars.iloc[0]
        first_high, first_low = first_bar["High"], first_bar["Low"]

        # 依結算日決定當天強制出場時間
        settle = is_settlement_day(trade_date)
        trade_end = SETTLE_DAY_END if settle else TRADE_END

        # 取得當日ATR，決定停損停利
        atr = atr_map.get(trade_date, np.nan)
        if use_fixed or pd.isna(atr) or atr <= 0:
            stop_loss, take_profit = fixed_sl, fixed_tp
            atr_val = atr if pd.notna(atr) else 0
        else:
            stop_loss = round(atr * sl_mult)
            take_profit = round(atr * tp_mult)
            atr_val = round(atr)

        subsequent = group[group["Time"] > FIRST_BAR_START]
        if subsequent.empty:
            continue

        direction = entry_price = exit_price = exit_reason = None
        pnl_points = 0
        peak_profit = 0   # 移動停利用：紀錄最高獲利

        for _, bar in subsequent.iterrows():
            if bar["Time"] > trade_end:
                break

            # 進場訊號
            if direction is None:
                if bar["High"] > first_high:
                    direction, entry_price = "多", first_high
                elif bar["Low"] < first_low:
                    direction, entry_price = "空", first_low

            # 出場判斷
            if direction is not None and exit_reason is None:
                # 計算當前浮動獲利
                if direction == "多":
                    cur_profit = bar["High"] - entry_price
                    cur_loss = entry_price - bar["Low"]
                else:
                    cur_profit = entry_price - bar["Low"]
                    cur_loss = bar["High"] - entry_price

                peak_profit = max(peak_profit, cur_profit)

                # ① 固定停損
                if cur_loss >= stop_loss:
                    exit_price = entry_price - stop_loss if direction == "多" else entry_price + stop_loss
                    pnl_points = -stop_loss
                    exit_reason = "停損"
                    break

                # ② 移動停利（獲利達觸發點後啟動）
                if USE_TRAILING and peak_profit >= TRAIL_TRIGGER:
                    if peak_profit - cur_profit >= TRAIL_DISTANCE:
                        locked = peak_profit - TRAIL_DISTANCE
                        exit_price = entry_price + locked if direction == "多" else entry_price - locked
                        pnl_points = locked
                        exit_reason = "移動停利"
                        break

                # ③ 固定停利
                if cur_profit >= take_profit:
                    exit_price = entry_price + take_profit if direction == "多" else entry_price - take_profit
                    pnl_points = take_profit
                    exit_reason = "停利"
                    break

        # ④ 尾盤強制出場
        if direction is not None and exit_reason is None:
            last_bar = subsequent.iloc[-1]
            exit_price = last_bar["Close"]
            pnl_points = (exit_price - entry_price) if direction == "多" else (entry_price - exit_price)
            exit_reason = "尾盤出場"

        if direction is None:
            continue

        net_pnl = pnl_points * POINT_VALUE - COMMISSION

        trades.append({
            "日期": str(trade_date), "方向": direction,
            "結算日": "是" if settle else "",
            "ATR": atr_val, "停損": stop_loss, "停利": take_profit,
            "進場價": round(entry_price), "出場價": round(exit_price),
            "出場原因": exit_reason, "損益點數": round(pnl_points, 1),
            "淨損益(元)": round(net_pnl),
        })

    return pd.DataFrame(trades)

# ══════════════════════════════════════
# ▌ 報表
# ══════════════════════════════════════

def print_report(trades_df):
    if trades_df.empty:
        print("❌ 無交易紀錄")
        return

    total = len(trades_df)
    wins = trades_df[trades_df["損益點數"] > 0]
    losses = trades_df[trades_df["損益點數"] < 0]
    win_rate = len(wins) / total * 100
    avg_win = wins["損益點數"].mean() if len(wins) else 0
    avg_loss = losses["損益點數"].mean() if len(losses) else 0
    total_net = trades_df["淨損益(元)"].sum()
    equity = trades_df["淨損益(元)"].cumsum()
    max_dd = (equity - equity.cummax()).min()
    pf = (wins["損益點數"].sum() / abs(losses["損益點數"].sum())) if len(losses) else 99

    mode = "固定點數" if USE_FIXED else f"ATR動態(×{ATR_SL_MULT}/{ATR_TP_MULT})"
    trail = f"移動停利(觸發{TRAIL_TRIGGER}/回撤{TRAIL_DISTANCE})" if USE_TRAILING else "無移動停利"

    print("=" * 56)
    print("  微台期｜開盤15分K突破策略 v2.0｜回測報告")
    print("=" * 56)
    print(f"  回測期間：{trades_df['日期'].min()} ～ {trades_df['日期'].max()}")
    print(f"  停損模式：{mode}")
    print(f"  停利機制：{trail}")
    print(f"  風控規則：每日{'單次' if ONE_TRADE_DAY else '多次'}交易（機械化執行，不間斷）")
    print("-" * 56)
    print(f"  總交易次數：{total} 次")
    print(f"  勝     率：{win_rate:.1f}%")
    print(f"  平均獲利： +{avg_win:.1f} 點")
    print(f"  平均虧損： {avg_loss:.1f} 點")
    print(f"  獲利因子： {pf:.2f}")
    print(f"  最大回撤： {max_dd:,.0f} 元")
    print(f"  累積淨利： {total_net:,.0f} 元")
    if total > 0:
        days = (pd.to_datetime(trades_df['日期'].max()) - pd.to_datetime(trades_df['日期'].min())).days
        months = max(days / 30, 1)
        print(f"  月均損益： {total_net/months:,.0f} 元")
    print("-" * 56)
    print("  出場原因分佈：")
    for reason, cnt in trades_df["出場原因"].value_counts().items():
        print(f"    {reason}：{cnt}次（{cnt/total*100:.1f}%）")
    print("=" * 56)

# ══════════════════════════════════════
# ▌ 繪圖
# ══════════════════════════════════════

def plot_results(trades_df):
    if trades_df.empty:
        return
    for font in ["Noto Sans CJK TC", "Microsoft JhengHei", "PingFang TC", "Arial Unicode MS"]:
        try:
            plt.rcParams["font.family"] = font
            break
        except: pass
    plt.rcParams["axes.unicode_minus"] = False

    fig, axes = plt.subplots(3, 1, figsize=(12, 11))
    fig.patch.set_facecolor("#0f172a")
    for ax in axes:
        ax.set_facecolor("#1e293b")
        ax.tick_params(colors="#94a3b8")
        for s in ["top","right"]: ax.spines[s].set_visible(False)
        for s in ["bottom","left"]: ax.spines[s].set_color("#334155")

    equity = trades_df["淨損益(元)"].cumsum()
    color = "#22c55e" if equity.iloc[-1] >= 0 else "#ef4444"
    axes[0].plot(range(len(equity)), equity.values, color=color, linewidth=2)
    axes[0].fill_between(range(len(equity)), equity.values, 0, alpha=0.15, color=color)
    axes[0].axhline(0, color="#475569", ls="--", lw=1)
    axes[0].set_title("累積損益曲線（元）", color="#e2e8f0", fontsize=13, pad=10)

    colors = ["#22c55e" if p > 0 else "#ef4444" for p in trades_df["淨損益(元)"]]
    axes[1].bar(range(len(trades_df)), trades_df["淨損益(元)"].values, color=colors, alpha=0.8)
    axes[1].axhline(0, color="#475569", ls="--", lw=1)
    axes[1].set_title("每筆交易損益（元）", color="#e2e8f0", fontsize=13, pad=10)

    counts = trades_df["出場原因"].value_counts()
    axes[2].pie(counts.values, labels=counts.index, autopct="%1.1f%%",
                colors=["#22c55e","#ef4444","#f59e0b","#60a5fa"][:len(counts)],
                textprops={"color": "#e2e8f0"})
    axes[2].set_title("出場原因分佈", color="#e2e8f0", fontsize=13, pad=10)

    plt.tight_layout()
    plt.savefig("backtest_v2_result.png", dpi=150, bbox_inches="tight", facecolor="#0f172a")
    print("\n📊 圖表已儲存：backtest_v2_result.png")
    plt.show()

# ══════════════════════════════════════
# ▌ 敏感度分析（自動找最佳ATR係數）
# ══════════════════════════════════════

def sensitivity_analysis(df_15, atr_map):
    print("\n🔍 敏感度分析（測試不同 ATR 停損/停利係數）")
    print(f"{'停損×':>8}{'停利×':>8}{'勝率':>9}{'獲利因子':>11}{'淨損益':>13}")
    print("-" * 56)
    results = []
    for sl_m in [0.3, 0.4, 0.5, 0.6]:
        for tp_m in [0.6, 0.8, 1.0, 1.2, 1.5]:
            t = run_backtest(df_15, atr_map, {
                "sl_mult": sl_m, "tp_mult": tp_m, "use_fixed": False
            })
            if t.empty: continue
            w = t[t["損益點數"] > 0]; l = t[t["損益點數"] < 0]
            wr = len(w)/len(t)*100
            pf = (w["損益點數"].sum()/abs(l["損益點數"].sum())) if len(l) else 99
            net = t["淨損益(元)"].sum()
            results.append((sl_m, tp_m, wr, pf, net))
            print(f"{sl_m:>8.1f}{tp_m:>8.1f}{wr:>8.1f}%{pf:>11.2f}{net:>12,.0f}元")
    if results:
        best = max(results, key=lambda x: x[4])
        print(f"\n🏆 最佳組合：停損 ATR×{best[0]} / 停利 ATR×{best[1]}")
        print(f"   勝率 {best[2]:.1f}% ／ 獲利因子 {best[3]:.2f} ／ 淨損益 {best[4]:,.0f}元")

# ══════════════════════════════════════
# ▌ 主程式
# ══════════════════════════════════════

if __name__ == "__main__":
    print("\n🚀 微台期 開盤15分K突破策略 v2.0 啟動")
    print(f"   停損模式：{'固定點數' if USE_FIXED else 'ATR動態'}")
    print(f"   移動停利：{'啟用' if USE_TRAILING else '關閉'}\n")

    df = load_data(CSV_FILE)
    print(f"✅ 資料載入：{len(df):,} 筆")

    df_15, atr_map = prepare_data(df)
    print(f"✅ 15分K聚合完成，ATR計算完成\n")

    trades = run_backtest(df_15, atr_map)
    print(f"✅ 回測完成：{len(trades)} 筆交易\n")

    print_report(trades)

    trades.to_csv("trades_v2_detail.csv", index=False, encoding="utf-8-sig")
    print("📄 交易明細已儲存：trades_v2_detail.csv")

    plot_results(trades)

    ans = input("\n是否執行敏感度分析（找最佳ATR係數）？[y/N] ").strip().lower()
    if ans == "y":
        sensitivity_analysis(df_15, atr_map)
