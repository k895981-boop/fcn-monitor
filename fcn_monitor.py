from flask import Flask, jsonify, render_template_string
import yfinance as yf
from datetime import datetime, date

app = Flask(__name__)

# FCN 商品參數
FCN = {
    "name": "BBVA 4個月期 USD 自動提前贖回 FCN・20萬 USD",
    "code": "很節省的黃大哥",
    "start_date": "2026/05/29",
    "maturity_date": "2026/10/07",
    "first_ko_date": "2026/07/06",
    "last_ko_date": "2026/10/05",
    "coupon_annual": 27.74,
    "guaranteed_months": 1,
    "currency": "USD",
    "underlyings": [
        {
            "ticker": "AMD",
            "name": "超微半導體 (AMD)",
            "initial": 516.10,
            "strike": 361.27,    # 70%
            "ko": 516.10,        # 100%
            "ki": 309.66,        # 60%
        },
        {
            "ticker": "ARM",
            "name": "安謀控股 (ARM)",
            "initial": 353.29,
            "strike": 247.303,
            "ko": 353.29,
            "ki": 211.974,
        },
        {
            "ticker": "TSLA",
            "name": "特斯拉 (TSLA)",
            "initial": 435.79,
            "strike": 305.053,
            "ko": 435.79,
            "ki": 261.474,
        },
    ],
}

# 計算每月票息（年化 27.74%，4個月期）
MONTHLY_COUPON = FCN["coupon_annual"] / 12 / 100

# 黃先生專屬版本
FCN_CONAN = {**FCN, "code": "柯南"}


@app.route("/")
def index():
    return render_template_string(HTML_TEMPLATE, fcn=FCN, monthly_coupon=MONTHLY_COUPON * 100)

@app.route("/conan")
def index_conan():
    return render_template_string(HTML_TEMPLATE, fcn=FCN_CONAN, monthly_coupon=MONTHLY_COUPON * 100)


@app.route("/api/prices")
def get_prices():
    result = []
    for u in FCN["underlyings"]:
        try:
            ticker = yf.Ticker(u["ticker"])
            info = ticker.fast_info
            price = info.last_price
            prev_close = info.previous_close
            change = price - prev_close
            change_pct = change / prev_close * 100

            # 距離各關鍵價位的距離%
            to_ko = (price / u["ko"] - 1) * 100
            to_ki = (price / u["ki"] - 1) * 100
            to_strike = (price / u["strike"] - 1) * 100

            # 狀態判斷（KO 觀察期 2026/07/06 起才生效）
            first_ko_date = date(2026, 7, 6)
            ko_observation_active = date.today() >= first_ko_date
            if ko_observation_active and price >= u["ko"]:
                status = "KO_TRIGGERED"
            elif price <= u["ki"]:
                status = "KI_TRIGGERED"
            elif price <= u["strike"]:
                status = "BELOW_STRIKE"
            elif not ko_observation_active and price >= u["ko"]:
                status = "ABOVE_KO_NOT_YET"
            else:
                status = "SAFE"

            result.append({
                "ticker": u["ticker"],
                "name": u["name"],
                "price": round(price, 4),
                "change": round(change, 4),
                "change_pct": round(change_pct, 2),
                "initial": u["initial"],
                "ko": u["ko"],
                "strike": u["strike"],
                "ki": u["ki"],
                "to_ko_pct": round(to_ko, 2),
                "to_ki_pct": round(to_ki, 2),
                "to_strike_pct": round(to_strike, 2),
                "status": status,
                "price_pct_of_initial": round(price / u["initial"] * 100, 2),
            })
        except Exception as e:
            result.append({"ticker": u["ticker"], "error": str(e)})

    # 判斷整張 FCN 的 worst-of
    worst = None
    for item in result:
        if "error" not in item:
            pct = item["price_pct_of_initial"]
            if worst is None or pct < worst["price_pct_of_initial"]:
                worst = item

    # 計算剩餘天數與 KO 觀察狀態
    maturity = date(2026, 10, 7)
    first_ko = date(2026, 7, 6)
    last_ko = date(2026, 10, 5)
    today = date.today()
    days_left = (maturity - today).days
    ko_active = first_ko <= today <= last_ko
    days_to_first_ko = max(0, (first_ko - today).days)

    return jsonify({
        "underlyings": result,
        "worst_of": worst["ticker"] if worst else None,
        "worst_pct": worst["price_pct_of_initial"] if worst else None,
        "days_left": days_left,
        "ko_active": ko_active,
        "days_to_first_ko": days_to_first_ko,
        "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    })


HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="zh-TW">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>FCN 即時監控 | {{ fcn.code }}</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: 'Segoe UI', Arial, sans-serif; background: #0f1117; color: #e2e8f0; min-height: 100vh; font-size: 17px; }

  .header { background: linear-gradient(135deg, #1a1f35, #252d4a); padding: 20px 24px; border-bottom: 1px solid #2d3748; }
  .header h1 { font-size: 1.1rem; color: #94a3b8; font-weight: 400; }
  .header h2 { font-size: 1.5rem; color: #e2e8f0; margin: 4px 0; }
  .header-meta { display: flex; gap: 24px; margin-top: 8px; flex-wrap: wrap; }
  .meta-item { font-size: 0.82rem; color: #64748b; }
  .meta-item span { color: #94a3b8; font-weight: 600; }
  .ko-period-bar { padding: 10px 24px; background: #0f1117; border-bottom: 1px solid #1e2535; display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }
  .ko-period-badge { padding: 4px 12px; border-radius: 20px; font-size: 0.78rem; font-weight: 700; }
  .ko-period-active { background: #064e3b; color: #10b981; border: 1px solid #10b981; }
  .ko-period-waiting { background: #1e293b; color: #64748b; border: 1px solid #374151; }
  .ko-period-text { font-size: 0.8rem; color: #64748b; }
  .ko-period-text strong { color: #94a3b8; }
  .dist-pills { display: flex; gap: 8px; padding: 0 20px 14px; }
  .dist-pill { flex: 1; border-radius: 8px; padding: 8px 10px; text-align: center; }
  .dist-pill .dp-label { font-size: 0.68rem; color: #64748b; text-transform: uppercase; letter-spacing: 0.05em; }
  .dist-pill .dp-value { font-size: 1.2rem; font-weight: 800; margin-top: 2px; }
  .dp-ko { background: rgba(16,185,129,0.08); border: 1px solid rgba(16,185,129,0.2); }
  .dp-strike { background: rgba(245,158,11,0.08); border: 1px solid rgba(245,158,11,0.2); }
  .dp-ki { background: rgba(239,68,68,0.08); border: 1px solid rgba(239,68,68,0.15); }

  .summary-bar { display: flex; gap: 16px; padding: 16px 24px; background: #141820; border-bottom: 1px solid #1e2535; flex-wrap: wrap; }
  .summary-card { flex: 1; min-width: 160px; background: #1a1f35; border-radius: 8px; padding: 12px 16px; border: 1px solid #2d3748; }
  .summary-card .label { font-size: 0.75rem; color: #64748b; text-transform: uppercase; letter-spacing: 0.05em; }
  .summary-card .value { font-size: 1.4rem; font-weight: 700; margin-top: 4px; }
  .summary-card .sub { font-size: 0.78rem; color: #64748b; margin-top: 2px; }

  .cards { display: flex; gap: 16px; padding: 20px 24px; flex-wrap: wrap; }
  .card { flex: 1; min-width: 300px; background: #1a1f35; border-radius: 12px; border: 1px solid #2d3748; overflow: hidden; transition: border-color 0.3s; }
  .card.status-SAFE { border-color: #2d3748; }
  .card.status-KO_TRIGGERED { border-color: #10b981; box-shadow: 0 0 20px rgba(16,185,129,0.15); }
  .card.status-KI_TRIGGERED { border-color: #ef4444; box-shadow: 0 0 20px rgba(239,68,68,0.2); }
  .card.status-BELOW_STRIKE { border-color: #f59e0b; box-shadow: 0 0 20px rgba(245,158,11,0.1); }
  .card.status-ABOVE_KO_NOT_YET { border-color: #3b82f6; box-shadow: 0 0 20px rgba(59,130,246,0.1); }
  .card.worst-of { border-top: 3px solid #f59e0b; }

  .card-header { padding: 16px 20px 12px; background: #141820; display: flex; justify-content: space-between; align-items: flex-start; }
  .card-ticker { font-size: 1.5rem; font-weight: 800; letter-spacing: -0.02em; }
  .card-name { font-size: 0.78rem; color: #64748b; margin-top: 2px; }
  .status-badge { padding: 4px 10px; border-radius: 20px; font-size: 0.72rem; font-weight: 600; }
  .badge-SAFE { background: #1e293b; color: #64748b; }
  .badge-KO_TRIGGERED { background: #064e3b; color: #10b981; }
  .badge-KI_TRIGGERED { background: #450a0a; color: #ef4444; }
  .badge-BELOW_STRIKE { background: #451a03; color: #f59e0b; }
  .badge-ABOVE_KO_NOT_YET { background: #1e3a5f; color: #60a5fa; }
  .badge-WORST { background: #422006; color: #fb923c; margin-top: 4px; display: block; text-align: center; }

  .price-section { padding: 16px 20px; }
  .current-price { display: flex; align-items: baseline; gap: 10px; }
  .price-value { font-size: 2rem; font-weight: 700; }
  .price-change { font-size: 0.9rem; font-weight: 600; }
  .positive { color: #10b981; }
  .negative { color: #ef4444; }
  .neutral { color: #64748b; }

  .price-pct { font-size: 0.82rem; color: #64748b; margin-top: 4px; }
  .price-pct span { color: #94a3b8; }

  .levels { padding: 0 20px 16px; display: flex; flex-direction: column; gap: 8px; }
  .level-row { display: flex; align-items: center; gap: 10px; }
  .level-label { width: 90px; font-size: 0.75rem; color: #64748b; flex-shrink: 0; }
  .level-bar-container { flex: 1; background: #0f1117; border-radius: 4px; height: 6px; position: relative; overflow: visible; }
  .level-bar { height: 100%; border-radius: 4px; transition: width 0.5s ease; }
  .level-value { width: 70px; text-align: right; font-size: 0.78rem; color: #94a3b8; flex-shrink: 0; }
  .level-dist { width: 55px; text-align: right; font-size: 0.72rem; flex-shrink: 0; }

  .bar-ko { background: #10b981; }
  .bar-strike { background: #f59e0b; }
  .bar-ki { background: #ef4444; }
  .bar-current { position: absolute; top: -3px; width: 2px; height: 12px; background: #fff; border-radius: 1px; }

  .gauge-section { padding: 0 20px 20px; }
  .gauge-label { font-size: 0.75rem; color: #64748b; margin-bottom: 8px; }
  .gauge-track { background: #0f1117; border-radius: 6px; height: 24px; position: relative; overflow: hidden; }
  .gauge-ki-zone { position: absolute; left: 0; height: 100%; background: rgba(239,68,68,0.15); border-right: 1px dashed #ef4444; }
  .gauge-strike-zone { position: absolute; height: 100%; background: rgba(245,158,11,0.1); border-right: 1px dashed #f59e0b; }
  .gauge-ko-line { position: absolute; height: 100%; width: 2px; background: #10b981; }
  .gauge-cursor { position: absolute; top: 0; height: 100%; width: 3px; background: #fff; border-radius: 1px; transition: left 0.5s ease; }
  .gauge-labels { display: flex; justify-content: space-between; margin-top: 4px; font-size: 0.68rem; color: #4b5563; }

  .footer { text-align: center; padding: 16px; color: #374151; font-size: 0.75rem; }
  .update-time { text-align: right; padding: 0 24px 8px; font-size: 0.75rem; color: #374151; }

  /* 配息期程表 */
  .coupon-schedule { padding: 14px 24px 0; }
  .cs-title { font-size: 0.78rem; color: #64748b; text-transform: uppercase; letter-spacing: 0.05em; margin-bottom: 8px; }
  .cs-table-wrap { overflow-x: auto; }
  .cs-table { width: 100%; border-collapse: collapse; font-size: 0.8rem; }
  .cs-table th { color: #64748b; font-weight: 600; padding: 6px 10px; text-align: left; border-bottom: 1px solid #2d3748; white-space: nowrap; }
  .cs-table td { padding: 7px 10px; color: #94a3b8; border-bottom: 1px solid #1e2535; white-space: nowrap; }
  .cs-table td small { color: #4b5563; font-size: 0.72rem; }
  .cs-row-current td { background: rgba(16,185,129,0.07); color: #e2e8f0; }
  .cs-row-current td:first-child { border-left: 2px solid #10b981; }
  .cs-row-past td { color: #374151; }
  .cs-total td { border-top: 1px solid #374151; color: #e2e8f0; font-weight: 700; padding-top: 8px; }
  .cs-note td { color: #4b5563; font-size: 0.72rem; padding-top: 4px; border-bottom: none; }

  #loading { text-align: center; padding: 60px; color: #4b5563; font-size: 1rem; }
  .spinner { display: inline-block; width: 20px; height: 20px; border: 2px solid #374151; border-top-color: #60a5fa; border-radius: 50%; animation: spin 0.8s linear infinite; margin-right: 8px; vertical-align: middle; }
  @keyframes spin { to { transform: rotate(360deg); } }

  .alert-banner { margin: 0 24px 16px; padding: 12px 16px; border-radius: 8px; font-size: 0.85rem; font-weight: 600; display: none; }
  .alert-ko { background: #064e3b; border: 1px solid #10b981; color: #34d399; }
  .alert-ki { background: #450a0a; border: 1px solid #ef4444; color: #fca5a5; }
</style>
</head>
<body>

<div class="header">
  <h1>FCN 即時監控 | {{ fcn.code }}</h1>
  <h2>{{ fcn.name }}</h2>
  <div class="header-meta">
    <div class="meta-item">交易日 <span>{{ fcn.start_date }}</span></div>
    <div class="meta-item">到期日 <span>{{ fcn.maturity_date }}</span></div>
    <div class="meta-item">年化票息 <span>{{ "%.2f"|format(fcn.coupon_annual) }}%</span></div>
    <div class="meta-item">月息 <span>約 2.31%・14.3萬台幣</span><span style="color:#4b5563;font-size:0.72rem;margin-left:4px;">（20萬USD × 27.74%÷12 × 匯率31）</span></div>
    <div class="meta-item">KO 觀察 <span>每日（Memory型）</span></div>
    <div class="meta-item">幣別 <span>{{ fcn.currency }}</span></div>
  </div>
</div>

<div class="ko-period-bar">
  <span class="ko-period-badge" id="ko-badge">載入中…</span>
  <span class="ko-period-text">
    首個比價日 <strong>{{ fcn.first_ko_date }}</strong>
    最後比價日 <strong>{{ fcn.last_ko_date }}</strong>
    保證配息期（前1個月不比價）
  </span>
  <span class="ko-period-text" id="ko-period-sub"></span>
</div>

<div class="coupon-schedule">
  <div class="cs-title">配息期程</div>
  <div class="cs-table-wrap">
    <table class="cs-table">
      <thead>
        <tr>
          <th>期</th>
          <th>起始日</th>
          <th>終止日</th>
          <th>配息日</th>
          <th>預計配息</th>
        </tr>
      </thead>
      <tbody>
        <tr class="cs-row" data-start="2026-06-05" data-end="2026-07-06">
          <td>1</td><td>2026/6/5</td><td>2026/7/6</td><td>2026/7/8</td>
          <td>$4,623 USD・14.3萬台幣<small>（匯率31）</small></td>
        </tr>
        <tr class="cs-row" data-start="2026-07-07" data-end="2026-08-05">
          <td>2</td><td>2026/7/7</td><td>2026/8/5</td><td>2026/8/7</td>
          <td>$4,623 USD・14.3萬台幣<small>（匯率31）</small></td>
        </tr>
        <tr class="cs-row" data-start="2026-08-06" data-end="2026-09-08">
          <td>3</td><td>2026/8/6</td><td>2026/9/8</td><td>2026/9/10</td>
          <td>$4,623 USD・14.3萬台幣<small>（匯率31）</small></td>
        </tr>
        <tr class="cs-row" data-start="2026-09-09" data-end="2026-10-05">
          <td>4</td><td>2026/9/9</td><td>2026/10/5</td><td>2026/10/7</td>
          <td>$4,623 USD・14.3萬台幣<small>（匯率31）</small></td>
        </tr>
        <tr class="cs-total">
          <td colspan="4">總計（4期全拿）<small style="color:#4b5563;font-weight:400;">　※ 若提前 KO，僅累計至觸發當期為止</small></td>
          <td>$18,493 USD・約57.3萬台幣<small>（匯率31）</small></td>
        </tr>
      </tbody>
    </table>
  </div>
</div>

<div class="summary-bar">
  <div class="summary-card">
    <div class="label">最弱標的（Worst-of）</div>
    <div class="value" id="worst-ticker">—</div>
    <div class="sub" id="worst-pct">載入中…</div>
  </div>
  <div class="summary-card">
    <div class="label">距到期</div>
    <div class="value" id="days-left">—</div>
    <div class="sub">天</div>
  </div>
  <div class="summary-card">
    <div class="label">整體狀態</div>
    <div class="value" id="overall-status" style="font-size:1rem; margin-top:6px;">載入中…</div>
    <div class="sub" id="overall-sub"></div>
  </div>
  <div class="summary-card">
    <div class="label">更新時間</div>
    <div class="value" id="update-time" style="font-size:0.9rem; margin-top:6px;">—</div>
    <div class="sub">每30秒自動更新</div>
  </div>
</div>

<div id="alert-ko" class="alert-banner alert-ko">✅ 三檔標的今日全部 ≥ 期初價！符合提前贖回條件，請確認當日收盤價是否維持。</div>
<div id="alert-ki" class="alert-banner alert-ki">⚠️ 警告：有標的已跌破 KI（觸及）價位，本金保護已失效！</div>

<div id="loading"><span class="spinner"></span>正在抓取即時報價…</div>
<div class="cards" id="cards-container" style="display:none;"></div>

<div class="footer">
  <div style="display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:8px;margin-bottom:16px;">
    <div style="background:#0f1117;border:0.5px solid #374151;border-top:3px solid #10b981;border-radius:10px;padding:10px 8px;">
      <div style="color:#10b981;font-size:0.78rem;font-weight:700;margin-bottom:6px;">KO 自動提前贖回</div>
      <div style="color:#9ca3af;font-size:0.72rem;line-height:1.6;">三檔標的皆曾經 ≥ 期初價，產品提前結束，拿回本金＋已累積票息（未到的期數不計）。只要有一檔未達標，當天就不觸發。</div>
    </div>
    <div style="background:#0f1117;border:0.5px solid #374151;border-top:3px solid #f59e0b;border-radius:10px;padding:10px 8px;">
      <div style="color:#f59e0b;font-size:0.78rem;font-weight:700;margin-bottom:6px;">Strike 執行價</div>
      <div style="color:#9ca3af;font-size:0.72rem;line-height:1.6;">到期時若最弱標的低於此價，將以此價格買進最弱標的股票，而非返還現金本金。</div>
    </div>
    <div style="background:#0f1117;border:0.5px solid #374151;border-top:3px solid #ef4444;border-radius:10px;padding:10px 8px;">
      <div style="color:#ef4444;font-size:0.78rem;font-weight:700;margin-bottom:6px;">KI 保護線</div>
      <div style="color:#9ca3af;font-size:0.72rem;line-height:1.6;">若最後比價日，任一檔低於 KI 價，到期時將以執行價（Strike）買進最弱的標的。到期日前若曾經跌破，不在此限。</div>
    </div>
  </div>
  <div style="color:#374151;font-size:0.72rem;">資料來源：Yahoo Finance（15分鐘延遲）｜僅供參考，不構成投資建議</div>
</div>

<script>
const underlyings = {{ fcn.underlyings | tojson }};

function statusText(s) {
  return { SAFE: '正常', KO_TRIGGERED: '已觸 KO', KI_TRIGGERED: '已觸 KI', BELOW_STRIKE: '低於執行價', ABOVE_KO_NOT_YET: '超過KO價（未到比價日）' }[s] || s;
}
function badgeClass(s) {
  return 'badge-' + s;
}
function cardClass(s) {
  return 'status-' + s;
}

function buildCard(u, data, isWorst) {
  const pct = data.price_pct_of_initial;

  // 計算 gauge 位置（以 40%~120% 期初價為範圍）
  const rangeMin = 40, rangeMax = 120;
  const toPos = v => Math.max(0, Math.min(100, (v - rangeMin) / (rangeMax - rangeMin) * 100));

  const kiPos = toPos(60);
  const strikePos = toPos(70);
  const koPos = toPos(100);
  const cursorPos = toPos(pct);

  const changeColor = data.change >= 0 ? 'positive' : 'negative';
  const changeSign = data.change >= 0 ? '+' : '';

  const distKOColor = data.to_ko_pct >= 0 ? 'positive' : (data.to_ko_pct < -15 ? 'negative' : 'neutral');
  const distKIColor = data.to_ki_pct <= 0 ? 'negative' : (data.to_ki_pct < 20 ? '#f59e0b' : 'positive');
  const distStrikeColor = data.to_strike_pct <= 0 ? 'negative' : 'neutral';

  return `
  <div class="card ${cardClass(data.status)}${isWorst ? ' worst-of' : ''}">
    <div class="card-header">
      <div>
        <div class="card-ticker">${data.ticker}</div>
        <div class="card-name">${u.name}</div>
        ${isWorst ? '<span class="badge-WORST">⚠ Worst-of</span>' : ''}
      </div>
      <span class="status-badge ${badgeClass(data.status)}">${statusText(data.status)}</span>
    </div>

    <div class="price-section">
      <div class="current-price">
        <span class="price-value">$${data.price.toFixed(2)}</span>
        <span class="price-change ${changeColor}">${changeSign}${data.change.toFixed(2)} (${changeSign}${data.change_pct.toFixed(2)}%)</span>
      </div>
      <div class="price-pct">期初價 <span>$${u.initial}</span>｜目前為期初價的 <span style="color:${pct<60?'#ef4444':pct<70?'#f59e0b':pct>=100?'#10b981':'#94a3b8'}">${pct.toFixed(2)}%</span></div>
    </div>

    <div class="gauge-section">
      <div class="gauge-label">股價位置（灰區=KI，橘線=Strike，綠線=KO）</div>
      <div class="gauge-track">
        <div class="gauge-ki-zone" style="width:${kiPos}%"></div>
        <div class="gauge-strike-zone" style="left:${kiPos}%;width:${strikePos-kiPos}%"></div>
        <div class="gauge-ko-line" style="left:${koPos}%"></div>
        <div class="gauge-cursor" style="left:${cursorPos}%"></div>
      </div>
      <div class="gauge-labels">
        <span>40%</span><span>KI 60%</span><span>Strike 70%</span><span>KO 100%</span><span>120%</span>
      </div>
    </div>

    <div class="dist-pills">
      <div class="dist-pill dp-ko">
        <div class="dp-label">距 KO</div>
        <div class="dp-value" style="color:${data.to_ko_pct >= 0 ? '#10b981' : '#ef4444'}">${data.to_ko_pct > 0 ? '+' : ''}${data.to_ko_pct.toFixed(1)}%</div>
      </div>
      <div class="dist-pill dp-strike">
        <div class="dp-label">距 Strike</div>
        <div class="dp-value" style="color:${data.to_strike_pct >= 0 ? '#f59e0b' : '#ef4444'}">${data.to_strike_pct > 0 ? '+' : ''}${data.to_strike_pct.toFixed(1)}%</div>
      </div>
      <div class="dist-pill dp-ki">
        <div class="dp-label">距 KI</div>
        <div class="dp-value" style="color:${data.to_ki_pct > 20 ? '#64748b' : data.to_ki_pct > 0 ? '#f59e0b' : '#ef4444'}">+${data.to_ki_pct.toFixed(1)}%</div>
      </div>
    </div>

    <div class="levels">
      <div class="level-row">
        <div class="level-label" style="color:#10b981">▲ KO 價 <span style="color:#374151;font-size:0.65rem">100%</span></div>
        <div class="level-value">$${u.ko.toFixed(2)}</div>
        <div class="level-dist" style="color:${distKOColor}">${data.to_ko_pct > 0 ? '+' : ''}${data.to_ko_pct.toFixed(1)}%</div>
      </div>
      <div class="level-row">
        <div class="level-label" style="color:#f59e0b">― Strike <span style="color:#374151;font-size:0.65rem">70%</span></div>
        <div class="level-value">$${u.strike.toFixed(2)}</div>
        <div class="level-dist" style="color:${distStrikeColor}">${data.to_strike_pct > 0 ? '+' : ''}${data.to_strike_pct.toFixed(1)}%</div>
      </div>
      <div class="level-row">
        <div class="level-label" style="color:#ef4444">▼ KI 價 <span style="color:#374151;font-size:0.65rem">60%</span></div>
        <div class="level-value">$${u.ki.toFixed(2)}</div>
        <div class="level-dist" style="color:${distKIColor}">+${data.to_ki_pct.toFixed(1)}%</div>
      </div>
    </div>
  </div>`;
}

async function refresh() {
  try {
    const res = await fetch('/api/prices');
    const data = await res.json();

    document.getElementById('loading').style.display = 'none';
    document.getElementById('cards-container').style.display = 'flex';

    document.getElementById('worst-ticker').textContent = data.worst_of || '—';
    document.getElementById('worst-pct').textContent = data.worst_pct ? `期初價的 ${data.worst_pct.toFixed(2)}%` : '';
    document.getElementById('days-left').textContent = data.days_left;
    document.getElementById('update-time').textContent = data.updated_at;

    // KO 觀察期狀態
    const badge = document.getElementById('ko-badge');
    const sub = document.getElementById('ko-period-sub');
    if (data.ko_active) {
      badge.textContent = '✅ KO 觀察中';
      badge.className = 'ko-period-badge ko-period-active';
      sub.textContent = '每個交易日收盤後比對，所有標的 ≥ 期初價即提前贖回';
    } else {
      badge.textContent = `⏳ 保證配息期（還有 ${data.days_to_first_ko} 天開始比價）`;
      badge.className = 'ko-period-badge ko-period-waiting';
      sub.textContent = '首個比價日前不會觸發提前贖回';
    }

    // 整體狀態
    const items = data.underlyings.filter(u => !u.error);
    const hasKI = items.some(u => u.status === 'KI_TRIGGERED');
    const allKO = items.every(u => u.status === 'KO_TRIGGERED');
    const aboveKONotYet = items.some(u => u.status === 'ABOVE_KO_NOT_YET');
    const belowStrike = items.some(u => u.status === 'BELOW_STRIKE');

    document.getElementById('alert-ko').style.display = allKO ? 'block' : 'none';
    document.getElementById('alert-ki').style.display = hasKI ? 'block' : 'none';

    let statusEl = document.getElementById('overall-status');
    let subEl = document.getElementById('overall-sub');
    if (hasKI) {
      statusEl.innerHTML = '<span style="color:#ef4444">⚠ KI 已觸及</span>';
      subEl.textContent = '本金保護失效';
    } else if (allKO) {
      statusEl.innerHTML = '<span style="color:#10b981">✅ 三檔全部 ≥ KO</span>';
      subEl.textContent = '符合提前贖回條件（需三檔同時達標）';
    } else if (aboveKONotYet) {
      statusEl.innerHTML = '<span style="color:#60a5fa">📅 超過KO但未到比價日</span>';
      subEl.textContent = '保證配息期中，7/6 起才開始比價';
    } else if (belowStrike) {
      statusEl.innerHTML = '<span style="color:#f59e0b">⚠ 部分低於執行價</span>';
      subEl.textContent = '需持續關注';
    } else {
      statusEl.innerHTML = '<span style="color:#64748b">正常（未觸發）</span>';
      subEl.textContent = '所有標的在執行價以上';
    }

    // 渲染卡片
    const container = document.getElementById('cards-container');
    container.innerHTML = data.underlyings.map((item, i) => {
      if (item.error) return `<div class="card"><div class="card-header"><div class="card-ticker">${item.ticker}</div></div><div class="price-section" style="color:#ef4444">載入失敗：${item.error}</div></div>`;
      return buildCard(underlyings[i], item, item.ticker === data.worst_of);
    }).join('');

  } catch(e) {
    console.error(e);
  }
}

// 高亮當前配息期
(function() {
  const today = new Date();
  today.setHours(0,0,0,0);
  document.querySelectorAll('.cs-row').forEach(row => {
    const s = new Date(row.dataset.start);
    const e = new Date(row.dataset.end);
    if (today >= s && today <= e) {
      row.classList.add('cs-row-current');
    } else if (today > e) {
      row.classList.add('cs-row-past');
    }
  });
})();

refresh();
setInterval(refresh, 30000);
</script>
</body>
</html>
"""

if __name__ == "__main__":
    import os
    port = int(os.environ.get("PORT", 5000))
    print("=" * 50)
    print("FCN 即時監控啟動中...")
    print(f"請用瀏覽器開啟：http://127.0.0.1:{port}")
    print("Ctrl+C 停止伺服器")
    print("=" * 50)
    app.run(debug=False, host="0.0.0.0", port=port)
