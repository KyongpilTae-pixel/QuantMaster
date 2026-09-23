"""Generate HTML report for US event study v2 results."""
import json, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
import numpy as np

with open(r"C:\project\quant\us_eventstudy_results_v2.json", encoding="utf-8") as f:
    d = json.load(f)

trades = d["trades"]
touch_all = [t for t in trades if t["type"] == "touch"]
reclaim_all = [t for t in trades if t["type"] == "reclaim"]

years = list(range(2019, 2026))

def yr_stats(sig_trades, yr):
    ts = [t for t in sig_trades if t["date"].startswith(str(yr))]
    ret12 = [t["ret12m"] for t in ts if t["ret12m"] is not None]
    if not ret12:
        return {"n": len(ts), "wr": "–", "avg": "–", "stop": "–"}
    wr = round(sum(1 for r in ret12 if r > 0) / len(ret12) * 100, 1)
    avg = round(float(np.mean(ret12)), 1)
    stop_r = round(sum(1 for t in ts if t["stop_hit"]) / len(ts) * 100, 1) if ts else 0
    return {"n": len(ts), "wr": f"{wr}%", "avg": f"{avg:+.1f}%", "stop": f"{stop_r}%"}

def color_avg(v):
    try:
        num = float(v.replace("+", "").replace("%", ""))
        c = "#22c55e" if num > 0 else "#ef4444" if num < 0 else "#94a3b8"
        return f'<span style="color:{c}">{v}</span>'
    except:
        return f'<span style="color:#94a3b8">{v}</span>'

def yr_row(yr):
    ts = yr_stats(touch_all, yr)
    rs = yr_stats(reclaim_all, yr)
    note = ""
    if yr == 2025:
        note = '<sup title="2025년: 대부분 12M창 미완성 (ret12m=None 제외됨)">*</sup>'
    return f"""<tr>
      <td class="yr">{yr}{note}</td>
      <td>{ts['n']}</td><td>{ts['wr']}</td><td>{color_avg(ts['avg'])}</td><td>{ts['stop']}</td>
      <td class="sep"></td>
      <td>{rs['n']}</td><td>{rs['wr']}</td><td>{color_avg(rs['avg'])}</td><td>{rs['stop']}</td>
    </tr>"""

year_rows = "\n".join(yr_row(yr) for yr in years)

# Top winners
def top_trades(sig_list, n=15):
    with_ret = [t for t in sig_list if t["ret12m"] is not None]
    return sorted(with_ret, key=lambda x: x["ret12m"], reverse=True)[:n]

def trade_rows(ts_list):
    rows = []
    for t in ts_list:
        ret = t.get("ret12m")
        stop = "Y" if t["stop_hit"] else "–"
        ret_str = f"{ret:+.1f}%" if ret is not None else "–"
        c = "#22c55e" if ret and ret > 0 else "#ef4444"
        rows.append(f"""<tr>
          <td>{t['ticker']}</td>
          <td>{t['date']}</td>
          <td>${t['entry_price']:,.2f}</td>
          <td style="color:{c};font-weight:600">{ret_str}</td>
          <td>{t['mdd']:+.1f}%</td>
          <td style="color:{'#ef4444' if t['stop_hit'] else '#94a3b8'}">{stop}</td>
        </tr>""")
    return "\n".join(rows)

sm = d["summary"]
html = f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="utf-8">
<title>US Event Study — MA200 Touch/Reclaim 2019-2025</title>
<style>
:root {{
  --bg: #0f172a; --bg2: #1e293b; --bg3: #334155;
  --text: #e2e8f0; --muted: #94a3b8;
  --green: #22c55e; --red: #ef4444; --blue: #38bdf8; --amber: #fbbf24;
}}
* {{ box-sizing: border-box; margin:0; padding:0; }}
body {{ background: var(--bg); color: var(--text); font-family: 'Segoe UI', system-ui, sans-serif; font-size:14px; padding:24px; max-width:1100px; }}
h1 {{ font-size:22px; font-weight:700; color: var(--blue); margin-bottom:4px; }}
.meta {{ color: var(--muted); font-size:12px; margin-bottom:20px; }}
h2 {{ font-size:13px; font-weight:600; color: var(--amber); margin:20px 0 10px; text-transform:uppercase; letter-spacing:.05em; }}
.cards {{ display:grid; grid-template-columns:1fr 1fr; gap:16px; margin-bottom:20px; }}
.card {{ background: var(--bg2); border-radius:10px; padding:18px; border:1px solid var(--bg3); }}
.card-title {{ font-size:11px; text-transform:uppercase; letter-spacing:.08em; color:var(--muted); margin-bottom:12px; }}
.kv {{ display:grid; grid-template-columns:1fr 1fr; gap:8px; }}
.kv-item label {{ font-size:11px; color:var(--muted); display:block; margin-bottom:2px; }}
.kv-item .val {{ font-size:17px; font-weight:700; }}
.pos {{ color: var(--green); }} .neg {{ color: var(--red); }} .neu {{ color: var(--blue); }}
table {{ width:100%; border-collapse:collapse; margin-bottom:16px; overflow-x:auto; }}
th {{ font-size:11px; text-transform:uppercase; letter-spacing:.04em; color:var(--muted); padding:7px 8px; text-align:right; border-bottom:1px solid var(--bg3); white-space:nowrap; }}
th:first-child, td:first-child {{ text-align:left; }}
td {{ padding:6px 8px; text-align:right; border-bottom:1px solid var(--bg3); font-variant-numeric:tabular-nums; font-size:13px; }}
tr:hover td {{ background: rgba(255,255,255,.03); }}
tr:last-child td {{ border-bottom:none; }}
.yr {{ color:var(--amber); font-weight:600; }}
.sep {{ width:12px; background:var(--bg); border:none !important; }}
.ref-box {{ background:var(--bg2); border:1px solid var(--bg3); border-left:3px solid var(--amber); border-radius:6px; padding:12px 14px; margin-bottom:20px; }}
.ref-box p {{ color:var(--muted); font-size:12px; line-height:1.7; }}
.ref-box strong {{ color:var(--text); }}
.note {{ color:var(--muted); font-size:11px; margin-top:6px; }}
</style>
</head>
<body>
<h1>US Event Study — MA200 Touch / Reclaim</h1>
<div class="meta">Period: 2019-01-01 ~ 2025-12-31 &nbsp;|&nbsp; Universe: 79 S&P500 (80 sampled, MMC 실패) &nbsp;|&nbsp; Stop: −10% &nbsp;|&nbsp; Cooldown: 30d &nbsp;|&nbsp; Hold: 12M &nbsp;|&nbsp; Source: yfinance auto_adjust=True</div>

<div class="ref-box">
  <p><strong>Cloud reference (2013-2018, 470종목):</strong>
  Touch Win 64.9% / Avg +7.9% &nbsp;|&nbsp; Reclaim Win 64.5% / Avg +7.7%</p>
  <p>→ 2019-2025에는 COVID 2020 + Fed 긴축 2022 등 2회의 주요 약세장 포함. 승률 급감(65%→37%)하나 평균수익은 양수 유지. 2025년 수치는 대부분 12M창 미완성 데이터(ret12m=None 제외)로 참고용.</p>
</div>

<div class="cards">
  <div class="card">
    <div class="card-title">Touch — MA200 0~+5% 위</div>
    <div class="kv">
      <div class="kv-item"><label>신호 총수</label><span class="val neu">{sm['touch']['count']:,}</span></div>
      <div class="kv-item"><label>연간 빈도</label><span class="val">{sm['touch']['annual_freq']}/yr</span></div>
      <div class="kv-item"><label>12M 승률</label><span class="val neg">{sm['touch']['win_rate_12m']}%</span></div>
      <div class="kv-item"><label>평균 12M</label><span class="val pos">{sm['touch']['avg_ret_12m']:+.2f}%</span></div>
      <div class="kv-item"><label>중앙값 12M</label><span class="val neg">{sm['touch']['median_ret_12m']:+.1f}%</span></div>
      <div class="kv-item"><label>평균 MDD</label><span class="val neg">{sm['touch']['avg_mdd']:.1f}%</span></div>
      <div class="kv-item"><label>손절율</label><span class="val neg">{sm['touch']['stop_rate']}%</span></div>
    </div>
  </div>
  <div class="card">
    <div class="card-title">Reclaim — MA200 하회→회복</div>
    <div class="kv">
      <div class="kv-item"><label>신호 총수</label><span class="val neu">{sm['reclaim']['count']:,}</span></div>
      <div class="kv-item"><label>연간 빈도</label><span class="val">{sm['reclaim']['annual_freq']}/yr</span></div>
      <div class="kv-item"><label>12M 승률</label><span class="val neg">{sm['reclaim']['win_rate_12m']}%</span></div>
      <div class="kv-item"><label>평균 12M</label><span class="val pos">{sm['reclaim']['avg_ret_12m']:+.2f}%</span></div>
      <div class="kv-item"><label>중앙값 12M</label><span class="val neg">{sm['reclaim']['median_ret_12m']:+.1f}%</span></div>
      <div class="kv-item"><label>평균 MDD</label><span class="val neg">{sm['reclaim']['avg_mdd']:.1f}%</span></div>
      <div class="kv-item"><label>손절율</label><span class="val neg">{sm['reclaim']['stop_rate']}%</span></div>
    </div>
  </div>
</div>

<h2>연도별 신호 분포</h2>
<div style="overflow-x:auto">
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
</div>
<div class="note">* 2025년: 12M창 미완성(ret12m=None) 제외 후 통계. 손절 조기 발생 건만 포함되어 승률 과소 추정.</div>

<h2>Touch — Top 15 수익 거래</h2>
<div style="overflow-x:auto">
<table>
  <thead><tr><th>Ticker</th><th style="text-align:left">진입일</th><th>진입가</th><th>12M수익</th><th>MDD</th><th>손절</th></tr></thead>
  <tbody>{trade_rows(top_trades(touch_all))}</tbody>
</table>
</div>

<h2>Reclaim — Top 15 수익 거래</h2>
<div style="overflow-x:auto">
<table>
  <thead><tr><th>Ticker</th><th style="text-align:left">진입일</th><th>진입가</th><th>12M수익</th><th>MDD</th><th>손절</th></tr></thead>
  <tbody>{trade_rows(top_trades(reclaim_all))}</tbody>
</table>
</div>

<div class="meta" style="margin-top:24px">Generated: 2026-09-10 | cloud-002 REPLY 첨부 | v2 (배치 다운로드, 데이터오염 수정)</div>
</body>
</html>"""

out = r"C:\project\quant\us_eventstudy_report_v2_20260910.html"
with open(out, "w", encoding="utf-8") as f:
    f.write(html)
print(f"저장: {out}  ({len(html):,}bytes)")
