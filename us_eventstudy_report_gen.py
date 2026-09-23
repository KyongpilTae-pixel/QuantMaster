"""Generate HTML report for US event study results."""
import json, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

with open(r"C:\project\quant\us_eventstudy_results.json", encoding="utf-8") as f:
    d = json.load(f)

trades = d["trades"]
touch_all = [t for t in trades if t["type"] == "touch"]
reclaim_all = [t for t in trades if t["type"] == "reclaim"]

# Year breakdown
years = list(range(2019, 2026))
yr_touch = {yr: [t for t in touch_all if t["date"].startswith(str(yr))] for yr in years}
yr_reclaim = {yr: [t for t in reclaim_all if t["date"].startswith(str(yr))] for yr in years}

def stats(ts):
    ret12 = [t["ret12m"] for t in ts if t["ret12m"] is not None]
    if not ret12:
        return {"count": len(ts), "win_rate": None, "avg": None, "stop_rate": None}
    import numpy as np
    return {
        "count": len(ts),
        "win_rate": round(sum(1 for r in ret12 if r > 0)/len(ret12)*100, 1),
        "avg": round(float(np.mean(ret12)), 2),
        "stop_rate": round(sum(1 for t in ts if t["stop_hit"])/len(ts)*100, 1) if ts else None,
    }

# Top winners / losers
touch_with_ret = [t for t in touch_all if t["ret12m"] is not None]
touch_sorted_win = sorted(touch_with_ret, key=lambda x: x["ret12m"], reverse=True)[:10]
touch_sorted_lose = sorted(touch_with_ret, key=lambda x: x["ret12m"])[:10]

reclaim_with_ret = [t for t in reclaim_all if t["ret12m"] is not None]
reclaim_sorted_win = sorted(reclaim_with_ret, key=lambda x: x["ret12m"], reverse=True)[:10]

# Per-ticker summary
from collections import defaultdict
ticker_stats = defaultdict(lambda: {"touch": [], "reclaim": []})
for t in trades:
    if t["ret12m"] is not None:
        ticker_stats[t["ticker"]][t["type"]].append(t["ret12m"])

import numpy as np

def fmt_ret(v):
    if v is None: return "–"
    c = "#22c55e" if v > 0 else "#ef4444"
    return f'<span style="color:{c}">{v:+.1f}%</span>'

def yr_row(yr):
    ts = yr_touch[yr]
    rs = yr_reclaim[yr]
    ts_ret = [t["ret12m"] for t in ts if t["ret12m"] is not None]
    rs_ret = [t["ret12m"] for t in rs if t["ret12m"] is not None]
    t_wr = f"{round(sum(1 for r in ts_ret if r>0)/len(ts_ret)*100,1)}%" if ts_ret else "–"
    r_wr = f"{round(sum(1 for r in rs_ret if r>0)/len(rs_ret)*100,1)}%" if rs_ret else "–"
    t_avg = f"{np.mean(ts_ret):+.1f}%" if ts_ret else "–"
    r_avg = f"{np.mean(rs_ret):+.1f}%" if rs_ret else "–"
    t_stop = f"{round(sum(1 for t in ts if t['stop_hit'])/len(ts)*100,1)}%" if ts else "–"
    r_stop = f"{round(sum(1 for t in rs if t['stop_hit'])/len(rs)*100,1)}%" if rs else "–"
    return f"""<tr>
      <td class="yr">{yr}</td>
      <td>{len(ts)}</td><td>{t_wr}</td><td>{t_avg}</td><td>{t_stop}</td>
      <td class="sep"></td>
      <td>{len(rs)}</td><td>{r_wr}</td><td>{r_avg}</td><td>{r_stop}</td>
    </tr>"""

year_rows = "\n".join(yr_row(yr) for yr in years)

def trade_rows(ts_list):
    rows = []
    for t in ts_list[:20]:
        ret = t.get("ret12m")
        stop = "Y" if t["stop_hit"] else "–"
        ret_str = f"{ret:+.1f}%" if ret is not None else "–"
        c = "#22c55e" if ret and ret > 0 else "#ef4444"
        rows.append(f"""<tr>
          <td>{t['ticker']}</td>
          <td>{t['date']}</td>
          <td>{t['entry_price']:,.2f}</td>
          <td style="color:{c};font-weight:600">{ret_str}</td>
          <td>{t['mdd']:+.1f}%</td>
          <td style="color:{'#ef4444' if t['stop_hit'] else '#94a3b8'}">{stop}</td>
        </tr>""")
    return "\n".join(rows)

html = f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="utf-8">
<title>US Event Study — MA200 Touch/Reclaim (2019-2025)</title>
<style>
:root {{
  --bg: #0f172a; --bg2: #1e293b; --bg3: #334155;
  --text: #e2e8f0; --muted: #94a3b8;
  --green: #22c55e; --red: #ef4444; --blue: #38bdf8; --amber: #fbbf24;
}}
* {{ box-sizing: border-box; margin:0; padding:0; }}
body {{ background: var(--bg); color: var(--text); font-family: 'Segoe UI', system-ui, sans-serif; font-size:14px; padding:24px; }}
h1 {{ font-size:22px; font-weight:700; color: var(--blue); margin-bottom:4px; }}
.meta {{ color: var(--muted); font-size:12px; margin-bottom:24px; }}
h2 {{ font-size:14px; font-weight:600; color: var(--amber); margin:20px 0 10px; text-transform:uppercase; letter-spacing:.05em; }}
.cards {{ display:grid; grid-template-columns:1fr 1fr; gap:16px; margin-bottom:24px; }}
.card {{ background: var(--bg2); border-radius:10px; padding:20px; border:1px solid var(--bg3); }}
.card-title {{ font-size:11px; text-transform:uppercase; letter-spacing:.08em; color:var(--muted); margin-bottom:12px; }}
.kv {{ display:grid; grid-template-columns:1fr 1fr; gap:8px; }}
.kv-item label {{ font-size:11px; color:var(--muted); display:block; margin-bottom:2px; }}
.kv-item .val {{ font-size:18px; font-weight:700; }}
.pos {{ color: var(--green); }} .neg {{ color: var(--red); }} .neu {{ color: var(--blue); }}
table {{ width:100%; border-collapse:collapse; margin-bottom:20px; }}
th {{ font-size:11px; text-transform:uppercase; letter-spacing:.05em; color:var(--muted); padding:8px 10px; text-align:right; border-bottom:1px solid var(--bg3); }}
th:first-child, td:first-child {{ text-align:left; }}
td {{ padding:7px 10px; text-align:right; border-bottom:1px solid var(--bg3); font-variant-numeric:tabular-nums; }}
tr:last-child td {{ border-bottom:none; }}
.yr {{ color:var(--amber); font-weight:600; }}
.sep {{ width:16px; background:var(--bg); border:none; }}
.ref-box {{ background:var(--bg2); border:1px solid var(--bg3); border-left:3px solid var(--amber); border-radius:6px; padding:14px 16px; margin-bottom:20px; }}
.ref-box p {{ color:var(--muted); font-size:12px; line-height:1.6; }}
.ref-box strong {{ color:var(--text); }}
</style>
</head>
<body>
<h1>US Event Study — MA200 Touch / Reclaim</h1>
<div class="meta">Period: 2019-01-01 ~ 2025-12-31 &nbsp;|&nbsp; Universe: 79 S&P500 stocks (80 sampled, 1 failed) &nbsp;|&nbsp; Stop: −10% &nbsp;|&nbsp; Cooldown: 30d &nbsp;|&nbsp; Hold: 12M</div>

<div class="ref-box">
  <p><strong>Cloud reference (2013-2018, 470종목):</strong><br>
  Touch: Win 64.9%, Avg +7.9% &nbsp;|&nbsp; Reclaim: Win 64.5%, Avg +7.7%<br>
  → 2019-2025에는 COVID 2020 + Fed 긴축 2022 영향으로 승률 급감 / 손절율 상승, 그러나 승자 평균 수익률(~+40%)이 기대수익을 양수로 유지.</p>
</div>

<div class="cards">
  <div class="card">
    <div class="card-title">Touch (MA200 0~+5% 위)</div>
    <div class="kv">
      <div class="kv-item"><label>신호수</label><span class="val neu">{d['summary']['touch']['count']:,}</span></div>
      <div class="kv-item"><label>연간빈도</label><span class="val">{d['summary']['touch']['annual_freq']}/yr</span></div>
      <div class="kv-item"><label>12M 승률</label><span class="val {'pos' if d['summary']['touch']['win_rate_12m'] and d['summary']['touch']['win_rate_12m']>50 else 'neg'}">{d['summary']['touch']['win_rate_12m']}%</span></div>
      <div class="kv-item"><label>평균 12M</label><span class="val pos">{d['summary']['touch']['avg_ret_12m']:+.2f}%</span></div>
      <div class="kv-item"><label>중앙값 12M</label><span class="val neg">{d['summary']['touch']['median_ret_12m']:+.1f}%</span></div>
      <div class="kv-item"><label>평균 MDD</label><span class="val neg">{d['summary']['touch']['avg_mdd']:.1f}%</span></div>
      <div class="kv-item"><label>손절율</label><span class="val neg">{d['summary']['touch']['stop_rate']}%</span></div>
    </div>
  </div>
  <div class="card">
    <div class="card-title">Reclaim (MA200 하회 → 회복)</div>
    <div class="kv">
      <div class="kv-item"><label>신호수</label><span class="val neu">{d['summary']['reclaim']['count']:,}</span></div>
      <div class="kv-item"><label>연간빈도</label><span class="val">{d['summary']['reclaim']['annual_freq']}/yr</span></div>
      <div class="kv-item"><label>12M 승률</label><span class="val {'pos' if d['summary']['reclaim']['win_rate_12m'] and d['summary']['reclaim']['win_rate_12m']>50 else 'neg'}">{d['summary']['reclaim']['win_rate_12m']}%</span></div>
      <div class="kv-item"><label>평균 12M</label><span class="val pos">{d['summary']['reclaim']['avg_ret_12m']:+.2f}%</span></div>
      <div class="kv-item"><label>중앙값 12M</label><span class="val neg">{d['summary']['reclaim']['median_ret_12m']:+.1f}%</span></div>
      <div class="kv-item"><label>평균 MDD</label><span class="val neg">{d['summary']['reclaim']['avg_mdd']:.1f}%</span></div>
      <div class="kv-item"><label>손절율</label><span class="val neg">{d['summary']['reclaim']['stop_rate']}%</span></div>
    </div>
  </div>
</div>

<h2>연도별 신호 분포</h2>
<table>
  <thead>
    <tr>
      <th>연도</th>
      <th>Touch수</th><th>12M승률</th><th>평균12M</th><th>손절율</th>
      <th class="sep"></th>
      <th>Reclaim수</th><th>12M승률</th><th>평균12M</th><th>손절율</th>
    </tr>
  </thead>
  <tbody>
    {year_rows}
  </tbody>
</table>

<h2>Touch — Top 20 거래 (수익순)</h2>
<table>
  <thead><tr><th>Ticker</th><th style="text-align:left">진입일</th><th>진입가</th><th>12M수익</th><th>MDD</th><th>손절</th></tr></thead>
  <tbody>{trade_rows(touch_sorted_win)}</tbody>
</table>

<h2>Touch — 손절 하위 10</h2>
<table>
  <thead><tr><th>Ticker</th><th style="text-align:left">진입일</th><th>진입가</th><th>12M수익</th><th>MDD</th><th>손절</th></tr></thead>
  <tbody>{trade_rows(touch_sorted_lose)}</tbody>
</table>

<h2>Reclaim — Top 20 거래 (수익순)</h2>
<table>
  <thead><tr><th>Ticker</th><th style="text-align:left">진입일</th><th>진입가</th><th>12M수익</th><th>MDD</th><th>손절</th></tr></thead>
  <tbody>{trade_rows(reclaim_sorted_win)}</tbody>
</table>

<div class="meta" style="margin-top:24px">Generated: 2026-09-10 | Source: yfinance | MA200=200일 단순이동평균 | 수정주가 기준</div>
</body>
</html>"""

out = r"C:\project\quant\us_eventstudy_report_20260910.html"
with open(out, "w", encoding="utf-8") as f:
    f.write(html)
print(f"저장: {out}  ({len(html):,}bytes)")
