"""
기간별 종목 모멘텀 스캐너.
삼성전기·LG이노텍 류 '꾸준한 강세주' 발굴.
당일 급등(세력 탐지)이 아닌 수주/수개월 상승 추세 종목 탐색.
"""

import concurrent.futures as cf
import json
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta

import FinanceDataReader as fdr
import pandas as pd

_CACHE_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "cache")

# 기간별 달력일 수 (여유분 포함)
_CALENDAR_DAYS: dict[str, int] = {
    "1W":  12,
    "1M":  35,
    "2M":  65,
    "3M": 100,
}

# 기간별 거래일 수
_TRADE_DAYS: dict[str, int] = {
    "1W":  5,
    "1M": 20,
    "2M": 40,
    "3M": 60,
}

PERIOD_LABELS: dict[str, str] = {
    "1W": "1주",
    "1M": "1개월",
    "2M": "2개월",
    "3M": "3개월",
}


class ScanResults(list):
    """list 서브클래스 — 기존 코드와 완전 호환되면서 경고 메시지를 함께 반환.

    callers:
        results = scan_stock_momentum(...)   # isinstance(results, list) == True
        if results.warning:
            show_warning(results.warning)
    """
    def __init__(self, items=(), *, warning: str = ""):
        super().__init__(items)
        self.warning = warning


def _calc_stock(args: tuple) -> dict | None:
    """단일 종목 OHLCV에서 N일 수익률 + 거래량비를 계산."""
    code, name, mktcap_eok, period = args
    try:
        cal_days   = _CALENDAR_DAYS.get(period, _CALENDAR_DAYS["1M"])
        trade_days = _TRADE_DAYS.get(period, _TRADE_DAYS["1M"])
        end   = datetime.today()
        start = end - timedelta(days=cal_days + 10)

        df = fdr.DataReader(code, start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d"))
        df = df[df["Volume"] > 0].dropna(subset=["Close"])

        if len(df) < max(trade_days, 20):
            return None

        close_now   = float(df["Close"].iloc[-1])
        close_start = float(df["Close"].iloc[-trade_days])
        if close_start == 0:
            return None
        ret = (close_now - close_start) / close_start * 100

        # 거래량 비율 (최근 5일 평균 / 20일 평균)
        vol_5d  = float(df["Volume"].tail(5).mean())
        vol_20d = float(df["Volume"].tail(20).mean())
        vol_ratio = round(vol_5d / vol_20d, 2) if vol_20d > 0 else 1.0

        # 1주 수익률 추가 컬럼 (1M/3M 기간일 때만)
        ret_1w = None
        if period in ("1M", "3M") and len(df) >= 5:
            c_1w = float(df["Close"].iloc[-5])
            if c_1w > 0:
                ret_1w = round((close_now - c_1w) / c_1w * 100, 2)

        return {
            "code":       code,
            "name":       name,
            "close":      close_now,
            "ret_pct":    round(ret, 2),
            "ret_1w":     ret_1w,
            "vol_ratio":  vol_ratio,
            "mktcap_eok": mktcap_eok,
        }
    except Exception:
        return None


def scan_stock_momentum(
    market: str = "KOSPI",
    period: str = "1M",
    min_mktcap_eok: int = 3_000,
    top_n: int = 30,
    max_universe: int = 150,
    _timeout_s: float = 90,
    progress_fn=None,
) -> "ScanResults":
    """기간별 수익률 상위 종목 스캔 (꾸준한 강세주 발굴).

    Args:
        market: "KOSPI" | "KOSDAQ" | "SP500"
        period: "1W" | "1M" | "3M"
        min_mktcap_eok: 최소 시가총액 억원 단위 (KR). US는 S&P500 구성이므로 무시.
        top_n: 반환 최대 종목 수.
        max_universe: 시총 상위 N개로 사전 제한 — 속도 제어. 0이면 전체 사용.
        _timeout_s: 전체 데이터 수신 제한 시간(초). 테스트에서 단축 가능.
    Returns:
        ScanResults — list[dict] 호환. .warning 속성에 문제 발생 시 경고 메시지.
    """
    if period not in _CALENDAR_DAYS:
        period = "1M"

    is_us = market not in ("KOSPI", "KOSDAQ")

    # ── 종목 리스트 ──────────────────────────────────────────────────
    if not is_us:
        from utils.data_loader import fetch_kr_stock_listing
        listing = fetch_kr_stock_listing(market, min_mktcap_eok)
        if listing.empty:
            return ScanResults(warning="종목 목록을 불러오지 못했습니다.")

        cols_lower = {c.lower(): c for c in listing.columns}
        code_col = cols_lower.get("code") or cols_lower.get("symbol", listing.columns[0])
        name_col = cols_lower.get("name", listing.columns[1])
        cap_col  = cols_lower.get("marcap") or cols_lower.get("marketcap")

        if cap_col and min_mktcap_eok > 0:
            listing = listing[listing[cap_col].fillna(0) >= min_mktcap_eok * 1e8]
        if listing.empty:
            return ScanResults(warning="시가총액 조건을 만족하는 종목이 없습니다.")

        # 시총 내림차순 정렬 후 상위 max_universe개로 제한 (속도 최적화)
        if max_universe > 0:
            listing = listing.head(max_universe)

        codes = listing[code_col].tolist()
        names = dict(zip(listing[code_col], listing[name_col]))
        caps: dict = {}
        if cap_col:
            for _, row in listing.iterrows():
                caps[row[code_col]] = round(float(row[cap_col]) / 1e8, 0)

    else:  # US — S&P500 구성 종목
        try:
            sp500 = fdr.StockListing("S&P500")
            code_col = "Symbol" if "Symbol" in sp500.columns else sp500.columns[0]
            name_col = "Name"   if "Name"   in sp500.columns else sp500.columns[1]
            codes = sp500[code_col].dropna().tolist()
            if max_universe > 0:
                codes = codes[:max_universe]
            names = dict(zip(sp500[code_col], sp500[name_col]))
            caps = {}
        except Exception:
            return ScanResults(warning="S&P500 종목 목록을 불러오지 못했습니다.")

    args_list = [(c, names.get(c, c), caps.get(c, 0.0), period) for c in codes]

    total_requested = len(args_list)
    if progress_fn:
        progress_fn(0, total_requested)

    # 10 workers + as_completed로 순차 결과 수집 + progress 콜백 지원
    import time as _time
    executor = ThreadPoolExecutor(max_workers=10)
    futures = [executor.submit(_calc_stock, a) for a in args_list]
    deadline = _time.monotonic() + _timeout_s

    raw = []
    not_done_count = 0
    completed_count = 0
    try:
        for f in cf.as_completed(futures, timeout=_timeout_s):
            try:
                raw.append(f.result(timeout=0))
            except Exception:
                pass
            completed_count += 1
            if progress_fn:
                progress_fn(completed_count, total_requested)
            if _time.monotonic() >= deadline:
                break
    except cf.TimeoutError:
        not_done_count = total_requested - completed_count
    executor.shutdown(wait=False)

    timed_out = not_done_count

    failed = len([r for r in raw if r is None])
    completed = completed_count

    # ── 경고 메시지 조립 ────────────────────────────────────────────
    warn_parts: list[str] = []
    if timed_out > 0:
        warn_parts.append(
            f"⏱ {timed_out}개 종목이 {int(_timeout_s)}초 내 응답하지 않아 제외됨"
        )
    if completed > 0 and failed / completed > 0.4:
        warn_parts.append(
            f"데이터 수신 실패 {failed}/{completed}개 "
            "(시장 데이터 서버 혼잡 가능)"
        )
    warning = " · ".join(warn_parts)

    results = [r for r in raw if r is not None]
    results.sort(key=lambda x: x["ret_pct"], reverse=True)
    top = results[:top_n]

    for i, r in enumerate(top):
        r["rank"]  = i + 1
        r["is_us"] = is_us

        r["ret_str"]       = f"{r['ret_pct']:+.2f}%"
        r["ret_positive"]  = r["ret_pct"] > 0
        r["vol_ratio_str"] = f"{r['vol_ratio']:.2f}x"
        r["vol_up"]        = r["vol_ratio"] >= 1.2

        c = r["close"]
        r["close_str"] = f"{c:,.0f}" if c >= 1 else f"{c:.2f}"

        cap = r["mktcap_eok"]
        r["mktcap_str"] = (
            f"{cap/10000:.1f}조" if cap >= 10_000
            else f"{cap:,.0f}억"  if cap > 0
            else "-"
        )

        ret1w = r.get("ret_1w")
        r["ret_1w_str"]      = f"{ret1w:+.2f}%" if ret1w is not None else "-"
        r["ret_1w_positive"] = ret1w is not None and ret1w > 0
        r["has_ret_1w"]      = ret1w is not None

    return ScanResults(top, warning=warning)


def refresh_stock_momentum(
    existing: list[dict],
    period: str = "1M",
    _timeout_s: float = 60,
) -> "ScanResults":
    """기존 스캔 결과의 종목 코드만 다시 조회해 수익률을 최신화한다.

    전체 유니버스(150종목)를 재스캔하지 않고 이미 발굴된 30종목만 재조회하므로
    훨씬 빠르다 (~10초).

    Args:
        existing: scan_stock_momentum 이 반환한 기존 결과 list[dict].
        period:   재조회 기간. 기존과 다른 기간으로 변환도 가능.
        _timeout_s: 전체 타임아웃(초). 30종목이라 기본 60초면 충분.
    Returns:
        ScanResults — 수익률 내림차순으로 재정렬된 결과.
    """
    if period not in _CALENDAR_DAYS:
        period = "1M"

    if not existing:
        return ScanResults(warning="갱신할 기존 결과가 없습니다.")

    is_us = existing[0].get("is_us", False)
    args_list = [
        (r["code"], r["name"], r.get("mktcap_eok", 0.0), period)
        for r in existing
    ]

    executor = ThreadPoolExecutor(max_workers=10)
    futures = [executor.submit(_calc_stock, a) for a in args_list]
    done, not_done = cf.wait(futures, timeout=_timeout_s)
    executor.shutdown(wait=False)

    timed_out = len(not_done)
    raw = []
    for f in done:
        try:
            raw.append(f.result(timeout=0))
        except Exception:
            pass

    warn_parts: list[str] = []
    if timed_out > 0:
        warn_parts.append(f"⏱ {timed_out}개 종목이 {int(_timeout_s)}초 내 응답하지 않아 제외됨")
    warning = " · ".join(warn_parts)

    results = [r for r in raw if r is not None]
    results.sort(key=lambda x: x["ret_pct"], reverse=True)

    for i, r in enumerate(results):
        r["rank"]  = i + 1
        r["is_us"] = is_us

        r["ret_str"]       = f"{r['ret_pct']:+.2f}%"
        r["ret_positive"]  = r["ret_pct"] > 0
        r["vol_ratio_str"] = f"{r['vol_ratio']:.2f}x"
        r["vol_up"]        = r["vol_ratio"] >= 1.2

        c = r["close"]
        r["close_str"] = f"{c:,.0f}" if c >= 1 else f"{c:.2f}"

        cap = r.get("mktcap_eok", 0)
        r["mktcap_str"] = (
            f"{cap/10000:.1f}조" if cap >= 10_000
            else f"{cap:,.0f}억"  if cap > 0
            else "-"
        )

        ret1w = r.get("ret_1w")
        r["ret_1w_str"]      = f"{ret1w:+.2f}%" if ret1w is not None else "-"
        r["ret_1w_positive"] = ret1w is not None and ret1w > 0
        r["has_ret_1w"]      = ret1w is not None

    return ScanResults(results, warning=warning)


# ---------------------------------------------------------------------------
# 3개월 슬라이딩 윈도우 캐시 — 1회 OHLCV 수집으로 1W/1M/2M/3M 동시 계산
# ---------------------------------------------------------------------------

def _momentum_all_cache_path(market: str) -> str:
    date_str = datetime.today().strftime("%Y%m%d")
    os.makedirs(_CACHE_DIR, exist_ok=True)
    return os.path.join(_CACHE_DIR, f"momentum_{market}_{date_str}.json")


def load_momentum_cache_all(market: str) -> "dict[str, list[dict]] | None":
    """오늘 날짜 전체 기간 캐시가 있으면 {"1W": [...], "1M": [...], ...} 반환."""
    path = _momentum_all_cache_path(market)
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if data else None
    except Exception:
        return None


def save_momentum_cache_all(market: str, data_by_period: "dict[str, list]") -> None:
    """전체 기간 모멘텀 결과를 캐시에 저장하고 30일 이상 된 파일 정리."""
    path = _momentum_all_cache_path(market)
    try:
        serializable = {k: list(v) for k, v in data_by_period.items()}
        with open(path, "w", encoding="utf-8") as f:
            json.dump(serializable, f, ensure_ascii=False, indent=2)
    except Exception:
        pass
    # 30일 초과 파일 자동 정리
    cutoff = datetime.today() - timedelta(days=30)
    try:
        for fname in os.listdir(_CACHE_DIR):
            if not fname.startswith("momentum_") or not fname.endswith(".json"):
                continue
            date_part = fname[:-5].rsplit("_", 1)[-1]
            try:
                if datetime.strptime(date_part, "%Y%m%d") < cutoff:
                    os.remove(os.path.join(_CACHE_DIR, fname))
            except ValueError:
                pass
    except Exception:
        pass


def _calc_stock_all_periods(args: tuple) -> "dict[str, dict] | None":
    """단일 종목 OHLCV 1회 수집으로 1W/1M/2M/3M 수익률을 동시 계산."""
    code, name, mktcap_eok = args
    try:
        end   = datetime.today()
        start = end - timedelta(days=110)  # 3개월 + 여유분

        df = fdr.DataReader(code, start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d"))
        df = df[df["Volume"] > 0].dropna(subset=["Close"])

        if len(df) < 20:
            return None

        close_now = float(df["Close"].iloc[-1])
        vol_5d    = float(df["Volume"].tail(5).mean())
        vol_20d   = float(df["Volume"].tail(20).mean())
        vol_ratio = round(vol_5d / vol_20d, 2) if vol_20d > 0 else 1.0

        # 1주 수익률 (1M/2M/3M 부가 컬럼)
        ret_1w = None
        if len(df) >= 5:
            c_1w = float(df["Close"].iloc[-5])
            if c_1w > 0:
                ret_1w = round((close_now - c_1w) / c_1w * 100, 2)

        results: dict[str, dict] = {}
        for period, trade_days in _TRADE_DAYS.items():
            if len(df) < max(trade_days, 20):
                continue
            close_start = float(df["Close"].iloc[-trade_days])
            if close_start == 0:
                continue
            ret = round((close_now - close_start) / close_start * 100, 2)
            results[period] = {
                "code":       code,
                "name":       name,
                "close":      close_now,
                "ret_pct":    ret,
                "ret_1w":     ret_1w if period != "1W" else None,
                "vol_ratio":  vol_ratio,
                "mktcap_eok": mktcap_eok,
            }
        return results if results else None
    except Exception:
        return None


def _format_results(top: list, is_us: bool) -> list:
    """상위 종목 리스트에 rank·표시용 문자열 필드 추가."""
    for i, r in enumerate(top):
        r["rank"]  = i + 1
        r["is_us"] = is_us

        r["ret_str"]       = f"{r['ret_pct']:+.2f}%"
        r["ret_positive"]  = r["ret_pct"] > 0
        r["vol_ratio_str"] = f"{r['vol_ratio']:.2f}x"
        r["vol_up"]        = r["vol_ratio"] >= 1.2

        c = r["close"]
        r["close_str"] = f"{c:,.0f}" if c >= 1 else f"{c:.2f}"

        cap = r.get("mktcap_eok", 0)
        r["mktcap_str"] = (
            f"{cap/10000:.1f}조" if cap >= 10_000
            else f"{cap:,.0f}억"  if cap > 0
            else "-"
        )

        ret1w = r.get("ret_1w")
        r["ret_1w_str"]      = f"{ret1w:+.2f}%" if ret1w is not None else "-"
        r["ret_1w_positive"] = ret1w is not None and ret1w > 0
        r["has_ret_1w"]      = ret1w is not None
    return top


def scan_stock_momentum_all_periods(
    market: str = "KOSPI",
    min_mktcap_eok: int = 1_000,
    top_n: int = 30,
    max_universe: int = 150,
    _timeout_s: float = 90,
    progress_fn=None,
) -> "dict[str, ScanResults]":
    """3개월 OHLCV 1회 수집으로 1W/1M/2M/3M 기간별 TOP N을 동시 반환.

    Returns:
        {"1W": ScanResults([...]), "1M": ScanResults([...]), ...}
        각 ScanResults는 list[dict] 호환이며 .warning 속성 포함.
    """
    is_us = market not in ("KOSPI", "KOSDAQ")

    # ── 종목 리스트 ──────────────────────────────────────────────────
    if not is_us:
        from utils.data_loader import fetch_kr_stock_listing
        listing = fetch_kr_stock_listing(market, min_mktcap_eok)
        if listing.empty:
            return {p: ScanResults(warning="종목 목록을 불러오지 못했습니다.") for p in _TRADE_DAYS}

        cols_lower = {c.lower(): c for c in listing.columns}
        code_col = cols_lower.get("code") or cols_lower.get("symbol", listing.columns[0])
        name_col = cols_lower.get("name", listing.columns[1])
        cap_col  = cols_lower.get("marcap") or cols_lower.get("marketcap")

        if cap_col and min_mktcap_eok > 0:
            listing = listing[listing[cap_col].fillna(0) >= min_mktcap_eok * 1e8]
        if listing.empty:
            return {p: ScanResults(warning="시가총액 조건을 만족하는 종목이 없습니다.") for p in _TRADE_DAYS}

        if max_universe > 0:
            listing = listing.head(max_universe)

        codes = listing[code_col].tolist()
        names = dict(zip(listing[code_col], listing[name_col]))
        caps: dict = {}
        if cap_col:
            for _, row in listing.iterrows():
                caps[row[code_col]] = round(float(row[cap_col]) / 1e8, 0)
    else:
        try:
            sp500 = fdr.StockListing("S&P500")
            code_col = "Symbol" if "Symbol" in sp500.columns else sp500.columns[0]
            name_col = "Name"   if "Name"   in sp500.columns else sp500.columns[1]
            codes = sp500[code_col].dropna().tolist()
            if max_universe > 0:
                codes = codes[:max_universe]
            names = dict(zip(sp500[code_col], sp500[name_col]))
            caps = {}
        except Exception:
            return {p: ScanResults(warning="S&P500 종목 목록을 불러오지 못했습니다.") for p in _TRADE_DAYS}

    args_list = [(c, names.get(c, c), caps.get(c, 0.0)) for c in codes]
    total_requested = len(args_list)
    if progress_fn:
        progress_fn(0, total_requested)

    # ── 병렬 수집 (as_completed + 타임아웃) ─────────────────────────
    import time as _time
    executor = ThreadPoolExecutor(max_workers=10)
    futures  = [executor.submit(_calc_stock_all_periods, a) for a in args_list]
    deadline = _time.monotonic() + _timeout_s

    per_period: dict[str, list] = {p: [] for p in _TRADE_DAYS}
    completed_count = 0
    timed_out = 0
    try:
        for f in cf.as_completed(futures, timeout=_timeout_s):
            try:
                result = f.result(timeout=0)
                if result:
                    for period, row in result.items():
                        per_period[period].append(row)
            except Exception:
                pass
            completed_count += 1
            if progress_fn:
                progress_fn(completed_count, total_requested)
            if _time.monotonic() >= deadline:
                timed_out = total_requested - completed_count
                break
    except cf.TimeoutError:
        timed_out = total_requested - completed_count
    executor.shutdown(wait=False)

    # ── 경고 메시지 ─────────────────────────────────────────────────
    warn = f"⏱ {timed_out}개 종목이 {int(_timeout_s)}초 내 응답하지 않아 제외됨" if timed_out > 0 else ""

    # ── 기간별 정렬·TOP N·포맷팅 ────────────────────────────────────
    output: dict[str, ScanResults] = {}
    for period, rows in per_period.items():
        rows.sort(key=lambda x: x["ret_pct"], reverse=True)
        top = rows[:top_n]
        _format_results(top, is_us)
        output[period] = ScanResults(top, warning=warn)

    return output
