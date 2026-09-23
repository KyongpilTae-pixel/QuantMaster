"""
cloud-013 Task A — 6-전략 풀사이클 포트폴리오 백테스트
KR (KOSPI 주요종목) + US (S&P500 주요종목)
기간: 2019-01-01 ~ 2025-12-31
월별 리밸런싱, 동일가중, 수수료 0.1% 편도
"""
import sys, io, json, warnings, time
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
warnings.filterwarnings("ignore")

import pandas as pd
import numpy as np
import yfinance as yf

# ── 유니버스 정의 ─────────────────────────────────────────────────────────────
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

DOWNLOAD_START = "2017-01-01"  # 252일 워밍업용
BACKTEST_START = pd.Timestamp("2019-01-01")
BACKTEST_END   = pd.Timestamp("2025-12-31")
TOP_N          = 15   # 전략별 포트폴리오 종목 수
TC             = 0.001  # 편도 수수료 0.1%
MA_WINDOW      = 200

STRATEGIES = [
    "breakout_52w",    # 52주 신고가 돌파
    "nearhigh_52w",    # 52주 고점 인근 (−5% 이내)
    "mom12_ma200",     # 12M 모멘텀 top25% + MA200 위
    "rs_ma200",        # RS vs 벤치 top25% + MA200 위
    "lowvol_trend",    # 6M 저변동성 + MA200 위
    "ma200_reclaim",   # MA200 재돌파 (최근 21일 내)
]

# ── 데이터 다운로드 ────────────────────────────────────────────────────────────
def download_prices(tickers, label):
    print(f"\n{label} 가격 데이터 다운로드: {len(tickers)}종목 ...", flush=True)
    raw = yf.download(
        tickers, start=DOWNLOAD_START, end="2026-01-01",
        auto_adjust=True, progress=False, group_by="ticker", threads=True,
    )
    prices = {}
    for tk in tickers:
        try:
            if len(tickers) == 1:
                s = raw["Close"].squeeze()
            else:
                s = raw[tk]["Close"].squeeze()
            s.index = pd.to_datetime(s.index).tz_localize(None)
            s = s.dropna().sort_index()
            if len(s) >= 400:
                prices[tk] = s
        except Exception:
            pass
    print(f"  성공: {len(prices)}/{len(tickers)}", flush=True)
    return prices

def build_monthly_price(prices_dict):
    """월말 종가 피벗 테이블"""
    monthly = {tk: s.resample("ME").last() for tk, s in prices_dict.items()}
    return pd.DataFrame(monthly).dropna(how="all")

# ── 신호 계산 ──────────────────────────────────────────────────────────────────
def compute_signals(prices_dict, bench_monthly):
    """
    각 종목·월별 신호 계산
    반환: {strategy: DataFrame(월말 × 종목, bool/float)}
    """
    monthly_px = build_monthly_price(prices_dict)
    tickers = list(monthly_px.columns)

    # 일별 데이터 (MA200, 변동성 계산용)
    daily_close = pd.DataFrame({tk: s for tk, s in prices_dict.items()})

    # 월말 인덱스 (백테스트 기간)
    month_ends = monthly_px.loc[BACKTEST_START:BACKTEST_END].index

    # 전략별 점수/신호 저장
    sig = {s: pd.DataFrame(index=month_ends, columns=tickers, dtype=float) for s in STRATEGIES}

    for dt in month_ends:
        # 해당 월말 기준 일별 데이터 슬라이스 (과거 300일)
        daily_slice = daily_close.loc[:dt].tail(300)

        for tk in tickers:
            if tk not in daily_close.columns:
                continue
            ds = daily_slice[tk].dropna()
            if len(ds) < 50:
                continue

            close_now = float(ds.iloc[-1])
            ma200     = float(ds.rolling(MA_WINDOW, min_periods=100).mean().iloc[-1]) if len(ds) >= 100 else np.nan
            high252   = float(ds.tail(252).max()) if len(ds) >= 100 else np.nan
            ratio_h   = close_now / high252 if high252 > 0 else np.nan

            # 1. 52주 신고가 돌파 (top 5% of ratio)
            sig["breakout_52w"].loc[dt, tk] = ratio_h if not np.isnan(ratio_h) else np.nan

            # 2. 52주 고점 인근 (0.95 ~ 1.0)
            sig["nearhigh_52w"].loc[dt, tk] = ratio_h if (not np.isnan(ratio_h) and 0.95 <= ratio_h <= 1.02) else np.nan

            # 3. 12M 모멘텀 + MA200 위
            if len(ds) >= 252:
                mom12 = close_now / float(ds.iloc[-252]) - 1
                sig["mom12_ma200"].loc[dt, tk] = mom12 if (not np.isnan(ma200) and close_now > ma200) else np.nan
            else:
                sig["mom12_ma200"].loc[dt, tk] = np.nan

            # 4. RS vs 벤치 (월별 데이터로 계산)
            # → 아래 별도 처리

            # 5. 6M 저변동성 + MA200 위
            if len(ds) >= 126:
                vol6m = float(ds.pct_change().tail(126).std()) * np.sqrt(252)
                sig["lowvol_trend"].loc[dt, tk] = -vol6m if (not np.isnan(ma200) and close_now > ma200) else np.nan
            else:
                sig["lowvol_trend"].loc[dt, tk] = np.nan

            # 6. MA200 재돌파 (최근 21일 내 close가 MA200 아래였다가 위로)
            if len(ds) >= MA_WINDOW + 21:
                ma_series = ds.rolling(MA_WINDOW, min_periods=100).mean()
                recent_21 = ds.tail(21)
                ma_21     = ma_series.tail(21)
                below_then = (recent_21 < ma_21).any()  # 최근 21일 중 아래였던 적 있음
                above_now  = close_now > ma200 if not np.isnan(ma200) else False
                sig["ma200_reclaim"].loc[dt, tk] = 1.0 if (below_then and above_now) else np.nan
            else:
                sig["ma200_reclaim"].loc[dt, tk] = np.nan

        # RS 계산 (월별)
        if dt in monthly_px.index and dt in bench_monthly.index:
            m_px = monthly_px.loc[:dt].tail(13)
            bench_ret = bench_monthly.loc[:dt].tail(13)
            for tk in tickers:
                if tk in m_px.columns and len(m_px[tk].dropna()) >= 12:
                    tk_ret = m_px[tk].dropna().pct_change(12).iloc[-1]
                    b_ret  = bench_ret.dropna().pct_change(12).iloc[-1] if len(bench_ret.dropna()) >= 12 else np.nan
                    if not np.isnan(tk_ret) and not np.isnan(b_ret) and b_ret != 0:
                        rs = tk_ret / abs(b_ret)
                        ds2 = daily_close[tk].dropna().loc[:dt]
                        ma200_rs = float(ds2.rolling(MA_WINDOW, min_periods=100).mean().iloc[-1]) if len(ds2) >= 100 else np.nan
                        close_rs = float(ds2.iloc[-1]) if len(ds2) > 0 else np.nan
                        above_rs = (close_rs > ma200_rs) if (not np.isnan(ma200_rs) and close_rs is not None) else False
                        sig["rs_ma200"].loc[dt, tk] = rs if above_rs else np.nan

    return sig, monthly_px, month_ends

# ── 포트폴리오 시뮬레이션 ──────────────────────────────────────────────────────
def run_backtest(sig, monthly_px, month_ends, strategy, top_n=TOP_N):
    """
    월별 TOP_N 선택 → 동일가중 → 수수료 적용 → 월별 수익 계산
    """
    portfolio_rets = []
    holdings_prev  = set()

    for i, dt in enumerate(month_ends[:-1]):
        nxt_dt = month_ends[i + 1]

        # 신호 기준 TOP_N 선택
        row = sig[strategy].loc[dt].dropna()
        if len(row) == 0:
            portfolio_rets.append((nxt_dt, 0.0, 0))
            holdings_prev = set()
            continue

        if strategy in ("breakout_52w", "mom12_ma200", "rs_ma200"):
            selected = row.nlargest(top_n).index.tolist()
        elif strategy == "nearhigh_52w":
            # ratio가 있는 것 중 top_n (ratio 높을수록 고점에 가까움)
            selected = row.nlargest(top_n).index.tolist()
        elif strategy == "lowvol_trend":
            # 낮은 변동성 (-vol 저장됐으므로 nlargest = 최저 변동성)
            selected = row.nlargest(top_n).index.tolist()
        elif strategy == "ma200_reclaim":
            # 1.0인 종목 선택 (최대 top_n)
            selected = row[row > 0].index.tolist()[:top_n]
        else:
            selected = row.nlargest(top_n).index.tolist()

        if not selected:
            portfolio_rets.append((nxt_dt, 0.0, 0))
            holdings_prev = set()
            continue

        # 회전율 기반 수수료
        new_set  = set(selected)
        turnover = len(new_set.symmetric_difference(holdings_prev)) / max(len(new_set | holdings_prev), 1)
        tc_cost  = turnover * TC

        # 다음달 수익 계산
        rets = []
        for tk in selected:
            if tk in monthly_px.columns:
                p0 = monthly_px.loc[dt, tk]  if dt  in monthly_px.index else np.nan
                p1 = monthly_px.loc[nxt_dt, tk] if nxt_dt in monthly_px.index else np.nan
                if pd.notna(p0) and pd.notna(p1) and p0 > 0:
                    rets.append((p1/p0 - 1) * 100)

        avg_ret = np.mean(rets) - tc_cost * 100 if rets else 0.0
        portfolio_rets.append((nxt_dt, avg_ret, len(selected)))
        holdings_prev = new_set

    return pd.Series(
        [r[1] for r in portfolio_rets],
        index=[r[0] for r in portfolio_rets],
        name=strategy,
    )

# ── 성과 지표 계산 ─────────────────────────────────────────────────────────────
def calc_metrics(monthly_ret_series, label=""):
    s = monthly_ret_series.dropna()
    if len(s) < 6:
        return {"label": label, "n_months": len(s), "CAGR": None, "Sharpe": None, "MDD": None, "Calmar": None}

    # 누적 수익
    cumret = (1 + s/100).cumprod()
    total_ret = float(cumret.iloc[-1]) - 1
    years = len(s) / 12
    cagr  = (1 + total_ret) ** (1/years) - 1 if years > 0 else 0

    # Sharpe (연환산)
    avg_m  = s.mean()
    std_m  = s.std()
    sharpe = (avg_m / std_m * np.sqrt(12)) if std_m > 0 else 0

    # MDD
    roll_max = cumret.cummax()
    drawdown = (cumret / roll_max - 1)
    mdd = float(drawdown.min())

    # Calmar
    calmar = cagr / abs(mdd) if mdd < 0 else None

    # 연도별
    annual = {}
    for yr in range(2019, 2026):
        sub = s[s.index.year == yr]
        if len(sub) >= 6:
            annual[yr] = round(float((1 + sub/100).prod() - 1) * 100, 2)

    return {
        "label":    label,
        "n_months": len(s),
        "CAGR":     round(cagr * 100, 2),
        "Sharpe":   round(sharpe, 3),
        "MDD":      round(mdd * 100, 2),
        "Calmar":   round(calmar, 3) if calmar else None,
        "win_rate": round((s > 0).mean() * 100, 1),
        "avg_monthly": round(avg_m, 2),
        "annual":   annual,
    }

# ── 벤치마크 다운로드 ──────────────────────────────────────────────────────────
def get_benchmark(ticker, label):
    print(f"벤치마크 {label}({ticker}) 다운로드 ...", flush=True)
    raw = yf.download(ticker, start=DOWNLOAD_START, end="2026-01-01",
                      auto_adjust=True, progress=False)
    s = raw["Close"].squeeze()
    s.index = pd.to_datetime(s.index).tz_localize(None)
    m = s.resample("ME").last().pct_change() * 100
    m = m.loc[BACKTEST_START:BACKTEST_END]
    return m

# ── 메인 실행 ──────────────────────────────────────────────────────────────────
results = {}

for market, universe, bench_ticker, bench_label in [
    ("US", US_UNIVERSE, "SPY", "SPY"),
    ("KR", KR_UNIVERSE, "^KS11", "KOSPI"),
]:
    print(f"\n{'='*60}")
    print(f"  {market} 백테스트 시작")
    print(f"{'='*60}")

    bench_daily = yf.download(bench_ticker, start=DOWNLOAD_START, end="2026-01-01",
                               auto_adjust=True, progress=False)["Close"].squeeze()
    bench_daily.index = pd.to_datetime(bench_daily.index).tz_localize(None)
    bench_monthly = bench_daily.resample("ME").last()

    prices = download_prices(universe, market)
    if not prices:
        print(f"  {market}: 데이터 없음, 스킵", flush=True)
        continue

    print(f"신호 계산 중 ...", flush=True)
    sig, monthly_px, month_ends = compute_signals(prices, bench_monthly)

    market_results = {}

    for strat in STRATEGIES:
        print(f"  [{market}] {strat} 시뮬레이션 ...", flush=True)
        ret_series = run_backtest(sig, monthly_px, month_ends, strat)
        metrics = calc_metrics(ret_series.loc[BACKTEST_START:BACKTEST_END], label=f"{market}_{strat}")
        market_results[strat] = {**metrics, "monthly_returns": ret_series.to_dict()}

    # 벤치마크 성과
    bench_ret = bench_monthly.pct_change() * 100
    bench_ret = bench_ret.loc[BACKTEST_START:BACKTEST_END]
    bench_metrics = calc_metrics(bench_ret, label=f"{market}_{bench_label}")
    market_results["benchmark"] = {**bench_metrics, "ticker": bench_ticker}

    results[market] = market_results

# ── 결과 출력 ──────────────────────────────────────────────────────────────────
STRAT_LABELS = {
    "breakout_52w":  "52주 신고가 돌파",
    "nearhigh_52w":  "52주 고점 인근(−5%)",
    "mom12_ma200":   "12M모멘텀+MA200",
    "rs_ma200":      "RS+MA200",
    "lowvol_trend":  "저변동성+추세",
    "ma200_reclaim": "MA200 재돌파",
    "benchmark":     "벤치마크",
}

for market in ["US", "KR"]:
    if market not in results:
        continue
    print(f"\n{'='*70}")
    print(f"  {market} 전략별 성과 요약 (2019-2025, TOP{TOP_N}, TC=0.1%)")
    print(f"{'='*70}")
    print(f"  {'전략':<20} {'CAGR%':>7} {'Sharpe':>7} {'MDD%':>7} {'Calmar':>7} {'승률%':>7}")
    print(f"  {'-'*60}")
    for strat in STRATEGIES + ["benchmark"]:
        if strat not in results[market]:
            continue
        m = results[market][strat]
        cagr   = f"{m['CAGR']:+.1f}" if m['CAGR'] is not None else "N/A"
        sharpe = f"{m['Sharpe']:.3f}" if m['Sharpe'] is not None else "N/A"
        mdd    = f"{m['MDD']:.1f}"    if m['MDD']   is not None else "N/A"
        calmar = f"{m['Calmar']:.3f}" if m['Calmar'] is not None else "N/A"
        winr   = f"{m['win_rate']:.1f}" if 'win_rate' in m and m['win_rate'] is not None else "N/A"
        lbl    = STRAT_LABELS.get(strat, strat)
        print(f"  {lbl:<20} {cagr:>7} {sharpe:>7} {mdd:>7} {calmar:>7} {winr:>7}")

    print(f"\n  연도별 수익률 (%)")
    print(f"  {'전략':<20} " + " ".join(f"{y:>7}" for y in range(2019, 2026)))
    print(f"  {'-'*70}")
    for strat in STRATEGIES + ["benchmark"]:
        if strat not in results[market]:
            continue
        m   = results[market][strat]
        ann = m.get("annual", {})
        row = " ".join(f"{ann.get(y, 0):>+7.1f}" if y in ann else f"{'N/A':>7}" for y in range(2019, 2026))
        lbl = STRAT_LABELS.get(strat, strat)
        print(f"  {lbl:<20} {row}")

# ── 저장 ───────────────────────────────────────────────────────────────────────
# monthly_returns는 timestamp key → str 변환
def serialize(obj):
    if isinstance(obj, dict):
        return {str(k): serialize(v) for k, v in obj.items()}
    if isinstance(obj, (pd.Timestamp, pd.Period)):
        return str(obj)
    if isinstance(obj, float) and np.isnan(obj):
        return None
    return obj

out_json = r"C:\project\quant\portfolio_backtest_results_v1.json"
with open(out_json, "w", encoding="utf-8") as f:
    json.dump(serialize(results), f, ensure_ascii=False, indent=2, default=str)
print(f"\n저장: {out_json}")
print("완료")
