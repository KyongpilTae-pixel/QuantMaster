"""유동성 국면 게이지 + 전략 성과 상관 — cloud-014 요청
FRED: NFCI, M2SL, FEDFUNDS, DFII10, BAMLH0A0HYM2
게이지: 완화(≥+2) / 중립 / 긴축(≤-2)
전략 성과: (a) US 12M 모멘텀 top20 시뮬, (b) GP touch 이벤트, (c) SPY 벤치
"""
import sys, io, json, warnings
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
warnings.filterwarnings("ignore")

import pandas as pd
import numpy as np

# ── FRED 데이터 수집 ─────────────────────────────────────────────────────────
print("FRED 데이터 수집 중 ...", flush=True)

import pandas_datareader.data as web

START = "2015-01-01"
END   = "2026-01-01"

nfci     = web.DataReader("NFCI",          "fred", START, END)
m2       = web.DataReader("M2SL",          "fred", START, END)
fedfunds = web.DataReader("FEDFUNDS",      "fred", START, END)
dfii10   = web.DataReader("DFII10",        "fred", START, END)
hy_oas   = web.DataReader("BAMLH0A0HYM2", "fred", START, END)
print(f"  NFCI: {nfci.index[0].date()}~{nfci.index[-1].date()} ({len(nfci)}행)", flush=True)
print(f"  M2SL: {m2.index[0].date()}~{m2.index[-1].date()} ({len(m2)}행)", flush=True)
print(f"  FEDFUNDS: {fedfunds.index[0].date()}~{fedfunds.index[-1].date()} ({len(fedfunds)}행)", flush=True)
print(f"  DFII10: {dfii10.index[0].date()}~{dfii10.index[-1].date()} ({len(dfii10)}행)", flush=True)
print(f"  HY OAS: {hy_oas.index[0].date()}~{hy_oas.index[-1].date()} ({len(hy_oas)}행)", flush=True)
print("  FRED 수집 완료", flush=True)

# ── 월말 리샘플 ─────────────────────────────────────────────────────────────
def resample_me(df):
    return df.resample("ME").last().ffill()

nfci_m     = resample_me(nfci)
m2_m       = resample_me(m2)
fedfunds_m = resample_me(fedfunds)
dfii10_m   = resample_me(dfii10)
hy_m       = resample_me(hy_oas)

# 공통 인덱스
idx_start = pd.Timestamp("2019-01-01")
idx_end   = pd.Timestamp("2025-12-31")

# ── 게이지 점수화 ────────────────────────────────────────────────────────────
def score_nfci(s):
    """NFCI < 0 완화(+1), > 0 긴축(-1)"""
    return np.where(s < -0.1, 1, np.where(s > 0.1, -1, 0))

def score_m2_yoy(s):
    """M2 YoY: 상위(>5%) +1, 마이너스·하락(<0%) -1"""
    yoy = s.pct_change(12) * 100
    return np.where(yoy > 5, 1, np.where(yoy < 0, -1, 0))

def score_fedfunds(s):
    """6개월 변화: 인하(-0.25이상) +1, 인상(+0.25이상) -1"""
    chg = s.diff(6)
    return np.where(chg <= -0.25, 1, np.where(chg >= 0.25, -1, 0))

def score_real_rate(s):
    """DFII10 실질금리: 절대 수준 기준 낮으면 완화, 높으면 긴축
    < 0% 완화(+1), > 1.5% 긴축(-1)"""
    return np.where(s < 0, 1, np.where(s > 1.5, -1, 0))

# outer join으로 전체 월 인덱스 생성 (데이터 누락 시 score=0)
all_monthly_idx = nfci_m.index.union(m2_m.index).union(fedfunds_m.index).union(hy_m.index)
all_monthly_idx = all_monthly_idx[(all_monthly_idx >= "2019-01-01") & (all_monthly_idx <= "2025-12-31")]

# 합산 프레임
gauge = pd.DataFrame(index=all_monthly_idx)
gauge["s_nfci"]   = score_nfci(nfci_m["NFCI"].reindex(all_monthly_idx).ffill())
gauge["s_m2"]     = score_m2_yoy(m2_m["M2SL"].reindex(all_monthly_idx).ffill())
gauge["s_fed"]    = score_fedfunds(fedfunds_m["FEDFUNDS"].reindex(all_monthly_idx).ffill())
gauge["s_rr"]     = score_real_rate(dfii10_m["DFII10"].reindex(all_monthly_idx).ffill())
gauge["total"]    = gauge[["s_nfci","s_m2","s_fed","s_rr"]].sum(axis=1)
gauge["regime"]   = np.where(gauge["total"] >= 2, "완화",
                    np.where(gauge["total"] <= -2, "긴축", "중립"))

g = gauge.dropna(subset=["total"]).copy()
print(f"\n게이지 기간: {g.index[0].date()} ~ {g.index[-1].date()}", flush=True)
print(g["regime"].value_counts().to_string(), flush=True)

# ── 전략 수익률 — SPY(벤치) + US 12M 모멘텀 시뮬 ──────────────────────────
print("\n벤치마크(SPY) 다운로드 ...", flush=True)
import yfinance as yf

spy_raw = yf.download("SPY", start="2018-01-01", end="2026-01-01",
                      auto_adjust=True, progress=False)
spy_close = spy_raw["Close"].squeeze()
spy_close.index = pd.to_datetime(spy_close.index).tz_localize(None)
spy_monthly = spy_close.resample("ME").last().pct_change() * 100

# US top20 모멘텀 시뮬 (12M mom, 월 리밸, 20종목 균등)
US_UNIVERSE_YF = [
    "AAPL","MSFT","GOOGL","META","NVDA","AMZN","INTC","CSCO","ORCL","IBM",
    "QCOM","TXN","AVGO","MU","ADI","AMAT","LRCX","KLAC","MCHP",
    "JPM","BAC","WFC","GS","MS","C","BRK-B","AXP","USB","PNC",
    "JNJ","PFE","UNH","ABBV","MRK","ABT","TMO","DHR","BMY","AMGN",
    "GILD","CVS","LLY","MDT","ISRG","SYK","BDX","BSX",
    "WMT","HD","PG","KO","PEP","MCD","SBUX","NKE","TGT","COST",
    "DIS","VZ","T","CMCSA","NFLX","LOW","TJX",
    "XOM","CVX","COP","SLB","HAL","CAT","BA","GE","HON",
    "DE","EMR","LMT","RTX","NOC","UPS","FDX","CSX",
]
print(f"모멘텀 포트 데이터 다운로드: {len(US_UNIVERSE_YF)}종목 ...", flush=True)
raw_us = yf.download(
    US_UNIVERSE_YF, start="2018-01-01", end="2026-01-01",
    auto_adjust=True, progress=False, group_by="ticker", threads=True,
)

def get_price(tk):
    try:
        c = raw_us[tk]["Close"].squeeze()
        c.index = pd.to_datetime(c.index).tz_localize(None)
        return c.dropna()
    except:
        return None

prices_dict = {tk: get_price(tk) for tk in US_UNIVERSE_YF}
prices_dict = {k: v for k, v in prices_dict.items() if v is not None and len(v) > 300}

# 월말 가격 피벗
all_monthly = {}
for tk, s in prices_dict.items():
    m = s.resample("ME").last()
    all_monthly[tk] = m
price_df = pd.DataFrame(all_monthly).dropna(how="all")

# 12M 모멘텀 → 매월 top20 선택 → 다음달 수익
mom12 = price_df.pct_change(12)
mom_returns = []
mom_dates   = []

month_ends = price_df.loc["2019-01-01":"2025-12-31"].index
for i, dt in enumerate(month_ends[:-1]):
    try:
        mom_row = mom12.loc[dt].dropna()
        top20   = mom_row.nlargest(20).index.tolist()
        nxt_dt  = month_ends[i + 1]
        rets    = []
        for tk in top20:
            if tk in price_df.columns:
                p0 = price_df.loc[dt, tk]
                p1 = price_df.loc[nxt_dt, tk]
                if pd.notna(p0) and pd.notna(p1) and p0 > 0:
                    rets.append((p1/p0 - 1) * 100)
        if rets:
            mom_returns.append(np.mean(rets))
            mom_dates.append(nxt_dt)
    except:
        pass

mom_series = pd.Series(mom_returns, index=mom_dates, name="mom20")

# GP 이벤트(US) 월별 수익 — us_eventstudy_results_v3.json에서 로드
gp_monthly = {}
try:
    with open(r"C:\project\quant\us_eventstudy_results_v3.json", encoding="utf-8") as f:
        v3 = json.load(f)
    for trade in v3["trades"]:
        if trade["type"] == "touch":
            dt = pd.Timestamp(trade["date"]).to_period("M").to_timestamp("M")
            if dt not in gp_monthly:
                gp_monthly[dt] = []
            gp_monthly[dt].append(trade["ret12m"] / 12)  # 12M수익 월할당
    gp_series = pd.Series({k: np.mean(v) for k, v in gp_monthly.items()}, name="gp_touch")
    gp_series.index = pd.DatetimeIndex(gp_series.index)
    print(f"  GP touch 이벤트 월별 수익 로드: {len(gp_series)}개월", flush=True)
except Exception as e:
    gp_series = pd.Series(dtype=float, name="gp_touch")
    print(f"  GP 이벤트 로드 실패: {e}", flush=True)

# ── 국면별 성과 집계 ─────────────────────────────────────────────────────────
def regime_stats(ret_series, gauge_df):
    """완화/중립/긴축별 평균·Sharpe·승률 계산"""
    aligned = pd.DataFrame({"ret": ret_series, "regime": gauge_df["regime"]}).dropna()
    results = {}
    for regime in ["완화", "중립", "긴축"]:
        sub = aligned[aligned["regime"] == regime]["ret"]
        if len(sub) < 3:
            results[regime] = {"n": len(sub), "avg": None, "sharpe": None, "win": None}
            continue
        avg    = sub.mean()
        sharpe = avg / sub.std() * (12**0.5) if sub.std() > 0 else 0
        win    = (sub > 0).mean() * 100
        results[regime] = {"n": len(sub), "avg": round(avg,2), "sharpe": round(sharpe,2), "win": round(win,1)}
    return results

spy_g = spy_monthly.reindex(g.index)
mom_g = mom_series.reindex(g.index)
gp_g  = gp_series.reindex(g.index)

spy_stats = regime_stats(spy_g, g)
mom_stats = regime_stats(mom_g, g)
gp_stats  = regime_stats(gp_g, g)

print("\n[국면별 평균 월수익 — SPY / 12M모멘텀 / GP touch]")
print(f"{'국면':<6} {'월수':<5} | {'SPY':>8} {'SPY_S':>7} | {'Mom20':>8} {'Mom_S':>7} | {'GP':>8} {'GP_S':>7}")
for r in ["완화", "중립", "긴축"]:
    sp = spy_stats[r]; mo = mom_stats[r]; gp = gp_stats[r]
    sp_avg = f"{sp['avg']:+.2f}%" if sp['avg'] is not None else "N/A"
    mo_avg = f"{mo['avg']:+.2f}%" if mo['avg'] is not None else "N/A"
    gp_avg = f"{gp['avg']:+.2f}%" if gp['avg'] is not None else "N/A"
    sp_sh  = f"{sp['sharpe']:+.2f}" if sp['sharpe'] is not None else "N/A"
    mo_sh  = f"{mo['sharpe']:+.2f}" if mo['sharpe'] is not None else "N/A"
    gp_sh  = f"{gp['sharpe']:+.2f}" if gp['sharpe'] is not None else "N/A"
    n = sp['n']
    print(f"{r:<6} n={n:<3} | {sp_avg:>8} {sp_sh:>7} | {mo_avg:>8} {mo_sh:>7} | {gp_avg:>8} {gp_sh:>7}")

# 최신 국면
latest = g.iloc[-1]
print(f"\n[최신 국면] {g.index[-1].date()} — {latest['regime']} (합계={int(latest['total'])})")
print(f"  NFCI={latest['s_nfci']:+.0f}  M2={latest['s_m2']:+.0f}  Fed={latest['s_fed']:+.0f}  RealRate={latest['s_rr']:+.0f}")

# 저장
out = {
    "gauge_latest": {
        "date": str(g.index[-1].date()),
        "regime": latest["regime"],
        "total_score": int(latest["total"]),
        "scores": {
            "nfci": int(latest["s_nfci"]),
            "m2_yoy": int(latest["s_m2"]),
            "fedfunds_6m": int(latest["s_fed"]),
            "real_rate_dfii10": int(latest["s_rr"]),
        }
    },
    "regime_counts": g["regime"].value_counts().to_dict(),
    "performance": {
        "spy": spy_stats,
        "mom20": mom_stats,
        "gp_touch": gp_stats,
    },
    "gauge_series": [
        {"date": str(row.Index.date()), "regime": row.regime, "total": int(row.total)}
        for row in g.itertuples()
    ]
}
out_json = r"C:\project\quant\liquidity_gauge_results_v1.json"
with open(out_json, "w", encoding="utf-8") as f:
    json.dump(out, f, ensure_ascii=False, indent=2)
print(f"\n저장: {out_json}")
print("완료")
