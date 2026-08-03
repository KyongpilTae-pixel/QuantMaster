# -*- coding: utf-8 -*-
"""
퀀트레터 듀얼마켓 주간 리포트
==============================
KR : 저변동성(LowVol) 상위 5종목
KR : MomSkip1m (단기반전 회피 모멘텀) 상위 5종목
US : 6개월 모멘텀 상위 6종목
→ out_weekly_dual.html 생성

사용: python run_weekly_dual.py
"""
import os, json
from datetime import datetime

import numpy as np
import pandas as pd

TOP_KR = 5
TOP_US = 6
LOOKBACK_DAYS = 126   # 6개월
MA_DAYS  = 100
STOP_PCT = 0.15
LEDGER_KR = "positions_kr.json"
LEDGER_US = "positions_us.json"


# ── 포지션 관리 ──────────────────────────────────────────────

def _load_led(path):
    return json.load(open(path, encoding="utf-8")) if os.path.exists(path) else {}

def _save_led(led, path):
    json.dump(led, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

def evaluate_positions(prices, ledger_path, name_fn=None):
    """보유 종목 평가 → 매도신호 포함 rows 반환. 매도신호 종목은 원장에서 제거."""
    led = _load_led(ledger_path)
    if not led:
        return [], []

    ma    = prices.rolling(MA_DAYS).mean()
    rows  = []
    close = []

    for tk, info in list(led.items()):
        col = tk
        if col not in prices.columns:
            continue
        s = prices[col].dropna()
        if len(s) < 2:
            continue

        cur   = float(s.iloc[-1])
        entry = info["entry"]
        ret   = (cur / entry - 1) * 100
        ma100 = float(ma[col].dropna().iloc[-1]) if ma[col].notna().any() else None
        stop  = entry * (1 - STOP_PCT)

        trend_break = (ma100 is not None) and cur < ma100
        stop_break  = cur < stop
        signal      = trend_break or stop_break
        reason      = ("추세이탈 (100MA↓)" if trend_break
                       else ("손절가 도달" if stop_break else "—"))

        display = name_fn(tk) if name_fn else tk
        rows.append(dict(
            ticker=tk, display=display,
            entry=entry, cur=cur, ret=round(ret, 1),
            ma100=round(ma100, 2) if ma100 else None,
            stop=round(stop, 2),
            signal=signal, reason=reason,
            entry_date=info.get("entry_date", "—"),
        ))
        if signal:
            close.append(tk)

    for tk in close:
        led.pop(tk, None)
    _save_led(led, ledger_path)

    rows.sort(key=lambda r: (not r["signal"], r["ret"]))
    return rows, close

def open_new_positions(prices, tickers, asof, ledger_path):
    """신규 추천 종목을 원장에 추가 (기존 보유 중이면 스킵)."""
    led = _load_led(ledger_path)
    for tk in tickers:
        if tk not in led and tk in prices.columns:
            led[tk] = {
                "entry_date": str(asof.date() if hasattr(asof, "date") else asof),
                "entry": float(prices[tk].dropna().iloc[-1]),
            }
    _save_led(led, ledger_path)


# ── 데이터 로드 ───────────────────────────────────────────────

def load_kr():
    df = pd.read_csv("kr_stocks_5yr.csv", parse_dates=["date"], dtype={"Name": str})
    prices = df.pivot(index="date", columns="Name", values="close").sort_index()
    with open("kr_names.json", encoding="utf-8") as f:
        names = json.load(f)
    return prices, names

def load_us():
    df = pd.read_csv("all_stocks_5yr.csv", parse_dates=["date"])
    return df.pivot(index="date", columns="Name", values="close").sort_index()


# ── KR: 저변동성 전략 ─────────────────────────────────────────

def kr_lowvol_picks(prices, names, top_n=TOP_KR):
    last_date = prices.index[-1]
    hist = prices.dropna(axis=1, how="all")

    # 252일 변동성
    vol = hist.iloc[-252:].pct_change(fill_method=None).std() * np.sqrt(252)
    # 6개월 수익률 (참고용)
    m6  = hist.iloc[-1] / hist.iloc[-LOOKBACK_DAYS] - 1
    # 현재가 vs 200MA
    ma200 = hist.iloc[-200:].mean()
    above_ma = hist.iloc[-1] > ma200

    tbl = pd.DataFrame({"vol": vol, "m6": m6, "above_ma200": above_ma}).dropna()
    tbl = tbl.sort_values("vol")   # 변동성 낮은 순

    picks = []
    for code, row in tbl.head(top_n * 2).iterrows():   # 여유분 확보
        if len(picks) >= top_n:
            break
        name = names.get(str(code), code)
        price = float(hist[code].iloc[-1])
        picks.append({
            "rank":       len(picks) + 1,
            "code":       str(code),
            "name":       name,
            "price":      price,
            "vol_pct":    round(float(row["vol"]) * 100, 1),
            "m6_pct":     round(float(row["m6"]) * 100, 1),
            "above_ma200": bool(row["above_ma200"]),
        })

    return picks, last_date


# ── KR: MomSkip1m 전략 ──────────────────────────────────────

def kr_momskip_picks(prices, names, top_n=TOP_KR):
    """최근 1개월 제외한 6개월 모멘텀 (D-147 → D-21)"""
    last_date = prices.index[-1]
    hist = prices.dropna(axis=1, how="all")

    if len(hist) < 150:
        return [], last_date

    mom   = hist.iloc[-21] / hist.iloc[-147] - 1   # 1m 건너뛴 6m 수익률
    m6    = hist.iloc[-1]  / hist.iloc[-126] - 1   # 참고용 일반 6m
    ma200 = hist.iloc[-200:].mean()
    above_ma = hist.iloc[-1] > ma200

    tbl = pd.DataFrame({"mom": mom, "m6": m6, "above_ma200": above_ma}).dropna()
    tbl = tbl.sort_values("mom", ascending=False)

    picks = []
    for code, row in tbl.head(top_n).iterrows():
        name  = names.get(str(code), code)
        price = float(hist[code].iloc[-1])
        picks.append({
            "rank":       len(picks) + 1,
            "code":       str(code),
            "name":       name,
            "price":      price,
            "skip_pct":   round(float(row["mom"]) * 100, 1),   # D-147→D-21
            "m6_pct":     round(float(row["m6"])  * 100, 1),   # 일반 6m (참고)
            "above_ma200": bool(row["above_ma200"]),
        })

    return picks, last_date


# ── US: 6개월 모멘텀 전략 ────────────────────────────────────

def us_momentum_picks(prices, top_n=TOP_US):
    last_date = prices.index[-1]
    hist = prices.dropna(axis=1, how="all")

    m6  = hist.iloc[-1] / hist.iloc[-LOOKBACK_DAYS] - 1
    m3  = hist.iloc[-1] / hist.iloc[-63] - 1
    m12 = hist.iloc[-1] / hist.iloc[-252] - 1
    vol = hist.pct_change(fill_method=None).iloc[-252:].std() * np.sqrt(252)

    score = m6.rank(pct=True) * 0.6 + m12.rank(pct=True).fillna(0.5) * 0.4
    tbl   = pd.DataFrame({"score": score, "m6": m6, "m3": m3, "m12": m12, "vol": vol}).dropna()
    tbl   = tbl.sort_values("score", ascending=False)

    picks = []
    for ticker, row in tbl.head(top_n).iterrows():
        price = float(hist[ticker].iloc[-1])
        picks.append({
            "rank":    len(picks) + 1,
            "ticker":  ticker,
            "price":   round(price, 2),
            "m6_pct":  round(float(row["m6"]) * 100, 1),
            "m3_pct":  round(float(row["m3"]) * 100, 1),
            "m12_pct": round(float(row["m12"]) * 100, 1),
            "vol_pct": round(float(row["vol"]) * 100, 1),
        })

    return picks, last_date


# ── HTML 생성 ─────────────────────────────────────────────────

def _sgn(v):
    return "+" if v >= 0 else ""

def _cls(v):
    return "pos" if v >= 0 else "neg"

def positions_section(rows, market_label, currency="₩"):
    """보유 종목 현황 + 매도신호 HTML 블록."""
    if not rows:
        return ""

    sell_rows  = [r for r in rows if r["signal"]]
    hold_rows  = [r for r in rows if not r["signal"]]
    sell_count = len(sell_rows)

    def price_fmt(v):
        if currency == "$":
            return f"${v:,.2f}"
        return f"₩{v:,.0f}"

    def row_html(r):
        ret_cls  = "sell-ret" if r["signal"] else (_cls(r["ret"]))
        bg_style = 'style="background:#fff5f5"' if r["signal"] else ""
        status   = (f'<span class="sell-badge">매도▲ {r["reason"]}</span>'
                    if r["signal"] else
                    '<span class="hold-badge">보유유지</span>')
        ma_str   = price_fmt(r["ma100"]) if r["ma100"] else "—"
        return f"""<tr {bg_style}>
          <td><b>{r['display']}</b><br><span style="font-size:11px;color:#8090a0">{r['entry_date']}</span></td>
          <td>{price_fmt(r['entry'])}</td>
          <td>{price_fmt(r['cur'])}</td>
          <td class="{ret_cls}">{_sgn(r['ret'])}{r['ret']}%</td>
          <td>{ma_str}</td>
          <td>{price_fmt(r['stop'])}</td>
          <td>{status}</td>
        </tr>"""

    all_rows_html = "".join(row_html(r) for r in rows)
    alert = (f'<div class="sell-alert">⚠️ 매도 신호 {sell_count}건 — '
             + ", ".join(r["display"] for r in sell_rows) +
             '</div>') if sell_count else ""

    return f"""
  <div class="pos-section">
    <div class="pos-head">
      <span>📋 {market_label} 보유 종목 현황</span>
      <span style="font-size:12px;color:#8090a0">{len(rows)}종목 보유 중</span>
    </div>
    {alert}
    <div style="overflow-x:auto">
    <table class="pos-table">
      <thead>
        <tr><th>종목</th><th>진입가</th><th>현재가</th>
            <th>수익률</th><th>100MA</th><th>손절가</th><th>상태</th></tr>
      </thead>
      <tbody>{all_rows_html}</tbody>
    </table>
    </div>
  </div>"""

def kr_card(p):
    ma_badge = (
        '<span class="badge green">200MA 위</span>'
        if p["above_ma200"] else
        '<span class="badge grey">200MA 아래</span>'
    )
    vol_bar_w = min(100, int(p["vol_pct"] / 40 * 100))
    return f"""
    <div class="pick-card">
      <div class="pick-top">
        <span class="pick-num">{p['rank']}</span>
        <span class="pick-name">{p['name']}</span>
        <span class="pick-code">{p['code']}</span>
        {ma_badge}
      </div>
      <div class="pick-price">₩{p['price']:,.0f}</div>
      <div class="pick-stats">
        <div class="ps-item">
          <span class="ps-label">연간 변동성</span>
          <div class="vol-track">
            <div class="vol-fill" style="width:{vol_bar_w}%"></div>
          </div>
          <span class="ps-val bold-kr">{p['vol_pct']}%</span>
        </div>
        <div class="ps-item">
          <span class="ps-label">6개월 수익</span>
          <span class="ps-val {_cls(p['m6_pct'])}">{_sgn(p['m6_pct'])}{p['m6_pct']}%</span>
        </div>
      </div>
    </div>"""

def kr_momskip_card(p):
    ma_badge = (
        '<span class="badge green">200MA 위</span>'
        if p["above_ma200"] else
        '<span class="badge grey">200MA 아래</span>'
    )
    return f"""
    <div class="pick-card">
      <div class="pick-top">
        <span class="pick-num">{p['rank']}</span>
        <span class="pick-name">{p['name']}</span>
        <span class="pick-code">{p['code']}</span>
        {ma_badge}
      </div>
      <div class="pick-price">₩{p['price']:,.0f}</div>
      <div class="pick-stats">
        <div class="ps-item">
          <span class="ps-label">추세 점수</span>
          <span class="ps-val {_cls(p['skip_pct'])}">{_sgn(p['skip_pct'])}{p['skip_pct']}%</span>
        </div>
        <div class="ps-item">
          <span class="ps-label">6개월 수익</span>
          <span class="ps-val {_cls(p['m6_pct'])}">{_sgn(p['m6_pct'])}{p['m6_pct']}%</span>
        </div>
      </div>
    </div>"""

def us_card(p):
    return f"""
    <div class="pick-card">
      <div class="pick-top">
        <span class="pick-num">{p['rank']}</span>
        <span class="pick-name">{p['ticker']}</span>
        <span class="badge blue">모멘텀 상위</span>
      </div>
      <div class="pick-price">${p['price']:,.2f}</div>
      <div class="pick-stats">
        <div class="ps-item">
          <span class="ps-label">6개월</span>
          <span class="ps-val {_cls(p['m6_pct'])}">{_sgn(p['m6_pct'])}{p['m6_pct']}%</span>
        </div>
        <div class="ps-item">
          <span class="ps-label">3개월</span>
          <span class="ps-val {_cls(p['m3_pct'])}">{_sgn(p['m3_pct'])}{p['m3_pct']}%</span>
        </div>
        <div class="ps-item">
          <span class="ps-label">12개월</span>
          <span class="ps-val {_cls(p['m12_pct'])}">{_sgn(p['m12_pct'])}{p['m12_pct']}%</span>
        </div>
        <div class="ps-item">
          <span class="ps-label">변동성</span>
          <span class="ps-val">{p['vol_pct']}%</span>
        </div>
      </div>
    </div>"""


def build_html(kr_picks, kr_skip_picks, kr_date, us_picks, us_date,
               kr_pos_rows=None, us_pos_rows=None):
    today = datetime.today().strftime("%Y년 %m월 %d일")
    kr_date_str = kr_date.strftime("%Y-%m-%d")
    us_date_str = us_date.strftime("%Y-%m-%d")

    kr_cards_html      = "".join(kr_card(p) for p in kr_picks)
    kr_skip_cards_html = "".join(kr_momskip_card(p) for p in kr_skip_picks)
    us_cards_html      = "".join(us_card(p) for p in us_picks)
    us_pos_html        = positions_section(us_pos_rows  or [], "🇺🇸 미국주식", "$")
    kr_pos_html        = positions_section(kr_pos_rows  or [], "🇰🇷 한국주식", "₩")

    return f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>퀀트레터 WEEKLY — {today}</title>
<style>
:root {{
  --kr: #1b3a6b; --kr-l: #2b6fb3; --kr-bg: #eaf0fb;
  --us: #1a5c3a; --us-l: #2e8b57; --us-bg: #e6f4ec;
  --bg: #eef1f7; --card: #ffffff; --txt: #1c2430;
  --sub: #5a6b7e; --border: #dde4ef;
}}
@media (prefers-color-scheme: dark) {{
  :root {{
    --bg: #0f1620; --card: #1a2332; --txt: #e8edf5;
    --sub: #8a9ab0; --border: #2a3548;
    --kr-bg: #152038; --us-bg: #0f2820;
  }}
}}
:root[data-theme="light"] {{ --bg:#eef1f7;--card:#ffffff;--txt:#1c2430;--sub:#5a6b7e;--border:#dde4ef;--kr-bg:#eaf0fb;--us-bg:#e6f4ec; }}
:root[data-theme="dark"]  {{ --bg:#0f1620;--card:#1a2332;--txt:#e8edf5;--sub:#8a9ab0;--border:#2a3548;--kr-bg:#152038;--us-bg:#0f2820; }}

* {{ box-sizing:border-box; margin:0; padding:0; }}
body {{ background:var(--bg); color:var(--txt); font-family:'Apple SD Gothic Neo','Malgun Gothic',system-ui,sans-serif; line-height:1.65; }}

/* header */
.header {{ background:linear-gradient(135deg,#0d2040 0%,#1b3a6b 50%,#1a5c3a 100%); padding:32px 28px 28px; }}
.header-inner {{ max-width:700px; margin:0 auto; }}
.brand {{ font-size:13px; font-weight:800; letter-spacing:.15em; text-transform:uppercase; color:rgba(255,255,255,.6); margin-bottom:8px; }}
.header h1 {{ font-family:Georgia,serif; font-size:clamp(20px,3.5vw,28px); font-weight:700; color:#fff; line-height:1.25; }}
.header-meta {{ margin-top:12px; display:flex; gap:16px; flex-wrap:wrap; font-size:12px; color:rgba(255,255,255,.65); }}

/* body */
.body {{ max-width:700px; margin:0 auto; padding:28px 16px 60px; }}

/* section headers */
.sec-head {{
  display:flex; align-items:center; gap:12px;
  padding:14px 18px; border-radius:12px; margin:24px 0 14px;
}}
.sec-head.kr {{ background:var(--kr-bg); border-left:5px solid var(--kr-l); }}
.sec-head.us {{ background:var(--us-bg); border-left:5px solid var(--us-l); }}
.sec-icon {{ font-size:22px; }}
.sec-title {{ font-size:15px; font-weight:800; }}
.sec-title.kr {{ color:var(--kr); }}
.sec-title.us {{ color:var(--us); }}
.sec-sub {{ font-size:12px; color:var(--sub); margin-top:2px; }}

/* pick cards */
.picks {{ display:flex; flex-direction:column; gap:10px; }}
.pick-card {{
  background:var(--card); border-radius:12px;
  padding:16px 18px; border:1px solid var(--border);
  box-shadow:0 1px 3px rgba(0,0,0,.06);
}}
.pick-top {{ display:flex; align-items:center; gap:8px; margin-bottom:8px; flex-wrap:wrap; }}
.pick-num {{
  width:24px; height:24px; border-radius:50%;
  background:var(--border); display:flex; align-items:center; justify-content:center;
  font-size:11px; font-weight:800; color:var(--sub); flex-shrink:0;
}}
.pick-name {{ font-size:16px; font-weight:800; color:var(--txt); }}
.pick-code {{ font-size:12px; color:var(--sub); }}
.pick-price {{ font-size:14px; font-weight:700; color:var(--sub); margin-bottom:10px; font-variant-numeric:tabular-nums; }}

/* badges */
.badge {{ display:inline-flex; align-items:center; padding:2px 9px; border-radius:20px; font-size:11px; font-weight:700; }}
.badge.green {{ background:#d4edda; color:#155724; }}
.badge.grey  {{ background:var(--border); color:var(--sub); }}
.badge.blue  {{ background:#d1e4f7; color:var(--kr); }}

/* stat rows */
.pick-stats {{ display:flex; flex-direction:column; gap:5px; }}
.ps-item {{ display:flex; align-items:center; gap:8px; font-size:13px; }}
.ps-label {{ color:var(--sub); width:70px; flex-shrink:0; font-size:12px; }}
.ps-val {{ font-weight:700; font-variant-numeric:tabular-nums; }}
.ps-val.pos {{ color:#1a7a46; }}
.ps-val.neg {{ color:#c0392b; }}
.bold-kr {{ color:var(--kr-l); }}

/* vol bar */
.vol-track {{ flex:1; max-width:100px; height:6px; background:var(--border); border-radius:3px; overflow:hidden; }}
.vol-fill {{ height:100%; background:linear-gradient(90deg,var(--kr-l),#5b9bd5); border-radius:3px; }}

/* info box */
.info-box {{
  background:var(--card); border:1px solid var(--border); border-radius:10px;
  padding:13px 16px; margin-top:20px; font-size:13px; color:var(--sub); line-height:1.7;
}}
.info-box b {{ color:var(--txt); }}

/* strategy pill */
.strategy-tag {{
  display:inline-block; padding:3px 10px; border-radius:20px;
  font-size:11px; font-weight:700; margin-left:auto;
}}
.strategy-tag.kr {{ background:var(--kr-bg); color:var(--kr-l); }}
.strategy-tag.us {{ background:var(--us-bg); color:var(--us-l); }}

/* positions */
.pos-section {{
  background:var(--card); border:1px solid var(--border); border-radius:12px;
  margin-bottom:20px; overflow:hidden;
}}
.pos-head {{
  display:flex; justify-content:space-between; align-items:center;
  padding:12px 16px; background:var(--bg); font-size:14px; font-weight:700;
  border-bottom:1px solid var(--border);
}}
.sell-alert {{
  background:#fff0f0; border-bottom:1px solid #f5c6cb;
  padding:9px 16px; font-size:13px; color:#c0392b; font-weight:700;
}}
.pos-table {{ width:100%; border-collapse:collapse; font-size:12.5px; }}
.pos-table th {{
  background:var(--bg); color:var(--sub); font-size:11px; font-weight:700;
  padding:7px 10px; text-align:right; border-bottom:1px solid var(--border);
}}
.pos-table th:first-child {{ text-align:left; }}
.pos-table td {{ padding:9px 10px; border-bottom:1px solid var(--border); text-align:right; vertical-align:middle; }}
.pos-table td:first-child {{ text-align:left; }}
.pos-table tr:last-child td {{ border-bottom:none; }}
.sell-badge {{ background:#c0392b; color:#fff; border-radius:20px; padding:2px 8px; font-size:11px; font-weight:700; white-space:nowrap; }}
.hold-badge {{ background:#d4edda; color:#155724; border-radius:20px; padding:2px 8px; font-size:11px; font-weight:700; }}
.sell-ret {{ color:#c0392b; font-weight:700; }}

/* footer */
.footer {{ background:var(--border); padding:20px 28px; font-size:11px; color:var(--sub); line-height:1.7; }}
.footer-inner {{ max-width:700px; margin:0 auto; }}
</style>
</head>
<body>

<div class="header">
  <div class="header-inner">
    <div class="brand">퀀트레터 · Weekly Signal</div>
    <h1>이번 주 알고리즘 추천 종목</h1>
    <div class="header-meta">
      <span>📅 발행일 {today}</span>
      <span>🇰🇷 KR 기준일 {kr_date_str}</span>
      <span>🇺🇸 US 기준일 {us_date_str}</span>
      <span>📌 매주 월요일 발송</span>
    </div>
  </div>
</div>

<div class="body">

  {us_pos_html}

  <!-- US -->
  <div class="sec-head us">
    <span class="sec-icon">🇺🇸</span>
    <div>
      <div class="sec-title us">미국 주식 — 모멘텀 전략</div>
      <div class="sec-sub">6개월 추세 상위 종목 | Sharpe 1.03 검증 · 초과수익 연 +14.6%</div>
    </div>
    <span class="strategy-tag us">Momentum Top {TOP_US}</span>
  </div>

  <div class="picks">
    {us_cards_html}
  </div>

  <div class="info-box">
    <b>모멘텀 전략이란?</b><br>
    6개월 수익률(60%) + 12개월 수익률(40%) 복합 점수로 상위 종목을 선별합니다.
    백테스트(2021–2026) 결과 연 CAGR <b>+28.0%</b>, 샤프 <b>1.03</b>으로
    S&P500 벤치마크 대비 연 <b>+14.6%</b> 초과수익을 기록했습니다.<br><br>
    <b>운용 방법:</b> 동일 비중 월 1회 리밸런싱 (매월 첫 주). 중기 보유(1개월) 기준.
  </div>

  {kr_pos_html}

  <!-- KR LowVol -->
  <div class="sec-head kr">
    <span class="sec-icon">🇰🇷</span>
    <div>
      <div class="sec-title kr">한국 주식 ① — 저변동성 전략</div>
      <div class="sec-sub">연간 변동성이 가장 낮은 KOSPI 상위 종목 | Sharpe 1.05 검증</div>
    </div>
    <span class="strategy-tag kr">LowVol Top {TOP_KR}</span>
  </div>

  <div class="picks">
    {kr_cards_html}
  </div>

  <div class="info-box">
    <b>저변동성 전략이란?</b><br>
    과거 1년간 가격 변동이 가장 안정적인 종목을 선별합니다. 백테스트(2021–2026) 결과
    샤프 비율 <b>1.05</b>로 단순 모멘텀(0.51) 대비 2배 높은 위험조정 수익을 기록했습니다.
    최대 낙폭 –12.8%로 KOSPI 지수(-34.6%)보다 훨씬 방어적으로 운용됩니다.<br><br>
    <b>운용 방법:</b> 동일 비중 보유. 종목이 자신의 200일 이동평균 아래로 내려오면 청산 고려.
    <b>성향:</b> 안정 지향 · 방어적
  </div>

  <!-- KR MomSkip1m -->
  <div class="sec-head kr" style="border-left-color:#8e44ad">
    <span class="sec-icon">🇰🇷</span>
    <div>
      <div class="sec-title kr" style="color:#5b2d8e">한국 주식 ② — 반전회피 모멘텀</div>
      <div class="sec-sub">최근 1개월 제외한 6개월 추세 상위 종목 | Sharpe 0.59 · CAGR +28%</div>
    </div>
    <span class="strategy-tag kr" style="color:#5b2d8e">MomSkip1m Top {TOP_KR}</span>
  </div>

  <div class="picks">
    {kr_skip_cards_html}
  </div>

  <div class="info-box">
    <b>반전회피 모멘텀(MomSkip1m)이란?</b><br>
    한국 시장에서 최근 한 달 급등 종목은 다음 달 되돌림이 빠릅니다.
    이를 피하기 위해 <b>가장 최근 1개월을 제외</b>하고 그 이전 6개월의 추세를 봅니다.
    (측정 구간: D-147일 → D-21일) 백테스트 CAGR <b>+28.0%</b>, 단순 모멘텀 대비 샤프 개선.<br><br>
    <b>운용 방법:</b> 동일 비중 월 1회 리밸런싱. <b>성향:</b> 수익 추구 · 중위험
  </div>

  <div class="info-box" style="margin-top:14px;border-color:rgba(184,134,11,.3);background:rgba(184,134,11,.05)">
    ⚠️ <b>주의:</b> 본 시그널은 알고리즘이 자동 생성한 정보 제공 목적의 리스트입니다.
    개별 종목의 매수·매도 결정은 본인 판단으로 하시기 바랍니다.
    과거 백테스트 성과는 미래 수익을 보장하지 않습니다.
  </div>

</div>

<div class="footer">
  <div class="footer-inner">
    퀀트레터 · 유사투자자문업자(신고 예정) · no-reply@quantletter.example<br>
    본 콘텐츠는 불특정 다수 대상 정보 제공이며 개별 투자 자문이 아닙니다 (1:1 상담 불가).
    원금 손실 가능성이 있으며 과거 성과는 미래 수익을 보장하지 않습니다.
  </div>
</div>

</body>
</html>"""


# ── 메인 ─────────────────────────────────────────────────────

def main():
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    print("=== 퀀트레터 듀얼마켓 주간 리포트 ===\n")

    print("[KR ①] 저변동성 전략 계산 중...")
    kr_prices, kr_names  = load_kr()
    kr_picks, kr_date    = kr_lowvol_picks(kr_prices, kr_names)
    print(f"  기준일: {kr_date.strftime('%Y-%m-%d')}")
    for p in kr_picks:
        print(f"  {p['rank']}. {p['name']} ({p['code']})  변동성 {p['vol_pct']}%  6m {_sgn(p['m6_pct'])}{p['m6_pct']}%")

    print("\n[KR ②] 반전회피 모멘텀(MomSkip1m) 계산 중...")
    kr_skip_picks, _ = kr_momskip_picks(kr_prices, kr_names)
    for p in kr_skip_picks:
        print(f"  {p['rank']}. {p['name']} ({p['code']})  추세 {_sgn(p['skip_pct'])}{p['skip_pct']}%  6m {_sgn(p['m6_pct'])}{p['m6_pct']}%")

    print("\n[US] 모멘텀 전략 계산 중...")
    us_prices         = load_us()
    us_picks, us_date = us_momentum_picks(us_prices)
    print(f"  기준일: {us_date.strftime('%Y-%m-%d')}")
    for p in us_picks:
        print(f"  {p['rank']}. {p['ticker']}  6m {_sgn(p['m6_pct'])}{p['m6_pct']}%  3m {_sgn(p['m3_pct'])}{p['m3_pct']}%")

    # ── 포지션 평가 (매도신호 체크)
    kr_name_fn = lambda code: kr_names.get(str(code), code)
    kr_all_tickers = [p["code"] for p in kr_picks] + [p["code"] for p in kr_skip_picks]

    print("\n[포지션] KR 보유 현황 평가...")
    kr_pos_rows, kr_closed = evaluate_positions(kr_prices, LEDGER_KR, kr_name_fn)
    if kr_closed:
        print(f"  매도 신호: {[kr_names.get(t,t) for t in kr_closed]}")
    open_new_positions(kr_prices, kr_all_tickers, kr_date, LEDGER_KR)

    print("[포지션] US 보유 현황 평가...")
    us_pos_rows, us_closed = evaluate_positions(us_prices, LEDGER_US)
    if us_closed:
        print(f"  매도 신호: {us_closed}")
    open_new_positions(us_prices, [p["ticker"] for p in us_picks], us_date, LEDGER_US)

    html = build_html(kr_picks, kr_skip_picks, kr_date, us_picks, us_date,
                      kr_pos_rows, us_pos_rows)
    out  = "out_weekly_dual.html"
    with open(out, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"\n저장: {out}")


if __name__ == "__main__":
    main()
