# -*- coding: utf-8 -*-
"""
퀀트레터 히스토리 배치 생성
============================
2026-06-01 부터 현재까지 주간·월간 리포트를 일괄 생성.

주간: 매주 금요일 종가 기준 (KR 저변동성·반전회피 / US 모멘텀)
월간: 자산배분 + 전략별 성적표 (US 모멘텀 / KR 저변동성 / KR 반전회피)

출력 폴더: quantletter/output/  (누적 저장)
사용: python generate_history.py
"""

import os, json
from datetime import datetime, timedelta

import numpy as np
import pandas as pd

# ── 설정 ──────────────────────────────────────────────────────
TOP_KR        = 5
TOP_US        = 6
LOOKBACK_DAYS = 126
MA_DAYS       = 100
STOP_PCT      = 0.15
OUT_DIR       = "output"

os.makedirs(OUT_DIR, exist_ok=True)
os.chdir(os.path.dirname(os.path.abspath(__file__)))


# ── 데이터 로드 ────────────────────────────────────────────────

def load_all():
    kr_df  = pd.read_csv("kr_stocks_5yr.csv", parse_dates=["date"], dtype={"Name": str})
    kr_px  = kr_df.pivot(index="date", columns="Name", values="close").sort_index()
    us_df  = pd.read_csv("all_stocks_5yr.csv", parse_dates=["date"])
    us_px  = us_df.pivot(index="date", columns="Name", values="close").sort_index()
    with open("kr_names.json", encoding="utf-8") as f:
        kr_names = json.load(f)

    def msi(s):
        s = s.copy(); s.index = s.index.to_period("M").to_timestamp()
        return s[~s.index.duplicated(keep="last")]

    gold  = msi(pd.read_csv("d_gold.csv",   index_col=0, parse_dates=True)["gold"])
    spx   = pd.read_csv("d_spx.csv",        index_col=0, parse_dates=True)
    spx.index = spx.index.to_period("M").to_timestamp()
    spx   = spx[~spx.index.duplicated(keep="last")]
    bond  = msi(pd.read_csv("d_bond.csv",   index_col=0, parse_dates=True)["y10"])
    fx    = msi(pd.read_csv("d_usdkrw.csv", index_col=0, parse_dates=True)["usdkrw"])
    kospi = msi(pd.read_csv("d_kospi.csv",  index_col=0, parse_dates=True)["kospi"])

    us_stk = (spx["spx"] + spx["div"].fillna(0)/12) / spx["spx"].shift(1) - 1
    y  = bond / 100.0
    br = pd.Series(index=y.index, dtype=float)
    n  = np.arange(1, 21)
    for i in range(1, len(y)):
        y0, y1 = y.iloc[i-1], y.iloc[i]
        c = y0/2; cf = np.full(20, c); cf[-1] += 1
        br.iloc[i] = y0/12 + ((cf/(1+y1/2)**n).sum()-1)
    fxr = fx.pct_change()
    def krw(r): return (1+r)*(1+fxr)-1

    macro = pd.DataFrame({
        "한국주식": kospi.pct_change(),
        "미국주식": krw(us_stk),
        "미국채권": krw(br),
        "금":       krw(gold.pct_change()),
    }).dropna()

    return kr_px, us_px, kr_names, macro


# ── 픽 계산 ────────────────────────────────────────────────────

def _sgn(v): return "+" if v >= 0 else ""
def _cls(v): return "pos" if v >= 0 else "neg"

def picks_lowvol(prices, names, cutoff, top_n=TOP_KR):
    h = prices[prices.index <= cutoff].dropna(axis=1, how="all")
    if len(h) < 252: return [], cutoff
    vol   = h.iloc[-252:].pct_change(fill_method=None).std() * np.sqrt(252)
    m6    = h.iloc[-1] / h.iloc[min(-LOOKBACK_DAYS, -len(h))] - 1
    ma200 = h.iloc[-200:].mean()
    above = h.iloc[-1] > ma200
    tbl   = pd.DataFrame({"vol":vol,"m6":m6,"above_ma200":above}).dropna().sort_values("vol")
    out = []
    for code, row in tbl.iterrows():
        if len(out) >= top_n: break
        out.append(dict(rank=len(out)+1, code=str(code), name=names.get(str(code),code),
                        price=float(h[code].iloc[-1]),
                        vol_pct=round(float(row["vol"])*100,1),
                        m6_pct=round(float(row["m6"])*100,1),
                        above_ma200=bool(row["above_ma200"])))
    return out, h.index[-1]

def picks_momskip(prices, names, cutoff, top_n=TOP_KR):
    h = prices[prices.index <= cutoff].dropna(axis=1, how="all")
    if len(h) < 150: return [], cutoff
    mom   = h.iloc[-21] / h.iloc[-147] - 1
    m6    = h.iloc[-1]  / h.iloc[min(-LOOKBACK_DAYS,-len(h))] - 1
    ma200 = h.iloc[-200:].mean()
    above = h.iloc[-1] > ma200
    tbl   = pd.DataFrame({"mom":mom,"m6":m6,"above_ma200":above}).dropna().sort_values("mom",ascending=False)
    out = []
    for code, row in tbl.head(top_n).iterrows():
        out.append(dict(rank=len(out)+1, code=str(code), name=names.get(str(code),code),
                        price=float(h[code].iloc[-1]),
                        skip_pct=round(float(row["mom"])*100,1),
                        m6_pct=round(float(row["m6"])*100,1),
                        above_ma200=bool(row["above_ma200"])))
    return out, h.index[-1]

def picks_us_mom(prices, cutoff, top_n=TOP_US):
    h = prices[prices.index <= cutoff].dropna(axis=1, how="all")
    if len(h) < LOOKBACK_DAYS+5: return [], cutoff
    m6    = h.iloc[-1]/h.iloc[-LOOKBACK_DAYS]-1
    m3    = h.iloc[-1]/h.iloc[-63]-1
    m12   = h.iloc[-1]/h.iloc[min(-252,-len(h))]-1
    vol   = h.pct_change(fill_method=None).iloc[-252:].std()*np.sqrt(252)
    score = m6.rank(pct=True)*0.6 + m12.rank(pct=True).fillna(0.5)*0.4
    tbl   = pd.DataFrame({"score":score,"m6":m6,"m3":m3,"m12":m12,"vol":vol}).dropna().sort_values("score",ascending=False)
    out = []
    for tk, row in tbl.head(top_n).iterrows():
        out.append(dict(rank=len(out)+1, ticker=tk, price=round(float(h[tk].iloc[-1]),2),
                        m6_pct=round(float(row["m6"])*100,1),
                        m3_pct=round(float(row["m3"])*100,1),
                        m12_pct=round(float(row["m12"])*100,1),
                        vol_pct=round(float(row["vol"])*100,1)))
    return out, h.index[-1]


# ── 성적표 계산 ────────────────────────────────────────────────

def compute_sc(ids, prices, base_ts, cutoff_ts, name_fn=None):
    """
    ids: list of column names in prices
    base_ts / cutoff_ts: pd.Timestamp
    returns dict or None
    """
    h_base   = prices[prices.index >= base_ts]
    h_cutoff = prices[prices.index <= cutoff_ts]
    valid = [i for i in ids if i in prices.columns
             and h_base[i].dropna().shape[0] > 0
             and h_cutoff[i].dropna().shape[0] > 0]
    if not valid:
        return None
    p0 = h_base[valid].dropna(how="all").iloc[0]   # 첫 거래일 가격
    p1 = h_cutoff[valid].dropna(how="all").iloc[-1] # 마지막 가격
    rets = (p1 / p0 - 1) * 100
    avg  = float(rets.mean())
    pos  = int((rets > 0).sum())
    rows = []
    for i in valid:
        r   = float(rets[i])
        lbl = name_fn(i) if name_fn else i
        rows.append({"id": i, "label": lbl, "ret": round(r,1), "above_avg": r > avg})
    rows.sort(key=lambda x: -x["ret"])
    return {
        "from":  str(base_ts.date()),
        "to":    str(cutoff_ts.date()),
        "avg":   round(avg, 1),
        "pos":   pos,
        "n":     len(valid),
        "rows":  rows,
    }


# ── 포지션 관리 ────────────────────────────────────────────────

def eval_ledger(led, prices, cutoff, name_fn=None):
    h  = prices[prices.index <= cutoff]
    ma = h.rolling(MA_DAYS).mean()
    rows, closed = [], []
    for tk, info in list(led.items()):
        if tk not in h.columns: continue
        s = h[tk].dropna()
        if len(s) < 2: continue
        cur   = float(s.iloc[-1])
        entry = info["entry"]
        ret   = (cur/entry-1)*100
        ma100 = float(ma[tk].dropna().iloc[-1]) if ma[tk].notna().any() else None
        stop  = entry*(1-STOP_PCT)
        trend = (ma100 is not None) and cur < ma100
        stopb = cur < stop
        sig   = trend or stopb
        reason= "추세이탈(100MA↓)" if trend else ("손절가 도달" if stopb else "—")
        display = name_fn(tk) if name_fn else tk
        rows.append(dict(ticker=tk, display=display, entry=entry, cur=cur,
                         ret=round(ret,1), ma100=round(ma100,2) if ma100 else None,
                         stop=round(stop,2), signal=sig, reason=reason,
                         entry_date=info.get("entry_date","—")))
        if sig: closed.append(tk)
    for tk in closed: led.pop(tk, None)
    rows.sort(key=lambda r: (not r["signal"], r["ret"]))
    return rows, closed

def add_to_ledger(led, tickers, prices, cutoff):
    h = prices[prices.index <= cutoff]
    for tk in tickers:
        if tk not in led and tk in h.columns:
            led[tk] = {"entry_date": str(cutoff.date()), "entry": float(h[tk].dropna().iloc[-1])}


# ── 공통 CSS ──────────────────────────────────────────────────

_CSS = """
:root{--kr:#1b3a6b;--kr-l:#2b6fb3;--kr-bg:#eaf0fb;--us:#1a5c3a;--us-l:#2e8b57;--us-bg:#e6f4ec;
      --pu:#5b2d8e;--pu-l:#8e44ad;--pu-bg:#f4ebfd;
      --bg:#eef1f7;--card:#ffffff;--txt:#1c2430;--sub:#5a6b7e;--border:#dde4ef}
@media(prefers-color-scheme:dark){:root{--bg:#0f1620;--card:#1a2332;--txt:#e8edf5;--sub:#8a9ab0;
  --border:#2a3548;--kr-bg:#152038;--us-bg:#0f2820;--pu-bg:#1e0f2e}}
:root[data-theme=light]{--bg:#eef1f7;--card:#fff;--txt:#1c2430;--sub:#5a6b7e;--border:#dde4ef;
  --kr-bg:#eaf0fb;--us-bg:#e6f4ec;--pu-bg:#f4ebfd}
:root[data-theme=dark]{--bg:#0f1620;--card:#1a2332;--txt:#e8edf5;--sub:#8a9ab0;--border:#2a3548;
  --kr-bg:#152038;--us-bg:#0f2820;--pu-bg:#1e0f2e}
*{box-sizing:border-box;margin:0;padding:0}
body{background:var(--bg);color:var(--txt);font-family:'Apple SD Gothic Neo','Malgun Gothic',system-ui,sans-serif;line-height:1.65}
.header{background:linear-gradient(135deg,#0d2040 0%,#1b3a6b 50%,#1a5c3a 100%);padding:28px 24px}
.header-inner{max-width:680px;margin:0 auto}
.brand{font-size:12px;font-weight:800;letter-spacing:.15em;text-transform:uppercase;color:rgba(255,255,255,.6);margin-bottom:6px}
.header h1{font-family:Georgia,serif;font-size:clamp(18px,3vw,26px);font-weight:700;color:#fff;line-height:1.25}
.header-meta{margin-top:10px;display:flex;gap:14px;flex-wrap:wrap;font-size:12px;color:rgba(255,255,255,.65)}
.body{max-width:680px;margin:0 auto;padding:24px 14px 52px}
.sec-head{display:flex;align-items:center;gap:10px;padding:12px 16px;border-radius:12px;margin:22px 0 12px}
.sec-head.kr{background:var(--kr-bg);border-left:5px solid var(--kr-l)}
.sec-head.us{background:var(--us-bg);border-left:5px solid var(--us-l)}
.sec-icon{font-size:20px}
.sec-title{font-size:14px;font-weight:800}
.sec-title.kr{color:var(--kr)}
.sec-title.us{color:var(--us)}
.sec-sub{font-size:11px;color:var(--sub);margin-top:2px}
.strategy-tag{display:inline-block;padding:2px 9px;border-radius:20px;font-size:11px;font-weight:700;margin-left:auto}
.strategy-tag.kr{background:var(--kr-bg);color:var(--kr-l)}
.strategy-tag.us{background:var(--us-bg);color:var(--us-l)}
.picks{display:flex;flex-direction:column;gap:9px}
.pick-card{background:var(--card);border-radius:11px;padding:14px 16px;border:1px solid var(--border);box-shadow:0 1px 3px rgba(0,0,0,.06)}
.pick-top{display:flex;align-items:center;gap:7px;margin-bottom:7px;flex-wrap:wrap}
.pick-num{width:22px;height:22px;border-radius:50%;background:var(--border);display:flex;align-items:center;justify-content:center;font-size:10px;font-weight:800;color:var(--sub);flex-shrink:0}
.pick-name{font-size:15px;font-weight:800;color:var(--txt)}
.pick-code{font-size:11px;color:var(--sub)}
.pick-price{font-size:13px;font-weight:700;color:var(--sub);margin-bottom:8px;font-variant-numeric:tabular-nums}
.badge{display:inline-flex;align-items:center;padding:2px 8px;border-radius:20px;font-size:10px;font-weight:700}
.badge.green{background:#d4edda;color:#155724}
.badge.grey{background:var(--border);color:var(--sub)}
.badge.blue{background:#d1e4f7;color:var(--kr)}
.pick-stats{display:flex;flex-direction:column;gap:4px}
.ps-item{display:flex;align-items:center;gap:7px;font-size:12.5px}
.ps-label{color:var(--sub);width:65px;flex-shrink:0;font-size:11.5px}
.ps-val{font-weight:700;font-variant-numeric:tabular-nums}
.ps-val.pos{color:#1a7a46}
.ps-val.neg{color:#c0392b}
.bold-kr{color:var(--kr-l)}
.vol-track{flex:1;max-width:90px;height:5px;background:var(--border);border-radius:3px;overflow:hidden}
.vol-fill{height:100%;background:linear-gradient(90deg,var(--kr-l),#5b9bd5);border-radius:3px}
.info-box{background:var(--card);border:1px solid var(--border);border-radius:10px;padding:12px 15px;margin-top:18px;font-size:12.5px;color:var(--sub);line-height:1.7}
.info-box b{color:var(--txt)}
.pos-section{background:var(--card);border:1px solid var(--border);border-radius:12px;margin-bottom:18px;overflow:hidden}
.pos-head{display:flex;justify-content:space-between;align-items:center;padding:10px 14px;background:var(--bg);font-size:13.5px;font-weight:700;border-bottom:1px solid var(--border)}
.sell-alert{background:#fff0f0;border-bottom:1px solid #f5c6cb;padding:8px 14px;font-size:12.5px;color:#c0392b;font-weight:700}
.pos-table{width:100%;border-collapse:collapse;font-size:12px}
.pos-table th{background:var(--bg);color:var(--sub);font-size:10.5px;font-weight:700;padding:6px 9px;text-align:right;border-bottom:1px solid var(--border)}
.pos-table th:first-child{text-align:left}
.pos-table td{padding:8px 9px;border-bottom:1px solid var(--border);text-align:right;vertical-align:middle}
.pos-table td:first-child{text-align:left}
.pos-table tr:last-child td{border-bottom:none}
.sell-badge{background:#c0392b;color:#fff;border-radius:20px;padding:2px 7px;font-size:10.5px;font-weight:700;white-space:nowrap}
.hold-badge{background:#d4edda;color:#155724;border-radius:20px;padding:2px 7px;font-size:10.5px;font-weight:700}
.sell-ret{color:#c0392b;font-weight:700}
.footer{background:var(--border);padding:16px 24px;font-size:11px;color:var(--sub);line-height:1.7}
.footer-inner{max-width:680px;margin:0 auto}
"""

# ── 월간 전용 CSS ─────────────────────────────────────────────

_CSS_M = _CSS + """
.m-card{background:var(--card);border:1px solid var(--border);border-radius:12px;padding:16px 18px;margin-bottom:14px}
.m-head{font-size:14px;font-weight:800;color:var(--txt);margin-bottom:10px;border-left:4px solid var(--kr-l);padding-left:9px;display:flex;align-items:baseline;gap:8px}
.m-head-period{font-size:11px;font-weight:400;color:var(--sub)}
.bar{height:13px;border-radius:7px;overflow:hidden;display:flex;margin:10px 0 4px}
.alloc-grid{display:flex;gap:9px;flex-wrap:wrap;margin:8px 0}
.a-card{flex:1;min-width:90px;background:var(--bg);border-radius:9px;padding:10px;text-align:center}
.a-name{font-size:11.5px;color:var(--sub)}
.a-val{font-size:20px;font-weight:800;margin-top:2px}
.kpi-row{display:flex;gap:9px;flex-wrap:wrap;margin:10px 0}
.kpi{background:var(--bg);border-radius:9px;padding:10px 12px;text-align:center;flex:1;min-width:80px}
.kn{font-size:10.5px;color:var(--sub)}
.kv{font-size:17px;font-weight:800;margin-top:2px}
.pos{color:#1a7a46}.neg{color:#c0392b}
/* 전략별 성적표 */
.sc-outer{margin-top:14px;display:flex;flex-direction:column;gap:10px}
.sc-strat{border:1px solid var(--border);border-radius:10px;overflow:hidden}
.sc-strat-head{display:flex;align-items:center;justify-content:space-between;padding:9px 13px;font-size:13px;font-weight:800}
.sc-strat-head.us{background:var(--us-bg);color:var(--us)}
.sc-strat-head.kr{background:var(--kr-bg);color:var(--kr)}
.sc-strat-head.pu{background:var(--pu-bg);color:var(--pu)}
.sc-avg-badge{font-size:12px;font-weight:700;padding:2px 8px;border-radius:20px}
.sc-avg-badge.pos{background:#d4edda;color:#155724}
.sc-avg-badge.neg{background:#fde8e8;color:#a00}
.sc-table{width:100%;border-collapse:collapse;font-size:12.5px}
.sc-table th{background:var(--bg);color:var(--sub);font-size:10.5px;font-weight:700;padding:5px 11px;text-align:right;border-bottom:1px solid var(--border)}
.sc-table th:first-child{text-align:left}
.sc-table td{padding:7px 11px;border-bottom:1px solid var(--border);text-align:right;font-variant-numeric:tabular-nums}
.sc-table td:first-child{text-align:left}
.sc-table tr:last-child td{border-bottom:none}
.above-avg{color:#1a7a46;font-weight:700}
.below-avg{color:#a05010}
.sc-empty{padding:11px 13px;color:var(--sub);font-size:12.5px}
"""


# ── 카드 빌더 ─────────────────────────────────────────────────

def kr_card(p):
    ma_b = '<span class="badge green">200MA 위</span>' if p["above_ma200"] else '<span class="badge grey">200MA 아래</span>'
    vw   = min(100, int(p["vol_pct"]/40*100))
    return (f'<div class="pick-card"><div class="pick-top"><span class="pick-num">{p["rank"]}</span>'
            f'<span class="pick-name">{p["name"]}</span><span class="pick-code">{p["code"]}</span>{ma_b}</div>'
            f'<div class="pick-price">₩{p["price"]:,.0f}</div>'
            f'<div class="pick-stats">'
            f'<div class="ps-item"><span class="ps-label">변동성</span>'
            f'<div class="vol-track"><div class="vol-fill" style="width:{vw}%"></div></div>'
            f'<span class="ps-val bold-kr">{p["vol_pct"]}%</span></div>'
            f'<div class="ps-item"><span class="ps-label">6개월</span>'
            f'<span class="ps-val {_cls(p["m6_pct"])}">{_sgn(p["m6_pct"])}{p["m6_pct"]}%</span></div>'
            f'</div></div>')

def kr_skip_card(p):
    ma_b = '<span class="badge green">200MA 위</span>' if p["above_ma200"] else '<span class="badge grey">200MA 아래</span>'
    return (f'<div class="pick-card"><div class="pick-top"><span class="pick-num">{p["rank"]}</span>'
            f'<span class="pick-name">{p["name"]}</span><span class="pick-code">{p["code"]}</span>{ma_b}</div>'
            f'<div class="pick-price">₩{p["price"]:,.0f}</div>'
            f'<div class="pick-stats">'
            f'<div class="ps-item"><span class="ps-label">추세점수</span>'
            f'<span class="ps-val {_cls(p["skip_pct"])}">{_sgn(p["skip_pct"])}{p["skip_pct"]}%</span></div>'
            f'<div class="ps-item"><span class="ps-label">6개월</span>'
            f'<span class="ps-val {_cls(p["m6_pct"])}">{_sgn(p["m6_pct"])}{p["m6_pct"]}%</span></div>'
            f'</div></div>')

def us_card(p):
    return (f'<div class="pick-card"><div class="pick-top"><span class="pick-num">{p["rank"]}</span>'
            f'<span class="pick-name">{p["ticker"]}</span><span class="badge blue">모멘텀 상위</span></div>'
            f'<div class="pick-price">${p["price"]:,.2f}</div>'
            f'<div class="pick-stats">'
            f'<div class="ps-item"><span class="ps-label">6개월</span><span class="ps-val {_cls(p["m6_pct"])}">{_sgn(p["m6_pct"])}{p["m6_pct"]}%</span></div>'
            f'<div class="ps-item"><span class="ps-label">3개월</span><span class="ps-val {_cls(p["m3_pct"])}">{_sgn(p["m3_pct"])}{p["m3_pct"]}%</span></div>'
            f'<div class="ps-item"><span class="ps-label">12개월</span><span class="ps-val {_cls(p["m12_pct"])}">{_sgn(p["m12_pct"])}{p["m12_pct"]}%</span></div>'
            f'</div></div>')


# ── 포지션 HTML ───────────────────────────────────────────────

def pos_section(rows, label, cur="₩"):
    if not rows: return ""
    sell  = [r for r in rows if r["signal"]]
    def fmt(v): return f"${v:,.2f}" if cur=="$" else f"₩{v:,.0f}"
    def row_html(r):
        bg = 'style="background:#fff5f5"' if r["signal"] else ""
        st = (f'<span class="sell-badge">매도 {r["reason"]}</span>' if r["signal"]
              else '<span class="hold-badge">보유유지</span>')
        ma  = fmt(r["ma100"]) if r["ma100"] else "—"
        rc  = "sell-ret" if r["signal"] else _cls(r["ret"])
        return (f'<tr {bg}><td><b>{r["display"]}</b><br>'
                f'<span style="font-size:11px;color:#8090a0">{r["entry_date"]}</span></td>'
                f'<td>{fmt(r["entry"])}</td><td>{fmt(r["cur"])}</td>'
                f'<td class="{rc}">{_sgn(r["ret"])}{r["ret"]}%</td>'
                f'<td>{ma}</td><td>{fmt(r["stop"])}</td><td>{st}</td></tr>')
    alert = (f'<div class="sell-alert">⚠️ 매도 신호 {len(sell)}건 — '
             + ", ".join(r["display"] for r in sell) + '</div>') if sell else ""
    trs   = "".join(row_html(r) for r in rows)
    return (f'<div class="pos-section"><div class="pos-head">'
            f'<span>📋 {label} 보유 현황</span>'
            f'<span style="font-size:12px;color:#8090a0">{len(rows)}종목</span></div>'
            f'{alert}<div style="overflow-x:auto"><table class="pos-table">'
            f'<thead><tr><th>종목</th><th>진입가</th><th>현재가</th>'
            f'<th>수익률</th><th>100MA</th><th>손절가</th><th>상태</th></tr></thead>'
            f'<tbody>{trs}</tbody></table></div></div>')


# ── 월간 성적표 HTML 블록 ──────────────────────────────────────

def _sc_strat_block(sc, cls, icon, strat_name):
    """전략 하나의 성적표 HTML."""
    if sc is None:
        return (f'<div class="sc-strat"><div class="sc-strat-head {cls}">'
                f'{icon} {strat_name}</div>'
                f'<div class="sc-empty">해당 기간 데이터 없음</div></div>')

    avg_cls = "pos" if sc["avg"] >= 0 else "neg"
    badge   = f'<span class="sc-avg-badge {avg_cls}">{_sgn(sc["avg"])}{sc["avg"]}% 평균</span>'
    def row_h(r):
        ret_cls = "above-avg" if r["above_avg"] else "below-avg"
        mark    = "▲" if r["above_avg"] else "▽"
        return (f'<tr><td><b>{r["label"]}</b></td>'
                f'<td class="{"pos" if r["ret"]>=0 else "neg"}">{_sgn(r["ret"])}{r["ret"]}%</td>'
                f'<td class="{ret_cls}">{mark} 평균대비 {_sgn(r["ret"]-sc["avg"])}{round(r["ret"]-sc["avg"],1)}%</td></tr>')
    trs = "".join(row_h(r) for r in sc["rows"])
    return (f'<div class="sc-strat">'
            f'<div class="sc-strat-head {cls}">{icon} {strat_name} '
            f'<span style="font-size:11px;font-weight:400">{sc["pos"]}/{sc["n"]} 종목 양수</span>'
            f'{badge}</div>'
            f'<div style="overflow-x:auto"><table class="sc-table">'
            f'<thead><tr><th>종목</th><th>수익률</th><th>전략 내 비교</th></tr></thead>'
            f'<tbody>{trs}</tbody></table></div></div>')

def scorecard_html(sc_us, sc_kr_lv, sc_kr_skip, period_from, period_to):
    """3개 전략 통합 성적표 HTML."""
    # 전체 종합 통계
    all_rets = []
    for sc in [sc_us, sc_kr_lv, sc_kr_skip]:
        if sc: all_rets.extend(r["ret"] for r in sc["rows"])
    if not all_rets:
        return '<div class="m-card"><div class="m-head">📋 지난달 추천 성적표</div><div class="sc-empty">첫 발송이라 아직 누적된 추천이 없습니다.</div></div>'

    total_avg = round(sum(all_rets)/len(all_rets),1)
    total_pos = sum(1 for r in all_rets if r > 0)
    total_n   = len(all_rets)

    kpi_cls  = "pos" if total_avg >= 0 else "neg"
    kpi2_cls = "pos" if total_pos >= total_n/2 else "neg"

    us_block     = _sc_strat_block(sc_us,     "us", "🇺🇸", "미국 모멘텀")
    kr_lv_block  = _sc_strat_block(sc_kr_lv,  "kr", "🇰🇷", "한국 ① 저변동성")
    kr_sk_block  = _sc_strat_block(sc_kr_skip,"pu", "🇰🇷", "한국 ② 반전회피 모멘텀")

    return f"""<div class="m-card">
  <div class="m-head">📋 지난달 추천 성적표
    <span class="m-head-period">{period_from} → {period_to}</span></div>
  <div class="kpi-row">
    <div class="kpi"><div class="kn">전체 평균</div>
      <div class="kv {kpi_cls}">{_sgn(total_avg)}{total_avg}%</div></div>
    <div class="kpi"><div class="kn">수익 종목</div>
      <div class="kv {kpi2_cls}">{total_pos} / {total_n}</div></div>
  </div>
  <div class="sc-outer">
    {us_block}
    {kr_lv_block}
    {kr_sk_block}
  </div>
</div>"""


# ── 자산배분 계산 ─────────────────────────────────────────────

TILT4      = [0.40, 0.30, 0.20, 0.10]
BAR_COLORS = {"한국주식":"#2b6fb3","미국주식":"#3da35d","금":"#e0a020","미국채권":"#8e44ad","현금":"#9aa7b5"}

def alloc_weights(macro, cutoff):
    R  = macro[macro.index <= cutoff].dropna()
    if len(R) < 13:
        return {"현금": 1.0}, pd.Series(dtype=float)
    px = (1+R).cumprod()
    sc = sum((px/px.shift(lb)-1) for lb in [1,3,6,12]) / 4.0
    s  = sc.iloc[-1]
    order = s.sort_values(ascending=False).index
    w = {a: TILT4[i] for i,a in enumerate(order)}
    cash = 0.0
    for a in R.columns:
        if s[a] <= 0:
            cash += w[a]; w[a] = 0.0
    w["현금"] = cash
    return w, s


# ── 주간 HTML ─────────────────────────────────────────────────

def build_weekly(cutoff, kr_lv, kr_sk, us_mo, us_pos, kr_pos):
    pub  = cutoff.strftime("%Y년 %m월 %d일")
    asof = cutoff.strftime("%Y-%m-%d")
    us_ph = pos_section(us_pos, "🇺🇸 미국주식", "$")
    kr_ph = pos_section(kr_pos, "🇰🇷 한국주식", "₩")
    lv_h  = "".join(kr_card(p) for p in kr_lv)
    sk_h  = "".join(kr_skip_card(p) for p in kr_sk)
    us_h  = "".join(us_card(p) for p in us_mo)

    return f"""<!DOCTYPE html>
<html lang="ko"><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>퀀트레터 WEEKLY — {asof}</title>
<style>{_CSS}</style></head><body>
<div class="header"><div class="header-inner">
  <div class="brand">퀀트레터 · Weekly Signal</div>
  <h1>이번 주 알고리즘 추천 종목</h1>
  <div class="header-meta">
    <span>📅 발행일 {pub}</span>
    <span>🇰🇷🇺🇸 기준일 {asof}</span>
    <span>📌 매주 발송</span>
  </div>
</div></div>
<div class="body">
  {us_ph}
  <div class="sec-head us"><span class="sec-icon">🇺🇸</span>
    <div><div class="sec-title us">미국 주식 — 모멘텀 전략</div>
    <div class="sec-sub">6개월 추세 상위 | Sharpe 1.03 · 초과수익 +14.6%/년</div></div>
    <span class="strategy-tag us">Top {TOP_US}</span>
  </div>
  <div class="picks">{us_h}</div>

  {kr_ph}
  <div class="sec-head kr"><span class="sec-icon">🇰🇷</span>
    <div><div class="sec-title kr">한국 ① 저변동성 전략</div>
    <div class="sec-sub">연간 변동성 최소 | Sharpe 1.05 · MDD –12.8%</div></div>
    <span class="strategy-tag kr">LowVol {TOP_KR}</span>
  </div>
  <div class="picks">{lv_h}</div>

  <div class="sec-head kr" style="border-left-color:#8e44ad"><span class="sec-icon">🇰🇷</span>
    <div><div class="sec-title kr" style="color:#5b2d8e">한국 ② 반전회피 모멘텀</div>
    <div class="sec-sub">최근 1개월 제외 6개월 추세 | CAGR +28%</div></div>
    <span class="strategy-tag kr" style="color:#5b2d8e">MomSkip {TOP_KR}</span>
  </div>
  <div class="picks">{sk_h}</div>

  <div class="info-box" style="margin-top:14px;border-color:rgba(184,134,11,.3);background:rgba(184,134,11,.05)">
    ⚠️ 본 시그널은 알고리즘이 자동 생성한 정보 제공용 리스트입니다. 투자 결정은 본인 판단으로 하시기 바랍니다.
  </div>
</div>
<div class="footer"><div class="footer-inner">
  퀀트레터 · 유사투자자문업자(신고 예정) · 본 콘텐츠는 불특정 다수 대상 정보 제공이며 개별 투자 자문이 아닙니다.
</div></div></body></html>"""


# ── 월간 HTML ─────────────────────────────────────────────────

def build_monthly(year, month, w, s, sc_us, sc_kr_lv, sc_kr_skip,
                  sc_from=None, sc_to=None):
    ym   = f"{year}-{month:02d}"
    asof = f"{year}-{month:02d}-{'30' if month==6 else '27'}"

    bar_segs   = "".join(
        f'<div style="width:{int(v*100)}%;background:{BAR_COLORS.get(k,"#aaa")}"></div>'
        for k,v in w.items() if v > 0)
    alloc_cards = "".join(
        f'<div class="a-card"><div class="a-name">{k}</div>'
        f'<div class="a-val" style="color:{BAR_COLORS.get(k,"#555")}">{int(v*100)}%</div></div>'
        for k,v in w.items() if v > 0)
    score_str = " · ".join(f"{k} <b>{v*100:.0f}</b>" for k,v in s.items()) if hasattr(s,"items") else ""

    sc_block = scorecard_html(sc_us, sc_kr_lv, sc_kr_skip,
                              sc_from or "—", sc_to or "—")

    return f"""<!DOCTYPE html>
<html lang="ko"><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>퀀트레터 MONTHLY — {ym}</title>
<style>{_CSS_M}</style></head><body>
<div class="header"><div class="header-inner">
  <div class="brand">퀀트레터 · Monthly</div>
  <h1>이달의 자산배분 &amp; 성적표</h1>
  <div class="header-meta">
    <span>📅 {year}년 {month}월호</span>
    <span>기준일 {asof}</span>
    <span>📌 매월 첫 주 발송</span>
  </div>
</div></div>
<div class="body">
  <div class="m-card">
    <div class="m-head">🧭 이달의 자산배분</div>
    <div class="bar">{bar_segs}</div>
    <div class="alloc-grid">{alloc_cards}</div>
    <div class="info-box" style="margin-top:8px;font-size:11.5px">
      모멘텀 점수 (최근 12개월 이동평균): {score_str}
    </div>
  </div>

  {sc_block}

  <div class="info-box" style="border-color:rgba(184,134,11,.3);background:rgba(184,134,11,.05)">
    ⚠️ 본 콘텐츠는 불특정 다수 대상 정보 제공이며 개별 투자 자문이 아닙니다.
    과거 성과는 미래 수익을 보장하지 않습니다.
  </div>
</div>
<div class="footer"><div class="footer-inner">퀀트레터 · 유사투자자문업자(신고 예정)</div></div>
</body></html>"""


# ── 인덱스 페이지 ─────────────────────────────────────────────

def build_index(weekly_files, monthly_files):
    w_rows = "".join(
        f'<tr><td><a href="{os.path.basename(f)}">'
        f'{os.path.basename(f).replace("weekly_","").replace(".html","")}</a></td><td>주간</td></tr>'
        for f in weekly_files)
    m_rows = "".join(
        f'<tr><td><a href="{os.path.basename(f)}">'
        f'{os.path.basename(f).replace("monthly_","").replace(".html","")}</a></td><td>월간</td></tr>'
        for f in monthly_files)
    return f"""<!DOCTYPE html>
<html lang="ko"><head><meta charset="UTF-8">
<title>퀀트레터 리포트 목록</title>
<style>
body{{font-family:'Apple SD Gothic Neo','Malgun Gothic',system-ui,sans-serif;max-width:500px;margin:40px auto;padding:0 16px;color:#1c2430;background:#eef1f7}}
h1{{font-family:Georgia,serif;font-size:22px;margin-bottom:6px}}
p{{color:#5a6b7e;font-size:13px;margin-bottom:24px}}
table{{width:100%;border-collapse:collapse;font-size:14px}}
th{{background:#f4f7fb;padding:9px 10px;text-align:left;color:#5a6b7e;font-size:11.5px;border-bottom:2px solid #dde4ef}}
td{{padding:9px 10px;border-bottom:1px solid #dde4ef}}
a{{color:#2b6fb3;text-decoration:none;font-weight:700}}
a:hover{{text-decoration:underline}}
</style></head><body>
<h1>퀀트레터 리포트</h1>
<p>2026년 6월 ~ 7월 | 자동 생성</p>
<table><thead><tr><th>날짜</th><th>구분</th></tr></thead>
<tbody>{m_rows}{w_rows}</tbody></table>
</body></html>"""


# ── 메인 ──────────────────────────────────────────────────────

def get_fridays(start_date, end_date):
    d = start_date
    while d.weekday() != 4:
        d += timedelta(days=1)
    out = []
    while d <= end_date:
        out.append(d)
        d += timedelta(weeks=1)
    return out


def main():
    print("=== 퀀트레터 히스토리 배치 생성 ===\n")
    print("데이터 로딩...")
    kr_px, us_px, kr_names, macro = load_all()
    name_fn = lambda c: kr_names.get(str(c), c)

    START = datetime(2026, 6, 1)
    END   = datetime(2026, 7, 27)

    fridays      = get_fridays(START, END)
    weekly_files = []
    monthly_files= []

    # 인메모리 포지션 원장
    kr_led = {}
    us_led = {}

    # 주간 픽 기록 (날짜 → 픽 목록), 월간 성적표 계산용
    weekly_picks = {}  # {datetime: {us, kr_lv, kr_skip}}

    print(f"\n주간 리포트 생성 ({len(fridays)}주)...")
    for cutoff in fridays:
        label = cutoff.strftime("%Y-%m-%d")
        print(f"  {label}...", end=" ")

        kr_lv, _ = picks_lowvol(kr_px, kr_names, cutoff)
        kr_sk, _ = picks_momskip(kr_px, kr_names, cutoff)
        us_mo, _ = picks_us_mom(us_px, cutoff)

        if not kr_lv or not us_mo:
            print("SKIP (데이터 부족)")
            continue

        # 픽 기록 저장
        weekly_picks[cutoff] = {
            "us":     [p["ticker"] for p in us_mo],
            "kr_lv":  [p["code"]   for p in kr_lv],
            "kr_skip":[p["code"]   for p in kr_sk],
        }

        # 포지션 평가
        kr_pos, kr_cls = eval_ledger(kr_led, kr_px, cutoff, name_fn)
        us_pos, us_cls = eval_ledger(us_led, us_px, cutoff)

        # 신규 편입
        add_to_ledger(kr_led, weekly_picks[cutoff]["kr_lv"] + weekly_picks[cutoff]["kr_skip"], kr_px, cutoff)
        add_to_ledger(us_led, weekly_picks[cutoff]["us"], us_px, cutoff)

        html  = build_weekly(cutoff, kr_lv, kr_sk, us_mo, us_pos, kr_pos)
        fname = os.path.join(OUT_DIR, f"weekly_{label}.html")
        with open(fname, "w", encoding="utf-8") as f:
            f.write(html)
        weekly_files.append(fname)

        sells = [name_fn(t) for t in kr_cls] + list(us_cls)
        print(f"OK | KR:{len(kr_led)} US:{len(us_led)}"
              + (f" | 매도: {sells}" if sells else ""))

    # ── 월간 리포트 ──────────────────────────────────────────
    print("\n월간 리포트 생성...")

    MONTHLY_SPECS = [
        (2026, 6, "2026-06-30"),
        (2026, 7, "2026-07-27"),
    ]

    for year, month, cutoff_str in MONTHLY_SPECS:
        cutoff = pd.Timestamp(cutoff_str)
        w, s   = alloc_weights(macro, cutoff)

        # 성적표 기간: 해당 월의 첫 번째 금요일 → 마지막 금요일
        month_fridays = [
            f for f in fridays
            if f.year == year and f.month == month and f in weekly_picks
        ]

        sc_us = sc_kr_lv = sc_kr_skip = None
        sc_from_str = sc_to_str = None

        if len(month_fridays) >= 2:
            base_dt   = pd.Timestamp(month_fridays[0])   # 첫 금요일 (픽 발행일)
            end_dt    = pd.Timestamp(month_fridays[-1])   # 마지막 금요일 (성과 측정일)
            picks_base = weekly_picks[month_fridays[0]]
            sc_from_str = str(base_dt.date())
            sc_to_str   = str(end_dt.date())

            sc_us    = compute_sc(picks_base["us"],     us_px, base_dt, end_dt)
            sc_kr_lv = compute_sc(picks_base["kr_lv"],  kr_px, base_dt, end_dt, name_fn)
            sc_kr_skip= compute_sc(picks_base["kr_skip"],kr_px, base_dt, end_dt, name_fn)

        html  = build_monthly(year, month, w, s,
                              sc_us, sc_kr_lv, sc_kr_skip,
                              sc_from_str, sc_to_str)
        fname = os.path.join(OUT_DIR, f"monthly_{year}-{month:02d}.html")
        with open(fname, "w", encoding="utf-8") as f:
            f.write(html)
        monthly_files.append(fname)

        if sc_us:
            print(f"  {year}-{month:02d}: 자산배분 {[f'{k} {int(v*100)}%' for k,v in w.items() if v>0]} | "
                  f"성적표 {sc_from_str}~{sc_to_str} "
                  f"US{sc_us['avg']:+.1f}% KR저변동성{sc_kr_lv['avg'] if sc_kr_lv else '—':}{''}")
        else:
            print(f"  {year}-{month:02d}: 성적표 데이터 없음")

    # ── 인덱스 ──
    idx = build_index(list(reversed(weekly_files)), list(reversed(monthly_files)))
    with open(os.path.join(OUT_DIR, "index.html"), "w", encoding="utf-8") as f:
        f.write(idx)

    total = len(weekly_files) + len(monthly_files)
    print(f"\n완료: {total}개 파일 → {OUT_DIR}/")


if __name__ == "__main__":
    main()
