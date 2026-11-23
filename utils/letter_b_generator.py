"""
B-axis weekly letter generator — MA200 Pullback touch/reclaim strategy.

Outputs a standalone HTML file with blue color scheme.
"""
from __future__ import annotations

import os
from datetime import datetime

import pandas as pd

_REPORTS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "letterService")
os.makedirs(_REPORTS_DIR, exist_ok=True)

_CSS = """
:root {
  --bg:       #F8FAFF;
  --bg2:      #EFF6FF;
  --surface:  #FFFFFF;
  --border:   #BFDBFE;
  --blue:     #1D4ED8;
  --blue-lt:  #3B82F6;
  --blue-dk:  #1E3A5F;
  --text:     #0F172A;
  --text-sub: #64748B;
  --up:       #15803D;
  --dn:       #B91C1C;
  --touch-bg: #EFF6FF;
  --touch-cl: #1D4ED8;
  --recl-bg:  #F0FDF4;
  --recl-cl:  #15803D;
  --stop-bg:  #FEF2F2;
  --stop-cl:  #B91C1C;
  --hold-bg:  #F5F5F4;
  --hold-cl:  #78716C;
}
@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) {
    --bg:#0F172A;--bg2:#1E3A5F;--surface:#1E293B;--border:#334155;
    --blue:#60A5FA;--blue-lt:#93C5FD;--blue-dk:#BFDBFE;
    --text:#F1F5F9;--text-sub:#94A3B8;--up:#34D399;--dn:#F87171;
    --touch-bg:#1E3A5F;--touch-cl:#93C5FD;
    --recl-bg:#052E16;--recl-cl:#34D399;
    --stop-bg:#450A0A;--stop-cl:#F87171;
    --hold-bg:#1E293B;--hold-cl:#94A3B8;
  }
}
:root[data-theme="dark"] {
  --bg:#0F172A;--bg2:#1E3A5F;--surface:#1E293B;--border:#334155;
  --blue:#60A5FA;--blue-lt:#93C5FD;--blue-dk:#BFDBFE;
  --text:#F1F5F9;--text-sub:#94A3B8;--up:#34D399;--dn:#F87171;
  --touch-bg:#1E3A5F;--touch-cl:#93C5FD;
  --recl-bg:#052E16;--recl-cl:#34D399;
  --stop-bg:#450A0A;--stop-cl:#F87171;
  --hold-bg:#1E293B;--hold-cl:#94A3B8;
}
:root[data-theme="light"] {
  --bg:#F8FAFF;--bg2:#EFF6FF;--surface:#FFFFFF;--border:#BFDBFE;
  --blue:#1D4ED8;--blue-lt:#3B82F6;--blue-dk:#1E3A5F;
  --text:#0F172A;--text-sub:#64748B;--up:#15803D;--dn:#B91C1C;
  --touch-bg:#EFF6FF;--touch-cl:#1D4ED8;
  --recl-bg:#F0FDF4;--recl-cl:#15803D;
  --stop-bg:#FEF2F2;--stop-cl:#B91C1C;
  --hold-bg:#F5F5F4;--hold-cl:#78716C;
}
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
body{
  font-family:'IBM Plex Sans KR','Noto Sans KR',sans-serif;
  background:var(--bg);color:var(--text);
  max-width:800px;margin:0 auto;padding:24px 16px 48px;
  font-size:15px;line-height:1.6;
}
.letter-header{
  border-top:4px solid var(--blue);
  background:var(--bg2);
  padding:20px 24px;border-radius:0 0 8px 8px;
  margin-bottom:28px;
}
.letter-header .series{
  font-size:11px;font-weight:700;letter-spacing:.12em;
  text-transform:uppercase;color:var(--blue);margin-bottom:4px;
}
.letter-header h1{font-size:1.4rem;font-weight:700;color:var(--text);margin-bottom:2px}
.letter-header .meta{font-size:12px;color:var(--text-sub)}
h2{
  font-size:1rem;font-weight:700;color:var(--blue-dk);
  border-left:3px solid var(--blue);padding-left:10px;
  margin:28px 0 12px;
}
.stat-row{
  display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin:12px 0;
}
@media(max-width:460px){.stat-row{grid-template-columns:repeat(2,1fr)}}
.stat-card{
  background:var(--surface);border:1px solid var(--border);
  border-radius:8px;padding:12px;text-align:center;
}
.stat-card .lbl{font-size:10px;color:var(--text-sub);letter-spacing:.04em;margin-bottom:2px}
.stat-card .val{font-size:1.3rem;font-weight:800;color:var(--text)}
.stat-card .sub{font-size:11px;color:var(--text-sub)}
table{width:100%;border-collapse:collapse;margin:12px 0;font-size:12px}
th{background:var(--bg2);color:var(--text-sub);font-weight:600;
   padding:8px 10px;text-align:left;font-size:11px;letter-spacing:.04em;
   border-bottom:2px solid var(--border)}
td{padding:8px 10px;border-bottom:1px solid var(--border)}
tr:last-child td{border-bottom:none}
.badge-touch{background:var(--touch-bg);color:var(--touch-cl);
  font-weight:700;font-size:10px;padding:2px 6px;border-radius:4px}
.badge-reclaim{background:var(--recl-bg);color:var(--recl-cl);
  font-weight:700;font-size:10px;padding:2px 6px;border-radius:4px}
.badge-stop{background:var(--stop-bg);color:var(--stop-cl);
  font-weight:700;font-size:10px;padding:2px 6px;border-radius:4px}
.badge-hold{background:var(--hold-bg);color:var(--hold-cl);
  font-weight:700;font-size:10px;padding:2px 6px;border-radius:4px}
.badge-new{background:#FEF9C3;color:#854D0E;
  font-weight:700;font-size:10px;padding:2px 6px;border-radius:4px}
.up{color:var(--up);font-weight:600}
.dn{color:var(--dn);font-weight:600}
.empty-note{
  text-align:center;padding:24px;color:var(--text-sub);
  font-size:13px;border:1px dashed var(--border);border-radius:8px;
}
.disclaimer{
  margin-top:40px;padding:12px 14px;border-radius:6px;
  background:var(--hold-bg);font-size:11px;color:var(--text-sub);line-height:1.5;
}
"""


def _fmt_pnl(pnl: float) -> str:
    cls = "up" if pnl >= 0 else "dn"
    return f'<span class="{cls}">{pnl:+.2f}%</span>'


def _fmt_days(days: int) -> str:
    if days >= 200:
        return f'<span style="color:var(--dn)">{days}일</span>'
    if days >= 150:
        return f'<span style="color:var(--gold,#D97706)">{days}일</span>'
    return f"{days}일"


def generate_b_weekly_letter(
    week_label: str,
    as_of_date: str,
    prev_as_of_date: str | None = None,
) -> str:
    """
    Generate HTML for B-axis weekly letter.

    week_label:     e.g. '2026-W47'
    as_of_date:     end-of-week date string 'YYYY-MM-DD'
    prev_as_of_date: prior week end date (to detect new entries / exits)
    """
    import sys, os as _os
    sys.path.insert(0, _os.path.dirname(_os.path.dirname(__file__)))
    from pullback_v3 import get_live_positions, load_all_cached_data

    # Load cached data (no network, parquet only)
    data = load_all_cached_data()

    cur_positions  = get_live_positions(data, as_of=as_of_date)
    prev_positions = get_live_positions(data, as_of=prev_as_of_date) if prev_as_of_date else None

    return _render_b_html(week_label, as_of_date, cur_positions, prev_positions)


def _render_b_html(
    week_label: str,
    as_of_date: str,
    cur: dict,
    prev: dict | None,
) -> str:
    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M")

    us_open = cur.get("us_open", [])
    kr_open = cur.get("kr_open", [])
    all_open = us_open + kr_open

    # Detect new entries and exits vs prior week
    new_tickers = set()
    exit_items  = []
    if prev:
        prev_keys = {(p["ticker"], p["signal_type"]) for p in prev.get("us_open", []) + prev.get("kr_open", [])}
        cur_keys  = {(p["ticker"], p["signal_type"]) for p in all_open}
        new_tickers = {k[0] for k in (cur_keys - prev_keys)}
        exited_keys = prev_keys - cur_keys
        for ek in exited_keys:
            exit_items.append({"ticker": ek[0], "signal_type": ek[1]})

    # Stats
    us_avg = cur.get("us_avg_pnl")
    kr_avg = cur.get("kr_avg_pnl")
    total  = cur.get("us_count", 0) + cur.get("kr_count", 0)

    stat_cards = f"""
<div class="stat-row">
  <div class="stat-card">
    <div class="lbl">활성 포지션</div>
    <div class="val">{total}</div>
    <div class="sub">US {cur.get('us_count',0)} + KR {cur.get('kr_count',0)}</div>
  </div>
  <div class="stat-card">
    <div class="lbl">US 평균 손익</div>
    <div class="val {'up' if (us_avg or 0) >= 0 else 'dn'}">{f'{us_avg:+.1f}%' if us_avg is not None else '-'}</div>
    <div class="sub">S&P500</div>
  </div>
  <div class="stat-card">
    <div class="lbl">KR 평균 손익</div>
    <div class="val {'up' if (kr_avg or 0) >= 0 else 'dn'}">{f'{kr_avg:+.1f}%' if kr_avg is not None else '-'}</div>
    <div class="sub">KOSPI200</div>
  </div>
  <div class="stat-card">
    <div class="lbl">신규 진입</div>
    <div class="val">{len(new_tickers)}</div>
    <div class="sub">이번 주</div>
  </div>
</div>
"""

    # Open positions table
    if not all_open:
        positions_html = '<div class="empty-note">현재 활성 포지션 없음</div>'
    else:
        rows = ""
        for p in sorted(all_open, key=lambda x: x["pnl_pct"], reverse=True):
            is_kr = ".KS" in p["ticker"]
            mkt   = "KR" if is_kr else "US"
            sym   = p["ticker"].replace(".KS", "")
            sig   = p["signal_type"]
            badge = f'<span class="badge-{sig}">{sig.upper()}</span>'
            isnew = p["ticker"] in new_tickers
            new_b = ' <span class="badge-new">NEW</span>' if isnew else ""
            ep    = p["entry_price"]
            cp    = p["current_price"]
            ep_fmt = f"{ep:,.2f}"
            cp_fmt = f"{cp:,.2f}"
            ma_gap = ""
            # Compute MA200 gap if available
            ma_v   = p.get("ma200")
            if ma_v and cp:
                gap_pct = (cp / ma_v - 1) * 100
                ma_gap  = f'<span class="{"up" if gap_pct >= 0 else "dn"}">{gap_pct:+.1f}%</span>'
            else:
                ma_gap = "-"
            rows += (
                f"<tr>"
                f"<td><strong>{sym}</strong>{new_b}<br><span style='font-size:10px;color:var(--text-sub)'>{mkt}</span></td>"
                f"<td style='text-align:center'>{badge}</td>"
                f"<td style='text-align:right'>{ep_fmt}</td>"
                f"<td style='text-align:right'>{cp_fmt}</td>"
                f"<td style='text-align:right'>{ma_gap}</td>"
                f"<td style='text-align:right'>{_fmt_pnl(p['pnl_pct'])}</td>"
                f"<td style='text-align:center'>{_fmt_days(p['days_held'])}</td>"
                f"</tr>"
            )
        positions_html = f"""
<div style="overflow-x:auto">
<table>
<thead><tr>
  <th>종목</th><th>신호</th><th>진입가</th><th>현재가</th>
  <th>MA200 괴리</th><th>손익</th><th>보유일</th>
</tr></thead>
<tbody>{rows}</tbody>
</table>
</div>
"""

    # Exits this week
    if exit_items:
        exit_rows = ""
        for ex in exit_items:
            sym = ex["ticker"].replace(".KS", "")
            sig = ex["signal_type"]
            exit_rows += (
                f"<tr><td><strong>{sym}</strong></td>"
                f"<td style='text-align:center'><span class='badge-{sig}'>{sig.upper()}</span></td>"
                f"<td>-</td></tr>"
            )
        exits_html = f"""
<div style="overflow-x:auto">
<table>
<thead><tr><th>종목</th><th>신호</th><th>청산 사유</th></tr></thead>
<tbody>{exit_rows}</tbody>
</table>
</div>
"""
    else:
        exits_html = '<div class="empty-note">이번 주 청산 없음</div>'

    return f"""<!DOCTYPE html>
<html lang='ko'>
<head>
<meta charset='utf-8'>
<meta name='viewport' content='width=device-width,initial-scale=1'>
<title>QuantLetter B — {week_label}</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Sans+KR:wght@400;600;700&display=swap" rel="stylesheet">
<style>{_CSS}</style>
</head>
<body>

<div class="letter-header">
  <div class="series">QuantLetter · B축 MA200 Pullback</div>
  <h1>{week_label} 주간 레터</h1>
  <div class="meta">기준일: {as_of_date} &nbsp;|&nbsp; 발행: {generated_at} &nbsp;|&nbsp; Pullback v3</div>
</div>

<h2>이번 주 요약</h2>
{stat_cards}

<h2>활성 포지션 ({total}건)</h2>
<p style="font-size:12px;color:var(--text-sub);margin-bottom:8px;">
  진입가 대비 현재 손익 &nbsp;|&nbsp; 보유 180일 이상 시 만기 임박
</p>
{positions_html}

<h2>이번 주 청산</h2>
{exits_html}

<div class="disclaimer">
  과거 데이터 기반 모의결과이며 미래 수익을 보장하지 않습니다.
  손절(-10%) / 만기(252거래일) 규칙 적용. 본 레터는 투자자문이 아닙니다.
  QuantMaster Pro — 내부 검토용
</div>

</body>
</html>
"""


def save_b_weekly_letter(week_label: str, as_of_date: str, prev_as_of_date: str | None = None) -> str:
    html  = generate_b_weekly_letter(week_label, as_of_date, prev_as_of_date)
    fname = f"{week_label}_B.html"
    path  = os.path.join(_REPORTS_DIR, fname)
    with open(path, "w", encoding="utf-8") as f:
        f.write(html)
    return path
