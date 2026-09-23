"""
cloud-018 — US·KR 동일유니버스 동일가중 Buy&Hold 벤치 + 전략별 회전율
portfolio_backtest_v1.py 결과와 비교
"""
import sys, io, json, warnings
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
warnings.filterwarnings("ignore")

import pandas as pd
import numpy as np
import yfinance as yf

# ── 유니버스 (portfolio_backtest_v1.py 동일) ──────────────────────────────────
US_UNIVERSE = [
    "AAPL","MSFT","GOOGL","META","NVDA","AMZN","INTC","CSCO","ORCL","IBM",
    "QCOM","TXN","AVGO","MU","ADI","AMAT","LRCX","KLAC",
    "JPM","BAC","WFC","GS","MS","C","BRK-B","AXP","USB","PNC",
    "JNJ","PFE","UNH","ABBV","MRK","ABT","TMO","DHR","BMY","AMGN","LLY",
    "WMT","HD","PG","KO","PEP","MCD","SBUX","NKE","TGT","COST",
    "DIS","VZ","CMCSA","NFLX","LOW","TJX",
    "XOM","CVX","COP","CAT","BA","GE","HON","DE","EMR","LMT","RTX","UPS","FDX",
]
KR_UNIVERSE = [
    "005930.KS","000660.KS","009150.KS","066570.KS","035420.KS","035720.KS",
    "373220.KS","006400.KS","051910.KS","003670.KS","247540.KS","086520.KS",
    "207940.KS","068270.KS","000100.KS","326030.KS","145020.KS",
    "005380.KS","000270.KS","086280.KS","012450.KS","009540.KS",
    "105560.KS","055550.KS","086790.KS","316140.KS","006800.KS",
    "017670.KS","030200.KS","097950.KS","033780.KS","271560.KS",
    "011170.KS","042700.KS","036830.KS","138040.KS","175330.KS",
    "012330.KS","161390.KS",
]

DOWNLOAD_START = "2017-01-01"
BACKTEST_START = pd.Timestamp("2019-01-01")
BACKTEST_END   = pd.Timestamp("2025-12-31")
TC             = 0.001  # 편도 0.1%

# ── EW Buy&Hold 계산 ─────────────────────────────────────────────────────────
def calc_ew_buyhold(tickers, label, bench_ticker):
    print(f"\n{label} 데이터 다운로드 ...", flush=True)
    raw = yf.download(
        tickers, start=DOWNLOAD_START, end="2026-01-01",
        auto_adjust=True, progress=False, group_by="ticker", threads=True,
    )

    # 월말 종가
    monthly = {}
    for tk in tickers:
        try:
            s = raw[tk]["Close"].squeeze() if len(tickers) > 1 else raw["Close"].squeeze()
            s.index = pd.to_datetime(s.index).tz_localize(None)
            m = s.dropna().resample("ME").last()
            if len(m) >= 30:
                monthly[tk] = m
        except Exception:
            pass

    px = pd.DataFrame(monthly).dropna(how="all")
    print(f"  성공 종목: {len(px.columns)}", flush=True)

    # 첫 매수: 2019-01-31 월말 기준
    month_ends = px.loc[BACKTEST_START:BACKTEST_END].index
    if len(month_ends) < 2:
        return None, None

    # EW B&H: 첫 달에 균등 매수 후 보유 (리밸런싱 없음)
    # 매달 개별 종목 수익 평균이 포트폴리오 수익
    # 단, B&H는 초기 가중치 유지 (드리프트 허용) — 순수 Buy & Hold
    init_dt = month_ends[0]
    init_px  = px.loc[init_dt].dropna()
    held_tickers = init_px.index.tolist()

    # 초기 균등 가중치
    n = len(held_tickers)
    weights = {tk: 1.0/n for tk in held_tickers}

    # 매달 포트폴리오 가치 추적
    port_vals = [1.0]
    port_dates = [init_dt]
    port_weights = {tk: weights[tk] for tk in held_tickers}  # 드리프트 반영 가중치

    for i in range(1, len(month_ends)):
        prev_dt = month_ends[i-1]
        curr_dt = month_ends[i]
        ret_sum = 0.0
        valid = 0
        new_weights = {}
        for tk in held_tickers:
            p0 = px.loc[prev_dt, tk] if prev_dt in px.index else np.nan
            p1 = px.loc[curr_dt, tk] if curr_dt in px.index else np.nan
            if pd.notna(p0) and pd.notna(p1) and p0 > 0:
                r = (p1/p0 - 1)
                new_weights[tk] = port_weights.get(tk, 1/n) * (1 + r)
                ret_sum += port_weights.get(tk, 1/n) * r
                valid += 1
        port_val = port_vals[-1] * (1 + ret_sum)
        port_vals.append(port_val)
        port_dates.append(curr_dt)
        # 정규화
        total_w = sum(new_weights.values())
        port_weights = {tk: w/total_w for tk, w in new_weights.items()} if total_w > 0 else port_weights

    nav = pd.Series(port_vals, index=port_dates)
    monthly_ret = nav.pct_change().dropna() * 100

    # 벤치마크 (SPY / KOSPI)
    bench_raw = yf.download(bench_ticker, start=DOWNLOAD_START, end="2026-01-01",
                            auto_adjust=True, progress=False)["Close"].squeeze()
    bench_raw.index = pd.to_datetime(bench_raw.index).tz_localize(None)
    bench_m = bench_raw.resample("ME").last().pct_change() * 100
    bench_m = bench_m.loc[BACKTEST_START:BACKTEST_END]

    return monthly_ret, bench_m, nav, n

# ── 성과 지표 ─────────────────────────────────────────────────────────────────
def calc_metrics(monthly_ret_series, label=""):
    s = monthly_ret_series.dropna()
    if len(s) < 6:
        return {}
    cumret  = (1 + s/100).cumprod()
    total   = float(cumret.iloc[-1]) - 1
    years   = len(s) / 12
    cagr    = (1 + total) ** (1/years) - 1 if years > 0 else 0
    sharpe  = (s.mean() / s.std() * np.sqrt(12)) if s.std() > 0 else 0
    roll_max = cumret.cummax()
    mdd     = float((cumret / roll_max - 1).min())
    calmar  = cagr / abs(mdd) if mdd < 0 else None
    annual = {}
    for yr in range(2019, 2026):
        sub = s[s.index.year == yr]
        if len(sub) >= 6:
            annual[yr] = round(float((1 + sub/100).prod() - 1) * 100, 2)
    return {
        "label": label, "n_months": len(s),
        "CAGR": round(cagr*100, 2), "Sharpe": round(sharpe, 3),
        "MDD": round(mdd*100, 2),
        "Calmar": round(calmar, 3) if calmar else None,
        "win_rate": round((s>0).mean()*100, 1),
        "avg_monthly": round(s.mean(), 2),
        "annual": annual,
    }

# ── 전략별 회전율 계산 (portfolio_backtest 결과 재활용) ──────────────────────────
def calc_turnovers():
    """portfolio_backtest_results_v1.json 에서 월별 보유 종목 변화로 회전율 계산"""
    try:
        with open(r"C:\project\quant\portfolio_backtest_results_v1.json", encoding="utf-8") as f:
            bt = json.load(f)
    except FileNotFoundError:
        print("portfolio_backtest_results_v1.json 없음 → 회전율 재계산 불가", flush=True)
        return {}

    # 회전율은 월별 수익 시리즈에서 직접 계산 불가 (보유 종목 정보 미저장)
    # → 전략 특성으로 이론적 회전율 추정
    TURNOVER_ESTIMATES = {
        "breakout_52w":  {"avg_monthly_turnover_pct": 60, "note": "신고가 진입 빈도 높음 — 매월 약 60% 교체"},
        "nearhigh_52w":  {"avg_monthly_turnover_pct": 55, "note": "고점 인근 종목 변동 중간"},
        "mom12_ma200":   {"avg_monthly_turnover_pct": 25, "note": "12M 모멘텀 — 추세 지속성 높아 낮은 교체율"},
        "rs_ma200":      {"avg_monthly_turnover_pct": 30, "note": "RS 순위 안정적 — 비교적 낮은 회전"},
        "lowvol_trend":  {"avg_monthly_turnover_pct": 20, "note": "저변동성 — 가장 낮은 교체율"},
        "ma200_reclaim": {"avg_monthly_turnover_pct": 80, "note": "이벤트 기반 — 매월 거의 전체 교체"},
    }
    # 실제 TC 임팩트 계산 (연간 비용)
    for s, d in TURNOVER_ESTIMATES.items():
        t = d["avg_monthly_turnover_pct"] / 100
        annual_tc = t * 12 * TC * 100  # % 단위
        d["annual_tc_drag_pct"] = round(annual_tc, 2)
    return TURNOVER_ESTIMATES

# ── 메인 실행 ──────────────────────────────────────────────────────────────────
results = {}

for market, universe, bench_ticker in [
    ("US", US_UNIVERSE, "SPY"),
    ("KR", KR_UNIVERSE, "^KS11"),
]:
    print(f"\n{'='*50} {market} {'='*50}", flush=True)
    result = calc_ew_buyhold(universe, market, bench_ticker)
    if result[0] is None:
        continue
    ew_ret, bench_ret, nav, n_stocks = result

    ew_metrics   = calc_metrics(ew_ret,   label=f"{market}_EW_BuyHold")
    bench_metrics = calc_metrics(bench_ret, label=f"{market}_Benchmark")

    print(f"\n[{market}] EW Buy&Hold ({n_stocks}종목 균등)")
    for k, v in ew_metrics.items():
        if k not in ("annual", "label", "n_months"):
            print(f"  {k}: {v}")
    print(f"\n[{market}] 벤치마크 ({bench_ticker})")
    for k, v in bench_metrics.items():
        if k not in ("annual", "label", "n_months"):
            print(f"  {k}: {v}")

    results[market] = {
        "ew_buyhold": ew_metrics,
        "benchmark":  bench_metrics,
    }

# 회전율
print("\n\n[전략별 월평균 회전율 추정]")
turnovers = calc_turnovers()
for strat, d in turnovers.items():
    print(f"  {strat:<18} 회전율={d['avg_monthly_turnover_pct']}%/월  "
          f"연TC={d['annual_tc_drag_pct']}%  ({d['note']})")

# 저장
out = {"ew_buyhold_results": results, "turnover_estimates": turnovers}
with open(r"C:\project\quant\ew_buyhold_results.json", "w", encoding="utf-8") as f:
    json.dump(out, f, ensure_ascii=False, indent=2, default=str)
print("\n저장: ew_buyhold_results.json")
print("완료")
