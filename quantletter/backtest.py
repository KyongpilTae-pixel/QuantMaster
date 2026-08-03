# -*- coding: utf-8 -*-
"""
퀀트레터 모멘텀 전략 백테스트
==============================
- 한국(KOSPI 40종목) / 미국(S&P500 대형주 20종목) 각각 백테스트
- 파라미터 스윕: 룩백(3·6·12개월) × 상위 N(3·5·10종목) = 18 설정
- 벤치마크 대비 CAGR·MDD·샤프 비교
- 결과를 backtest_kr.html / backtest_us.html 로 저장

사용
  python backtest.py          # KR + US 모두
  python backtest.py kr       # 한국만
  python backtest.py us       # 미국만

필요 파일 (없으면 안내 메시지)
  kr_stocks_5yr.csv   ← python fetch_kr_stocks.py
  all_stocks_5yr.csv  ← python fetch_sample_data.py
  d_kospi.csv / d_spx.csv
"""
import os
import sys
import json
from datetime import datetime

import numpy as np
import pandas as pd

# ── 설정 ──────────────────────────────────────────────────────
LOOKBACKS   = [3, 6, 12]        # 월
TOP_NS      = [3, 5, 10]        # 보유 종목 수
TX_COST     = 0.0015            # 편도 거래비용 (0.15%)
REPORT_DATE = datetime.today().strftime("%Y-%m-%d")


# ── 데이터 로드 ───────────────────────────────────────────────

def load_data(market: str):
    if market == "KR":
        stock_csv = "kr_stocks_5yr.csv"
        bench_csv = "d_kospi.csv"
        bench_col = "kospi"
        fetch_cmd = "python fetch_kr_stocks.py"
    else:
        stock_csv = "all_stocks_5yr.csv"
        bench_csv = "d_spx.csv"
        bench_col = "spx"
        fetch_cmd = "python fetch_sample_data.py"

    if not os.path.exists(stock_csv):
        print(f"[오류] {stock_csv} 없음 — {fetch_cmd} 를 먼저 실행하세요.")
        return None, None

    df     = pd.read_csv(stock_csv, parse_dates=["date"], dtype={"Name": str})
    prices = df.pivot(index="date", columns="Name", values="close").sort_index()
    bench  = pd.read_csv(bench_csv, index_col=0, parse_dates=True)[bench_col]
    bench  = bench.reindex(prices.index, method="ffill").dropna()

    return prices, bench


# ── 단일 백테스트 ─────────────────────────────────────────────

def run_backtest(prices: pd.DataFrame, bench: pd.Series,
                 lookback_m: int, top_n: int,
                 tx_cost: float = TX_COST):
    """
    월말 리밸런싱 모멘텀 전략.
    lookback_m 개월 수익률 상위 top_n 종목을 동일비중 보유.
    """
    LOOKBACK_DAYS = lookback_m * 21

    month_ends = prices.resample("ME").last().index

    port_rets   = []
    bench_rets  = []
    dates       = []
    picks_log   = []
    prev_hold   = set()

    for i in range(len(month_ends) - 1):
        t0 = month_ends[i]
        t1 = month_ends[i + 1]

        # 룩백 기간 확보 확인
        hist = prices[prices.index <= t0]
        if len(hist) < LOOKBACK_DAYS + 5:
            continue

        # 모멘텀 계산 (t0 기준 lookback 전 대비 현재)
        mom = {}
        for col in hist.columns:
            s = hist[col].dropna()
            if len(s) >= LOOKBACK_DAYS:
                mom[col] = float(s.iloc[-1] / s.iloc[-LOOKBACK_DAYS] - 1)

        if len(mom) < top_n:
            continue

        ranked   = sorted(mom.items(), key=lambda x: x[1], reverse=True)
        selected = [tk for tk, _ in ranked[:top_n]]

        # 턴오버 추정 → 거래비용
        new_set  = set(selected)
        changed  = len(new_set - prev_hold) if prev_hold else top_n
        turnover = changed / top_n
        prev_hold = new_set

        # t0 → t1 종목 수익률
        p0 = prices.loc[prices.index <= t0].iloc[-1]
        p1 = prices.loc[prices.index <= t1].iloc[-1]

        rets = []
        for s in selected:
            if s in p0 and s in p1 and p0[s] > 0 and p1[s] > 0:
                rets.append(float(p1[s] / p0[s] - 1))

        if not rets:
            continue

        port_ret  = np.mean(rets) - turnover * tx_cost * 2
        bench_ret = float(bench[bench.index <= t1].iloc[-1] /
                          bench[bench.index <= t0].iloc[-1] - 1)

        port_rets.append(port_ret)
        bench_rets.append(bench_ret)
        dates.append(t1)
        picks_log.append({
            "date":    t1.strftime("%Y-%m"),
            "picks":   selected,
            "ret_pct": round(port_ret * 100, 2),
            "bench_pct": round(bench_ret * 100, 2),
        })

    if len(port_rets) < 6:
        return None

    port  = pd.Series(port_rets,  index=dates)
    bench_s = pd.Series(bench_rets, index=dates)

    def metrics(r: pd.Series) -> dict:
        n_yr  = len(r) / 12
        cagr  = float((1 + r).prod() ** (1 / n_yr) - 1)
        vol   = float(r.std() * np.sqrt(12))
        sharpe = cagr / vol if vol > 0 else 0.0
        cum    = (1 + r).cumprod()
        mdd    = float(((cum - cum.cummax()) / cum.cummax()).min())
        total  = float((1 + r).prod() - 1)
        hit    = int((r > bench_s).sum())
        return dict(cagr=cagr, vol=vol, sharpe=sharpe, mdd=mdd,
                    total=total, n_months=len(r), hit=hit)

    return {
        "port":          port,
        "bench":         bench_s,
        "cum_port":      (1 + port).cumprod(),
        "cum_bench":     (1 + bench_s).cumprod(),
        "port_m":        metrics(port),
        "bench_m":       metrics(bench_s),
        "picks_log":     picks_log,
        "lookback_m":    lookback_m,
        "top_n":         top_n,
    }


# ── 파라미터 스윕 ─────────────────────────────────────────────

def sweep(prices, bench):
    results = {}
    for lb in LOOKBACKS:
        for tn in TOP_NS:
            r = run_backtest(prices, bench, lb, tn)
            if r:
                results[(lb, tn)] = r
    return results


# ── SVG 차트 ──────────────────────────────────────────────────

def svg_chart(cum_port: pd.Series, cum_bench: pd.Series,
              width=560, height=240) -> str:
    df = pd.DataFrame({"port": cum_port, "bench": cum_bench}).dropna()
    if df.empty:
        return ""

    y_all  = df.values.flatten()
    y_min  = max(0.3, y_all.min() * 0.93)
    y_max  = y_all.max() * 1.07
    x_min  = df.index[0]
    x_max  = df.index[-1]
    days   = max((x_max - x_min).days, 1)

    PL, PR, PT, PB = 50, 10, 12, 28

    def px(d, v):
        x = PL + (d - x_min).days / days * (width - PL - PR)
        y = PT + (height - PT - PB) * (1 - (v - y_min) / (y_max - y_min))
        return round(x, 1), round(y, 1)

    lines = []

    # Horizontal grid
    grid_vals = [v / 10 for v in range(int(y_min * 10), int(y_max * 10) + 2)
                 if v % 5 == 0 and y_min <= v / 10 <= y_max]
    for yv in grid_vals:
        _, gy = px(x_min, yv)
        lines.append(
            f'<line x1="{PL}" y1="{gy}" x2="{width-PR}" y2="{gy}" '
            f'stroke="#e6ebf1" stroke-width="1"/>'
        )
        pct = f"{(yv-1)*100:+.0f}%"
        lines.append(
            f'<text x="{PL-4}" y="{gy+4}" text-anchor="end" '
            f'font-size="9" fill="#8090a0">{pct}</text>'
        )

    # Year ticks on x-axis
    seen = set()
    for d in df.index:
        yr = d.year
        if yr not in seen:
            seen.add(yr)
            gx, _ = px(d, y_min)
            gy = height - PB + 12
            lines.append(
                f'<text x="{gx}" y="{gy}" text-anchor="middle" '
                f'font-size="9" fill="#8090a0">{yr}</text>'
            )

    # Benchmark (dashed grey)
    pts_b = " ".join(f"{px(d,v)[0]},{px(d,v)[1]}" for d, v in df["bench"].items())
    lines.append(
        f'<polyline points="{pts_b}" fill="none" stroke="#b0bec8" '
        f'stroke-width="1.5" stroke-dasharray="4,3"/>'
    )

    # Strategy (solid blue)
    pts_p = " ".join(f"{px(d,v)[0]},{px(d,v)[1]}" for d, v in df["port"].items())
    lines.append(
        f'<polyline points="{pts_p}" fill="none" stroke="#2b6fb3" stroke-width="2.5"/>'
    )

    # Legend
    lx, ly = PL + 5, PT + 14
    lines += [
        f'<line x1="{lx}" y1="{ly}" x2="{lx+20}" y2="{ly}" stroke="#2b6fb3" stroke-width="2.5"/>',
        f'<text x="{lx+24}" y="{ly+4}" font-size="10" fill="#33475b">모멘텀 전략</text>',
        f'<line x1="{lx+90}" y1="{ly}" x2="{lx+110}" y2="{ly}" stroke="#b0bec8" stroke-width="1.5" stroke-dasharray="4,3"/>',
        f'<text x="{lx+114}" y="{ly+4}" font-size="10" fill="#33475b">벤치마크</text>',
    ]

    return (
        f'<svg viewBox="0 0 {width} {height}" width="100%" '
        f'xmlns="http://www.w3.org/2000/svg">{"".join(lines)}</svg>'
    )


# ── HTML 리포트 ───────────────────────────────────────────────

_CSS = """<style>
body{margin:0;background:#eef1f5;font-family:'Apple SD Gothic Neo','Malgun Gothic',system-ui,sans-serif;color:#1c2430;line-height:1.6}
.wrap{max-width:720px;margin:0 auto;padding:28px 16px}
.hd{background:linear-gradient(135deg,#12233b,#1b3a6b);color:#fff;border-radius:14px;padding:26px 28px;margin-bottom:24px}
.hd h1{margin:0 0 4px;font-size:22px;font-weight:800}
.hd p{margin:0;opacity:.85;font-size:13px}
.card{background:#fff;border-radius:14px;padding:20px 22px;margin-bottom:18px;box-shadow:0 1px 4px rgba(0,0,0,.07)}
h2{font-size:16px;margin:0 0 14px;color:#12233b;border-left:4px solid #2b6fb3;padding-left:10px}
.kpis{display:flex;gap:10px;margin-bottom:14px;flex-wrap:wrap}
.kpi{flex:1;min-width:110px;background:#f4f7fb;border-radius:10px;padding:12px;text-align:center}
.kpi .n{font-size:11px;color:#5a6b7e}
.kpi .v{font-size:20px;font-weight:800;margin-top:2px}
.kpi.g .v{color:#1e7e46}
.kpi.r .v{color:#c0392b}
.kpi.b .v{color:#2b6fb3}
table{width:100%;border-collapse:collapse;font-size:13px;margin-top:6px}
th,td{padding:8px 7px;border-bottom:1px solid #e6ebf1;text-align:center}
th{background:#f4f7fb;color:#5a6b7e;font-size:11.5px;font-weight:700}
td:first-child{text-align:left;font-weight:700;color:#12233b}
.pos{color:#1e7e46;font-weight:700}
.neg{color:#c0392b;font-weight:700}
.cell-best{background:#dbeafe;font-weight:800;color:#1b3a6b}
.legend{display:flex;gap:16px;font-size:12px;color:#5a6b7e;margin-bottom:10px}
.legend span{display:flex;align-items:center;gap:5px}
.dot{width:10px;height:10px;border-radius:50%;display:inline-block}
.picks-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:8px}
.pick-item{background:#f4f7fb;border-radius:8px;padding:8px 10px;font-size:12px}
.pick-item .date{color:#8090a0;font-size:11px}
.pick-item .ret{font-weight:700}
.note{font-size:12px;color:#8090a0;margin-top:10px;line-height:1.5}
</style>"""


def _pct(v: float, decimals=1) -> str:
    s = f"{v*100:+.{decimals}f}%"
    return s


def _cls(v: float) -> str:
    return "pos" if v >= 0 else "neg"


def _heatmap_color(v: float, lo: float, hi: float) -> str:
    """Blue gradient for heatmap cells."""
    if hi == lo:
        return ""
    t = (v - lo) / (hi - lo)
    t = max(0.0, min(1.0, t))
    r = int(219 - 127 * t)
    g = int(234 - 97 * t)
    b = int(254 - 89 * t)
    return f"background:rgb({r},{g},{b});color:{'#1b3a6b' if t > 0.5 else '#33475b'}"


def build_report(market: str, sweep_results: dict, kr_names: dict = None) -> str:
    if not sweep_results:
        return "<p>백테스트 결과 없음</p>"

    market_name = "한국(KOSPI)" if market == "KR" else "미국(S&P500)"
    bench_name  = "KOSPI" if market == "KR" else "S&P 500"

    # ── Best configuration (6m lookback, top_n=5 or closest)
    best_key = (6, 5) if (6, 5) in sweep_results else list(sweep_results.keys())[0]
    best     = sweep_results[best_key]

    # ── Heatmap data
    cagr_matrix = {}
    for (lb, tn), r in sweep_results.items():
        cagr_matrix[(lb, tn)] = r["port_m"]["cagr"]

    all_cagrs = list(cagr_matrix.values())
    c_lo, c_hi = min(all_cagrs), max(all_cagrs)
    best_combo = max(cagr_matrix.items(), key=lambda x: x[1])[0]

    # ── SVG chart
    chart = svg_chart(best["cum_port"], best["cum_bench"])

    # ── KPI cards
    pm = best["port_m"]
    bm = best["bench_m"]
    kpi_html = f"""
    <div class="kpis">
      <div class="kpi {'g' if pm['cagr']>0 else 'r'}">
        <div class="n">전략 CAGR</div>
        <div class="v">{_pct(pm['cagr'],1)}</div>
      </div>
      <div class="kpi {'g' if bm['cagr']>0 else 'r'}">
        <div class="n">{bench_name} CAGR</div>
        <div class="v">{_pct(bm['cagr'],1)}</div>
      </div>
      <div class="kpi b">
        <div class="n">초과수익 (연)</div>
        <div class="v">{_pct(pm['cagr']-bm['cagr'],1)}</div>
      </div>
      <div class="kpi">
        <div class="n">샤프</div>
        <div class="v">{pm['sharpe']:.2f}</div>
      </div>
      <div class="kpi r">
        <div class="n">최대 낙폭</div>
        <div class="v">{_pct(pm['mdd'],1)}</div>
      </div>
      <div class="kpi">
        <div class="n">월간 승률</div>
        <div class="v">{pm['hit']/pm['n_months']*100:.0f}%</div>
      </div>
    </div>"""

    # ── Metrics comparison table
    metrics_html = f"""
    <table>
      <tr><th>지표</th><th>전략 ({best_key[0]}m / 상위{best_key[1]})</th>
          <th>{bench_name}</th><th>초과</th></tr>
      <tr><td>CAGR</td>
          <td class="{_cls(pm['cagr'])}">{_pct(pm['cagr'])}</td>
          <td class="{_cls(bm['cagr'])}">{_pct(bm['cagr'])}</td>
          <td class="{_cls(pm['cagr']-bm['cagr'])}">{_pct(pm['cagr']-bm['cagr'])}</td></tr>
      <tr><td>총수익</td>
          <td class="{_cls(pm['total'])}">{_pct(pm['total'])}</td>
          <td class="{_cls(bm['total'])}">{_pct(bm['total'])}</td>
          <td class="{_cls(pm['total']-bm['total'])}">{_pct(pm['total']-bm['total'])}</td></tr>
      <tr><td>변동성(연)</td>
          <td>{_pct(pm['vol'])}</td><td>{_pct(bm['vol'])}</td>
          <td class="{_cls(bm['vol']-pm['vol'])}">{_pct(bm['vol']-pm['vol'])}</td></tr>
      <tr><td>샤프</td>
          <td>{pm['sharpe']:.2f}</td><td>{bm['sharpe']:.2f}</td>
          <td class="{_cls(pm['sharpe']-bm['sharpe'])}">{pm['sharpe']-bm['sharpe']:+.2f}</td></tr>
      <tr><td>최대 낙폭</td>
          <td class="neg">{_pct(pm['mdd'])}</td>
          <td class="neg">{_pct(bm['mdd'])}</td>
          <td class="{_cls(bm['mdd']-pm['mdd'])}">{_pct(bm['mdd']-pm['mdd'])}</td></tr>
      <tr><td>관찰 기간</td>
          <td colspan="3">{pm['n_months']}개월
          ({best['cum_port'].index[0].strftime('%Y-%m')} ~
           {best['cum_port'].index[-1].strftime('%Y-%m')})</td></tr>
    </table>
    <p class="note">※ 거래비용 {TX_COST*100:.2f}% 편도 적용. 보유기간: 1개월.</p>"""

    # ── Heatmap
    heat_rows = ""
    for lb in LOOKBACKS:
        heat_rows += f"<tr><td>{lb}개월</td>"
        for tn in TOP_NS:
            key = (lb, tn)
            if key in cagr_matrix:
                v   = cagr_matrix[key]
                sty = _heatmap_color(v, c_lo, c_hi)
                cls = " class='cell-best'" if key == best_combo else ""
                heat_rows += f"<td{cls} style='{sty}'>{_pct(v)}</td>"
            else:
                heat_rows += "<td>—</td>"
        heat_rows += "</tr>"

    heat_html = f"""
    <table>
      <tr><th>룩백 \\ 상위</th>
          <th>3종목</th><th>5종목</th><th>10종목</th></tr>
      {heat_rows}
    </table>
    <p class="note">진한 파란색 = 높은 CAGR. 굵은 테두리(cell-best) = 최고 설정.</p>"""

    # ── Recent 12 picks
    log = best["picks_log"][-12:]
    picks_html = "<div class='picks-grid'>"
    for entry in reversed(log):
        ret_cls = "pos" if entry["ret_pct"] >= 0 else "neg"
        b_cls   = "pos" if entry["bench_pct"] >= 0 else "neg"
        names   = []
        for code in entry["picks"]:
            code = str(code)
            if kr_names and code in kr_names:
                names.append(kr_names[code])
            else:
                names.append(code)
        picks_html += (
            f"<div class='pick-item'>"
            f"<div class='date'>{entry['date']}</div>"
            f"<div style='font-size:11px;margin:3px 0;color:#33475b'>"
            + " · ".join(names[:4])
            + ("…" if len(names) > 4 else "") +
            f"</div>"
            f"<div class='ret {ret_cls}'>{entry['ret_pct']:+.1f}% "
            f"<span class='{b_cls}' style='font-weight:400;font-size:11px'>"
            f"vs {entry['bench_pct']:+.1f}%</span></div>"
            f"</div>"
        )
    picks_html += "</div>"

    return f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>퀀트레터 백테스트 — {market_name}</title>
{_CSS}
</head>
<body>
<div class="wrap">
  <div class="hd">
    <h1>퀀트레터 모멘텀 전략 백테스트</h1>
    <p>{market_name} · 기준일 {REPORT_DATE} · 거래비용 {TX_COST*100:.2f}% 편도</p>
  </div>

  <div class="card">
    <h2>📈 누적 수익률 (6개월 룩백 · 상위 5종목)</h2>
    {chart}
    {kpi_html}
  </div>

  <div class="card">
    <h2>📊 전략 vs 벤치마크 지표 비교</h2>
    {metrics_html}
  </div>

  <div class="card">
    <h2>🔲 파라미터 스윕 — CAGR 히트맵</h2>
    <p style="font-size:13px;color:#33475b;margin-bottom:10px">
      룩백 기간 × 보유 종목 수 조합별 연환산 수익률 (거래비용 차감 후)</p>
    {heat_html}
  </div>

  <div class="card">
    <h2>📋 최근 12개월 월별 픽 (6개월 룩백 · 상위 5종목)</h2>
    {picks_html}
  </div>

  <div class="card" style="background:#f8fafc">
    <h2 style="border-color:#9aa7b5">⚠ 유의사항</h2>
    <p class="note">
    · 본 백테스트는 과거 데이터를 이용한 시뮬레이션이며 미래 수익을 보장하지 않습니다.<br>
    · 인샘플 백테스트입니다. 실제 투자 성과는 거래비용·슬리피지·유동성에 따라 크게 달라질 수 있습니다.<br>
    · 거래세(한국 0.18~0.23%), 증권사 수수료가 포함되지 않은 단순화된 비용 구조입니다.<br>
    · 보유종목이 상장폐지·합병된 경우 생존자 편향(Survivorship Bias)이 일부 존재합니다.<br>
    · 유사투자자문업 신고 전 유료 배포 불가.
    </p>
  </div>
</div>
</body>
</html>"""


# ── 메인 ──────────────────────────────────────────────────────

def main():
    args   = sys.argv[1:]
    run_kr = "us" not in args
    run_us = "kr" not in args

    # 종목 이름 매핑 (한국)
    kr_names = {}
    if os.path.exists("kr_names.json"):
        with open("kr_names.json", encoding="utf-8") as f:
            kr_names = json.load(f)

    results = {}

    if run_kr:
        print("=== 한국(KOSPI) 백테스트 ===")
        prices_kr, bench_kr = load_data("KR")
        if prices_kr is not None:
            sw_kr = sweep(prices_kr, bench_kr)
            print(f"  완료: {len(sw_kr)}개 설정")
            html  = build_report("KR", sw_kr, kr_names)
            out   = "backtest_kr.html"
            with open(out, "w", encoding="utf-8") as f:
                f.write(html)
            print(f"  저장: {out}")
            results["KR"] = sw_kr

    if run_us:
        print("\n=== 미국(S&P500) 백테스트 ===")
        prices_us, bench_us = load_data("US")
        if prices_us is not None:
            sw_us = sweep(prices_us, bench_us)
            print(f"  완료: {len(sw_us)}개 설정")
            html  = build_report("US", sw_us)
            out   = "backtest_us.html"
            with open(out, "w", encoding="utf-8") as f:
                f.write(html)
            print(f"  저장: {out}")
            results["US"] = sw_us

    # ── Summary table
    print("\n=== 요약 (6m 룩백 · 상위5) ===")
    header = f"{'시장':6s}  {'전략CAGR':>10s}  {'벤치CAGR':>10s}  {'초과':>8s}  {'MDD':>8s}  {'샤프':>6s}"
    print(header)
    print("-" * len(header))
    for mkt, sw in results.items():
        key = (6, 5) if (6, 5) in sw else list(sw.keys())[0]
        r   = sw[key]
        pm, bm = r["port_m"], r["bench_m"]
        label = "KR(KOSPI)" if mkt == "KR" else "US(S&P500)"
        print(f"{label:10s}  {pm['cagr']*100:+8.1f}%  {bm['cagr']*100:+8.1f}%  "
              f"{(pm['cagr']-bm['cagr'])*100:+6.1f}%  "
              f"{pm['mdd']*100:+6.1f}%  {pm['sharpe']:6.2f}")


if __name__ == "__main__":
    main()
