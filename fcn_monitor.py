from flask import Flask, jsonify, render_template_string
import yfinance as yf
from datetime import datetime, date

app = Flask(__name__)

# ── FCN 商品定義 ──────────────────────────────────────────

FCN = {
    "name": "BBVA 4個月期 USD 自動提前贖回 FCN・20萬 USD",
    "code": "節省的黃大哥",
    "start_date": "2026/05/29",
    "maturity_date": "2026/10/07",
    "first_ko_date": "2026/07/06",
    "last_ko_date": "2026/10/05",
    "coupon_annual": 27.74,
    "guaranteed_months": 1,
    "currency": "USD",
    "coupon_note": "約 2.31%・14.3萬台幣（20萬USD × 27.74%÷12 × 匯率31）",
    "coupon_per_period_usd": 4623,
    "coupon_per_period_twd": "14.3萬",
    "total_coupon_usd": 18493,
    "total_coupon_twd": "約57.3萬",
    "periods": [
        {"t": 1, "start": "2026/6/5",  "end": "2026/7/6",  "pay": "2026/7/8",  "start_iso": "2026-06-05", "end_iso": "2026-07-06"},
        {"t": 2, "start": "2026/7/7",  "end": "2026/8/5",  "pay": "2026/8/7",  "start_iso": "2026-07-07", "end_iso": "2026-08-05"},
        {"t": 3, "start": "2026/8/6",  "end": "2026/9/8",  "pay": "2026/9/10", "start_iso": "2026-08-06", "end_iso": "2026-09-08"},
        {"t": 4, "start": "2026/9/9",  "end": "2026/10/5", "pay": "2026/10/7", "start_iso": "2026-09-09", "end_iso": "2026-10-05"},
    ],
    "underlyings": [
        {"ticker": "AMD",  "name": "超微半導體 (AMD)",  "initial": 516.10,  "strike": 361.27,  "ko": 516.10,  "ki": 309.66},
        {"ticker": "ARM",  "name": "安謀控股 (ARM)",   "initial": 353.29,  "strike": 247.303, "ko": 353.29,  "ki": 211.974},
        {"ticker": "TSLA", "name": "特斯拉 (TSLA)",    "initial": 435.79,  "strike": 305.053, "ko": 435.79,  "ki": 261.474},
    ],
}

FCN_CONAN = {**FCN, "code": "2026SN3011"}

FCN_SN3565 = {
    "name": "Goldman Sachs 6個月期 USD 自動提前贖回 FCN・5萬 USD",
    "code": "2026SN3565",
    "start_date": "2026/06/16",
    "maturity_date": "2026/12/28",
    "first_ko_date": "2026/07/23",
    "last_ko_date": "2026/12/23",
    "coupon_annual": 23.61,
    "guaranteed_months": 1,
    "currency": "USD",
    "coupon_note": "約 1.97%・3.0萬台幣（5萬USD × 23.61%÷12 × 匯率31）",
    "coupon_per_period_usd": 984,
    "coupon_per_period_twd": "3.0萬",
    "total_coupon_usd": 5902,
    "total_coupon_twd": "約18.3萬",
    "periods": [
        {"t": 1, "start": "2026/6/24",  "end": "2026/7/23",  "pay": "2026/7/27",  "start_iso": "2026-06-24", "end_iso": "2026-07-23"},
        {"t": 2, "start": "2026/7/24",  "end": "2026/8/24",  "pay": "2026/8/26",  "start_iso": "2026-07-24", "end_iso": "2026-08-24"},
        {"t": 3, "start": "2026/8/25",  "end": "2026/9/23",  "pay": "2026/9/25",  "start_iso": "2026-08-25", "end_iso": "2026-09-23"},
        {"t": 4, "start": "2026/9/24",  "end": "2026/10/23", "pay": "2026/10/27", "start_iso": "2026-09-24", "end_iso": "2026-10-23"},
        {"t": 5, "start": "2026/10/26", "end": "2026/11/23", "pay": "2026/11/25", "start_iso": "2026-10-26", "end_iso": "2026-11-23"},
        {"t": 6, "start": "2026/11/24", "end": "2026/12/23", "pay": "2026/12/28", "start_iso": "2026-11-24", "end_iso": "2026-12-23"},
    ],
    "underlyings": [
        {"ticker": "TSM",  "name": "台積電 (TSM)",   "initial": 425.83,   "strike": 255.498,  "ko": 425.83,   "ki": 212.915},
        {"ticker": "MU",   "name": "美光科技 (MU)",  "initial": 1020.76,  "strike": 612.456,  "ko": 1020.76,  "ki": 510.38},
        {"ticker": "NVDA", "name": "輝達 (NVDA)",    "initial": 207.41,   "strike": 124.446,  "ko": 207.41,   "ki": 103.705},
    ],
}

FCN_YQ = {
    **FCN_SN3565,
    "name": "Goldman Sachs 6個月期 USD 自動提前贖回 FCN・10萬 USD",
    "code": "2026SN3565",
    "coupon_note": "約 1.97%・6.1萬台幣（10萬USD × 23.61%÷12 × 匯率31）",
    "coupon_per_period_usd": 1968,
    "coupon_per_period_twd": "6.1萬",
    "total_coupon_usd": 11808,
    "total_coupon_twd": "約36.6萬",
}

MONTHLY_COUPON = FCN["coupon_annual"] / 12 / 100


# ── 共用價格抓取 ──────────────────────────────────────────

def fetch_prices(fcn):
    parts = fcn["first_ko_date"].replace("/", "-").split("-")
    first_ko = date(int(parts[0]), int(parts[1]), int(parts[2]))
    lparts = fcn["last_ko_date"].replace("/", "-").split("-")
    last_ko = date(int(lparts[0]), int(lparts[1]), int(lparts[2]))
    mparts = fcn["maturity_date"].replace("/", "-").split("-")
    maturity = date(int(mparts[0]), int(mparts[1]), int(mparts[2]))

    result = []
    for u in fcn["underlyings"]:
        try:
            ticker = yf.Ticker(u["ticker"])
            info = ticker.fast_info
            price = info.last_price
            prev_close = info.previous_close
            change = price - prev_close
            change_pct = change / prev_close * 100
            to_ko = (price / u["ko"] - 1) * 100
            to_ki = (price / u["ki"] - 1) * 100
            to_strike = (price / u["strike"] - 1) * 100

            ko_observation_active = date.today() >= first_ko
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

    worst = None
    for item in result:
        if "error" not in item:
            pct = item["price_pct_of_initial"]
            if worst is None or pct < worst["price_pct_of_initial"]:
                worst = item

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


# ── 路由 ──────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template_string(HTML_TEMPLATE, fcn=FCN, api_url="/api/prices", monthly_coupon=MONTHLY_COUPON * 100)

@app.route("/conan")
def index_conan():
    return render_template_string(HTML_TEMPLATE, fcn=FCN_CONAN, api_url="/api/prices", monthly_coupon=MONTHLY_COUPON * 100)

@app.route("/sn3565")
def index_sn3565():
    mc = FCN_SN3565["coupon_annual"] / 12 / 100
    return render_template_string(HTML_TEMPLATE, fcn=FCN_SN3565, api_url="/api/prices/sn3565", monthly_coupon=mc * 100)

@app.route("/api/prices")
def get_prices():
    return fetch_prices(FCN)

@app.route("/api/prices/sn3565")
def get_prices_sn3565():
    return fetch_prices(FCN_SN3565)

@app.route("/yq")
def index_yq():
    mc = FCN_YQ["coupon_annual"] / 12 / 100
    return render_template_string(HTML_TEMPLATE, fcn=FCN_YQ, api_url="/api/prices/yq", monthly_coupon=mc * 100)

@app.route("/api/prices/yq")
def get_prices_yq():
    return fetch_prices(FCN_YQ)


# ── HTML 模板 ─────────────────────────────────────────────

HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="zh-TW">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>FCN 即時監控 | {{ fcn.code }}</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: 'Segoe UI', Arial, sans-serif; background: #f8fafc; color: #0f172a; min-height: 100vh; font-size: 17px; }

  .header { background: #ffffff; padding: 20px 24px; border-bottom: 1px solid #e2e8f0; }
  .header h1 { font-size: 1.1rem; color: #94a3b8; font-weight: 400; }
  .header h2 { font-size: 1.5rem; color: #0f172a; margin: 4px 0; }
  .header-meta { display: flex; gap: 24px; margin-top: 8px; flex-wrap: wrap; }
  .meta-item { font-size: 0.82rem; color: #94a3b8; }
  .meta-item span { color: #475569; font-weight: 600; }
  .ko-period-bar { padding: 10px 24px; background: #f8fafc; border-bottom: 1px solid #e2e8f0; display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }
  .ko-period-badge { padding: 4px 12px; border-radius: 20px; font-size: 0.78rem; font-weight: 700; }
  .ko-period-active { background: #f0fdf4; color: #16a34a; border: 1px solid #86efac; }
  .ko-period-waiting { background: #f1f5f9; color: #64748b; border: 1px solid #cbd5e1; }
  .ko-period-text { font-size: 0.8rem; color: #94a3b8; }
  .ko-period-text strong { color: #475569; }

  /* 配息期程表 */
  .coupon-schedule { padding: 14px 24px 0; }
  .cs-title { font-size: 0.78rem; color: #94a3b8; text-transform: uppercase; letter-spacing: 0.05em; margin-bottom: 8px; }
  .cs-table-wrap { overflow-x: auto; }
  .cs-table { width: 100%; border-collapse: collapse; font-size: 0.8rem; }
  .cs-table th { color: #94a3b8; font-weight: 600; padding: 6px 10px; text-align: left; border-bottom: 1px solid #e2e8f0; white-space: nowrap; }
  .cs-table td { padding: 7px 10px; color: #64748b; border-bottom: 1px solid #f1f5f9; white-space: nowrap; }
  .cs-table td small { color: #94a3b8; font-size: 0.72rem; }
  .cs-row-current td { background: #f0fdf4; }
  .cs-row-current td:first-child { border-left: 2px solid #16a34a; color: #16a34a; font-weight: 700; font-size: 0.9rem; }
  .cs-row-current .cs-amount { color: #b45309; font-size: 0.92rem; font-weight: 700; }
  .cs-row-current .cs-amount-twd { color: #d97706; font-size: 0.85rem; font-weight: 700; }
  .cs-row-past td { color: #cbd5e1; }
  .cs-amount { color: #1e293b; font-weight: 600; font-size: 0.9rem; }
  .cs-amount-twd { color: #475569; font-size: 0.82rem; }
  .cs-total td { border-top: 1px solid #e2e8f0; color: #0f172a; font-weight: 700; padding-top: 8px; }
  .cs-total .cs-amount { color: #b45309; font-size: 0.92rem; }
  .cs-total .cs-amount-twd { color: #d97706; }

  .dist-pills { display: flex; gap: 8px; padding: 0 20px 14px; }
  .dist-pill { flex: 1; border-radius: 8px; padding: 8px 10px; text-align: center; }
  .dist-pill .dp-label { font-size: 0.68rem; color: #94a3b8; text-transform: uppercase; letter-spacing: 0.05em; }
  .dist-pill .dp-value { font-size: 1.2rem; font-weight: 800; margin-top: 2px; }
  .dp-ko { background: #f0fdf4; border: 1px solid #bbf7d0; }
  .dp-strike { background: #fffbeb; border: 1px solid #fde68a; }
  .dp-ki { background: #fff1f2; border: 1px solid #fecdd3; }

  .summary-bar { display: flex; gap: 16px; padding: 16px 24px; background: #f1f5f9; border-bottom: 1px solid #e2e8f0; flex-wrap: wrap; }
  .summary-card { flex: 1; min-width: 160px; background: #ffffff; border-radius: 8px; padding: 12px 16px; border: 1px solid #e2e8f0; }
  .summary-card .label { font-size: 0.75rem; color: #94a3b8; text-transform: uppercase; letter-spacing: 0.05em; }
  .summary-card .value { font-size: 1.4rem; font-weight: 700; margin-top: 4px; color: #0f172a; }
  .summary-card .sub { font-size: 0.78rem; color: #94a3b8; margin-top: 2px; }

  .cards { display: flex; gap: 16px; padding: 20px 24px; flex-wrap: wrap; }
  .card { flex: 1; min-width: 300px; background: #ffffff; border-radius: 12px; border: 1px solid #e2e8f0; overflow: hidden; transition: border-color 0.3s; }
  .card.status-SAFE { border-color: #e2e8f0; }
  .card.status-KO_TRIGGERED { border-color: #16a34a; box-shadow: 0 0 20px rgba(22,163,74,0.1); }
  .card.status-KI_TRIGGERED { border-color: #dc2626; box-shadow: 0 0 20px rgba(220,38,38,0.1); }
  .card.status-BELOW_STRIKE { border-color: #d97706; box-shadow: 0 0 20px rgba(217,119,6,0.1); }
  .card.status-ABOVE_KO_NOT_YET { border-color: #2563eb; box-shadow: 0 0 20px rgba(37,99,235,0.08); }
  .card.worst-of { border-top: 3px solid #d97706; }

  .card-header { padding: 16px 20px 12px; background: #f8fafc; display: flex; justify-content: space-between; align-items: flex-start; }
  .card-ticker { font-size: 1.5rem; font-weight: 800; letter-spacing: -0.02em; color: #0f172a; }
  .card-name { font-size: 0.78rem; color: #94a3b8; margin-top: 2px; }
  .status-badge { padding: 4px 10px; border-radius: 20px; font-size: 0.72rem; font-weight: 600; }
  .badge-SAFE { background: #f1f5f9; color: #64748b; }
  .badge-KO_TRIGGERED { background: #f0fdf4; color: #16a34a; border: 1px solid #86efac; }
  .badge-KI_TRIGGERED { background: #fff1f2; color: #dc2626; border: 1px solid #fecdd3; }
  .badge-BELOW_STRIKE { background: #fffbeb; color: #d97706; border: 1px solid #fde68a; }
  .badge-ABOVE_KO_NOT_YET { background: #eff6ff; color: #2563eb; border: 1px solid #bfdbfe; }
  .badge-WORST { background: #fff7ed; color: #c2410c; border: 1px solid #fed7aa; margin-top: 4px; display: block; text-align: center; }

  .price-section { padding: 16px 20px; }
  .current-price { display: flex; align-items: baseline; gap: 10px; }
  .price-value { font-size: 2rem; font-weight: 700; color: #0f172a; }
  .price-change { font-size: 0.9rem; font-weight: 600; }
  .positive { color: #16a34a; }
  .negative { color: #dc2626; }
  .neutral { color: #94a3b8; }
  .price-pct { font-size: 0.82rem; color: #94a3b8; margin-top: 4px; }
  .price-pct span { color: #475569; }

  .levels { padding: 0 20px 16px; display: flex; flex-direction: column; gap: 8px; }
  .level-row { display: flex; align-items: center; gap: 10px; }
  .level-label { width: 90px; font-size: 0.75rem; color: #94a3b8; flex-shrink: 0; }
  .level-bar-container { flex: 1; background: #f1f5f9; border-radius: 4px; height: 6px; position: relative; overflow: visible; }
  .level-bar { height: 100%; border-radius: 4px; transition: width 0.5s ease; }
  .level-value { width: 70px; text-align: right; font-size: 0.78rem; color: #475569; flex-shrink: 0; }
  .level-dist { width: 55px; text-align: right; font-size: 0.72rem; flex-shrink: 0; }
  .bar-ko { background: #16a34a; }
  .bar-strike { background: #d97706; }
  .bar-ki { background: #dc2626; }
  .bar-current { position: absolute; top: -3px; width: 2px; height: 12px; background: #0f172a; border-radius: 1px; }

  .gauge-section { padding: 0 20px 20px; }
  .gauge-label { font-size: 0.75rem; color: #94a3b8; margin-bottom: 8px; }
  .gauge-track { background: #f1f5f9; border-radius: 6px; height: 24px; position: relative; overflow: hidden; }
  .gauge-ki-zone { position: absolute; left: 0; height: 100%; background: rgba(220,38,38,0.08); border-right: 1px dashed #fca5a5; }
  .gauge-strike-zone { position: absolute; height: 100%; background: rgba(217,119,6,0.07); border-right: 1px dashed #fde68a; }
  .gauge-ko-line { position: absolute; height: 100%; width: 2px; background: #16a34a; }
  .gauge-cursor { position: absolute; top: 0; height: 100%; width: 3px; background: #0f172a; border-radius: 1px; transition: left 0.5s ease; }
  .gauge-labels { display: flex; justify-content: space-between; margin-top: 4px; font-size: 0.68rem; color: #94a3b8; }

  .footer { text-align: center; padding: 16px; color: #94a3b8; font-size: 0.75rem; }

  #loading { text-align: center; padding: 60px; color: #94a3b8; font-size: 1rem; }
  .spinner { display: inline-block; width: 20px; height: 20px; border: 2px solid #e2e8f0; border-top-color: #2563eb; border-radius: 50%; animation: spin 0.8s linear infinite; margin-right: 8px; vertical-align: middle; }
  @keyframes spin { to { transform: rotate(360deg); } }

  .alert-banner { margin: 0 24px 16px; padding: 12px 16px; border-radius: 8px; font-size: 0.85rem; font-weight: 600; display: none; }
  .alert-ko { background: #f0fdf4; border: 1px solid #86efac; color: #15803d; }
  .alert-ki { background: #fff1f2; border: 1px solid #fecdd3; color: #dc2626; }
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
    <div class="meta-item">月息 <span>{{ fcn.coupon_note }}</span></div>
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
        {% for p in fcn.periods %}
        <tr class="cs-row" data-start="{{ p.start_iso }}" data-end="{{ p.end_iso }}">
          <td>{{ p.t }}</td>
          <td>{{ p.start }}</td>
          <td>{{ p.end }}</td>
          <td>{{ p.pay }}</td>
          <td class="cs-amount">${{ "{:,}".format(fcn.coupon_per_period_usd) }} USD　<span class="cs-amount-twd">{{ fcn.coupon_per_period_twd }}台幣<small>（匯率31）</small></span></td>
        </tr>
        {% endfor %}
        <tr class="cs-total">
          <td colspan="4">總計（{{ fcn.periods|length }}期全拿）<small style="color:#94a3b8;font-weight:400;">　※ 若提前 KO，僅累計至觸發當期為止</small></td>
          <td class="cs-amount">${{ "{:,}".format(fcn.total_coupon_usd) }} USD　<span class="cs-amount-twd">{{ fcn.total_coupon_twd }}台幣<small>（匯率31）</small></span></td>
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
    <div style="background:#f0fdf4;border:0.5px solid #bbf7d0;border-top:3px solid #16a34a;border-radius:10px;padding:10px 8px;">
      <div style="color:#15803d;font-size:0.78rem;font-weight:700;margin-bottom:6px;">KO 自動提前贖回</div>
      <div style="color:#475569;font-size:0.72rem;line-height:1.6;">三檔標的皆曾經 ≥ 期初價，產品提前結束，拿回本金＋已累積票息（未到的期數不計）。只要有一檔未達標，當天就不觸發。</div>
    </div>
    <div style="background:#fffbeb;border:0.5px solid #fde68a;border-top:3px solid #d97706;border-radius:10px;padding:10px 8px;">
      <div style="color:#b45309;font-size:0.78rem;font-weight:700;margin-bottom:6px;">Strike 執行價</div>
      <div style="color:#475569;font-size:0.72rem;line-height:1.6;">到期時若最弱標的低於此價，將以此價格買進最弱標的股票，而非返還現金本金。</div>
    </div>
    <div style="background:#fff1f2;border:0.5px solid #fecdd3;border-top:3px solid #dc2626;border-radius:10px;padding:10px 8px;">
      <div style="color:#dc2626;font-size:0.78rem;font-weight:700;margin-bottom:6px;">KI 保護價</div>
      <div style="color:#475569;font-size:0.72rem;line-height:1.6;">若最後比價日，任一檔低於 KI 價，到期時將以執行價（Strike）買進最弱的標的。到期日前若曾經跌破，不在此限。</div>
    </div>
  </div>
  <div style="color:#cbd5e1;font-size:0.72rem;">資料來源：Yahoo Finance（15分鐘延遲）｜僅供參考，不構成投資建議</div>
</div>

<script>
const underlyings = {{ fcn.underlyings | tojson }};
const API_URL = "{{ api_url }}";

function statusText(s) {
  return { SAFE: '正常', KO_TRIGGERED: '已觸 KO', KI_TRIGGERED: '已觸 KI', BELOW_STRIKE: '低於執行價', ABOVE_KO_NOT_YET: '超過KO價（未到比價日）' }[s] || s;
}

function buildCard(u, data, isWorst) {
  const pct = data.price_pct_of_initial;
  const rangeMin = 35, rangeMax = 120;
  const toPos = v => Math.max(0, Math.min(100, (v - rangeMin) / (rangeMax - rangeMin) * 100));
  const ki_pct = (u.ki / u.initial) * 100;
  const strike_pct = (u.strike / u.initial) * 100;
  const ko_pct = (u.ko / u.initial) * 100;
  const kiPos = toPos(ki_pct);
  const strikePos = toPos(strike_pct);
  const koPos = toPos(ko_pct);
  const cursorPos = toPos(pct);
  const changeColor = data.change >= 0 ? 'positive' : 'negative';
  const changeSign = data.change >= 0 ? '+' : '';
  const distKOColor = data.to_ko_pct >= 0 ? 'positive' : (data.to_ko_pct < -15 ? 'negative' : 'neutral');
  const distKIColor = data.to_ki_pct <= 0 ? 'negative' : (data.to_ki_pct < 20 ? '#f59e0b' : 'positive');
  const distStrikeColor = data.to_strike_pct <= 0 ? 'negative' : 'neutral';

  return `
  <div class="card status-${data.status}${isWorst ? ' worst-of' : ''}">
    <div class="card-header">
      <div>
        <div class="card-ticker">${data.ticker}</div>
        <div class="card-name">${u.name}</div>
        ${isWorst ? '<span class="badge-WORST">⚠ Worst-of</span>' : ''}
      </div>
      <span class="status-badge badge-${data.status}">${statusText(data.status)}</span>
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
        <span>35%</span><span>KI ${ki_pct.toFixed(0)}%</span><span>Strike ${strike_pct.toFixed(0)}%</span><span>KO 100%</span><span>120%</span>
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
        <div class="level-label" style="color:#f59e0b">― Strike <span style="color:#374151;font-size:0.65rem">${strike_pct.toFixed(0)}%</span></div>
        <div class="level-value">$${u.strike.toFixed(2)}</div>
        <div class="level-dist" style="color:${distStrikeColor}">${data.to_strike_pct > 0 ? '+' : ''}${data.to_strike_pct.toFixed(1)}%</div>
      </div>
      <div class="level-row">
        <div class="level-label" style="color:#ef4444">▼ KI 價 <span style="color:#374151;font-size:0.65rem">${ki_pct.toFixed(0)}%</span></div>
        <div class="level-value">$${u.ki.toFixed(2)}</div>
        <div class="level-dist" style="color:${distKIColor}">+${data.to_ki_pct.toFixed(1)}%</div>
      </div>
    </div>
  </div>`;
}

async function refresh() {
  try {
    const res = await fetch(API_URL);
    const data = await res.json();

    document.getElementById('loading').style.display = 'none';
    document.getElementById('cards-container').style.display = 'flex';

    document.getElementById('worst-ticker').textContent = data.worst_of || '—';
    document.getElementById('worst-pct').textContent = data.worst_pct ? `期初價的 ${data.worst_pct.toFixed(2)}%` : '';
    document.getElementById('days-left').textContent = data.days_left;
    document.getElementById('update-time').textContent = data.updated_at;

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
      subEl.textContent = '保證配息期中';
    } else if (belowStrike) {
      statusEl.innerHTML = '<span style="color:#f59e0b">⚠ 部分低於執行價</span>';
      subEl.textContent = '需持續關注';
    } else {
      statusEl.innerHTML = '<span style="color:#64748b">正常（未觸發）</span>';
      subEl.textContent = '所有標的在執行價以上';
    }

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
