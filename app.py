import streamlit as st
import streamlit.components.v1 as components
import yfinance as yf
from datetime import datetime, date
import time
import json as _json
import base64 as _b64

st.set_page_config(page_title="FCN 即時監控", layout="wide", page_icon="📊")

# 防複製保護
st.markdown("""
<style>
* { -webkit-user-select:none; -moz-user-select:none; -ms-user-select:none; user-select:none; }
[data-testid="stAppViewContainer"] > .main > div { padding: 0 !important; }
</style>
<script>
document.addEventListener('contextmenu',e=>e.preventDefault());
document.addEventListener('keydown',e=>{if((e.ctrlKey||e.metaKey)&&['c','u','s','a','p'].includes(e.key.toLowerCase()))e.preventDefault();});
</script>
""", unsafe_allow_html=True)

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

PRODUCTS = {
    "":       FCN,
    "conan":  FCN_CONAN,
    "sn3565": FCN_SN3565,
    "yq":     FCN_YQ,
}

# ── 價格抓取（快取 30 秒）──────────────────────────────────

@st.cache_data(ttl=30)
def fetch_prices(tickers_key: str, underlyings: tuple, first_ko_str: str, last_ko_str: str, maturity_str: str):
    def parse_date(s):
        p = s.replace("/", "-").split("-")
        return date(int(p[0]), int(p[1]), int(p[2]))

    first_ko = parse_date(first_ko_str)
    last_ko  = parse_date(last_ko_str)
    maturity = parse_date(maturity_str)
    today    = date.today()

    result = []
    for u_raw in underlyings:
        u = dict(u_raw) if not isinstance(u_raw, dict) else u_raw
        try:
            info       = yf.Ticker(u["ticker"]).fast_info
            price      = float(info.last_price)
            prev_close = float(info.previous_close)
            change     = price - prev_close
            change_pct = change / prev_close * 100

            ko_active = first_ko <= today <= last_ko
            if ko_active and price >= u["ko"]:
                status = "KO_TRIGGERED"
            elif price <= u["ki"]:
                status = "KI_TRIGGERED"
            elif price <= u["strike"]:
                status = "BELOW_STRIKE"
            elif not ko_active and price >= u["ko"]:
                status = "ABOVE_KO_NOT_YET"
            else:
                status = "SAFE"

            result.append({
                "ticker":              u["ticker"],
                "name":                u["name"],
                "price":               round(price, 2),
                "change":              round(change, 2),
                "change_pct":          round(change_pct, 2),
                "initial":             u["initial"],
                "ko":                  u["ko"],
                "strike":              u["strike"],
                "ki":                  u["ki"],
                "to_ko_pct":           round((price / u["ko"]   - 1) * 100, 2),
                "to_ki_pct":           round((price / u["ki"]   - 1) * 100, 2),
                "to_strike_pct":       round((price / u["strike"] - 1) * 100, 2),
                "price_pct_of_initial": round(price / u["initial"] * 100, 2),
                "status":              status,
            })
        except Exception as e:
            result.append({"ticker": u["ticker"], "name": u.get("name",""), "error": str(e)})

    valid = [r for r in result if "error" not in r]
    worst = min(valid, key=lambda x: x["price_pct_of_initial"]) if valid else None

    return {
        "underlyings":      result,
        "worst_of":         worst["ticker"] if worst else None,
        "worst_pct":        worst["price_pct_of_initial"] if worst else None,
        "days_left":        (maturity - today).days,
        "ko_active":        first_ko <= today <= last_ko,
        "days_to_first_ko": max(0, (first_ko - today).days),
        "updated_at":       datetime.now().strftime("%Y-%m-%d %H:%M"),
    }

# ── HTML 產生 ─────────────────────────────────────────────

def build_html(fcn: dict, data: dict) -> str:
    underlyings = fcn["underlyings"]

    # 配息期程列
    today = date.today()
    period_rows = ""
    for p in fcn["periods"]:
        s = date.fromisoformat(p["start_iso"])
        e = date.fromisoformat(p["end_iso"])
        row_class = "cs-row-current" if s <= today <= e else ("cs-row-past" if today > e else "")
        if not row_class and not any(date.fromisoformat(q["start_iso"]) <= today <= date.fromisoformat(q["end_iso"]) for q in fcn["periods"]):
            if p["t"] == 1:
                row_class = "cs-row-current"
        amount_html = f'<td class="cs-amount">${fcn["coupon_per_period_usd"]:,} USD&nbsp;<span class="cs-amount-twd">{fcn["coupon_per_period_twd"]}台幣<small>（匯率31）</small></span></td>'
        period_rows += f'<tr class="{row_class}"><td>{p["t"]}</td><td>{p["start"]}</td><td>{p["end"]}</td><td>{p["pay"]}</td>{amount_html}</tr>'
    total_row = (f'<tr class="cs-total"><td colspan="4">總計（{len(fcn["periods"])}期全拿）'
                 f'<small style="color:#94a3b8;font-weight:400">　※ 若提前 KO，僅累計至觸發當期為止</small></td>'
                 f'<td class="cs-amount">${fcn["total_coupon_usd"]:,} USD&nbsp;'
                 f'<span class="cs-amount-twd">{fcn["total_coupon_twd"]}台幣<small>（匯率31）</small></span></td></tr>')

    # KO 狀態列
    if data["ko_active"]:
        ko_badge = '<span class="ko-period-badge ko-period-active">✅ KO 觀察中</span>'
        ko_sub   = "每個交易日收盤後比對，所有標的 ≥ 期初價即提前贖回"
    else:
        ko_badge = f'<span class="ko-period-badge ko-period-waiting">⏳ 保證配息期（還有 {data["days_to_first_ko"]} 天開始比價）</span>'
        ko_sub   = "首個比價日前不會觸發提前贖回"

    # 整體狀態
    items = [r for r in data["underlyings"] if "error" not in r]
    has_ki       = any(u["status"] == "KI_TRIGGERED"    for u in items)
    all_ko       = bool(items) and all(u["status"] == "KO_TRIGGERED"   for u in items)
    above_not_yet= any(u["status"] == "ABOVE_KO_NOT_YET" for u in items)
    below_strike = any(u["status"] == "BELOW_STRIKE"    for u in items)

    if has_ki:
        overall_html = '<span style="color:#ef4444">⚠ KI 已觸及</span>'
        overall_sub  = "本金保護失效"
    elif all_ko:
        overall_html = '<span style="color:#10b981">✅ 三檔全部 ≥ KO</span>'
        overall_sub  = "符合提前贖回條件"
    elif above_not_yet:
        overall_html = '<span style="color:#60a5fa">📅 超過KO但未到比價日</span>'
        overall_sub  = "保證配息期中"
    elif below_strike:
        overall_html = '<span style="color:#f59e0b">⚠ 部分低於執行價</span>'
        overall_sub  = "需持續關注"
    else:
        overall_html = '<span style="color:#64748b">正常（未觸發）</span>'
        overall_sub  = "所有標的在執行價以上"

    alert_ko = 'style="display:block"' if all_ko else 'style="display:none"'
    alert_ki = 'style="display:block"' if has_ki else 'style="display:none"'

    # 個股卡片
    def card_html(u_cfg, u_data, is_worst):
        if "error" in u_data:
            return f'<div class="card"><div class="card-header"><div class="card-ticker">{u_data["ticker"]}</div></div><div class="price-section" style="color:#ef4444">載入失敗：{u_data["error"]}</div></div>'

        pct      = u_data["price_pct_of_initial"]
        ki_pct   = u_cfg["ki"]   / u_cfg["initial"] * 100
        st_pct   = u_cfg["strike"] / u_cfg["initial"] * 100
        ko_pct   = u_cfg["ko"]   / u_cfg["initial"] * 100
        rmin, rmax = 35, 120
        def pos(v): return max(0, min(100, (v - rmin) / (rmax - rmin) * 100))
        ki_pos = pos(ki_pct); st_pos = pos(st_pct); ko_pos = pos(ko_pct); cur_pos = pos(pct)

        chg_sign = "+" if u_data["change"] >= 0 else ""
        chg_col  = "#16a34a" if u_data["change"] >= 0 else "#dc2626"
        pct_col  = "#ef4444" if pct < 60 else ("#f59e0b" if pct < 70 else ("#10b981" if pct >= 100 else "#94a3b8"))
        status   = u_data["status"]
        status_map = {"SAFE":"正常","KO_TRIGGERED":"已觸 KO","KI_TRIGGERED":"已觸 KI","BELOW_STRIKE":"低於執行價","ABOVE_KO_NOT_YET":"超過KO（未到比價日）"}

        to_ko_col  = "#10b981" if u_data["to_ko_pct"] >= 0 else "#ef4444"
        to_st_col  = "#f59e0b" if u_data["to_strike_pct"] >= 0 else "#ef4444"
        to_ki_col  = "#64748b" if u_data["to_ki_pct"] > 20 else ("#f59e0b" if u_data["to_ki_pct"] > 0 else "#ef4444")

        worst_badge = '<span class="badge-WORST">⚠ Worst-of</span>' if is_worst else ""
        return f"""
<div class="card status-{status}{' worst-of' if is_worst else ''}">
  <div class="card-header">
    <div>
      <div class="card-ticker">{u_data["ticker"]}</div>
      <div class="card-name">{u_cfg["name"]}</div>
      {worst_badge}
    </div>
    <span class="status-badge badge-{status}">{status_map.get(status, status)}</span>
  </div>
  <div class="price-section">
    <div class="current-price">
      <span class="price-value">${u_data["price"]:.2f}</span>
      <span class="price-change" style="color:{chg_col}">{chg_sign}{u_data["change"]:.2f} ({chg_sign}{u_data["change_pct"]:.2f}%)</span>
    </div>
    <div class="price-pct">期初價 <span>${u_cfg["initial"]}</span>｜目前為期初價的 <span style="color:{pct_col}">{pct:.2f}%</span></div>
  </div>
  <div class="gauge-section">
    <div class="gauge-label">股價位置（灰區=KI，橘線=Strike，綠線=KO）</div>
    <div class="gauge-track">
      <div class="gauge-ki-zone"     style="width:{ki_pos:.1f}%"></div>
      <div class="gauge-strike-zone" style="left:{ki_pos:.1f}%;width:{st_pos-ki_pos:.1f}%"></div>
      <div class="gauge-ko-line"     style="left:{ko_pos:.1f}%"></div>
      <div class="gauge-cursor"      style="left:{cur_pos:.1f}%"></div>
    </div>
    <div class="gauge-labels">
      <span>35%</span><span>KI {ki_pct:.0f}%</span><span>Strike {st_pct:.0f}%</span><span>KO 100%</span><span>120%</span>
    </div>
  </div>
  <div class="dist-pills">
    <div class="dist-pill dp-ko">
      <div class="dp-label">距 KO</div>
      <div class="dp-value" style="color:{to_ko_col}">{'+' if u_data["to_ko_pct"]>0 else ''}{u_data["to_ko_pct"]:.1f}%</div>
    </div>
    <div class="dist-pill dp-strike">
      <div class="dp-label">距 Strike</div>
      <div class="dp-value" style="color:{to_st_col}">{'+' if u_data["to_strike_pct"]>0 else ''}{u_data["to_strike_pct"]:.1f}%</div>
    </div>
    <div class="dist-pill dp-ki">
      <div class="dp-label">距 KI</div>
      <div class="dp-value" style="color:{to_ki_col}">+{u_data["to_ki_pct"]:.1f}%</div>
    </div>
  </div>
  <div class="levels">
    <div class="level-row">
      <div class="level-label" style="color:#10b981">▲ KO 價 <span style="color:#374151;font-size:.65rem">100%</span></div>
      <div class="level-value">${u_cfg["ko"]:.2f}</div>
      <div class="level-dist" style="color:{to_ko_col}">{'+' if u_data["to_ko_pct"]>0 else ''}{u_data["to_ko_pct"]:.1f}%</div>
    </div>
    <div class="level-row">
      <div class="level-label" style="color:#f59e0b">― Strike <span style="color:#374151;font-size:.65rem">{st_pct:.0f}%</span></div>
      <div class="level-value">${u_cfg["strike"]:.3f}</div>
      <div class="level-dist" style="color:{to_st_col}">{'+' if u_data["to_strike_pct"]>0 else ''}{u_data["to_strike_pct"]:.1f}%</div>
    </div>
    <div class="level-row">
      <div class="level-label" style="color:#ef4444">▼ KI 價 <span style="color:#374151;font-size:.65rem">{ki_pct:.0f}%</span></div>
      <div class="level-value">${u_cfg["ki"]:.3f}</div>
      <div class="level-dist" style="color:{to_ki_col}">+{u_data["to_ki_pct"]:.1f}%</div>
    </div>
  </div>
</div>"""

    cards_html = "".join(
        card_html(underlyings[i], data["underlyings"][i], data["underlyings"][i].get("ticker") == data["worst_of"])
        for i in range(len(underlyings))
    )

    worst_sub = f'期初價的 {data["worst_pct"]:.2f}%' if data["worst_pct"] else ""

    return f"""<!DOCTYPE html>
<html lang="zh-TW">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
*{{box-sizing:border-box;margin:0;padding:0;-webkit-user-select:none;user-select:none}}
body{{font-family:'Segoe UI',Arial,sans-serif;background:#f8fafc;color:#0f172a;font-size:16px}}
.header{{background:#fff;padding:16px 20px;border-bottom:1px solid #e2e8f0}}
.header h1{{font-size:1rem;color:#94a3b8;font-weight:400}}
.header h2{{font-size:1.35rem;color:#0f172a;margin:4px 0}}
.header-meta{{display:flex;gap:16px;margin-top:6px;flex-wrap:wrap}}
.meta-item{{font-size:.78rem;color:#94a3b8}}.meta-item span{{color:#475569;font-weight:600}}
.ko-period-bar{{padding:10px 20px;background:#f8fafc;border-bottom:1px solid #e2e8f0;display:flex;align-items:center;gap:10px;flex-wrap:wrap}}
.ko-period-badge{{padding:4px 12px;border-radius:20px;font-size:.76rem;font-weight:700}}
.ko-period-active{{background:#f0fdf4;color:#16a34a;border:1px solid #86efac}}
.ko-period-waiting{{background:#f1f5f9;color:#64748b;border:1px solid #cbd5e1}}
.ko-period-text{{font-size:.78rem;color:#94a3b8}}.ko-period-text strong{{color:#475569}}
.coupon-schedule{{padding:12px 20px 0}}
.cs-title{{font-size:.76rem;color:#94a3b8;text-transform:uppercase;letter-spacing:.05em;margin-bottom:6px}}
.cs-table-wrap{{overflow-x:auto;-webkit-overflow-scrolling:touch}}
.cs-table{{width:100%;min-width:420px;border-collapse:collapse;font-size:.78rem}}
.cs-table th{{color:#94a3b8;font-weight:600;padding:6px 10px;text-align:left;border-bottom:1px solid #e2e8f0;white-space:nowrap}}
.cs-table td{{padding:7px 10px;color:#64748b;border-bottom:1px solid #f1f5f9;white-space:nowrap}}
.cs-table td small{{color:#94a3b8;font-size:.7rem}}
.cs-row-current td{{background:#f0fdf4}}
.cs-row-current td:first-child{{border-left:2px solid #16a34a;color:#16a34a;font-weight:700;font-size:.88rem}}
.cs-row-current .cs-amount{{color:#b45309;font-size:.9rem;font-weight:700}}
.cs-row-current .cs-amount-twd{{color:#d97706;font-size:.82rem;font-weight:700}}
.cs-row-past td{{color:#cbd5e1}}
.cs-amount{{color:#1e293b;font-weight:600;font-size:.88rem}}.cs-amount-twd{{color:#475569;font-size:.8rem}}
.cs-total td{{border-top:1px solid #e2e8f0;color:#0f172a;font-weight:700;padding-top:8px}}
.cs-total .cs-amount{{color:#b45309;font-size:.9rem}}.cs-total .cs-amount-twd{{color:#d97706}}
.summary-bar{{display:flex;gap:12px;padding:12px 20px;background:#f1f5f9;border-bottom:1px solid #e2e8f0;flex-wrap:wrap}}
.summary-card{{flex:1;min-width:140px;background:#fff;border-radius:8px;padding:10px 14px;border:1px solid #e2e8f0}}
.summary-card .label{{font-size:.72rem;color:#94a3b8;text-transform:uppercase;letter-spacing:.05em}}
.summary-card .value{{font-size:1.3rem;font-weight:700;margin-top:4px;color:#0f172a}}
.summary-card .sub{{font-size:.75rem;color:#94a3b8;margin-top:2px}}
.alert-banner{{margin:0 20px 12px;padding:10px 14px;border-radius:8px;font-size:.82rem;font-weight:600}}
.alert-ko{{background:#f0fdf4;border:1px solid #86efac;color:#15803d}}
.alert-ki{{background:#fff1f2;border:1px solid #fecdd3;color:#dc2626}}
.cards{{display:flex;gap:14px;padding:16px 20px;flex-wrap:wrap}}
.card{{flex:1;min-width:280px;background:#fff;border-radius:12px;border:1px solid #e2e8f0;overflow:hidden}}
.card.status-KO_TRIGGERED{{border-color:#16a34a;box-shadow:0 0 16px rgba(22,163,74,.12)}}
.card.status-KI_TRIGGERED{{border-color:#dc2626;box-shadow:0 0 16px rgba(220,38,38,.12)}}
.card.status-BELOW_STRIKE{{border-color:#d97706;box-shadow:0 0 16px rgba(217,119,6,.12)}}
.card.status-ABOVE_KO_NOT_YET{{border-color:#2563eb;box-shadow:0 0 16px rgba(37,99,235,.08)}}
.card.worst-of{{border-top:3px solid #d97706}}
.card-header{{padding:14px 18px 10px;background:#f8fafc;display:flex;justify-content:space-between;align-items:flex-start}}
.card-ticker{{font-size:1.4rem;font-weight:800;letter-spacing:-.02em;color:#0f172a}}
.card-name{{font-size:.75rem;color:#94a3b8;margin-top:2px}}
.status-badge{{padding:4px 10px;border-radius:20px;font-size:.7rem;font-weight:600}}
.badge-SAFE{{background:#f1f5f9;color:#64748b}}
.badge-KO_TRIGGERED{{background:#f0fdf4;color:#16a34a;border:1px solid #86efac}}
.badge-KI_TRIGGERED{{background:#fff1f2;color:#dc2626;border:1px solid #fecdd3}}
.badge-BELOW_STRIKE{{background:#fffbeb;color:#d97706;border:1px solid #fde68a}}
.badge-ABOVE_KO_NOT_YET{{background:#eff6ff;color:#2563eb;border:1px solid #bfdbfe}}
.badge-WORST{{background:#fff7ed;color:#c2410c;border:1px solid #fed7aa;margin-top:4px;display:block;text-align:center;font-size:.7rem;font-weight:600;padding:3px 8px;border-radius:20px}}
.price-section{{padding:14px 18px}}
.current-price{{display:flex;align-items:baseline;gap:8px}}
.price-value{{font-size:1.9rem;font-weight:700;color:#0f172a}}
.price-change{{font-size:.87rem;font-weight:600}}
.price-pct{{font-size:.78rem;color:#94a3b8;margin-top:4px}}.price-pct span{{color:#475569}}
.gauge-section{{padding:0 18px 14px}}
.gauge-label{{font-size:.72rem;color:#94a3b8;margin-bottom:6px}}
.gauge-track{{background:#f1f5f9;border-radius:6px;height:22px;position:relative;overflow:hidden}}
.gauge-ki-zone{{position:absolute;left:0;height:100%;background:rgba(220,38,38,.08);border-right:1px dashed #fca5a5}}
.gauge-strike-zone{{position:absolute;height:100%;background:rgba(217,119,6,.07);border-right:1px dashed #fde68a}}
.gauge-ko-line{{position:absolute;height:100%;width:2px;background:#16a34a}}
.gauge-cursor{{position:absolute;top:0;height:100%;width:3px;background:#0f172a;border-radius:1px}}
.gauge-labels{{display:flex;justify-content:space-between;margin-top:3px;font-size:.65rem;color:#94a3b8}}
.dist-pills{{display:flex;gap:6px;padding:0 18px 14px}}
.dist-pill{{flex:1;border-radius:8px;padding:7px 8px;text-align:center}}
.dp-label{{font-size:.65rem;color:#94a3b8;text-transform:uppercase;letter-spacing:.04em}}
.dp-value{{font-size:1.1rem;font-weight:800;margin-top:2px}}
.dp-ko{{background:#f0fdf4;border:1px solid #bbf7d0}}
.dp-strike{{background:#fffbeb;border:1px solid #fde68a}}
.dp-ki{{background:#fff1f2;border:1px solid #fecdd3}}
.levels{{padding:0 18px 18px;display:flex;flex-direction:column;gap:6px}}
.level-row{{display:flex;align-items:center;gap:8px}}
.level-label{{width:90px;font-size:.72rem;color:#94a3b8;flex-shrink:0}}
.level-value{{width:70px;text-align:right;font-size:.76rem;color:#475569;flex-shrink:0}}
.level-dist{{width:50px;text-align:right;font-size:.7rem;flex-shrink:0}}
.footer{{padding:14px 20px 20px}}
.footer-legend{{display:grid;grid-template-columns:repeat(3,1fr);gap:8px;margin-bottom:12px}}
.legend-item{{border-radius:10px;padding:10px 8px}}
.legend-title{{font-size:.76rem;font-weight:700;margin-bottom:5px}}
.legend-body{{font-size:.7rem;color:#475569;line-height:1.55}}
.footer-note{{text-align:center;color:#94a3b8;font-size:.7rem}}
@media(max-width:480px){{
  body{{font-size:15px}}
  .cards{{padding:12px}}
  .card{{min-width:100%}}
  .footer-legend{{grid-template-columns:1fr}}
  .summary-bar{{gap:8px}}
  .summary-card{{min-width:calc(50% - 4px)}}
}}
</style>
</head>
<body>

<div class="header">
  <h1>FCN 即時監控 | {fcn["code"]}</h1>
  <h2>{fcn["name"]}</h2>
  <div class="header-meta">
    <div class="meta-item">交易日 <span>{fcn["start_date"]}</span></div>
    <div class="meta-item">到期日 <span>{fcn["maturity_date"]}</span></div>
    <div class="meta-item">年化票息 <span>{fcn["coupon_annual"]:.2f}%</span></div>
    <div class="meta-item">月息 <span>{fcn["coupon_note"]}</span></div>
  </div>
</div>

<div class="ko-period-bar">
  {ko_badge}
  <span class="ko-period-text">
    首個比價日 <strong>{fcn["first_ko_date"]}</strong>
    最後比價日 <strong>{fcn["last_ko_date"]}</strong>
  </span>
  <span class="ko-period-text">{ko_sub}</span>
</div>

<div class="coupon-schedule">
  <div class="cs-title">配息期程</div>
  <div class="cs-table-wrap">
    <table class="cs-table">
      <thead><tr><th>期</th><th>起始日</th><th>終止日</th><th>配息日</th><th>預計配息</th></tr></thead>
      <tbody>{period_rows}{total_row}</tbody>
    </table>
  </div>
</div>

<div class="summary-bar">
  <div class="summary-card">
    <div class="label">最弱標的（Worst-of）</div>
    <div class="value">{data["worst_of"] or "—"}</div>
    <div class="sub">{worst_sub}</div>
  </div>
  <div class="summary-card">
    <div class="label">距到期</div>
    <div class="value">{data["days_left"]}</div>
    <div class="sub">天</div>
  </div>
  <div class="summary-card">
    <div class="label">整體狀態</div>
    <div class="value" style="font-size:.95rem;margin-top:6px">{overall_html}</div>
    <div class="sub">{overall_sub}</div>
  </div>
  <div class="summary-card">
    <div class="label">更新時間</div>
    <div class="value" style="font-size:.85rem;margin-top:6px">{data["updated_at"]}</div>
    <div class="sub">每30秒自動更新</div>
  </div>
</div>

<div class="alert-banner alert-ko" {alert_ko}>✅ 三檔標的今日全部 ≥ 期初價！符合提前贖回條件。</div>
<div class="alert-banner alert-ki" {alert_ki}>⚠️ 警告：有標的已跌破 KI（觸及）價位，本金保護已失效！</div>

<div class="cards">{cards_html}</div>

<div class="footer">
  <div class="footer-legend">
    <div class="legend-item" style="background:#f0fdf4;border:.5px solid #bbf7d0;border-top:3px solid #16a34a">
      <div class="legend-title" style="color:#15803d">KO 自動提前贖回</div>
      <div class="legend-body">三檔標的皆曾經 ≥ 期初價，產品提前結束，拿回本金＋已累積票息（未到的期數不計）。只要有一檔未達標，當天就不觸發。</div>
    </div>
    <div class="legend-item" style="background:#fffbeb;border:.5px solid #fde68a;border-top:3px solid #d97706">
      <div class="legend-title" style="color:#b45309">Strike 執行價</div>
      <div class="legend-body">到期時若最弱標的低於此價，將以此價格買進最弱標的股票，而非返還現金本金。</div>
    </div>
    <div class="legend-item" style="background:#fff1f2;border:.5px solid #fecdd3;border-top:3px solid #dc2626">
      <div class="legend-title" style="color:#dc2626">KI 保護價</div>
      <div class="legend-body">若最後比價日，任一檔低於 KI 價，到期時將以執行價（Strike）買進最弱的標的。到期日前若曾跌破，不在此限。</div>
    </div>
  </div>
  <div class="footer-note">資料來源：Yahoo Finance（15分鐘延遲）｜僅供參考，不構成投資建議</div>
</div>

</body>
</html>"""


# ── 主程式 ────────────────────────────────────────────────

product_key = st.query_params.get("product", "")
d_param     = st.query_params.get("d", "")

if d_param:
    try:
        _padded = d_param + "=" * ((4 - len(d_param) % 4) % 4)
        fcn = _json.loads(_b64.urlsafe_b64decode(_padded).decode())
    except Exception as e:
        st.error(f"連結解碼失敗：{e}")
        st.stop()
    tickers_key = "custom|" + ",".join(u["ticker"] for u in fcn["underlyings"])
elif product_key in PRODUCTS:
    fcn = PRODUCTS[product_key]
    tickers_key = product_key + "|" + ",".join(u["ticker"] for u in fcn["underlyings"])
else:
    st.error("找不到此商品頁面，請確認連結是否正確。")
    st.stop()
data = fetch_prices(
    tickers_key,
    tuple(tuple(u.items()) for u in fcn["underlyings"]),
    fcn["first_ko_date"],
    fcn["last_ko_date"],
    fcn["maturity_date"],
)

# 顯示 HTML 儀表板
html = build_html(fcn, data)
components.html(html, height=1400, scrolling=True)

# 每 30 秒自動重跑
time.sleep(30)
st.rerun()
