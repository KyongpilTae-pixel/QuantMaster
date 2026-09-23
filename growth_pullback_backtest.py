# -*- coding: utf-8 -*-
import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")
"""
growth_pullback_backtest.py
============================
성장주 눌림목(Growth Pullback / GP) 전략 백테스트
2019-01-01 ~ 2025-12-31, KR / US

가격 프록시 성장주 판정:
  - 최근 lookback거래일 중 Close > MA200 비율 >= 0.70
  - AND 12M 수익률 상위 top_n

Entry:
  - [touch]   Close > MA200  AND  0 <= (Close-MA200)/MA200 <= 0.05
  - [reclaim] t-1 Close < MA200, t Close > MA200

Exit:
  - Hard stop: (Close-MA200)/MA200 < stop_pct
  - Universe 탈락 (성장주 조건 미충족)

포트폴리오: 균등비중, 월 리밸런싱
비교군: 성장주 B&H, 지수(KOSPI/S&P500)
"""

import warnings
warnings.filterwarnings("ignore")

import os, sys, json
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed

import numpy as np
import pandas as pd
import FinanceDataReader as fdr

# ── 설정 ──────────────────────────────────────────────────────────────────
START = "2019-01-01"
END   = "2025-12-31"

KR_COST  = 0.003   # 한국 왕복 거래비용 (세금0.18%+수수료0.03%×2+슬리피지0.05%×2)
US_COST  = 0.0011  # 미국 왕복 거래비용

PARAM_GRID = [
    # (entry_mode, stop_pct, lookback_days, top_n)
    ("touch",   -0.08, 500, 10),
    ("touch",   -0.10, 500, 10),
    ("touch",   -0.12, 500, 10),
    ("touch",   -0.10, 750, 10),
    ("touch",   -0.10, 500,  5),
    ("reclaim", -0.08, 500, 10),
    ("reclaim", -0.10, 500, 10),
    ("reclaim", -0.12, 500, 10),
    ("reclaim", -0.10, 750, 10),
    ("reclaim", -0.10, 500,  5),
]

INITIAL_CAPITAL = 100_000_000  # 1억원

# ── 종목 유니버스 ──────────────────────────────────────────────────────────

def get_kr_universe(n=80):
    """KOSPI 시가총액 상위 n 종목 코드 반환."""
    # 수동 하드코딩 + FDR 시도 (안되면 fallback)
    KOSPI_TOP = [
        "005930","000660","207940","005380","051910","035420","006400","028260",
        "000270","105560","035720","055550","012330","066570","017670","032830",
        "003550","086790","009150","010130","011200","018260","302440","034020",
        "011170","033780","096770","003490","010950","030200","047050","051600",
        "034730","000810","005490","003670","090430","018880","009830","010140",
        "011780","024110","069960","015760","004020","029780","000720","001040",
        "139480","086280","000080","004370","002790","023530","001120","032640",
        "000100","011070","007070","020150","011760","005040","001570","012750",
        "000060","008770","004000","003830","000990","001800","010680","024900",
        "005830","004130","082640","009540","006800","078930","004490","009780",
    ]
    try:
        df = fdr.StockListing("KRX")
        if df is not None and "Marcap" in df.columns and len(df) > 0:
            df = df.dropna(subset=["Marcap"]).sort_values("Marcap", ascending=False)
            col = "Code" if "Code" in df.columns else df.columns[0]
            tickers = df[col].head(n).tolist()
            tickers = [str(t).zfill(6) for t in tickers if str(t).isdigit() or str(t).zfill(6).isdigit()]
            if len(tickers) >= 20:
                return tickers[:n]
    except Exception as e:
        print(f"[KR universe FDR] {e} - fallback 사용")
    return KOSPI_TOP[:n]

def get_us_universe(n=80):
    """S&P500 상위 n 종목 (시가총액 기준 앞쪽)."""
    SP500_TOP = [
        "AAPL","MSFT","NVDA","AMZN","GOOGL","META","TSLA","BRK-B","AVGO","JPM",
        "LLY","V","UNH","XOM","MA","JNJ","PG","COST","HD","ABBV",
        "MRK","ORCL","CVX","CRM","BAC","KO","NFLX","AMD","PEP","WMT",
        "TMO","ACN","MCD","CSCO","ABT","GE","MS","NOW","ADBE","DHR",
        "ISRG","TXN","IBM","RTX","NEE","AMGN","LOW","INTU","GS","SPGI",
        "CAT","BKNG","UBER","AXP","PLD","VRTX","MDT","DE","BLK","T",
        "ELV","SYK","CI","GILD","MMC","CB","SO","FI","MO","ZTS",
        "BSX","PGR","DUK","SCHW","APD","ICE","EOG","WM","REGN","CME",
    ]
    return SP500_TOP[:n]

# ── 데이터 다운로드 ────────────────────────────────────────────────────────

def _fetch_one(ticker, start, end, is_kr):
    try:
        if is_kr:
            raw = fdr.DataReader(ticker, start, end)
        else:
            import yfinance as yf
            raw = yf.download(ticker, start=start, end=end, progress=False, auto_adjust=True)
        if raw is None or len(raw) == 0:
            return ticker, None
        # MultiIndex 컬럼 -> flat
        if isinstance(raw.columns, pd.MultiIndex):
            raw = raw.copy()
            raw.columns = [c[0] if isinstance(c, tuple) else c for c in raw.columns]
        # 중복 컬럼 제거
        raw = raw.loc[:, ~raw.columns.duplicated()]
        # Close 컬럼 탐색 (대소문자 무관)
        col_map = {str(c).lower(): c for c in raw.columns}
        if "close" not in col_map:
            return ticker, None
        s = raw[col_map["close"]]
        if isinstance(s, pd.DataFrame):
            s = s.iloc[:, 0]
        s = s.squeeze()
        # 인덱스 정규화: tz 제거, datetime
        idx = pd.to_datetime(s.index)
        if hasattr(idx, "tz") and idx.tz is not None:
            idx = idx.tz_localize(None)
        s.index = idx
        s = s.dropna()
        if len(s) < 100:
            return ticker, None
        return ticker, s.rename(ticker)
    except Exception:
        return ticker, None

def download_prices(tickers, start, end, is_kr, workers=8, label=""):
    prices = {}
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futures = {ex.submit(_fetch_one, t, start, end, is_kr): t for t in tickers}
        done = 0
        for f in as_completed(futures):
            ticker, s = f.result()
            done += 1
            if s is not None:
                prices[ticker] = s
            if done % 10 == 0 or done == len(tickers):
                print(f"  [{label}] {done}/{len(tickers)} 다운로드 완료", flush=True)
    return prices

# ── 전략 핵심 ──────────────────────────────────────────────────────────────

def compute_ma200(s: pd.Series) -> pd.Series:
    return s.rolling(200, min_periods=100).mean()

def growth_filter(price_df: pd.DataFrame, lookback: int, top_n: int, date) -> list:
    """
    date 기준으로 성장주 판정:
    1) 최근 lookback일 중 Close > MA200 비율 >= 70%
    2) 12M 수익률 상위 top_n
    """
    history = price_df.loc[:date].iloc[-lookback:]
    ma200 = price_df["ma200"].loc[:date].iloc[-lookback:]

    above_ratio = ((history > ma200).sum() / lookback)
    candidates = above_ratio[above_ratio >= 0.70].index.tolist()

    if not candidates:
        return []

    # 12M 모멘텀
    start_12m = price_df.loc[:date].index[-1] - pd.DateOffset(months=12)
    mom_scores = {}
    for t in candidates:
        if t not in price_df.columns:
            continue
        hist = price_df[t].dropna()
        idx_now = hist.index.get_loc(hist.index.asof(date))
        idx_12m = hist.index.searchsorted(start_12m)
        if idx_now > idx_12m and hist.iloc[idx_12m] > 0:
            mom_scores[t] = hist.iloc[idx_now] / hist.iloc[idx_12m] - 1
        else:
            mom_scores[t] = -999

    if not mom_scores:
        return []
    top = sorted(mom_scores, key=lambda x: -mom_scores[x])[:top_n]
    return top

# ── 포트폴리오 백테스트 ────────────────────────────────────────────────────

def run_backtest(
    prices: dict,          # {ticker: pd.Series(close)}
    index_series: pd.Series,
    entry_mode: str,       # "touch" | "reclaim"
    stop_pct: float,       # e.g. -0.10
    lookback: int,         # 500 or 750
    top_n: int,            # 5 or 10
    cost: float,           # transaction cost (round-trip ratio)
):
    """Monthly-rebalanced portfolio backtest."""
    all_tickers = list(prices.keys())

    # 가격 DataFrame (aligned)
    price_df = pd.DataFrame(prices)
    price_df = price_df.sort_index()
    price_df = price_df[price_df.index >= pd.Timestamp(START)]
    price_df = price_df[price_df.index <= pd.Timestamp(END)]

    if len(price_df) < 200:
        return None

    # MA200 계산
    ma200_df = price_df.apply(compute_ma200)
    ratio_df  = (price_df - ma200_df) / ma200_df  # (Close-MA200)/MA200

    # 월별 리밸런싱 날짜
    rebal_dates = pd.date_range(price_df.index[0], price_df.index[-1], freq="BME")
    rebal_dates = rebal_dates[rebal_dates.isin(price_df.index)]

    capital = float(INITIAL_CAPITAL)
    holdings = {}   # {ticker: shares}
    equity_curve = []

    prev_prices = None

    for date in price_df.index:
        today_prices = price_df.loc[date]
        today_ratio  = ratio_df.loc[date]
        today_ma200  = ma200_df.loc[date]

        # 청산 조건 먼저 체크
        exit_set = set()
        for t, shares in list(holdings.items()):
            if t not in today_prices.index or pd.isna(today_prices[t]):
                exit_set.add(t)
            elif pd.notna(today_ratio[t]) and today_ratio[t] < stop_pct:
                exit_set.add(t)

        for t in exit_set:
            if t in holdings and t in today_prices.index and pd.notna(today_prices[t]):
                proceeds = holdings[t] * today_prices[t] * (1 - cost / 2)
                capital += proceeds
            holdings.pop(t, None)

        # 월 리밸런싱
        if date in rebal_dates and len(price_df.loc[:date]) >= max(lookback, 200):
            # 성장주 판정 (price proxy)
            above_ratio_series = {}
            for t in all_tickers:
                if t not in price_df.columns:
                    continue
                hist_prices = price_df[t].loc[:date]
                hist_ma200  = ma200_df[t].loc[:date]
                # 공통 인덱스만 사용
                common_idx = hist_prices.dropna().index.intersection(hist_ma200.dropna().index)
                if len(common_idx) < lookback:
                    continue
                hp = hist_prices.loc[common_idx].iloc[-lookback:]
                hm = hist_ma200.loc[common_idx].iloc[-lookback:]
                above_ratio_series[t] = (hp.values > hm.values).mean()

            growth_candidates = [t for t, r in above_ratio_series.items() if r >= 0.70]

            # 12M 모멘텀 상위
            date_12m_ago = date - pd.DateOffset(months=12)
            mom = {}
            for t in growth_candidates:
                hist = price_df[t].dropna()
                past = hist[hist.index <= date_12m_ago]
                if len(past) == 0:
                    continue
                p_now  = today_prices.get(t, np.nan)
                p_past = past.iloc[-1]
                if pd.notna(p_now) and p_past > 0:
                    mom[t] = p_now / p_past - 1

            top_growth = sorted(mom, key=lambda x: -mom[x])[:top_n]

            # Entry 신호 필터
            entry_stocks = []
            for t in top_growth:
                if pd.isna(today_ratio.get(t)) or pd.isna(today_ma200.get(t)):
                    continue
                r = today_ratio[t]
                if entry_mode == "touch":
                    if 0 <= r <= 0.05:
                        entry_stocks.append(t)
                elif entry_mode == "reclaim":
                    if prev_prices is not None and t in prev_prices.index:
                        prev_r = (prev_prices[t] - ma200_df.loc[prev_prices.name, t]) if prev_prices.name in ma200_df.index else np.nan
                        if pd.notna(prev_r) and prev_r < 0 and r > 0:
                            entry_stocks.append(t)

            # 기존 보유 중 성장주 조건 유지되는 종목 유지
            keep = [t for t in holdings if t in top_growth]
            new_buy = [t for t in entry_stocks if t not in holdings]
            target = list(set(keep + new_buy))[:top_n]

            # 청산: target에 없는 보유 종목
            to_sell = [t for t in list(holdings.keys()) if t not in target]
            for t in to_sell:
                if t in today_prices.index and pd.notna(today_prices[t]):
                    proceeds = holdings[t] * today_prices[t] * (1 - cost / 2)
                    capital += proceeds
                holdings.pop(t)

            # 매수: target에 있는 신규 종목
            if target:
                alloc_per = capital / len(target) if capital > 0 else 0
                for t in target:
                    if t not in holdings and alloc_per > 0:
                        p = today_prices.get(t, np.nan)
                        if pd.notna(p) and p > 0:
                            shares = alloc_per * (1 - cost / 2) / p
                            capital -= alloc_per
                            holdings[t] = shares

        # 자산 평가
        portfolio_val = capital + sum(
            holdings[t] * today_prices.get(t, 0)
            for t in holdings
            if pd.notna(today_prices.get(t, np.nan))
        )
        equity_curve.append({"date": date, "value": portfolio_val, "n_stocks": len(holdings)})

        if prev_prices is None or (date != prev_prices.name):
            prev_prices = today_prices
            prev_prices.name = date

    eq = pd.DataFrame(equity_curve).set_index("date")["value"]
    return eq

# ── 성과 지표 ──────────────────────────────────────────────────────────────

def calc_metrics(eq: pd.Series, label: str, cost=0.0) -> dict:
    if eq is None or len(eq) < 10:
        return {"label": label, "CAGR%": None, "MDD%": None, "Sharpe": None, "Win%": None}

    total_ret = eq.iloc[-1] / eq.iloc[0] - 1
    n_years   = (eq.index[-1] - eq.index[0]).days / 365.25
    cagr      = (1 + total_ret) ** (1 / max(n_years, 0.01)) - 1

    rolling_max = eq.cummax()
    dd = (eq - rolling_max) / rolling_max
    mdd = dd.min()

    daily_ret = eq.pct_change().dropna()
    sharpe = (daily_ret.mean() / daily_ret.std() * np.sqrt(252)) if daily_ret.std() > 0 else 0

    win_pct = (daily_ret > 0).mean() * 100

    return {
        "label":  label,
        "CAGR%":  round(cagr * 100, 2),
        "MDD%":   round(mdd * 100, 2),
        "Sharpe": round(sharpe, 3),
        "Win%":   round(win_pct, 1),
        "TotalRet%": round(total_ret * 100, 1),
    }

# ── Buy & Hold 기준선 ─────────────────────────────────────────────────────

def buy_and_hold(prices: dict, cost: float) -> pd.Series:
    price_df = pd.DataFrame(prices).sort_index()
    price_df = price_df[(price_df.index >= pd.Timestamp(START)) & (price_df.index <= pd.Timestamp(END))]
    # 균등비중 BH
    norm = price_df / price_df.iloc[0]
    portfolio = norm.mean(axis=1) * INITIAL_CAPITAL * (1 - cost)
    return portfolio


# ── 메인 ──────────────────────────────────────────────────────────────────

def main():
    print("=" * 60)
    print("Growth Pullback (GP) 백테스트")
    print(f"기간: {START} ~ {END}")
    print("=" * 60)

    results = []

    for region, is_kr in [("KR", True), ("US", False)]:
        print(f"\n{'='*20} {region} 시장 {'='*20}")
        cost = KR_COST if is_kr else US_COST

        # 유니버스
        tickers = get_kr_universe(80) if is_kr else get_us_universe(80)
        print(f"유니버스: {len(tickers)}종목 다운로드 시작...")

        prices = download_prices(tickers, START, END, is_kr, workers=10, label=region)
        print(f"  → 유효 종목: {len(prices)}개")

        if len(prices) < 5:
            print(f"[{region}] 데이터 부족 -건너뜀")
            continue

        # 지수
        idx_ticker = "KS11" if is_kr else "S&P500"
        try:
            idx_raw = fdr.DataReader(idx_ticker, START, END)
            idx_series = idx_raw["Close"].rename(idx_ticker)
        except Exception:
            idx_series = pd.Series(dtype=float)

        # Buy & Hold 기준선
        bh_eq = buy_and_hold(prices, cost)
        m_bh  = calc_metrics(bh_eq, f"[{region}] 성장주 B&H")
        results.append({**m_bh, "region": region, "entry": "-", "stop": "-", "lookback": "-", "topn": "-"})
        print(f"  B&H: CAGR={m_bh['CAGR%']}% MDD={m_bh['MDD%']}% Sharpe={m_bh['Sharpe']}")

        # 지수 기준선
        if len(idx_series) > 100:
            idx_eq = idx_series / idx_series.iloc[0] * INITIAL_CAPITAL
            m_idx  = calc_metrics(idx_eq, f"[{region}] 지수({idx_ticker})")
            results.append({**m_idx, "region": region, "entry": "-", "stop": "-", "lookback": "-", "topn": "-"})
            print(f"  지수: CAGR={m_idx['CAGR%']}% MDD={m_idx['MDD%']}% Sharpe={m_idx['Sharpe']}")

        # 파라미터 스윕
        for entry_mode, stop_pct, lookback, top_n in PARAM_GRID:
            label = f"[{region}] GP/{entry_mode} stop={int(stop_pct*100)}% lb={lookback} top{top_n}"
            print(f"  실행: {label} ...", end="", flush=True)
            try:
                eq = run_backtest(prices, idx_series, entry_mode, stop_pct, lookback, top_n, cost)
                if eq is not None:
                    m = calc_metrics(eq, label)
                    results.append({
                        **m,
                        "region": region,
                        "entry": entry_mode,
                        "stop": f"{int(stop_pct*100)}%",
                        "lookback": lookback,
                        "topn": top_n,
                    })
                    print(f" CAGR={m['CAGR%']}% MDD={m['MDD%']}% Sharpe={m['Sharpe']}")
                else:
                    print(" → 데이터 부족")
            except Exception as e:
                print(f" → 오류: {e}")

    # 결과 출력
    df_res = pd.DataFrame(results)
    if len(df_res) == 0:
        print("\n결과 없음")
        return

    print("\n" + "=" * 80)
    print("최종 결과 요약")
    print("=" * 80)
    print(df_res.to_string(index=False))

    # JSON 저장
    out_json = "growth_pullback_results.json"
    df_res.to_json(out_json, orient="records", force_ascii=False, indent=2)
    print(f"\n결과 저장: {out_json}")

    # HTML 리포트 생성
    _make_html_report(df_res)

    return df_res


def _make_html_report(df: pd.DataFrame):
    """결과 HTML 리포트 생성."""
    ts = datetime.now().strftime("%Y-%m-%d %H:%M")

    rows_html = ""
    for _, r in df.iterrows():
        bg = ""
        try:
            cagr = float(r.get("CAGR%", 0) or 0)
            if cagr > 10: bg = "background:#e8f5e9"
            elif cagr > 5: bg = "background:#f1f8e9"
            elif cagr < 0: bg = "background:#fce4ec"
        except Exception:
            pass
        rows_html += f"""<tr style="{bg}">
  <td>{r.get('region','-')}</td>
  <td>{r.get('entry','-')}</td>
  <td>{r.get('stop','-')}</td>
  <td>{r.get('lookback','-')}</td>
  <td>{r.get('topn','-')}</td>
  <td><b>{r.get('CAGR%','-')}</b></td>
  <td>{r.get('MDD%','-')}</td>
  <td>{r.get('Sharpe','-')}</td>
  <td>{r.get('Win%','-')}</td>
  <td>{r.get('TotalRet%','-')}</td>
</tr>"""

    html = f"""<!DOCTYPE html><html lang="ko"><head>
<meta charset="utf-8">
<title>Growth Pullback 백테스트</title>
<style>
body{{font-family:sans-serif;margin:20px;background:#fafafa}}
h1{{color:#1a237e}}
table{{border-collapse:collapse;width:100%;background:white;box-shadow:0 1px 4px rgba(0,0,0,.12)}}
th{{background:#1a237e;color:white;padding:8px 10px;font-size:13px}}
td{{padding:7px 10px;border-bottom:1px solid #eee;font-size:13px}}
tr:hover{{background:#fffde7!important}}
.tag{{display:inline-block;padding:2px 8px;border-radius:3px;font-size:11px}}
.green{{background:#e8f5e9;color:#2e7d32}}.red{{background:#fce4ec;color:#c62828}}
</style></head><body>
<h1>📊 성장주 눌림목(Growth Pullback) 백테스트 결과</h1>
<p>기간: {START} ~ {END} &nbsp;|&nbsp; 생성: {ts} &nbsp;|&nbsp; 초기자본: 1억원</p>
<h3>전략: 가격 프록시 성장주 필터 + 200일선 눌림 매수</h3>
<ul>
<li>성장주 판정: 최근 lookback일 중 Close &gt; MA200 비율 ≥ 70% + 12M 모멘텀 상위 top_n</li>
<li>Entry[touch]: 종가 &gt; MA200 AND (Close-MA200)/MA200 ∈ [0, +5%]</li>
<li>Entry[reclaim]: 전일 종가 &lt; MA200, 당일 종가 &gt; MA200 (재탈환)</li>
<li>Exit: Hard Stop (지정 비율 이상 하회) 또는 성장주 탈락</li>
<li>포트폴리오: 균등비중, 월 리밸런싱</li>
<li>거래비용: KR 0.30%, US 0.11% (왕복)</li>
</ul>
<table>
<tr>
  <th>시장</th><th>Entry</th><th>Stop</th><th>Lookback</th><th>Top-N</th>
  <th>CAGR%</th><th>MDD%</th><th>Sharpe</th><th>Win%</th><th>총수익률%</th>
</tr>
{rows_html}
</table>
<hr style="margin-top:30px">
<p style="color:#888;font-size:12px">QuantMaster Pro -local session 자동 생성. 이 결과는 과거 데이터 기반 시뮬레이션이며 미래 수익을 보장하지 않습니다.</p>
</body></html>"""

    out_html = "growth_pullback_report.html"
    with open(out_html, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"HTML 리포트: {out_html}")


if __name__ == "__main__":
    main()
