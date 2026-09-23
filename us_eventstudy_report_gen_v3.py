"""Generate HTML report for US event study v3 (with growth gate)."""
import json, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
import numpy as np

with open(r"C:\project\quant\us_eventstudy_results_v3.json", encoding="utf-8") as f:
    d = json.load(f)

trades = d["trades"]
touch_all = [t for t in trades if t["type"] == "touch"]
reclaim_all = [t for t in trades if t["type"] == "reclaim"]
sm = d["summary"]

CLOUD_REF = {
    "touch": {"win": 64.9, "avg": 7.9, "median": 7.0, "mdd": -13.2, "stop": 50.0},
    "reclaim": {"win": 64.5, "avg": 7.7, "median": None, "mdd": -13.7, "stop": 51.0},
}

def yr_row(yr):
    tc = [x for x in touch_all if x["date"].startswith(str(yr))]
    rc = [x for x in reclaim_all if x["date"].startswith(str(yr))]
    def s(lst):
        ret = [x["ret12m"] for x in lst]
        if not ret: return ("–","–","–")
        wr = f"{round(sum(1 for r in ret if r>0)/len(ret)*100,1)}%"
        avg = f"{np.mean(ret):+.1f}%"
        stop = f"{round(sum(1 for x in lst if x['stop_hit'])/len(lst)*100,1)}%"
        return (wr, avg, stop)
    tw, ta, ts = s(tc); rw, ra, rs = s(rc)
    def ca(v):
        try:
            n=float(v.replace("+","").replace("%",""))
            c="#22c55e" if n>0 else "#ef4444" if n<0 else "#94a3b8"
            return f'<span style="color:{c}">{v}</span>'
        except: return v
    return f"""<tr><td class="yr">{yr}</td>
      <td>{len(tc)}</td><td>{tw}</td><td>{ca(ta)}</td><td>{ts}</td>
      <td class="sep"></td>
      <td>{len(rc)}</td><td>{rw}</td><td>{ca(ra)}</td><td>{rs}</td></tr>"""

year_rows = "\n".join(yr_row(yr) for yr in range(2019, 2025))

def top_rows(sig_list, n=12):
    s = sorted(sig_list, key=lambda x: x["ret12m"], reverse=True)[:n]
    rows = []
    for t in s:
        c = "#22c55e" if t["ret12m"] > 0 else "#ef4444"
        stop_s = "Y" if t["stop_hit"] else "–"
        rows.append(f"""<tr><td>{t['ticker']}</td><td>{t['date']}</td>
          <td>${t['entry_price']:,.2f}</td>
          <td style="color:{c};font-weight:600">{t['ret12m']:+.1f}%</td>
          <td>{t['mdd']:+.1f}%</td>
          <td style="color:{'#ef4444' if t['stop_hit'] else '#94a3b8'}">{stop_s}</td></tr>""")
    return "\n".join(rows)

def delta(v1, v2, reverse=False):
    """colored delta (v1=local, v2=cloud_ref)"""
    if v2 is None: return "–"
    d = v1 - v2
    better = d > 0 if not reverse else d < 0
    c = "#22c55e" if better else "#ef4444"
    return f'<span style="color:{c}">{d:+.1f}%</span>'

html = f"""<!DOCTYPE html>
<html lang="ko"><head><meta charset="utf-8">
<title>US Event Study v3 — Growth Gate (2019-2024)</title>
<style>
:root{{--bg:#0f172a;--bg2:#1e293b;--bg3:#334155;--text:#e2e8f0;--muted:#94a3b8;
  --green:#22c55e;--red:#ef4444;--blue:#38bdf8;--amber:#fbbf24;}}
*{{box-sizing:border-box;margin:0;padding:0}}
body{{background:var(--bg);color:var(--text);font-family:'Segoe UI',system-ui,sans-serif;font-size:14px;padding:24px;max-width:1100px}}
h1{{font-size:21px;font-weight:700;color:var(--blue);margin-bottom:4px}}
.meta{{color:var(--muted);font-size:12px;margin-bottom:20px}}
h2{{font-size:13px;font-weight:600;color:var(--amber);margin:20px 0 10px;text-transform:uppercase;letter-spacing:.05em}}
.cards{{display:grid;grid-template-columns:1fr 1fr;gap:16px;margin-bottom:20px}}
.card{{background:var(--bg2);border-radius:10px;padding:18px;border:1px solid var(--bg3)}}
.ct{{font-size:11px;text-transform:uppercase;letter-spacing:.08em;color:var(--muted);margin-bottom:12px}}
.kv{{display:grid;grid-template-columns:1fr 1fr;gap:8px}}
.kv label{{font-size:11px;color:var(--muted);display:block;margin-bottom:2px}}
.kv .val{{font-size:17px;font-weight:700}}
.pos{{color:var(--green)}}.neg{{color:var(--red)}}.neu{{color:var(--blue)}}
table{{width:100%;border-collapse:collapse;margin-bottom:14px}}
th{{font-size:11px;text-transform:uppercase;color:var(--muted);padding:7px 8px;text-align:right;border-bottom:1px solid var(--bg3);white-space:nowrap}}
th:first-child,td:first-child{{text-align:left}}
td{{padding:6px 8px;text-align:right;border-bottom:1px solid var(--bg3);font-variant-numeric:tabular-nums;font-size:13px}}
tr:hover td{{background:rgba(255,255,255,.03)}}
tr:last-child td{{border-bottom:none}}
.yr{{color:var(--amber);font-weight:600}}
.sep{{width:10px;background:var(--bg);border:none!important}}
.ref-box{{background:var(--bg2);border:1px solid var(--bg3);border-left:3px solid var(--amber);border-radius:6px;padding:12px 14px;margin-bottom:18px}}
.ref-box p{{color:var(--muted);font-size:12px;line-height:1.7}}
.ref-box strong{{color:var(--text)}}
.compare-table td,.compare-table th{{text-align:center}}
.compare-table td:first-child,.compare-table th:first-child{{text-align:left}}
</style></head><body>
<h1>US Event Study v3 — MA200 Touch / Reclaim + Growth Gate</h1>
<div class="meta">Period: 2019-01-01 ~ 2024-12-31 (12M완성 신호만) &nbsp;|&nbsp;
Universe: 79 S&P500 &nbsp;|&nbsp; Growth Gate: ratio250≥70% AND MA200↑ &nbsp;|&nbsp;
Stop: −10% / Cooldown: 30d / Hold: 12M</div>

<div class="ref-box">
  <p><strong>Cloud reference (2013-2018, 470종목, 동일 성장게이트):</strong><br>
  Touch: Win 64.9%, Avg +7.9%, Median +7.0%, MDD −13.2%, Stop 50%<br>
  Reclaim: Win 64.5%, Avg +7.7%, MDD −13.7%, Stop 51%<br>
  → 2019-2024: 2회 약세장(COVID 2020, Fed긴축 2022) 포함. 승률·평균수익 하락, 손절율 상승. 성장 게이트 적용 후에도 구조적 차이 지속.</p>
</div>

<div class="cards">
  <div class="card">
    <div class="ct">Touch — MA200 0~+5% 위 (성장게이트 적용)</div>
    <div class="kv">
      <div><label>신호수</label><span class="val neu">{sm['touch']['count']}</span></div>
      <div><label>연간 빈도(전체)</label><span class="val">{sm['touch']['annual_freq_total']}/yr</span></div>
      <div><label>종목당</label><span class="val">{sm['touch']['annual_freq_per_ticker']}/yr</span></div>
      <div><label>Top10 바스켓</label><span class="val neu">{sm['touch']['annual_freq_top10']}/yr</span></div>
      <div><label>12M 승률</label><span class="val neg">{sm['touch']['win_rate_12m']}%</span></div>
      <div><label>평균 12M</label><span class="val pos">{sm['touch']['avg_ret_12m']:+.2f}%</span></div>
      <div><label>중앙값 12M</label><span class="val neg">{sm['touch']['median_ret_12m']:+.1f}%</span></div>
      <div><label>평균 MDD</label><span class="val neg">{sm['touch']['avg_mdd']:.1f}%</span></div>
      <div><label>손절율</label><span class="val neg">{sm['touch']['stop_rate']}%</span></div>
    </div>
  </div>
  <div class="card">
    <div class="ct">Reclaim — MA200 하회→회복 (성장게이트 적용)</div>
    <div class="kv">
      <div><label>신호수</label><span class="val neu">{sm['reclaim']['count']}</span></div>
      <div><label>연간 빈도(전체)</label><span class="val">{sm['reclaim']['annual_freq_total']}/yr</span></div>
      <div><label>종목당</label><span class="val">{sm['reclaim']['annual_freq_per_ticker']}/yr</span></div>
      <div><label>Top10 바스켓</label><span class="val neu">{sm['reclaim']['annual_freq_top10']}/yr</span></div>
      <div><label>12M 승률</label><span class="val neg">{sm['reclaim']['win_rate_12m']}%</span></div>
      <div><label>평균 12M</label><span class="val pos">{sm['reclaim']['avg_ret_12m']:+.2f}%</span></div>
      <div><label>중앙값 12M</label><span class="val neg">{sm['reclaim']['median_ret_12m']:+.1f}%</span></div>
      <div><label>평균 MDD</label><span class="val neg">{sm['reclaim']['avg_mdd']:.1f}%</span></div>
      <div><label>손절율</label><span class="val neg">{sm['reclaim']['stop_rate']}%</span></div>
    </div>
  </div>
</div>

<h2>Cloud 참고값 vs Local 비교 (v3)</h2>
<div style="overflow-x:auto"><table class="compare-table">
  <thead><tr><th>지표</th>
    <th>Cloud Touch (2013-18)</th><th>Local Touch (2019-24)</th><th>△Touch</th>
    <th class="sep"></th>
    <th>Cloud Reclaim (2013-18)</th><th>Local Reclaim (2019-24)</th><th>△Reclaim</th>
  </tr></thead>
  <tbody>
    <tr><td>12M 승률</td>
      <td>64.9%</td><td class="neg">{sm['touch']['win_rate_12m']}%</td><td>{delta(sm['touch']['win_rate_12m'],64.9)}</td>
      <td class="sep"></td>
      <td>64.5%</td><td class="neg">{sm['reclaim']['win_rate_12m']}%</td><td>{delta(sm['reclaim']['win_rate_12m'],64.5)}</td>
    </tr>
    <tr><td>평균 12M</td>
      <td>+7.9%</td><td class="pos">{sm['touch']['avg_ret_12m']:+.2f}%</td><td>{delta(sm['touch']['avg_ret_12m'],7.9)}</td>
      <td class="sep"></td>
      <td>+7.7%</td><td class="pos">{sm['reclaim']['avg_ret_12m']:+.2f}%</td><td>{delta(sm['reclaim']['avg_ret_12m'],7.7)}</td>
    </tr>
    <tr><td>중앙값 12M</td>
      <td>+7.0%</td><td class="neg">{sm['touch']['median_ret_12m']:+.1f}%</td><td>{delta(sm['touch']['median_ret_12m'],7.0)}</td>
      <td class="sep"></td>
      <td>–</td><td class="neg">{sm['reclaim']['median_ret_12m']:+.1f}%</td><td>–</td>
    </tr>
    <tr><td>평균 MDD</td>
      <td>−13.2%</td><td class="neg">{sm['touch']['avg_mdd']:.1f}%</td><td>{delta(sm['touch']['avg_mdd'],-13.2,reverse=True)}</td>
      <td class="sep"></td>
      <td>−13.7%</td><td class="neg">{sm['reclaim']['avg_mdd']:.1f}%</td><td>{delta(sm['reclaim']['avg_mdd'],-13.7,reverse=True)}</td>
    </tr>
    <tr><td>손절율</td>
      <td>50.0%</td><td class="neg">{sm['touch']['stop_rate']}%</td><td>{delta(sm['touch']['stop_rate'],50.0,reverse=True)}</td>
      <td class="sep"></td>
      <td>51.0%</td><td class="neg">{sm['reclaim']['stop_rate']}%</td><td>{delta(sm['reclaim']['stop_rate'],51.0,reverse=True)}</td>
    </tr>
  </tbody>
</table></div>

<h2>연도별 분포 (2019-2024)</h2>
<div style="overflow-x:auto"><table>
  <thead><tr><th>연도</th>
    <th>Touch수</th><th>12M승률</th><th>평균12M</th><th>손절율</th>
    <th class="sep"></th>
    <th>Reclaim수</th><th>12M승률</th><th>평균12M</th><th>손절율</th>
  </tr></thead>
  <tbody>{year_rows}</tbody>
</table></div>

<h2>Touch — Top 12 수익 거래</h2>
<div style="overflow-x:auto"><table>
  <thead><tr><th>Ticker</th><th style="text-align:left">진입일</th><th>진입가</th><th>12M수익</th><th>MDD</th><th>손절</th></tr></thead>
  <tbody>{top_rows(touch_all)}</tbody>
</table></div>

<h2>Reclaim — Top 12 수익 거래</h2>
<div style="overflow-x:auto"><table>
  <thead><tr><th>Ticker</th><th style="text-align:left">진입일</th><th>진입가</th><th>12M수익</th><th>MDD</th><th>손절</th></tr></thead>
  <tbody>{top_rows(reclaim_all)}</tbody>
</table></div>

<div class="meta" style="margin-top:24px">
v3 (성장게이트 적용, 12M완성만) | 2026-09-11 | cloud-002 REPLY v2 첨부
</div></body></html>"""

out = r"C:\project\quant\us_eventstudy_report_v3_20260911.html"
with open(out, "w", encoding="utf-8") as f:
    f.write(html)
print(f"저장: {out}  ({len(html):,}bytes)")
