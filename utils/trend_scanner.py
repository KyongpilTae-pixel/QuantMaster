"""
추세추종 스캐너 (Trend Following Scanner)
방법론: 《시장의 마법사》 프롤리히 + 쿨라매기 스타일
전략: 상승장 + RS90+ / 절대강도 + EMA눌림목 / 신고가돌파 / 박스권돌파
순위: EV = (승률 × 손익비) - (1-승률), 반감기 3년 가중치
"""

import numpy as np
import pandas as pd
from concurrent.futures import ThreadPoolExecutor, as_completed
from utils.data_loader import QuantDataLoader

_loader = QuantDataLoader()

_HOLD_DAYS      = 60      # 기본 보유기간 (거래일)
_HALFLIFE_YEARS = 3.0     # 반감기 3년
_MIN_SAMPLES    = 10      # 최소 표본 수
_LOOKBACK_DAYS  = 1500    # ~6년 OHLCV


# ── 지표 계산 ──────────────────────────────────────────────────────

def _ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False).mean()


def _calc_stock_returns(df: pd.DataFrame) -> list:
    """1M/3M/6M/12M 수익률 반환"""
    close = df["Close"]
    result = []
    for p in [21, 63, 126, 252]:
        if len(close) >= p + 1:
            result.append(float(close.iloc[-1] / close.iloc[-(p + 1)] - 1))
        else:
            result.append(None)
    return result


def _compute_rs_composite(rets_map: dict) -> dict:
    """각 기간별 퍼센타일 → 평균 컴포짓 RS 스코어 (0~100)"""
    period_data = {i: {} for i in range(4)}
    for sym, rets in rets_map.items():
        for i, r in enumerate(rets):
            if r is not None:
                period_data[i][sym] = r
    scores: dict = {}
    for _, data in period_data.items():
        if not data:
            continue
        s = pd.Series(data)
        pct = s.rank(pct=True) * 100
        for sym, v in pct.items():
            scores.setdefault(sym, []).append(float(v))
    return {sym: float(np.mean(vs)) for sym, vs in scores.items()}


def _check_absolute_strength(df: pd.DataFrame) -> tuple:
    """단기(EMA10>EMA20 우상향) + 장기(200일선 6개월 유지)"""
    if len(df) < 210:
        return False, False
    close = df["Close"]
    ema10  = _ema(close, 10)
    ema20  = _ema(close, 20)
    sma200 = close.rolling(200).mean()

    short_ok = bool(
        ema10.iloc[-1] > ema20.iloc[-1]
        and all(ema10.diff().iloc[-5:] > 0)
        and all(ema20.diff().iloc[-5:] > 0)
    )

    above     = (close > sma200).iloc[-126:]
    max_breach = curr = 0
    for v in above:
        curr = curr + 1 if not v else 0
        max_breach = max(max_breach, curr)
    long_ok = max_breach <= 5

    return short_ok, long_ok


def _detect_signals(df: pd.DataFrame) -> list:
    """현재 진입 신호 감지 (눌림목 / 신고가 돌파 / 박스권 돌파)"""
    signals = []
    close   = df["Close"]
    high    = df["High"]
    low     = df["Low"]
    cur     = float(close.iloc[-1])

    # 1. MA 눌림목 (-2% ~ +3%)
    for period, label in [(10, "EMA10"), (20, "EMA20"), (60, "EMA60")]:
        if len(df) < period + 5:
            continue
        ma_val = float(_ema(close, period).iloc[-1])
        gap = (cur - ma_val) / ma_val * 100
        if -2.0 <= gap <= 3.0:
            signals.append({
                "entry_type":   "pullback",
                "entry_label":  f"{label} 눌림목",
                "ma_period":    period,
                "gap_pct":      round(gap, 2),
                "breakout_pct": 0.0,
            })

    # 2. N일 신고가 돌파 (20/55/252일)
    for n, label in [(20, "20일"), (55, "55일"), (252, "역대최고가")]:
        if len(df) < n + 2:
            continue
        prev_high = float(high.iloc[-n - 1: -1].max())
        if cur > prev_high:
            bp = (cur - prev_high) / prev_high * 100
            signals.append({
                "entry_type":   "breakout_n",
                "entry_label":  f"{label} 신고가 돌파",
                "ma_period":    n,
                "gap_pct":      0.0,
                "breakout_pct": round(bp, 2),
            })

    # 3. 박스권 돌파 (+5% 미만)
    if len(df) >= 63:
        box_high = float(high.iloc[-62:-1].max())
        box_low  = float(low.iloc[-62:-1].min())
        box_range = (box_high - box_low) / box_low * 100
        if box_range <= 20 and cur > box_high:
            bp = (cur - box_high) / box_high * 100
            if 0 < bp < 5.0:
                signals.append({
                    "entry_type":   "box_breakout",
                    "entry_label":  "박스권 돌파",
                    "ma_period":    61,
                    "gap_pct":      0.0,
                    "breakout_pct": round(bp, 2),
                })

    return signals


def _calc_ev(df: pd.DataFrame, entry_type: str, ma_period: int,
             hold_days: int = _HOLD_DAYS,
             halflife_years: float = _HALFLIFE_YEARS) -> dict:
    """반감기 가중 EV 계산 (벡터화)"""
    _empty = {
        "ev": None, "win_rate": None, "pl_ratio": None,
        "sample_n": 0, "avg_profit": None, "avg_loss": None,
    }
    lam   = np.log(2) / (halflife_years * 252)
    close = df["Close"]
    high  = df["High"]
    low   = df["Low"]
    n     = len(close)

    if n < hold_days + 20:
        return _empty

    # 진입 신호 벡터화
    if entry_type == "pullback":
        ma     = _ema(close, ma_period)
        gap    = (close - ma) / ma * 100
        signal = ((gap >= -2.0) & (gap <= 3.0)).values

    elif entry_type == "breakout_n":
        prev_high = high.shift(1).rolling(ma_period).max()
        signal    = (close > prev_high).values

    elif entry_type == "box_breakout":
        box_high  = high.shift(1).rolling(61).max()
        box_low   = low.shift(1).rolling(61).min()
        box_range = (box_high - box_low) / box_low * 100
        bp        = (close - box_high) / box_high * 100
        signal    = (
            (box_range <= 20) & (close > box_high) & (bp > 0) & (bp < 5.0)
        ).values

    else:
        return _empty

    # 진입 인덱스 (홀드 기간 확보)
    valid_idx = np.where(signal[: n - hold_days])[0]

    if len(valid_idx) < _MIN_SAMPLES:
        return {**_empty, "sample_n": int(len(valid_idx))}

    close_arr    = close.values
    entry_prices = close_arr[valid_idx]
    exit_prices  = close_arr[valid_idx + hold_days]
    returns      = (exit_prices - entry_prices) / entry_prices * 100

    # 반감기 가중치 (최신일수록 높음)
    days_ago = (n - 1) - valid_idx
    weights  = np.exp(-lam * days_ago)

    wins      = returns > 0
    total_w   = weights.sum()
    win_rate  = float(weights[wins].sum() / total_w) if total_w > 0 else 0.0

    if wins.sum() == 0 or (~wins).sum() == 0:
        return {**_empty,
                "win_rate":  round(win_rate * 100, 1),
                "sample_n":  int(len(valid_idx))}

    avg_profit = float((returns[wins]  * weights[wins]).sum()  / weights[wins].sum())
    avg_loss   = float(abs((returns[~wins] * weights[~wins]).sum() / weights[~wins].sum()))
    pl_ratio   = avg_profit / avg_loss if avg_loss > 0 else None
    ev         = float(win_rate * pl_ratio - (1 - win_rate)) if pl_ratio else None

    return {
        "ev":         round(ev, 3)       if ev         is not None else None,
        "win_rate":   round(win_rate * 100, 1),
        "avg_profit": round(avg_profit, 1),
        "avg_loss":   round(avg_loss, 1),
        "pl_ratio":   round(pl_ratio, 2) if pl_ratio   is not None else None,
        "sample_n":   int(len(valid_idx)),
    }


# ── 종목별 처리 ────────────────────────────────────────────────────

def _process_one(code, name, is_us, rs_score, df) -> list:
    """단일 종목 신호 감지 + EV 계산"""
    try:
        short_ok, long_ok = _check_absolute_strength(df)
        signals = _detect_signals(df)
        if not signals:
            return []

        cur_close = float(df["Close"].iloc[-1])
        results   = []

        for sig in signals:
            ev_info = _calc_ev(df, sig["entry_type"], sig["ma_period"])
            if ev_info["ev"] is None:
                continue
            ev_val  = ev_info.get("ev") or 0
            wr_val  = ev_info.get("win_rate") or 0
            pl_val  = ev_info.get("pl_ratio") or 0
            ap_val  = ev_info.get("avg_profit") or 0
            al_val  = ev_info.get("avg_loss") or 0
            sn_val  = ev_info.get("sample_n") or 0
            is_kr   = not is_us
            close_str = (
                f"₩{cur_close:,.0f}" if is_kr else f"${cur_close:,.2f}"
            )
            results.append({
                "code":            code,
                "name":            name,
                "close":           cur_close,
                "close_str":       close_str,
                "rs_score":        round(rs_score, 1),
                "rs_score_str":    f"{rs_score:.0f}",
                "entry_type":      sig["entry_type"],
                "entry_label":     sig["entry_label"],
                "ma_period":       sig["ma_period"],
                "gap_pct":         sig["gap_pct"],
                "breakout_pct":    sig["breakout_pct"],
                **ev_info,
                "ev_str":          f"{ev_val:.3f}",
                "win_rate_str":    f"{wr_val:.1f}%",
                "pl_ratio_str":    f"{pl_val:.2f}" if pl_val else "-",
                "avg_profit_str":  f"+{ap_val:.1f}%",
                "avg_loss_str":    f"-{al_val:.1f}%",
                "sample_n_str":    str(sn_val),
                "rank":            0,      # 정렬 후 재설정
                "short_ok":        short_ok,
                "long_ok":         long_ok,
                "is_us":           is_us,
                # rx.foreach bool flags
                "ev_high":         ev_val >= 1.0,
                "rs_high":         rs_score >= 95,
                "is_pullback":     sig["entry_type"] == "pullback",
                "is_breakout":     sig["entry_type"] in ("breakout_n", "box_breakout"),
            })

        return results
    except Exception:
        return []


# ── 보유기간별 상세 EV 계산 ────────────────────────────────────────

def calc_holding_period_ev(
    df: pd.DataFrame,
    entry_type: str,
    ma_period: int,
    periods: list = None,
    halflife_years: float = _HALFLIFE_YEARS,
) -> list:
    """보유기간별(2/3/5/10/20/60/126/252일) EV 계산 — 상세 백테스트용"""
    if periods is None:
        periods = [2, 3, 5, 10, 20, 60, 126, 252]

    results = []
    for hold_days in periods:
        ev_info = _calc_ev(df, entry_type, ma_period, hold_days, halflife_years)
        ev_val   = ev_info.get("ev")
        wr_val   = ev_info.get("win_rate") or 0.0
        ap_val   = ev_info.get("avg_profit") or 0.0
        al_val   = ev_info.get("avg_loss") or 0.0
        pl_val   = ev_info.get("pl_ratio")
        sn_val   = ev_info.get("sample_n") or 0

        results.append({
            "period":          hold_days,
            "period_label":    f"{hold_days}일",
            "ev":              ev_val,
            "ev_str":          f"{ev_val:.3f}" if ev_val is not None else "-",
            "win_rate":        wr_val,
            "win_rate_str":    f"{wr_val:.1f}%" if wr_val else "-",
            "avg_profit":      ap_val,
            "avg_profit_str":  f"+{ap_val:.1f}%" if ap_val else "-",
            "avg_loss":        al_val,
            "avg_loss_str":    f"-{al_val:.1f}%" if al_val else "-",
            "pl_ratio":        pl_val,
            "pl_ratio_str":    f"{pl_val:.2f}" if pl_val is not None else "-",
            "sample_n":        sn_val,
            "sample_n_str":    str(sn_val),
            # Reflex foreach bool flags
            "ev_high":         (ev_val or 0) >= 1.0,
            "ev_positive":     (ev_val or 0) > 0,
            "win_rate_high":   wr_val >= 60.0,
            "has_data":        ev_val is not None,
        })
    return results


# ── 메인 스캔 함수 ─────────────────────────────────────────────────

def scan_trend_following(
    market: str         = "KOSPI",
    filter_mode: str    = "relative",   # "relative"|"absolute"|"both"
    min_mktcap_eok: float = 3_000.0,
    top_n: int          = 30,
    max_universe: int   = 150,
    progress_fn         = None,
) -> "ScanResults":
    """
    추세추종 스캔
    filter_mode='relative'  → RS 90+ 필터
    filter_mode='absolute'  → EMA10>EMA20 + 200일선 6개월 필터
    filter_mode='both'      → RS90+ AND 절대강도 둘 다
    """
    from utils.stock_scanner import ScanResults

    is_us = market in ("SP500", "NASDAQ")

    # 1. 유니버스
    snap = _loader.get_market_snapshot(market)
    if snap is None or snap.empty:
        r = ScanResults([])
        r.warning = "시장 데이터 수집 실패"
        return r

    if "MarketCap" in snap.columns:
        snap = snap[snap["MarketCap"] >= min_mktcap_eok * 1e8]
    snap = snap.head(max_universe).reset_index(drop=True)

    symbols = snap["Symbol"].tolist()
    names   = dict(zip(snap["Symbol"],
                       snap["Name"] if "Name" in snap.columns else snap["Symbol"]))

    total        = len(symbols)
    done_count   = [0]
    rets_map: dict  = {}
    ohlcv_cache: dict = {}

    # 2. 병렬 OHLCV 수집
    def _fetch(sym):
        try:
            return sym, _loader.get_ohlcv(sym, lookback_days=_LOOKBACK_DAYS)
        except Exception:
            return sym, None

    with ThreadPoolExecutor(max_workers=8) as pool:
        futs = {pool.submit(_fetch, s): s for s in symbols}
        for fut in as_completed(futs):
            sym, df = fut.result()
            done_count[0] += 1
            if df is not None and len(df) >= 60:
                ohlcv_cache[sym] = df
                rets_map[sym]    = _calc_stock_returns(df)
            if progress_fn:
                progress_fn(done_count[0], total)

    # 3. RS 컴포짓 스코어
    rs_scores = _compute_rs_composite(rets_map)

    # 4. 필터링
    candidates = []
    for sym in symbols:
        if sym not in ohlcv_cache:
            continue
        rs = rs_scores.get(sym, 0.0)
        df = ohlcv_cache[sym]

        if filter_mode == "relative":
            if rs < 90:
                continue
        elif filter_mode == "absolute":
            short_ok, long_ok = _check_absolute_strength(df)
            if not (short_ok or long_ok):
                continue
        elif filter_mode == "both":
            if rs < 90:
                continue
            short_ok, long_ok = _check_absolute_strength(df)
            if not (short_ok or long_ok):
                continue

        candidates.append((sym, names.get(sym, sym), is_us, rs, df))

    # 5. EV 계산 + 신호 감지 (병렬)
    all_results: list = []
    with ThreadPoolExecutor(max_workers=6) as pool:
        futs = [pool.submit(_process_one, *c) for c in candidates]
        for fut in as_completed(futs):
            rows = fut.result()
            if rows:
                all_results.extend(rows)

    # 6. EV 내림차순 정렬 + 순위 번호
    all_results.sort(key=lambda x: x.get("ev") or -999, reverse=True)
    all_results = all_results[:top_n]
    for i, row in enumerate(all_results):
        row["rank"] = i + 1

    result = ScanResults(all_results)
    if not all_results:
        result.warning = (
            f"신호 없음 (RS90+ 후보: {len(candidates)}개, "
            f"유니버스: {len(ohlcv_cache)}개)"
        )
    return result
