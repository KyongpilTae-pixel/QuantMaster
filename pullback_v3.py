"""
pullback_v3.py — B-axis weekly recommendation: MA200 pullback touch/reclaim strategy

Universe : US S&P500 top large-caps + KR KOSPI200 top large-caps
Signal   : growth gate (ratio250 >= 0.70 AND MA200 rising) +
           touch (close just crossed above MA200 and within 0~+5% band) OR
           reclaim (close crossed above MA200 from below)
Exit     : -10% hard stop OR 252-day time exit
Cooldown : 30 trading days between signals for same ticker
"""
from __future__ import annotations

import json
import logging
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

import FinanceDataReader as fdr
import numpy as np
import pandas as pd
import yfinance as yf

log = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    stream=sys.stdout,
)

RESULT_FILE = Path(__file__).parent / "pullback_v3_results.json"
DATA_DIR    = Path(__file__).parent / "cache" / "pullback_v3"
DATA_DIR.mkdir(parents=True, exist_ok=True)

START_DATE  = "2018-01-01"
BACKTEST_START = "2019-01-01"
BACKTEST_END   = "2024-12-31"

MA_WINDOW   = 200
RATIO_WINDOW = 250
RATIO_MIN   = 0.70
MA_SLOPE_DAYS = 20
TOUCH_BAND  = 0.05   # 0~5% above MA200
COOLDOWN    = 30     # trading days
STOP_LOSS   = -0.10
MAX_HOLD    = 252    # trading days

US_UNIVERSE_SIZE = 80
KR_UNIVERSE_SIZE = 90
MAX_WORKERS = 8


# ---------------------------------------------------------------------------
# 1. Universe
# ---------------------------------------------------------------------------

def get_us_universe(n: int = US_UNIVERSE_SIZE) -> list[str]:
    """Top-n S&P500 tickers by market cap via FinanceDataReader."""
    try:
        df = fdr.StockListing("S&P500")
        if df is None or df.empty:
            raise ValueError("empty listing")
        # FDR S&P500 listing may not have market cap; use top-n by order
        tickers = df["Symbol"].dropna().tolist()
        log.info(f"US universe: {len(tickers)} -> top {n}")
        return tickers[:n]
    except Exception as e:
        log.warning(f"FDR S&P500 failed ({e}), using hardcoded fallback")
        # Minimal fallback — large caps
        return [
            "AAPL","MSFT","NVDA","AMZN","GOOGL","META","TSLA","BRK-B","JPM","V",
            "WMT","XOM","UNH","MA","JNJ","PG","HD","MRK","AVGO","CVX",
            "LLY","ABBV","COST","PEP","ADBE","CRM","AMD","TMO","ACN","MCD",
            "NFLX","BAC","TXN","ORCL","INTC","QCOM","DHR","LIN","PM","AMGN",
            "HON","UPS","INTU","CAT","DE","GS","BLK","ISRG","SBUX","AXP",
            "ELV","SYK","REGN","VRTX","SPGI","CB","CME","NOW","PLD","C",
            "GILD","ZTS","ADP","PANW","MO","EOG","SO","DUK","NEE","PGR",
            "MMM","USB","GE","TGT","F","GM","BA","RTX","LMT","NOC",
        ][:n]


def get_kr_universe(n: int = KR_UNIVERSE_SIZE) -> list[str]:
    """Top-n KOSPI200 tickers (appended .KS for yfinance)."""
    try:
        df = fdr.StockListing("KOSPI")
        if df is None or df.empty:
            raise ValueError("empty listing")
        # Marcap column may not exist or may be all NaN
        if "Marcap" in df.columns:
            df = df.dropna(subset=["Marcap"]).sort_values("Marcap", ascending=False)
        codes = df["Code"].dropna().head(n).tolist()
        if not codes:
            raise ValueError("no codes after filtering")
        tickers = [c + ".KS" for c in codes]
        log.info(f"KR universe: {len(tickers)} tickers")
        return tickers
    except Exception as e:
        log.warning(f"FDR KOSPI failed ({e}), using hardcoded fallback")
        codes = [
            "005930","000660","035420","005380","051910","035720","207940","006400",
            "068270","105560","055550","032830","003550","028260","012330","015760",
            "034020","066570","018260","009150","011200","010950","086790","047050",
            "002790","030200","000810","000270","097950","003490","001040","010130",
            "033780","024110","000100","009540","036570","251270","011780","088350",
        ]
        return [c + ".KS" for c in codes[:n]]


# ---------------------------------------------------------------------------
# 2. Data download
# ---------------------------------------------------------------------------

def _download_one(ticker: str) -> tuple[str, pd.DataFrame | None]:
    try:
        cache = DATA_DIR / f"{ticker.replace('/', '_')}.parquet"
        if cache.exists():
            df = pd.read_parquet(cache)
            if isinstance(df.columns, pd.MultiIndex):
                # Cached file has corrupted MultiIndex — delete and re-download
                cache.unlink()
                raise ValueError("MultiIndex columns in cache, forcing re-download")
        else:
            df = yf.download(ticker, start=START_DATE, auto_adjust=True,
                             progress=False, threads=False)
            if df.empty:
                return ticker, None
            # Flatten MultiIndex columns if present
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
            df.to_parquet(cache)
        if df.empty or "Close" not in df.columns:
            return ticker, None
        df = df[["Open", "High", "Low", "Close", "Volume"]].copy()
        df.index = pd.to_datetime(df.index)
        df = df.sort_index().ffill()
        return ticker, df
    except Exception as e:
        log.debug(f"Download failed {ticker}: {e}")
        return ticker, None


def download_universe(tickers: list[str]) -> dict[str, pd.DataFrame]:
    data = {}
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
        futs = {ex.submit(_download_one, t): t for t in tickers}
        for i, fut in enumerate(as_completed(futs), 1):
            ticker, df = fut.result()
            if df is not None:
                data[ticker] = df
            if i % 20 == 0:
                log.info(f"  downloaded {i}/{len(tickers)}")
    log.info(f"Data ready: {len(data)}/{len(tickers)} tickers")
    return data


# ---------------------------------------------------------------------------
# 3. Signal generation
# ---------------------------------------------------------------------------

def compute_signals(ticker: str, df: pd.DataFrame) -> pd.DataFrame:
    """Return DataFrame with signal columns for each trading day."""
    c = df["Close"]
    ma = c.rolling(MA_WINDOW, min_periods=MA_WINDOW).mean()
    above = c > ma
    ratio250 = above.rolling(RATIO_WINDOW, min_periods=RATIO_WINDOW).mean()
    ma_slope = ma > ma.shift(MA_SLOPE_DAYS)

    growth_gate = (ratio250 >= RATIO_MIN) & ma_slope

    # touch   = band-stay entry: above MA200 and within 0~+5% (no crossing required)
    # reclaim = crossing entry:  just crossed above MA200 from below (no band cap)
    # Both are independent streams, each with separate 30-day cooldown dedup.
    crossed_above = above & ~above.shift(1).fillna(False)
    touch   = growth_gate & above & (c <= ma * (1 + TOUCH_BAND))
    reclaim = growth_gate & crossed_above

    out = pd.DataFrame({
        "close": c,
        "ma200": ma,
        "ratio250": ratio250,
        "growth_gate": growth_gate,
        "touch": touch,
        "reclaim": reclaim,
    }, index=df.index)
    return out


# ---------------------------------------------------------------------------
# 4. Backtest
# ---------------------------------------------------------------------------

def run_backtest(
    data: dict[str, pd.DataFrame],
    start: str = BACKTEST_START,
    end: str = BACKTEST_END,
) -> dict:
    """Run touch/reclaim backtest over all tickers."""
    start_dt = pd.Timestamp(start)
    end_dt   = pd.Timestamp(end)

    trades_touch   = []
    trades_reclaim = []

    for ticker, df in data.items():
        sig = compute_signals(ticker, df)
        sig = sig.loc[start_dt:end_dt]
        if sig.empty:
            continue

        # Separate independent cooldown streams for touch and reclaim
        last_touch_idx:   int       = -COOLDOWN - 1
        last_reclaim_idx: int       = -COOLDOWN - 1
        open_touch:   dict | None = None
        open_reclaim: dict | None = None
        indices = sig.index.tolist()

        for i, date in enumerate(indices):
            row   = sig.loc[date]
            close = float(row["close"])

            # --- Touch stream exit ---
            if open_touch is not None:
                days_held = i - open_touch["entry_i"]
                pnl_pct   = close / open_touch["entry_price"] - 1
                exit_type = None
                if pnl_pct <= STOP_LOSS:
                    exit_type = "stop_loss"
                elif days_held >= MAX_HOLD:
                    exit_type = "hold_12m"
                if exit_type:
                    trades_touch.append({
                        **open_touch,
                        "exit_date": date, "exit_price": close,
                        "pnl_pct": pnl_pct, "days_held": days_held,
                        "exit_type": exit_type,
                    })
                    open_touch = None
                    last_touch_idx = i

            # --- Reclaim stream exit ---
            if open_reclaim is not None:
                days_held = i - open_reclaim["entry_i"]
                pnl_pct   = close / open_reclaim["entry_price"] - 1
                exit_type = None
                if pnl_pct <= STOP_LOSS:
                    exit_type = "stop_loss"
                elif days_held >= MAX_HOLD:
                    exit_type = "hold_12m"
                if exit_type:
                    trades_reclaim.append({
                        **open_reclaim,
                        "exit_date": date, "exit_price": close,
                        "pnl_pct": pnl_pct, "days_held": days_held,
                        "exit_type": exit_type,
                    })
                    open_reclaim = None
                    last_reclaim_idx = i

            # --- Touch entry ---
            if open_touch is None and (i - last_touch_idx) > COOLDOWN and bool(row["touch"]):
                open_touch = {
                    "ticker": ticker, "signal_type": "touch",
                    "entry_date": date, "entry_price": close, "entry_i": i,
                }
                last_touch_idx = i

            # --- Reclaim entry ---
            if open_reclaim is None and (i - last_reclaim_idx) > COOLDOWN and bool(row["reclaim"]):
                open_reclaim = {
                    "ticker": ticker, "signal_type": "reclaim",
                    "entry_date": date, "entry_price": close, "entry_i": i,
                }
                last_reclaim_idx = i

    return {"touch": trades_touch, "reclaim": trades_reclaim}


def summarize(trades: list[dict], label: str) -> dict:
    if not trades:
        return {"label": label, "count": 0}
    df = pd.DataFrame(trades)
    n_stop = (df["exit_type"] == "stop_loss").sum()
    n_hold = (df["exit_type"] == "hold_12m").sum()
    hold_df = df[df["exit_type"] == "hold_12m"]
    stop_df = df[df["exit_type"] == "stop_loss"]
    return {
        "label": label,
        "count": len(df),
        "stop_loss": int(n_stop),
        "stop_loss_pct": round(n_stop / len(df) * 100, 1),
        "hold_12m": int(n_hold),
        "hold_12m_avg_pnl": round(hold_df["pnl_pct"].mean() * 100, 1) if len(hold_df) else None,
        "hold_12m_win_rate": round((hold_df["pnl_pct"] > 0).mean() * 100, 1) if len(hold_df) else None,
        "stop_avg_pnl": round(stop_df["pnl_pct"].mean() * 100, 1) if len(stop_df) else None,
        "stop_median_days": int(stop_df["days_held"].median()) if len(stop_df) else None,
    }


# ---------------------------------------------------------------------------
# 5. Live open positions (current as of today)
# ---------------------------------------------------------------------------

def get_live_positions(data: dict[str, pd.DataFrame]) -> dict:
    today = pd.Timestamp.now(tz=None).normalize()
    open_us, open_kr = [], []

    for ticker, df in data.items():
        sig = compute_signals(ticker, df)
        # Separate independent cooldown streams for touch and reclaim
        last_touch_idx   = -COOLDOWN - 1
        last_reclaim_idx = -COOLDOWN - 1
        open_touch:   dict | None = None
        open_reclaim: dict | None = None
        indices = sig.index.tolist()

        for i, date in enumerate(indices):
            row   = sig.loc[date]
            close = float(row["close"])

            # Touch stream update / expire
            if open_touch is not None:
                days_held = i - open_touch["entry_i"]
                pnl_pct   = close / open_touch["entry_price"] - 1
                if pnl_pct <= STOP_LOSS or days_held >= MAX_HOLD:
                    open_touch = None
                    last_touch_idx = i
                else:
                    open_touch["current_price"] = close
                    open_touch["days_held"]     = days_held
                    open_touch["pnl_pct"]       = pnl_pct

            # Reclaim stream update / expire
            if open_reclaim is not None:
                days_held = i - open_reclaim["entry_i"]
                pnl_pct   = close / open_reclaim["entry_price"] - 1
                if pnl_pct <= STOP_LOSS or days_held >= MAX_HOLD:
                    open_reclaim = None
                    last_reclaim_idx = i
                else:
                    open_reclaim["current_price"] = close
                    open_reclaim["days_held"]     = days_held
                    open_reclaim["pnl_pct"]       = pnl_pct

            # Touch entry
            if open_touch is None and (i - last_touch_idx) > COOLDOWN and bool(row["touch"]):
                open_touch = {
                    "ticker": ticker, "signal_type": "touch",
                    "entry_date": str(date.date()), "entry_price": close,
                    "entry_i": i, "current_price": close, "days_held": 0, "pnl_pct": 0.0,
                }
                last_touch_idx = i

            # Reclaim entry
            if open_reclaim is None and (i - last_reclaim_idx) > COOLDOWN and bool(row["reclaim"]):
                open_reclaim = {
                    "ticker": ticker, "signal_type": "reclaim",
                    "entry_date": str(date.date()), "entry_price": close,
                    "entry_i": i, "current_price": close, "days_held": 0, "pnl_pct": 0.0,
                }
                last_reclaim_idx = i

        for open_trade in [open_touch, open_reclaim]:
            if open_trade is not None:
                rec = {k: v for k, v in open_trade.items() if k != "entry_i"}
                rec["pnl_pct"] = round(rec["pnl_pct"] * 100, 2)
                if ".KS" in ticker:
                    open_kr.append(rec)
                else:
                    open_us.append(rec)

    open_us.sort(key=lambda x: x["pnl_pct"], reverse=True)
    open_kr.sort(key=lambda x: x["pnl_pct"], reverse=True)
    return {
        "us_open": open_us,
        "kr_open": open_kr,
        "us_count": len(open_us),
        "kr_count": len(open_kr),
        "us_avg_pnl": round(np.mean([x["pnl_pct"] for x in open_us]), 1) if open_us else None,
        "kr_avg_pnl": round(np.mean([x["pnl_pct"] for x in open_kr]), 1) if open_kr else None,
    }


# ---------------------------------------------------------------------------
# 5b. Cache utilities
# ---------------------------------------------------------------------------

def clean_corrupted_us_cache(tickers: list[str]) -> int:
    """Delete US parquet files with MultiIndex column corruption for re-download."""
    removed = 0
    for ticker in tickers:
        cache = DATA_DIR / f"{ticker.replace('/', '_')}.parquet"
        if not cache.exists():
            continue
        try:
            df = pd.read_parquet(cache)
            if isinstance(df.columns, pd.MultiIndex):
                cache.unlink()
                removed += 1
                log.info(f"Removed corrupted cache: {cache.name}")
            elif "Close" not in df.columns:
                cache.unlink()
                removed += 1
                log.info(f"Removed cache missing Close column: {cache.name}")
        except Exception as e:
            cache.unlink()
            removed += 1
            log.info(f"Removed unreadable cache {cache.name}: {e}")
    return removed


# ---------------------------------------------------------------------------
# 6. Main
# ---------------------------------------------------------------------------

def main():
    log.info("=== pullback_v3: B-axis pullback strategy ===")

    us_tickers = get_us_universe()
    kr_tickers = get_kr_universe()
    all_tickers = us_tickers + kr_tickers
    log.info(f"Universe: {len(us_tickers)} US + {len(kr_tickers)} KR = {len(all_tickers)} total")

    log.info("Cleaning corrupted US parquet cache (MultiIndex fix)...")
    removed = clean_corrupted_us_cache(us_tickers)
    log.info(f"  Removed {removed} corrupted US cache files — will re-download")

    log.info("Downloading price data...")
    data = download_universe(all_tickers)

    log.info(f"Running backtest {BACKTEST_START} ~ {BACKTEST_END}...")
    bt = run_backtest(data)

    touch_summary   = summarize(bt["touch"],   "touch")
    reclaim_summary = summarize(bt["reclaim"], "reclaim")

    log.info("Computing live open positions...")
    live = get_live_positions(data)

    # Self-check comparison
    self_check = {
        "touch": {
            "target_count": 748, "target_stop_pct": 60,
            "target_hold_avg_pnl": 31, "target_hold_win_rate": 95,
        },
        "reclaim": {
            "target_count": 358, "target_stop_pct": 63,
            "target_hold_avg_pnl": 33, "target_hold_win_rate": 97,
        },
    }

    results = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "backtest_period": f"{BACKTEST_START} ~ {BACKTEST_END}",
        "universe": {"us": len(us_tickers), "kr": len(kr_tickers), "downloaded": len(data)},
        "touch": touch_summary,
        "reclaim": reclaim_summary,
        "self_check_targets": self_check,
        "live": live,
    }

    RESULT_FILE.write_text(json.dumps(results, indent=2, ensure_ascii=False, default=str),
                           encoding="utf-8")
    log.info(f"Results saved: {RESULT_FILE}")

    # Print summary
    for label, s in [("touch", touch_summary), ("reclaim", reclaim_summary)]:
        tgt = self_check[label]
        log.info(f"[{label}] count={s.get('count')} "
                 f"stop={s.get('stop_loss_pct')}% (target {tgt['target_stop_pct']}%) "
                 f"hold_avg={s.get('hold_12m_avg_pnl')}% (target +{tgt['target_hold_avg_pnl']}%) "
                 f"win={s.get('hold_12m_win_rate')}% (target {tgt['target_hold_win_rate']}%)")

    log.info(f"Live US: {live['us_count']} open (avg {live['us_avg_pnl']}%) | "
             f"KR: {live['kr_count']} open (avg {live['kr_avg_pnl']}%)")

    return results


if __name__ == "__main__":
    main()
