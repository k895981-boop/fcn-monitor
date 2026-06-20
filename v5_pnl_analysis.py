"""
v5.0 策略詳細盈虧分析
"""
import pandas as pd
import numpy as np

df = pd.read_csv('trades_v5_detail.csv', encoding='utf-8-sig')
df['日期'] = pd.to_datetime(df['日期'])
df['年份'] = df['日期'].dt.year
df['月份'] = df['日期'].dt.to_period('M')

wins  = df[df['損益點數'] > 0]
loses = df[df['損益點數'] < 0]
flat  = df[df['損益點數'] == 0]

n       = len(df)
n_win   = len(wins)
n_lose  = len(loses)
n_flat  = len(flat)

avg_win  = wins['損益點數'].mean()
avg_lose = loses['損益點數'].mean()
rr_ratio = abs(avg_win / avg_lose)           # 盈虧比（平均獲利 / 平均虧損）
total_win_pts  = wins['損益點數'].sum()
total_lose_pts = loses['損益點數'].sum()
profit_factor  = total_win_pts / abs(total_lose_pts)

total_win_ntd  = wins['淨損益(元)'].sum()
total_lose_ntd = loses['淨損益(元)'].sum()
net            = df['淨損益(元)'].sum()

# 最大單筆虧損
max_lose_pts = loses['損益點數'].min()
max_lose_ntd = loses['淨損益(元)'].min()

# 最大連續虧損次數
streak = 0; max_streak = 0; cur_streak = 0
for p in df['損益點數']:
    if p < 0:
        cur_streak += 1
        max_streak = max(max_streak, cur_streak)
    else:
        cur_streak = 0

# 最大連續虧損金額
max_consec_loss = 0; cur_loss = 0
for v in df['淨損益(元)']:
    if v < 0:
        cur_loss += v
        max_consec_loss = min(max_consec_loss, cur_loss)
    else:
        cur_loss = 0

# 月度統計
monthly = df.groupby('月份')['淨損益(元)'].sum()
lose_months = (monthly < 0).sum()
total_months = len(monthly)
avg_lose_month = monthly[monthly < 0].mean() if (monthly < 0).any() else 0
avg_win_month  = monthly[monthly > 0].mean() if (monthly > 0).any() else 0

print('=' * 62)
print('  微台期 v5.0 策略｜詳細盈虧分析報告')
print('=' * 62)

print('\n【一、盈虧比】')
print(f'  平均獲利（每筆）：+{avg_win:.1f} 點 = +{avg_win*10:.0f} 元')
print(f'  平均虧損（每筆）：{avg_lose:.1f} 點 = {avg_lose*10:.0f} 元')
print(f'  盈虧比           ：{rr_ratio:.2f}：1')
print(f'  （每虧1元，平均賺 {rr_ratio:.2f} 元）')
print(f'\n  獲利因子         ：{profit_factor:.2f}')
print(f'  （總獲利點 {total_win_pts:,.0f} ÷ 總虧損點 {abs(total_lose_pts):,.0f}）')

print('\n【二、虧損次數與金額】')
print(f'  總交易次數：{n} 次')
print(f'  ├─ 獲利次數：{n_win} 次（{n_win/n*100:.1f}%）  總獲利：+{total_win_ntd:,.0f} 元')
print(f'  ├─ 虧損次數：{n_lose} 次（{n_lose/n*100:.1f}%）  總虧損：{total_lose_ntd:,.0f} 元')
print(f'  └─ 平手次數：{n_flat} 次（{n_flat/n*100:.1f}%）')
print(f'\n  最大單筆虧損：{max_lose_pts:.0f} 點 = {max_lose_ntd:,.0f} 元')
print(f'  平均每筆虧損：{avg_lose:.1f} 點 = {avg_lose*10:.0f} 元')
print(f'  最大連續虧損：{max_streak} 次連敗')
print(f'  最大連續虧損金額：{max_consec_loss:,.0f} 元')

print('\n【三、月度虧損統計】')
print(f'  回測總月數：{total_months} 個月')
print(f'  虧損月數  ：{lose_months} 個月（{lose_months/total_months*100:.1f}%）')
print(f'  獲利月數  ：{total_months-lose_months} 個月（{(total_months-lose_months)/total_months*100:.1f}%）')
print(f'  平均獲利月：+{avg_win_month:,.0f} 元')
print(f'  平均虧損月：{avg_lose_month:,.0f} 元')

print('\n【四、逐年虧損明細】')
print(f"  {'年份':>5}  {'虧損次數':>6}  {'虧損總額':>10}  {'最大單筆虧損':>12}  {'虧損率':>6}")
print('  ' + '-'*54)
for yr, g in df.groupby('年份'):
    gl = g[g['損益點數'] < 0]
    yr_lose_n   = len(gl)
    yr_lose_ntd = gl['淨損益(元)'].sum() if len(gl) else 0
    yr_max_lose = gl['淨損益(元)'].min() if len(gl) else 0
    yr_lose_pct = yr_lose_n / len(g) * 100
    print(f'  {yr}  {yr_lose_n:>6} 次  {yr_lose_ntd:>9,.0f} 元  {yr_max_lose:>11,.0f} 元  {yr_lose_pct:>5.1f}%')

print('\n【五、出場原因別盈虧】')
for reason, g in df.groupby('出場原因'):
    gw = g[g['損益點數']>0]; gl = g[g['損益點數']<0]
    wr = len(gw)/len(g)*100
    net_r = g['淨損益(元)'].sum()
    avg_r = g['損益點數'].mean()
    print(f'  {reason:<8}：{len(g):>5}次  勝率{wr:>5.1f}%  均損益{avg_r:>+7.1f}點  累積{net_r:>+10,.0f}元')

print('=' * 62)
