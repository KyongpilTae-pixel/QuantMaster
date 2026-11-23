"""
A-axis monthly letter generator — TAA V3 asset allocation.

Outputs a standalone HTML file with gold color scheme.
"""
from __future__ import annotations

import os
from datetime import datetime

import pandas as pd
import yfinance as yf

_REPORTS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "quantLetters")
os.makedirs(_REPORTS_DIR, exist_ok=True)

ASSETS   = ["EWY", "SPY", "AGG", "GLD", "BIL"]
MA_WIN   = 200
MOM12_WIN = 252
MOM6_WIN  = 126
CAP      = 0.30

_ASSET_LABELS = {
    "EWY": ("EWY", "한국 주식 (iShares MSCI Korea)"),
    "SPY": ("SPY", "미국 주식 (S&P500)"),
    "AGG": ("AGG", "미국 국채 (US Agg Bond)"),
    "GLD": ("GLD", "금 (Gold)"),
    "BIL": ("BIL", "현금 (T-Bill)"),
}

_CSS = """
:root {
  --bg:       #FAFAF8;
  --bg2:      #FFF8E6;
  --surface:  #FFFFFF;
  --border:   #E8D9A0;
  --gold:     #B45309;
  --gold-lt:  #D97706;
  --gold-dk:  #92400E;
  --text:     #1C1917;
  --text-sub: #78716C;
  --up:       #15803D;
  --dn:       #B91C1C;
  --on-bg:    #ECFDF5;
  --on-cl:    #15803D;
  --off-bg:   #FEF2F2;
  --off-cl:   #B91C1C;
  --neu-bg:   #F5F5F4;
  --neu-cl:   #78716C;
}
@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) {
    --bg:       #1C1917;
    --bg2:      #292524;
    --surface:  #292524;
    --border:   #57534E;
    --gold:     #FCD34D;
    --gold-lt:  #FDE68A;
    --gold-dk:  #F59E0B;
    --text:     #F5F5F4;
    --text-sub: #A8A29E;
    --up:       #34D399;
    --dn:       #F87171;
    --on-bg:    #052E16;
    --on-cl:    #34D399;
    --off-bg:   #450A0A;
    --off-cl:   #F87171;
    --neu-bg:   #292524;
    --neu-cl:   #A8A29E;
  }
}
:root[data-theme="dark"] {
  --bg:#1C1917;--bg2:#292524;--surface:#292524;--border:#57534E;
  --gold:#FCD34D;--gold-lt:#FDE68A;--gold-dk:#F59E0B;
  --text:#F5F5F4;--text-sub:#A8A29E;--up:#34D399;--dn:#F87171;
  --on-bg:#052E16;--on-cl:#34D399;--off-bg:#450A0A;--off-cl:#F87171;
  --neu-bg:#292524;--neu-cl:#A8A29E;
}
:root[data-theme="light"] {
  --bg:#FAFAF8;--bg2:#FFF8E6;--surface:#FFFFFF;--border:#E8D9A0;
  --gold:#B45309;--gold-lt:#D97706;--gold-dk:#92400E;
  --text:#1C1917;--text-sub:#78716C;--up:#15803D;--dn:#B91C1C;
  --on-bg:#ECFDF5;--on-cl:#15803D;--off-bg:#FEF2F2;--off-cl:#B91C1C;
  --neu-bg:#F5F5F4;--neu-cl:#78716C;
}
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
body{
  font-family:'IBM Plex Sans KR','Noto Sans KR',sans-serif;
  background:var(--bg);color:var(--text);
  max-width:720px;margin:0 auto;padding:24px 16px 48px;
  font-size:15px;line-height:1.6;
}
.letter-header{
  border-top:4px solid var(--gold);
  background:var(--bg2);
  padding:20px 24px;border-radius:0 0 8px 8px;
  margin-bottom:28px;
}
.letter-header .series{
  font-size:11px;font-weight:700;letter-spacing:.12em;
  text-transform:uppercase;color:var(--gold);margin-bottom:4px;
}
.letter-header h1{font-size:1.4rem;font-weight:700;color:var(--text);margin-bottom:2px}
.letter-header .meta{font-size:12px;color:var(--text-sub)}
h2{
  font-size:1rem;font-weight:700;color:var(--gold-dk);
  border-left:3px solid var(--gold);padding-left:10px;
  margin:28px 0 12px;
}
.weight-grid{
  display:grid;grid-template-columns:repeat(5,1fr);gap:8px;margin:12px 0;
}
@media(max-width:460px){.weight-grid{grid-template-columns:repeat(3,1fr)}}
.weight-card{
  background:var(--surface);border:1px solid var(--border);
  border-radius:8px;padding:12px 8px;text-align:center;
}
.weight-card.active{border-color:var(--gold);background:var(--bg2)}
.weight-card .sym{font-size:11px;font-weight:700;color:var(--text-sub);letter-spacing:.05em}
.weight-card .pct{font-size:1.4rem;font-weight:800;color:var(--text);margin:2px 0}
.weight-card.active .pct{color:var(--gold-dk)}
.weight-card .lbl{font-size:10px;color:var(--text-sub)}
table{width:100%;border-collapse:collapse;margin:12px 0;font-size:13px}
th{background:var(--bg2);color:var(--text-sub);font-weight:600;
   padding:8px 10px;text-align:left;font-size:11px;letter-spacing:.04em;
   border-bottom:2px solid var(--border)}
td{padding:9px 10px;border-bottom:1px solid var(--border)}
tr:last-child td{border-bottom:none}
.badge-on{background:var(--on-bg);color:var(--on-cl);font-weight:700;
  font-size:11px;padding:2px 7px;border-radius:4px;white-space:nowrap}
.badge-off{background:var(--off-bg);color:var(--off-cl);font-weight:700;
  font-size:11px;padding:2px 7px;border-radius:4px;white-space:nowrap}
.badge-bil{background:var(--neu-bg);color:var(--neu-cl);font-weight:700;
  font-size:11px;padding:2px 7px;border-radius:4px;white-space:nowrap}
.up{color:var(--up);font-weight:600}
.dn{color:var(--dn);font-weight:600}
.change-box{
  background:var(--bg2);border:1px solid var(--border);
  border-radius:8px;padding:14px 16px;margin:12px 0;
}
.change-box .title{font-size:12px;font-weight:700;color:var(--gold);margin-bottom:6px}
.change-box ul{padding-left:16px;font-size:13px;color:var(--text)}
.change-box li{margin-bottom:4px}
.disclaimer{
  margin-top:40px;padding:12px 14px;border-radius:6px;
  background:var(--neu-bg);font-size:11px;color:var(--text-sub);line-height:1.5;
}
"""


def _compute_taa_signal(prices: pd.DataFrame, ref_date: pd.Timestamp) -> dict:
    adj   = prices.loc[:ref_date].ffill()
    if adj.empty:
        return {}
    ref_idx_all = len(adj) - 1
    gates, mom12, mom6, ma200_v = {}, {}, {}, {}

    for sym in ASSETS:
        if sym == "BIL":
            gates[sym] = False
            ma200_v[sym] = mom12[sym] = mom6[sym] = None
            continue
        series = adj[sym].dropna()
        idx = len(series) - 1
        p = float(series.iloc[idx])
        ma = float(series.iloc[max(0, idx - MA_WIN + 1):idx + 1].mean()) if idx >= MA_WIN - 1 else None
        p12 = float(series.iloc[idx - MOM12_WIN]) if idx >= MOM12_WIN else None
        p6  = float(series.iloc[idx - MOM6_WIN])  if idx >= MOM6_WIN  else None
        ma200_v[sym]  = ma
        mom12[sym]    = (p / p12 - 1) * 100 if p12 else None
        mom6[sym]     = (p / p6  - 1) * 100 if p6  else None
        gate_trend    = (p > ma) if ma else False
        gate_m12      = (mom12[sym] > 0) if mom12[sym] is not None else False
        gates[sym]    = gate_trend and gate_m12

    on_assets = [s for s in ["EWY", "SPY", "AGG", "GLD"] if gates[s]]
    if not on_assets:
        weights = {s: 0.0 for s in ASSETS}
        weights["BIL"] = 1.0
    else:
        raw_mom   = {s: max(mom6[s], 0) if mom6[s] is not None else 0 for s in on_assets}
        total_mom = sum(raw_mom.values())
        raw_w     = {s: raw_mom[s] / total_mom for s in on_assets} if total_mom else {s: 1 / len(on_assets) for s in on_assets}
        weights   = {s: 0.0 for s in ASSETS}
        excess    = 0.0
        for s in on_assets:
            w = raw_w[s]
            if w > CAP:
                excess += w - CAP
                weights[s] = CAP
            else:
                weights[s] = w
        weights["BIL"] = max(0.0, 1.0 - sum(weights[s] for s in ASSETS if s != "BIL"))

    prices_now = adj.iloc[-1]
    return {
        "ref_date": str(ref_date.date()),
        "weights": {s: round(weights[s] * 100, 1) for s in ASSETS},
        "gates": gates,
        "prices": {s: round(float(prices_now[s]), 2) if s in prices_now.index else None for s in ASSETS if s != "BIL"},
        "ma200": {s: round(ma200_v[s], 2) if ma200_v.get(s) else None for s in ASSETS if s != "BIL"},
        "mom12": {s: round(mom12[s], 1) if mom12.get(s) is not None else None for s in ASSETS if s != "BIL"},
        "mom6":  {s: round(mom6[s],  1) if mom6.get(s)  is not None else None for s in ASSETS if s != "BIL"},
    }


def _download_prices() -> pd.DataFrame:
    rows = {}
    for sym in ASSETS:
        df = yf.download(sym, start="2020-01-01", auto_adjust=True, progress=False, threads=False)
        if df.empty:
            continue
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        df.index = pd.to_datetime(df.index).tz_localize(None).normalize()
        rows[sym] = df["Close"].sort_index()
    return pd.DataFrame(rows).sort_index().ffill()


def generate_a_monthly_letter(
    ref_month: str,
    prev_month: str | None = None,
    prices: pd.DataFrame | None = None,
) -> str:
    """
    Generate HTML for A-axis monthly letter.

    ref_month:  'YYYY-MM' or 'YYYY-MM-DD' (uses last available trading day of that month)
    prev_month: prior month string for comparison (auto-derived if None)
    prices:     pre-loaded DataFrame to avoid repeated downloads
    """
    if prices is None:
        prices = _download_prices()

    # Resolve ref_date = last trading day of the given month
    year, mon = int(ref_month[:4]), int(ref_month[5:7])
    month_end_nominal = pd.Timestamp(year, mon, 28) + pd.offsets.MonthEnd(0)
    avail = prices.loc[:month_end_nominal].index
    if len(avail) == 0:
        raise ValueError(f"No price data for {ref_month}")
    ref_date = avail[-1]

    # Previous month
    if prev_month is None:
        prev_mon_nom = month_end_nominal - pd.offsets.MonthBegin(1) - pd.Timedelta(days=1)
        prev_avail   = prices.loc[:prev_mon_nom].index
        prev_date    = prev_avail[-1] if len(prev_avail) else None
    else:
        py, pm = int(prev_month[:4]), int(prev_month[5:7])
        prev_end_nom = pd.Timestamp(py, pm, 28) + pd.offsets.MonthEnd(0)
        prev_avail   = prices.loc[:prev_end_nom].index
        prev_date    = prev_avail[-1] if len(prev_avail) else None

    cur  = _compute_taa_signal(prices, ref_date)
    prev = _compute_taa_signal(prices, prev_date) if prev_date else None

    return _render_a_html(cur, prev)


def _render_a_html(cur: dict, prev: dict | None) -> str:
    ref_date = cur["ref_date"]
    weights  = cur["weights"]
    gates    = cur["gates"]
    prices   = cur["prices"]
    ma200    = cur["ma200"]
    mom12    = cur["mom12"]
    mom6     = cur["mom6"]

    dt   = datetime.strptime(ref_date, "%Y-%m-%d")
    year = dt.year
    mon  = dt.month
    month_ko = f"{year}년 {mon}월"
    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M")

    # Weight cards
    weight_cards = ""
    for sym in ASSETS:
        w     = weights[sym]
        active = " active" if w > 0 else ""
        sym_s, lbl = _ASSET_LABELS[sym]
        # Short label for card
        short = {"EWY": "한국", "SPY": "미국", "AGG": "채권", "GLD": "금", "BIL": "현금"}[sym]
        weight_cards += (
            f'<div class="weight-card{active}">'
            f'<div class="sym">{sym_s}</div>'
            f'<div class="pct">{w:.0f}%</div>'
            f'<div class="lbl">{short}</div>'
            f'</div>'
        )

    # Gate table rows
    gate_rows = ""
    for sym in ["EWY", "SPY", "AGG", "GLD"]:
        p     = prices.get(sym)
        ma    = ma200.get(sym)
        m12   = mom12.get(sym)
        m6    = mom6.get(sym)
        gate  = gates.get(sym, False)
        above = p > ma if (p and ma) else False
        gap   = (p / ma - 1) * 100 if (p and ma) else None

        badge     = '<span class="badge-on">ON</span>' if gate else '<span class="badge-off">OFF</span>'
        p_str     = f"{p:,.2f}" if p else "-"
        ma_str    = f"{ma:,.2f}" if ma else "-"
        gap_str   = f'<span class="{"up" if (gap or 0) >= 0 else "dn"}">{gap:+.1f}%</span>' if gap else "-"
        m12_str   = f'<span class="{"up" if (m12 or 0) >= 0 else "dn"}">{m12:+.1f}%</span>' if m12 is not None else "-"
        m6_str    = f'<span class="{"up" if (m6 or 0) >= 0 else "dn"}">{m6:+.1f}%</span>' if m6 is not None else "-"
        above_str = "✓" if above else "✗"
        _, full_name = _ASSET_LABELS[sym]
        gate_rows += (
            f"<tr>"
            f"<td><strong>{sym}</strong><br><span style='font-size:11px;color:var(--text-sub)'>{full_name.split('(')[0].strip()}</span></td>"
            f"<td style='text-align:center'>{badge}</td>"
            f"<td style='text-align:right'>{p_str}</td>"
            f"<td style='text-align:right'>{ma_str}</td>"
            f"<td style='text-align:center'>{above_str}</td>"
            f"<td style='text-align:right'>{gap_str}</td>"
            f"<td style='text-align:right'>{m12_str}</td>"
            f"<td style='text-align:right'>{m6_str}</td>"
            f"</tr>"
        )

    # Change vs prior month
    change_items = []
    if prev:
        for sym in ASSETS:
            cw = weights[sym]
            pw = prev["weights"].get(sym, 0)
            if abs(cw - pw) >= 0.5:
                arrow = "▲" if cw > pw else "▼"
                verb  = "증가" if cw > pw else "감소"
                gate_now  = gates.get(sym, False)
                gate_prev = prev["gates"].get(sym, False)
                reason = ""
                if sym != "BIL":
                    if gate_now and not gate_prev:
                        reason = " — 게이트 ON 전환"
                    elif not gate_now and gate_prev:
                        reason = " — 게이트 OFF 전환"
                change_items.append(
                    f"<li><strong>{sym}</strong>: {pw:.0f}% → {cw:.0f}% &nbsp;"
                    f"<span class='{'up' if cw>pw else 'dn'}'>{arrow} {abs(cw-pw):.0f}%p {verb}</span>{reason}</li>"
                )

    if not change_items:
        change_items = ["<li>전월 대비 비중 변화 없음 (리밸런싱 불필요)</li>"]

    change_html = (
        '<div class="change-box">'
        '<div class="title">전월 대비 비중 변화</div>'
        f'<ul>{"".join(change_items)}</ul>'
        '</div>'
    )

    # Risk / cash summary
    risk_pct = sum(weights[s] for s in ["EWY", "SPY", "AGG", "GLD"])
    cash_pct = weights["BIL"]
    summary_color = "up" if risk_pct >= 50 else "dn" if risk_pct == 0 else "text"
    posture = "공격적" if risk_pct >= 70 else "균형" if risk_pct >= 40 else "방어적"

    return f"""<!DOCTYPE html>
<html lang='ko'>
<head>
<meta charset='utf-8'>
<meta name='viewport' content='width=device-width,initial-scale=1'>
<title>QuantLetter A — {month_ko}</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Sans+KR:wght@400;600;700&display=swap" rel="stylesheet">
<style>{_CSS}</style>
</head>
<body>

<div class="letter-header">
  <div class="series">QuantLetter · A축 자산배분</div>
  <h1>{month_ko} 월간 레터</h1>
  <div class="meta">기준일: {ref_date} &nbsp;|&nbsp; 발행: {generated_at} &nbsp;|&nbsp; TAA V3</div>
</div>

<h2>이번 달 비중</h2>
<div class="weight-grid">
{weight_cards}
</div>
<p style="font-size:13px;color:var(--text-sub);margin-top:4px;">
  위험자산 <strong style="color:var(--{'up' if risk_pct >= 50 else 'gold'})">{risk_pct:.0f}%</strong>
  &nbsp;/&nbsp; 현금(BIL) <strong>{cash_pct:.0f}%</strong>
  &nbsp;→&nbsp; <span style="font-weight:700">{posture}</span> 포지션
</p>

{change_html}

<h2>자산별 게이트 상태</h2>
<p style="font-size:12px;color:var(--text-sub);margin-bottom:8px;">
  게이트 조건: 현재가 &gt; MA200 <strong>AND</strong> 12개월 모멘텀 &gt; 0
</p>
<div style="overflow-x:auto">
<table>
<thead><tr>
  <th>자산</th><th>게이트</th><th>현재가</th><th>MA200</th>
  <th>&gt;MA200</th><th>괴리율</th><th>12M 수익</th><th>6M 수익</th>
</tr></thead>
<tbody>{gate_rows}</tbody>
</table>
</div>

<div class="disclaimer">
  과거 데이터 기반 모의결과이며 미래 수익을 보장하지 않습니다.
  본 레터는 투자자문이 아니며, 실제 투자 결정은 본인의 판단으로 이루어져야 합니다.
  QuantMaster Pro — 내부 검토용
</div>

</body>
</html>
"""


def save_a_monthly_letter(ref_month: str, prev_month: str | None = None, prices: pd.DataFrame | None = None) -> str:
    html  = generate_a_monthly_letter(ref_month, prev_month, prices)
    fname = f"2026-M{ref_month[5:7]}_A.html"
    path  = os.path.join(_REPORTS_DIR, fname)
    with open(path, "w", encoding="utf-8") as f:
        f.write(html)
    return path
