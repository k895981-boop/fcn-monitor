import pandas as pd
from datetime import time

f1 = r'TXF20110101_20201231(CrazyIndicator.pixnet.net)\TXF20110101_20201231(CrazyIndicator.pixnet.net).csv'
f2 = r'TXF20210101_20231231(CrazyIndicator.pixnet.net)\TXF20210101_20231231(CrazyIndicator.pixnet.net).csv'
out = 'txf_1min.csv'

print('載入第一份資料（2011~2020）...')
df1 = pd.read_csv(f1, encoding='utf-8-sig')
print(f'  筆數：{len(df1):,}')

print('載入第二份資料（2021~2023）...')
df2 = pd.read_csv(f2, encoding='utf-8-sig')
print(f'  筆數：{len(df2):,}')

df = pd.concat([df1, df2], ignore_index=True)
print(f'合併後：{len(df):,} 筆')

df['DateTime'] = pd.to_datetime(df['Date'].astype(str) + ' ' + df['Time'].astype(str))
df['_time'] = df['DateTime'].dt.time
df = df[(df['_time'] >= time(8, 45)) & (df['_time'] <= time(13, 45))]
print(f'篩選日盤後：{len(df):,} 筆')

df = df.sort_values('DateTime').reset_index(drop=True)

before = len(df)
df = df.drop_duplicates(subset=['DateTime']).reset_index(drop=True)
print(f'移除重複：{before - len(df)} 筆，剩 {len(df):,} 筆')

df['Date'] = df['DateTime'].dt.strftime('%Y/%m/%d')
df['Time'] = df['DateTime'].dt.strftime('%H:%M:%S')
df = df[['Date', 'Time', 'Open', 'High', 'Low', 'Close', 'Volume']]

print(f'日期範圍：{df["Date"].min()} ~ {df["Date"].max()}')
print(f'時間範圍：{df["Time"].min()} ~ {df["Time"].max()}')

df.to_csv(out, index=False, encoding='utf-8-sig')
print(f'已儲存：{out}')
