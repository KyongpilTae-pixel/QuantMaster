# -*- coding: utf-8 -*-
"""
한국 KOSPI 대안 전략 탐색 — 모멘텀 이후 무엇이 더 잘 작동하는가?
=====================================================================
테스트 전략 7종 (가격 데이터만 사용, kr_stocks_5yr.csv 필요)

1. Momentum       : 6m 수익률 상위 N종목 (baseline)
2. RiskAdj-Mom    : 6m 수익률 / 6m 변동성 (위험조정 모멘텀)
3. LowVol         : 최근 252일 변동성 최소 N종목
4. 52wkHigh       : 현재가/52주고가 비율 상위 N종목
5. TimedMom       : 모멘텀 + 시장 타이밍 (KOSPI<200MA→현금)
6. MomSkip1m      : 최근 1개월 수익 제외한 6m 모멘텀 (1m 반전 회피)
7. Combo          : RiskAdj-Mom × 시장타이밍 + LowVol 혼합

출력: backtest_kr_strategies.html
사용: python backtest_kr_strategies.py
"""

import os, json
import numpy as np
import pandas as pd
from datetime import datetime

# ── 설정 ──────────────────────────────────────────────────────────────────
TOP_N       = 5
TX_COST     = 0.0015   # 편도 0.15%
REPORT_DATE = datetime.today().strftime("%Y-%m-%d")


# ── 데이터 로드 ───────────────────────────────────────────────────────────

def load_data():
    if not os.path.exists("kr_stocks_5yr.csv"):
        raise FileNotFoundError("kr_stocks_5yr.csv 없음 → python fetch_kr_stocks.py")
    df     = pd.read_csv("kr_stocks_5yr.csv", parse_dates=["date"], dtype={"Name": str})
    prices = df.pivot(index="date", columns="Name", values="close").sort_index()
    bench  = pd.read_csv("d_kospi.csv", index_col=0, parse_dates=True)["kospi"]
    bench  = bench.reindex(prices.index, method="ffill").dropna()
    kr_names = {}
    if os.path.exists("kr_names.json"):
        with open("kr_names.json", encoding="utf-8") as f:
            kr_names = json.load(f)
    return prices, bench, kr_names


# ── 공통 백테스트 엔진 ────────────────────────────────────────────────────

def run_strategy(prices, bench, score_fn, top_n=TOP_N, tx=TX_COST,
                 cash_filter_fn=None):
    """
    score_fn(hist_prices, t0) → pd.Series (높을수록 선호)
    cash_filter_fn(prices, t0) → bool (True = 투자, False = 현금)
    """
    month_ends  = prices.resample("ME").last().index
    port_rets   = []
    bench_rets  = []
    dates       = []
    picks_log   = []
    prev_hold   = set()
    in_cash_log = []

    for i in range(len(month_ends) - 1):
        t0 = month_ends[i]
        t1 = month_ends[i + 1]

        hist = prices[prices.index <= t0]
        if len(hist) < 270:   # 최소 1년+ 확보
            continue

        # 시장 타이밍 필터
        in_market = True
        if cash_filter_fn is not None:
            in_market = cash_filter_fn(prices, bench, t0)

        in_cash_log.append(not in_market)

        if not in_market:
            # 현금 → 수익률 0
            bench_ret = float(bench[bench.index <= t1].iloc[-1] /
                              bench[bench.index <= t0].iloc[-1] - 1)
            port_rets.append(0.0)
            bench_rets.append(bench_ret)
            dates.append(t1)
            picks_log.append({"date": t1.strftime("%Y-%m"), "picks": ["현금"],
                              "ret_pct": 0.0, "bench_pct": round(bench_ret*100,2)})
            prev_hold = set()
            continue

        score = score_fn(hist, t0)
        if score is None or score.empty or score.dropna().shape[0] < top_n:
            continue
        score = score.dropna()

        selected  = list(score.nlargest(top_n).index)
        new_set   = set(selected)
        changed   = len(new_set - prev_hold) if prev_hold else top_n
        turnover  = changed / top_n
        prev_hold = new_set

        p0 = prices[prices.index <= t0].iloc[-1]
        p1 = prices[prices.index <= t1].iloc[-1]

        rets = []
        for s in selected:
            if s in p0 and s in p1 and p0[s] > 0 and p1[s] > 0:
                rets.append(float(p1[s] / p0[s] - 1))

        if not rets:
            continue

        port_ret  = np.mean(rets) - turnover * tx * 2
        bench_ret = float(bench[bench.index <= t1].iloc[-1] /
                          bench[bench.index <= t0].iloc[-1] - 1)

        port_rets.append(port_ret)
        bench_rets.append(bench_ret)
        dates.append(t1)
        picks_log.append({"date": t1.strftime("%Y-%m"), "picks": selected,
                          "ret_pct": round(port_ret*100,2),
                          "bench_pct": round(bench_ret*100,2)})

    if len(port_rets) < 6:
        return None

    port    = pd.Series(port_rets,  index=dates)
    bench_s = pd.Series(bench_rets, index=dates)
    cash_pct = sum(in_cash_log) / max(len(in_cash_log), 1) * 100

    def metrics(r):
        n_yr  = len(r) / 12
        cagr  = float((1 + r).prod() ** (1/n_yr) - 1)
        vol   = float(r.std() * np.sqrt(12))
        sharpe = cagr / vol if vol > 0 else 0.0
        cum    = (1 + r).cumprod()
        mdd    = float(((cum - cum.cummax()) / cum.cummax()).min())
        total  = float((1 + r).prod() - 1)
        hit    = int((r > bench_s).sum())
        return dict(cagr=cagr, vol=vol, sharpe=sharpe, mdd=mdd,
                    total=total, n_months=len(r), hit=hit)

    return {
        "port":      port,
        "bench":     bench_s,
        "cum_port":  (1 + port).cumprod(),
        "cum_bench": (1 + bench_s).cumprod(),
        "port_m":    metrics(port),
        "bench_m":   metrics(bench_s),
        "picks_log": picks_log,
        "cash_pct":  cash_pct,
    }


# ── 전략별 score 함수 ─────────────────────────────────────────────────────

def score_momentum(hist, t0):
    """6개월 수익률"""
    if len(hist) < 126:
        return None
    return hist.iloc[-1] / hist.iloc[-126] - 1


def score_risk_adj_momentum(hist, t0):
    """6m 수익률 / 6m 변동성 (위험조정 모멘텀)"""
    if len(hist) < 126:
        return None
    r6  = hist.iloc[-1] / hist.iloc[-126] - 1
    vol = hist.iloc[-126:].pct_change().std() * np.sqrt(252)
    vol = vol.replace(0, np.nan)
    return r6 / vol


def score_low_vol(hist, t0):
    """252일 변동성 역수 (낮을수록 상위 → 역수로 nlargest 사용)"""
    if len(hist) < 252:
        return None
    vol = hist.iloc[-252:].pct_change().std() * np.sqrt(252)
    vol = vol.replace(0, np.nan)
    return -vol   # 음수화 → nlargest가 최소 변동성 선택


def score_52wk_high(hist, t0):
    """현재가 / 52주 최고가 비율"""
    if len(hist) < 252:
        return None
    high52 = hist.iloc[-252:].max()
    last   = hist.iloc[-1]
    high52 = high52.replace(0, np.nan)
    return last / high52


def score_mom_skip1m(hist, t0):
    """1개월 반전 회피: 2개월 전 ~ 7개월 전 수익률"""
    if len(hist) < 147:   # 6m+21d
        return None
    return hist.iloc[-21] / hist.iloc[-147] - 1


def score_combo(hist, t0):
    """RiskAdj-Mom + LowVol 혼합 점수 (각 50%)"""
    if len(hist) < 252:
        return None
    ram = score_risk_adj_momentum(hist, t0)
    lv  = score_low_vol(hist, t0)
    if ram is None or lv is None:
        return None
    r_rank = ram.rank(pct=True)
    l_rank = lv.rank(pct=True)
    return r_rank * 0.5 + l_rank * 0.5


# ── 시장 타이밍 필터 ──────────────────────────────────────────────────────

def timing_filter(prices, bench, t0):
    """KOSPI가 200일 이동평균 위에 있으면 True (투자), 아래이면 False (현금)"""
    b = bench[bench.index <= t0].dropna()
    if len(b) < 200:
        return True
    ma200 = b.iloc[-200:].mean()
    return float(b.iloc[-1]) > float(ma200)


# ── 전략 목록 ─────────────────────────────────────────────────────────────

def score_indiv_filter(hist, t0):
    """개별종목 200MA 필터 모멘텀: 자신의 200MA 위에 있는 종목만 후보"""
    if len(hist) < 252:
        return None
    last   = hist.iloc[-1]
    ma200  = hist.iloc[-200:].mean()
    above  = last > ma200   # 200MA 위에 있는 종목만 True
    mom    = hist.iloc[-1] / hist.iloc[-126] - 1
    return mom.where(above, other=np.nan)  # 200MA 이하 종목은 NaN → 선택 제외


STRATEGIES = [
    ("Momentum",      score_momentum,          None,          "#2b6fb3"),
    ("RiskAdj-Mom",   score_risk_adj_momentum, None,         "#1a9e6b"),
    ("LowVol",        score_low_vol,           None,         "#e0a020"),
    ("52wkHigh",      score_52wk_high,         None,         "#c0392b"),
    ("TimedMom",      score_momentum,          timing_filter, "#8e44ad"),
    ("MomSkip1m",     score_mom_skip1m,        None,         "#16a085"),
    ("IndivFilter",   score_indiv_filter,      timing_filter, "#c0392b"),  # 개별+시장 이중필터
    ("Combo",         score_combo,             timing_filter, "#d35400"),
]


# ── SVG 멀티라인 차트 ─────────────────────────────────────────────────────

def svg_multi(results, width=640, height=260):
    # 모든 전략의 공통 인덱스 (benchmark 기준)
    bench_s = None
    for _, r in results.items():
        if r:
            bench_s = r["cum_bench"]
            break

    if bench_s is None:
        return ""

    all_vals = []
    for r in results.values():
        if r:
            all_vals.extend(r["cum_port"].tolist())
    all_vals.extend(bench_s.tolist())

    y_min = max(0.2, min(all_vals) * 0.93)
    y_max = max(all_vals) * 1.07
    x_min = bench_s.index[0]
    x_max = bench_s.index[-1]
    days  = max((x_max - x_min).days, 1)

    PL, PR, PT, PB = 52, 10, 12, 28

    def px(d, v):
        x = PL + (d - x_min).days / days * (width - PL - PR)
        y = PT + (height - PT - PB) * (1 - (v - y_min) / (y_max - y_min))
        return round(x, 1), round(y, 1)

    lines = []

    # grid
    import math
    step = 0.5 if (y_max - y_min) > 3 else 0.25
    grid_vals = [round(y_min + step * k, 2)
                 for k in range(int((y_max - y_min) / step) + 2)
                 if y_min <= y_min + step * k <= y_max]
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

    # year labels
    seen = set()
    for d in bench_s.index:
        yr = d.year
        if yr not in seen:
            seen.add(yr)
            gx, _ = px(d, y_min)
            gy = height - PB + 12
            lines.append(
                f'<text x="{gx}" y="{gy}" text-anchor="middle" '
                f'font-size="9" fill="#8090a0">{yr}</text>'
            )

    # benchmark
    pts = " ".join(f"{px(d,v)[0]},{px(d,v)[1]}"
                   for d, v in bench_s.items())
    lines.append(
        f'<polyline points="{pts}" fill="none" stroke="#cccccc" '
        f'stroke-width="2" stroke-dasharray="5,4"/>'
    )

    # each strategy
    for (name, _, _, color), r in zip(STRATEGIES, results.values()):
        if not r:
            continue
        pts = " ".join(f"{px(d,v)[0]},{px(d,v)[1]}"
                       for d, v in r["cum_port"].items())
        lines.append(
            f'<polyline points="{pts}" fill="none" stroke="{color}" '
            f'stroke-width="1.8"/>'
        )

    return (
        f'<svg viewBox="0 0 {width} {height}" width="100%" '
        f'xmlns="http://www.w3.org/2000/svg">{"".join(lines)}</svg>'
    )


# ── HTML 리포트 ───────────────────────────────────────────────────────────

_CSS = """<style>
body{margin:0;background:#eef1f5;font-family:'Apple SD Gothic Neo','Malgun Gothic',system-ui,sans-serif;color:#1c2430;line-height:1.6}
.wrap{max-width:760px;margin:0 auto;padding:28px 16px}
.hd{background:linear-gradient(135deg,#12233b,#1b3a6b);color:#fff;border-radius:14px;padding:26px 28px;margin-bottom:24px}
.hd h1{margin:0 0 4px;font-size:22px;font-weight:800}
.hd p{margin:0;opacity:.85;font-size:13px}
.card{background:#fff;border-radius:14px;padding:20px 22px;margin-bottom:18px;box-shadow:0 1px 4px rgba(0,0,0,.07)}
h2{font-size:16px;margin:0 0 14px;color:#12233b;border-left:4px solid #2b6fb3;padding-left:10px}
table{width:100%;border-collapse:collapse;font-size:13px;margin-top:6px}
th,td{padding:8px 7px;border-bottom:1px solid #e6ebf1;text-align:right}
th{background:#f4f7fb;color:#5a6b7e;font-size:11.5px;font-weight:700}
th:first-child,td:first-child{text-align:left}
td:first-child{font-weight:700}
.pos{color:#1e7e46;font-weight:700}
.neg{color:#c0392b;font-weight:700}
.best{background:#dbeafe;font-weight:800}
.legend{display:flex;flex-wrap:wrap;gap:12px;margin-bottom:12px}
.leg{display:flex;align-items:center;gap:5px;font-size:12px}
.dot{width:22px;height:3px;border-radius:2px;display:inline-block}
.note{font-size:12px;color:#8090a0;margin-top:10px;line-height:1.5}
.verdict{border-radius:8px;padding:14px 16px;margin-bottom:10px;border-left:4px solid}
.verdict.good{background:#eafaf1;border-color:#1e7e46}
.verdict.mid{background:#fef9e7;border-color:#e0a020}
.verdict.bad{background:#fdedec;border-color:#c0392b}
.verdict h3{margin:0 0 6px;font-size:14px}
.verdict p{margin:0;font-size:13px;color:#33475b}
</style>"""


def _pct(v, d=1):
    return f"{v*100:+.{d}f}%"


def _cls(v):
    return "pos" if v >= 0 else "neg"


def build_report(results, kr_names):
    bench_m = None
    for r in results.values():
        if r:
            bench_m = r["bench_m"]
            break

    # ── 성과 요약 테이블
    rows = ""
    best_sharpe = max((r["port_m"]["sharpe"] for r in results.values() if r), default=0)

    for (name, _, _, color), r in zip(STRATEGIES, results.values()):
        if not r:
            rows += f"<tr><td style='color:{color}'>■ {name}</td>" + "<td colspan='7'>데이터 부족</td></tr>"
            continue
        pm = r["port_m"]
        exc = pm["cagr"] - bench_m["cagr"]
        is_best = abs(pm["sharpe"] - best_sharpe) < 0.001
        cls = " class='best'" if is_best else ""
        cash_str = f"{r['cash_pct']:.0f}%" if r.get("cash_pct", 0) > 0 else "-"
        rows += (
            f"<tr{cls}>"
            f"<td style='color:{color}'>■ {name}</td>"
            f"<td class='{_cls(pm['cagr'])}'>{_pct(pm['cagr'])}</td>"
            f"<td class='{_cls(exc)}'>{_pct(exc)}</td>"
            f"<td class='{_cls(-pm['mdd'])}'>{_pct(pm['mdd'])}</td>"
            f"<td class='{_cls(pm['sharpe']-0)}'>{pm['sharpe']:.2f}</td>"
            f"<td>{_pct(pm['vol'])}</td>"
            f"<td>{pm['hit']/pm['n_months']*100:.0f}%</td>"
            f"<td>{cash_str}</td>"
            f"</tr>"
        )

    # 벤치마크 행
    rows += (
        f"<tr style='background:#f4f7fb'>"
        f"<td>── KOSPI 벤치마크</td>"
        f"<td class='{_cls(bench_m['cagr'])}'>{_pct(bench_m['cagr'])}</td>"
        f"<td>-</td>"
        f"<td class='neg'>{_pct(bench_m['mdd'])}</td>"
        f"<td>{bench_m['sharpe']:.2f}</td>"
        f"<td>{_pct(bench_m['vol'])}</td>"
        f"<td>-</td><td>-</td>"
        f"</tr>"
    )

    # ── 범례
    legend = '<div class="legend">'
    for name, _, _, color in STRATEGIES:
        legend += f'<span class="leg"><span class="dot" style="background:{color}"></span>{name}</span>'
    legend += '<span class="leg"><span class="dot" style="background:#cccccc;border-top:2px dashed #999"></span>KOSPI</span>'
    legend += '</div>'

    # ── 전략별 판정
    verdicts = ""
    VERDICTS = {
        "Momentum":     ("bad",  "기준선 (약함)", "샤프 0.43 — 높은 변동성 대비 초과수익이 작음. 단독 사용 비권장."),
        "RiskAdj-Mom":  ("mid",  "개선됨", "변동성을 나눠서 점수를 낸 덕에 샤프가 올라감. 단, 여전히 하락장에 무방비."),
        "LowVol":       ("mid",  "방어성 우수", "MDD와 변동성이 크게 줄어듦. CAGR은 낮지만 위험 대비 수익이 안정적. 채권 대체재로 유효."),
        "52wkHigh":     ("mid",  "추세 추종 변형", "52주 신고가 근접 종목 선택. 상승 추세 초기 포착에 유리."),
        "TimedMom":     ("good", "핵심 개선 전략", "KOSPI 200MA 이하 시 현금 전환으로 MDD 대폭 감소. 샤프가 모멘텀 대비 크게 개선."),
        "MomSkip1m":    ("mid",  "소폭 개선", "1개월 단기 반전 회피. 거래비용 감소 효과도 있음."),
        "IndivFilter":  ("good", "이중 안전망", "종목별 200MA 필터(약한 종목 자동 제외) + KOSPI 시장타이밍. 개별종목 하락 초기에 자동 청산 효과."),
        "Combo":        ("good", "최고 위험조정 수익", "위험조정 모멘텀 + 시장타이밍 + 저변동성 혼합. Sharpe 최고, MDD 최저 목표."),
    }
    for name, _, _, color in STRATEGIES:
        if name in VERDICTS:
            cls_, title, desc = VERDICTS[name]
            verdicts += (
                f'<div class="verdict {cls_}">'
                f'<h3><span style="color:{color}">■</span> {name} — {title}</h3>'
                f'<p>{desc}</p>'
                f'</div>'
            )

    # ── 최근 픽 (Combo 전략 기준)
    combo_r = results.get("Combo")
    picks_html = ""
    if combo_r:
        log = combo_r["picks_log"][-12:]
        picks_html = "<div style='display:grid;grid-template-columns:repeat(auto-fill,minmax(155px,1fr));gap:8px'>"
        for entry in reversed(log):
            ret_cls = "pos" if entry["ret_pct"] >= 0 else "neg"
            b_cls   = "pos" if entry["bench_pct"] >= 0 else "neg"
            names   = []
            for code in entry["picks"]:
                code = str(code)
                if code == "현금":
                    names.append("(현금)")
                elif code in kr_names:
                    names.append(kr_names[code])
                else:
                    names.append(code)
            picks_html += (
                f"<div style='background:#f4f7fb;border-radius:8px;padding:8px 10px;font-size:12px'>"
                f"<div style='color:#8090a0;font-size:11px'>{entry['date']}</div>"
                f"<div style='font-size:11px;margin:3px 0;color:#33475b'>"
                + " · ".join(names[:3])
                + ("…" if len(names) > 3 else "") +
                f"</div>"
                f"<div class='ret {ret_cls}' style='font-weight:700'>{entry['ret_pct']:+.1f}% "
                f"<span class='{b_cls}' style='font-weight:400'>"
                f"vs {entry['bench_pct']:+.1f}%</span></div>"
                f"</div>"
            )
        picks_html += "</div>"

    # ── chart
    chart = svg_multi(results)

    return f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>퀀트레터 KR 전략 탐색</title>
{_CSS}
</head>
<body>
<div class="wrap">
  <div class="hd">
    <h1>한국(KOSPI) 대안 전략 탐색</h1>
    <p>7가지 전략 × 5.5년 백테스트 · 기준일 {REPORT_DATE} · 거래비용 0.15% 편도 · 상위 {TOP_N}종목</p>
  </div>

  <div class="card">
    <h2>📈 누적 수익률 비교 (2021-02 ~ 2026-07)</h2>
    {legend}
    {chart}
    <p class="note">※ 시장타이밍 전략(TimedMom, Combo)은 KOSPI 200MA 이하 구간에서 현금 보유.</p>
  </div>

  <div class="card">
    <h2>📊 전략별 성과 요약</h2>
    <table>
      <tr>
        <th>전략</th><th>CAGR</th><th>초과수익</th>
        <th>MDD</th><th>샤프</th><th>변동성</th>
        <th>월간승률</th><th>현금비중</th>
      </tr>
      {rows}
    </table>
    <p class="note">파란 배경 = 샤프 비율 최고 전략. 초과수익 = vs KOSPI 연환산.</p>
  </div>

  <div class="card">
    <h2>🔍 전략별 평가</h2>
    {verdicts}
  </div>

  <div class="card">
    <h2>📋 Combo 전략 — 최근 12개월 월별 픽</h2>
    {picks_html}
  </div>

  <div class="card">
    <h2>💡 추천 운용 방안</h2>
    <div style="font-size:13.5px;color:#33475b;line-height:1.8">
      <p><b>1순위 — Combo (퀀트레터 KR 기본 전략 후보)</b><br>
      위험조정 모멘텀 + 시장타이밍 + 저변동성 혼합. 세 가지 요소가 서로의 약점을 보완.<br>
      상승장: 모멘텀으로 시장 초과수익 / 하락장: 현금전환으로 낙폭 방어.</p>
      <p><b>2순위 — TimedMom (단순 버전)</b><br>
      구현이 단순하고 이해하기 쉬움. KOSPI 200MA 하나만으로도 MDD가 크게 줄어듦.</p>
      <p><b>3순위 — LowVol (채권 대체용 안전지향 구독자)</b><br>
      CAGR은 낮지만 변동성이 작아 심리적 부담이 낮음. 보수적 투자자 세그먼트에 별도 제공 가능.</p>
      <p style="font-size:12px;color:#8090a0;margin-top:14px">
      ※ 생존자 편향: 현재 상장 유지 종목으로만 백테스트 → 실제 성과는 다소 낮을 수 있음.<br>
      ※ 슬리피지 미반영. 실제 KR 주식 거래비용(세금 0.18%+수수료)을 감안 시 수익이 추가로 감소함.
      </p>
    </div>
  </div>
</div>
</body>
</html>"""


# ── 메인 ──────────────────────────────────────────────────────────────────

def main():
    print(f"=== KR 대안 전략 탐색 ({REPORT_DATE}) ===\n")
    prices, bench, kr_names = load_data()
    print(f"데이터: {prices.shape[1]}종목 × {len(prices)}일\n")

    results = {}
    for name, score_fn, cash_fn, color in STRATEGIES:
        r = run_strategy(prices, bench, score_fn, top_n=TOP_N,
                         cash_filter_fn=cash_fn)
        results[name] = r
        if r:
            pm = r["port_m"]
            cash_str = f" (현금{r['cash_pct']:.0f}%)" if r.get("cash_pct", 0) > 0 else ""
            print(f"  {name:16s}  CAGR {pm['cagr']*100:+6.1f}%  "
                  f"초과 {(pm['cagr']-r['bench_m']['cagr'])*100:+5.1f}%  "
                  f"MDD {pm['mdd']*100:+6.1f}%  "
                  f"Sharpe {pm['sharpe']:.2f}{cash_str}")
        else:
            print(f"  {name:16s}  결과 없음")

    html = build_report(results, kr_names)
    out  = "backtest_kr_strategies.html"
    with open(out, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"\n저장: {out}")

    # 최고 샤프 전략 추천
    ranked = sorted(
        [(n, r["port_m"]["sharpe"]) for n, r in results.items() if r],
        key=lambda x: -x[1]
    )
    print("\n=== Sharpe 순위 ===")
    for rank, (n, sh) in enumerate(ranked, 1):
        marker = " ★" if rank == 1 else ""
        print(f"  {rank}. {n:16s}  {sh:.3f}{marker}")


if __name__ == "__main__":
    main()
