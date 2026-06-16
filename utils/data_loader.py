"""
NAVER Finance 기반 시장 데이터 로더 (한국 + 미국).
한국: NAVER Finance 스크래핑 (pykrx KRX API 연결 불가로 대체)
미국: FinanceDataReader + yfinance 병렬 조회 + Yahoo Finance 스크리너
"""

import json
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta

_CACHE_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "cache")

import FinanceDataReader as fdr
import numpy as np
import pandas as pd
import requests
from bs4 import BeautifulSoup


# ---------------------------------------------------------------------------
# 한국 시장 (NAVER Finance)
# ---------------------------------------------------------------------------

_MARKET_CODE = {"KOSPI": "0", "KOSDAQ": "1"}

_ETF_API_URL = "https://finance.naver.com/api/sise/etfItemList.naver"
_ETF_MARKETS  = {"KR-ETF", "US-ETF"}
_US_ETF_MARKETS = {"US-ETF"}

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}

# 미국 시장: FinanceDataReader 리스팅 키
_US_MARKET_FDR = {"SP500": "S&P500", "NASDAQ": "NASDAQ"}


def _make_session() -> requests.Session:
    """PBR 필드가 포함된 NAVER Finance 세션 생성."""
    s = requests.Session()
    s.post(
        "https://finance.naver.com/sise/field_submit.naver",
        data={
            "menu": "market_sum",
            "returnUrl": "http://finance.naver.com/sise/sise_market_sum.naver",
            "fieldIds": ["market_sum", "sales", "dividend", "per", "roe", "pbr"],
        },
        headers=_HEADERS,
        timeout=10,
    )
    return s


def _parse_page(session: requests.Session, sosok: str, page: int) -> list[dict]:
    """NAVER Finance 시가총액 페이지 1장을 파싱해 종목 목록 반환."""
    url = (
        f"https://finance.naver.com/sise/sise_market_sum.naver"
        f"?sosok={sosok}&page={page}"
    )
    r = session.get(url, headers=_HEADERS, timeout=10)
    soup = BeautifulSoup(r.content.decode("euc-kr", errors="replace"), "lxml")

    rows = soup.select("table.type_2 tbody tr")
    records = []
    for row in rows:
        a = row.find("a", class_="tltle")
        if not a:
            continue
        href = a.get("href", "")
        code = href.split("code=")[-1] if "code=" in href else ""
        name = a.text.strip()

        cells = row.find_all("td")
        texts = [c.text.strip().replace(",", "").replace("%", "") for c in cells]
        # 컬럼 순서(field_submit market_sum+sales+dividend+per+roe+pbr 이후):
        # [0]N [1]종목명 [2]현재가 [3]전일비 [4]등락률 [5]거래량
        # [6]시가총액(억원) [7]매출액(억원) [8]배당수익률(%) [9]PER [10]ROE [11]PBR
        if len(texts) < 12:
            continue
        try:
            mktcap      = float(texts[6])  if texts[6]  not in ("", "N/A", "-") else np.nan
            sales       = float(texts[7])  if texts[7]  not in ("", "N/A", "-") else np.nan
            div_per_shr = float(texts[8])  if texts[8]  not in ("", "N/A", "-") else np.nan
            per         = float(texts[9])  if texts[9]  not in ("", "N/A", "-") else np.nan
            roe         = float(texts[10]) if texts[10] not in ("", "N/A", "-") else np.nan
            pbr         = float(texts[11]) if texts[11] not in ("", "N/A", "-") else np.nan
            price       = float(texts[2])  if texts[2]  else np.nan
        except ValueError:
            continue

        # NAVER dividend 필드는 주당배당금(원) → 수익률(%)로 변환
        if not np.isnan(div_per_shr) and not np.isnan(price) and price > 0:
            div_yld = round(div_per_shr / price * 100, 2)
            if div_yld > 30:   # 비정상값 방어
                div_yld = np.nan
        else:
            div_yld = np.nan

        if np.isnan(pbr) or pbr <= 0:
            continue

        psr = round(mktcap / sales, 2) if (sales and sales > 0 and not np.isnan(mktcap)) else np.nan

        records.append(
            {
                "Symbol": code,
                "Name": name,
                "Close": price,
                "PBR": pbr,
                "PER": per,
                "ROE": roe,
                "MarketCap": mktcap,   # 억원
                "Sales": sales,         # 억원
                "PSR": psr,
                "DivYield": div_yld,   # %
            }
        )
    return records


# ---------------------------------------------------------------------------
# 미국 시장 (yfinance)
# ---------------------------------------------------------------------------


def _fetch_us_fundamentals(symbol: str) -> dict | None:
    """yfinance로 단일 종목 기본 데이터(PBR, ROE, 현재가) 조회."""
    try:
        import yfinance as yf

        info = yf.Ticker(symbol).info
        pbr = info.get("priceToBook")
        roe = info.get("returnOnEquity")
        price = info.get("currentPrice") or info.get("regularMarketPrice") or 0.0
        name = info.get("shortName") or symbol
        if not pbr or pbr <= 0:
            return None
        mktcap_raw = info.get("marketCap")
        psr_raw    = info.get("priceToSalesTrailing12Months")
        div_raw    = info.get("dividendYield")  # decimal (e.g. 0.015 = 1.5%)
        return {
            "Symbol": symbol,
            "Name": name,
            "Close": float(price),
            "PBR": float(pbr),
            "ROE": float(roe * 100) if roe else np.nan,
            "PER": float(info.get("trailingPE") or np.nan),
            "MarketCap": float(mktcap_raw / 1e9) if mktcap_raw else np.nan,
            "PSR": float(psr_raw) if psr_raw else np.nan,
            "DivYield": round(float(div_raw) * 100, 2) if div_raw else np.nan,  # %
        }
    except Exception:
        return None


def _fetch_us_etf_price(symbol: str) -> dict | None:
    """yfinance로 미국 ETF 가격·시가총액 조회 (PBR 불필요)."""
    try:
        import yfinance as yf
        info = yf.Ticker(symbol).info
        price = info.get("currentPrice") or info.get("regularMarketPrice") or info.get("navPrice") or 0.0
        if not price or price <= 0:
            return None
        name = info.get("shortName") or info.get("longName") or symbol
        mktcap_raw = info.get("totalAssets") or info.get("marketCap")  # ETF는 totalAssets 우선
        div_raw = info.get("dividendYield")
        return {
            "Symbol":   symbol,
            "Name":     name,
            "Close":    float(price),
            "PBR":      0.0,        # ETF에는 PBR 없음
            "GPA_Score":1.0,        # 퀀트 필터 항상 통과
            "ROE":      50.0,
            "PER":      np.nan,
            "MarketCap":float(mktcap_raw / 1e9) if mktcap_raw else np.nan,  # billion USD
            "PSR":      np.nan,
            "DivYield": round(float(div_raw) * 100, 2) if div_raw else np.nan,
        }
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Main Loader
# ---------------------------------------------------------------------------


class QuantDataLoader:
    def __init__(self):
        self._session: requests.Session | None = None

    def _get_session(self) -> requests.Session:
        if self._session is None:
            self._session = _make_session()
        return self._session

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_market_snapshot(
        self, market: str = "KOSPI", max_pages: int = 8
    ) -> pd.DataFrame:
        """
        시장 스냅샷 조회.
        - 한국(KOSPI/KOSDAQ): NAVER Finance 스크래핑, max_pages × ~50종목
        - 미국(SP500/NASDAQ): FinanceDataReader 리스트 + yfinance 병렬 조회,
          max_pages × 30종목 처리
        GPA_Score = ROE 백분위 (Novy-Marx GP/A 프록시).
        """
        if market in _US_ETF_MARKETS:
            return self._get_etf_us_snapshot(max_pages)
        if market in _ETF_MARKETS:
            return self._get_etf_kr_snapshot()
        if market in _US_MARKET_FDR:
            return self._get_us_snapshot(market, max_pages)
        return self._get_kr_snapshot(market, max_pages)

    def _get_etf_kr_snapshot(self) -> pd.DataFrame:
        """NAVER ETF API로 한국 ETF 스냅샷 반환.
        PBR/GPA 없으므로 기술적 필터 전용으로 사용.
        """
        _empty = pd.DataFrame(
            columns=["Symbol", "Name", "Close", "MarketCap", "GPA_Score", "PBR", "ROE"]
        )
        try:
            r = requests.get(_ETF_API_URL, headers=_HEADERS, timeout=15)
            items = r.json()["result"]["etfItemList"]
        except Exception as e:
            print(f"[DataLoader] ETF 목록 조회 실패: {e}")
            return _empty

        records: list[dict] = []
        for item in items:
            try:
                price = item.get("nowVal") or 0
                if price <= 0:
                    continue
                records.append({
                    "Symbol":    str(item["itemcode"]),
                    "Name":      item["itemname"],
                    "Close":     float(price),
                    "MarketCap": float(item.get("marketSum") or 0),  # 억원
                    "Volume":    int(item.get("quant") or 0),
                    # ETF에는 PBR/GPA 없음 → 퀀트 필터를 항상 통과하도록 설정
                    "PBR":       0.0,
                    "GPA_Score": 1.0,
                    "ROE":       50.0,
                    "PSR":       float("nan"),
                    "DivYield":  float("nan"),
                })
            except Exception:
                continue

        if not records:
            return _empty
        df = pd.DataFrame(records)
        df = df.sort_values("MarketCap", ascending=False).reset_index(drop=True)
        return df

    def _get_etf_us_snapshot(self, max_pages: int) -> pd.DataFrame:
        """FinanceDataReader ETF/US 목록 + yfinance 병렬 가격 조회."""
        _empty = pd.DataFrame(
            columns=["Symbol", "Name", "Close", "MarketCap", "GPA_Score", "PBR", "ROE"]
        )
        try:
            listing = fdr.StockListing("ETF/US")
            sym_col = next((c for c in listing.columns if c.lower() in ("symbol", "code")), None)
            if sym_col is None:
                raise ValueError("Symbol 열 없음")
            symbols = listing[sym_col].dropna().astype(str).tolist()
        except Exception as e:
            print(f"[DataLoader] US ETF 목록 조회 실패: {e}")
            return _empty

        max_symbols = max_pages * 30
        symbols = [s for s in symbols if s and "." not in s][:max_symbols]

        records: list[dict] = []
        with ThreadPoolExecutor(max_workers=8) as executor:
            futures = {executor.submit(_fetch_us_etf_price, sym): sym for sym in symbols}
            for future in as_completed(futures):
                result = future.result()
                if result:
                    records.append(result)

        if not records:
            return _empty

        df = pd.DataFrame(records)
        df["GPA_Score"] = 1.0   # 퀀트 필터 스킵용 고정값
        df = df.sort_values("MarketCap", ascending=False).reset_index(drop=True)
        return df

    def _get_kr_snapshot(self, market: str, max_pages: int) -> pd.DataFrame:
        sosok = _MARKET_CODE.get(market, "0")
        session = self._get_session()

        all_records: list[dict] = []
        for page in range(1, max_pages + 1):
            try:
                records = _parse_page(session, sosok, page)
                all_records.extend(records)
                time.sleep(0.3)
            except Exception as e:
                print(f"[DataLoader] page {page} 오류: {e}")
                break

        if not all_records:
            return pd.DataFrame(
                columns=["Symbol", "Name", "Close", "PBR", "PER", "ROE", "MarketCap", "GPA_Score"]
            )

        df = pd.DataFrame(all_records)
        df["GPA_Score"] = df["ROE"].rank(pct=True)
        return df.reset_index(drop=True)

    def _get_us_snapshot(self, market: str, max_pages: int) -> pd.DataFrame:
        """yfinance 병렬 조회로 미국 시장 스냅샷 반환."""
        fdr_key = _US_MARKET_FDR[market]
        try:
            listing = fdr.StockListing(fdr_key)
            # 열 이름이 다를 수 있으므로 Symbol 열 탐색
            sym_col = next(
                (c for c in listing.columns if c.lower() in ("symbol", "code")), None
            )
            if sym_col is None:
                raise ValueError("Symbol 열 없음")
            symbols = listing[sym_col].dropna().astype(str).tolist()
        except Exception as e:
            print(f"[DataLoader] US 리스트 조회 실패: {e}")
            return pd.DataFrame(
                columns=["Symbol", "Name", "Close", "PBR", "PER", "ROE", "GPA_Score"]
            )

        max_symbols = max_pages * 30
        symbols = [s for s in symbols if s and "." not in s][:max_symbols]

        records: list[dict] = []
        with ThreadPoolExecutor(max_workers=8) as executor:
            futures = {
                executor.submit(_fetch_us_fundamentals, sym): sym for sym in symbols
            }
            for future in as_completed(futures):
                result = future.result()
                if result:
                    records.append(result)

        if not records:
            return pd.DataFrame(
                columns=["Symbol", "Name", "Close", "PBR", "PER", "ROE", "MarketCap", "GPA_Score"]
            )

        df = pd.DataFrame(records)
        df["GPA_Score"] = df["ROE"].rank(pct=True)
        return df.reset_index(drop=True)

    def get_quarterly_psr(self, symbol: str, market: str) -> list[dict]:
        """분기별 PSR 추이 반환 (최근 8분기)."""
        import yfinance as yf

        if market in ("KOSPI", "KOSDAQ"):
            suffix = ".KS" if market == "KOSPI" else ".KQ"
            yf_symbol = symbol + suffix
        else:
            yf_symbol = symbol

        try:
            ticker = yf.Ticker(yf_symbol)
            info = ticker.info
            shares = info.get("sharesOutstanding") or info.get("impliedSharesOutstanding")
            if not shares:
                return []

            fin = ticker.quarterly_financials
            rev_row = next(
                (r for r in ["Total Revenue", "Revenues", "Revenue"] if r in fin.index),
                None,
            )
            if rev_row is None:
                return []
            rev = fin.loc[rev_row].dropna().sort_index()

            hist = ticker.history(period="2y")
            if hist.empty:
                return []
            quarterly_close = hist["Close"].resample("QE").last().dropna()

            results = []
            for date, revenue in rev.items():
                if revenue <= 0:
                    continue
                # 해당 분기 종가
                idx = quarterly_close.index.get_indexer([date], method="nearest")[0]
                if idx < 0:
                    continue
                close = quarterly_close.iloc[idx]
                mktcap = close * shares
                annual_rev = revenue * 4  # 연환산
                psr = round(mktcap / annual_rev, 2)
                quarter = f"{date.year}Q{(date.month - 1) // 3 + 1}"
                results.append({"quarter": quarter, "PSR": psr})

            return sorted(results, key=lambda x: x["quarter"])[-8:]
        except Exception as e:
            print(f"[quarterly_psr] {yf_symbol}: {e}")
            return []

    def get_ohlcv(self, symbol: str, lookback_days: int = 400) -> pd.DataFrame:
        """FinanceDataReader로 OHLCV 데이터 반환 (한국/미국 공통)."""
        end = datetime.today()
        start = end - timedelta(days=lookback_days)
        df = fdr.DataReader(
            symbol,
            start.strftime("%Y-%m-%d"),
            end.strftime("%Y-%m-%d"),
        )
        df = df.dropna(subset=["Close", "Volume"])
        df = df[df["Volume"] > 0]
        return df


# ---------------------------------------------------------------------------
# 단일 종목 조회 (종목조회 탭용)
# ---------------------------------------------------------------------------

_kr_listing_cache: pd.DataFrame | None = None
_kr_etf_listing_cache: pd.DataFrame | None = None
_kr_etn_listing_cache: pd.DataFrame | None = None


def _get_kr_listing() -> pd.DataFrame:
    global _kr_listing_cache
    if _kr_listing_cache is None:
        try:
            _kr_listing_cache = fdr.StockListing("KRX")
        except Exception:
            return pd.DataFrame()  # 실패 시 캐시하지 않고 빈 DataFrame 반환
    return _kr_listing_cache


def _get_kr_etf_listing() -> pd.DataFrame:
    global _kr_etf_listing_cache
    if _kr_etf_listing_cache is None:
        try:
            _kr_etf_listing_cache = fdr.StockListing("ETF/KR")
        except Exception:
            _kr_etf_listing_cache = pd.DataFrame()
    return _kr_etf_listing_cache


def _get_kr_etn_listing() -> pd.DataFrame:
    global _kr_etn_listing_cache
    if _kr_etn_listing_cache is None:
        try:
            _kr_etn_listing_cache = fdr.StockListing("ETN/KR")
        except Exception:
            _kr_etn_listing_cache = pd.DataFrame()
    return _kr_etn_listing_cache


def _is_kr_etf(code: str) -> bool:
    """6자리 코드가 한국 ETF인지 확인."""
    try:
        listing = _get_kr_etf_listing()
        if listing.empty:
            return False
        sym_col = "Symbol" if "Symbol" in listing.columns else listing.columns[0]
        return not listing[listing[sym_col] == code].empty
    except Exception:
        return False


def _is_kr_structured_product(code: str, name: str = "") -> bool:
    """ETF 또는 ETN 여부 확인 (이름 기반 fallback 포함)."""
    if _is_kr_etf(code):
        return True
    if "ETN" in name.upper():
        return True
    try:
        listing = _get_kr_etn_listing()
        if not listing.empty:
            sym_col = "Symbol" if "Symbol" in listing.columns else listing.columns[0]
            if not listing[listing[sym_col] == code].empty:
                return True
    except Exception:
        pass
    return False


def fetch_etf_analysis(code: str) -> dict:
    """NAVER 모바일 API로 ETF 기본 정보 + 구성종목 TOP10 조회."""
    try:
        url = f"https://m.stock.naver.com/api/stock/{code}/etfAnalysis"
        r = requests.get(url, headers=_HEADERS, timeout=10)
        if r.status_code != 200:
            return {}
        d = r.json()

        components = [
            {
                "rank": str(item.get("seq", "")),
                "code": item.get("itemCode", ""),
                "name": item.get("itemName", ""),
                "count": item.get("stockCount", "-"),
                "weight": item.get("etfWeight", "-"),
            }
            for item in d.get("etfTop10MajorConstituentAssets", [])
        ]

        return {
            "base_index": d.get("etfBaseIndex", "-"),
            "nav": f"{d.get('nav', 0):,.0f}",
            "total_fee": f"{d.get('totalFee', 0):.2f}%",
            "chase_error": f"{d.get('chaseErrorRate', 0):.2f}%",
            "issuer": d.get("issuerName", "-"),
            "components": components,
        }
    except Exception:
        return {}


def fetch_kr_stock_listing(market: str, min_mktcap_eok: int = 0) -> pd.DataFrame:
    """KR 종목 목록 조회. fdr 실패 시 NAVER sise_market_sum으로 fallback.

    Returns DataFrame with columns: Code, Name, Marcap (원 단위).
    """
    try:
        df = fdr.StockListing(market)
        if df is not None and not df.empty:
            return df
    except Exception:
        pass

    # NAVER fallback — sise_market_sum 페이지 페이지네이션
    sosok = "0" if market == "KOSPI" else "1"
    session = _make_session()
    rows: list[dict] = []
    for page in range(1, 40):  # 최대 40페이지 ≈ 2000 종목
        page_data = _parse_page(session, sosok, page)
        if not page_data:
            break
        for item in page_data:
            mktcap_eok = item.get("MarketCap") or 0
            if min_mktcap_eok > 0 and mktcap_eok < min_mktcap_eok:
                # 시가총액 내림차순 정렬이므로 이하로 내려가면 종료
                return pd.DataFrame(rows) if rows else pd.DataFrame()
            rows.append({
                "Code": item["Symbol"],
                "Name": item["Name"],
                "Marcap": mktcap_eok * 1e8,  # 억원 → 원
            })
    return pd.DataFrame(rows) if rows else pd.DataFrame()


def _search_kr_symbol(query: str) -> tuple[str, str]:
    """종목명 또는 6자리 코드로 (심볼, 시장) 반환. 없으면 ("", "")."""
    q = query.strip()
    try:
        listing = _get_kr_listing()
        if not listing.empty:
            code_col = "Code" if "Code" in listing.columns else "Symbol"
            name_col = next((c for c in ["Name", "회사명", "종목명"] if c in listing.columns), None)
            mkt_col = next((c for c in ["Market", "시장구분"] if c in listing.columns), None)

            match = listing[listing[code_col].str.strip() == q]
            if match.empty and name_col:
                match = listing[listing[name_col].str.contains(q, case=False, na=False)]

            if not match.empty:
                row = match.iloc[0]
                code = str(row[code_col]).strip().zfill(6)
                market = str(row[mkt_col]).upper() if mkt_col else "KOSPI"
                return (code, market)
    except Exception:
        pass

    # KRX 목록 실패 or 미등재 — 6자리 숫자 코드이면 직접 KOSPI 처리
    if q.isdigit() and len(q) == 6:
        return (q, "KOSPI")

    return ("", "")


def _fetch_kr_naver_fundamentals(code: str) -> dict | None:
    """NAVER polling API로 KR 종목 실시간 기초 지표 반환.

    반환 키: nv(현재가), sv(전일종가), cv(변동금액), cr(변동률%), rf(방향 2=상승/5=하락),
             eps, bps, dv(주당배당금원), countOfListedStock, nm(종목명)
    """
    try:
        url = f"https://polling.finance.naver.com/api/realtime?query=SERVICE_ITEM:{code}"
        r = requests.get(url, headers=_HEADERS, timeout=5)
        r.raise_for_status()
        item = r.json()["result"]["areas"][0]["datas"][0]
        return item
    except Exception:
        return None


def fetch_stock_info(query: str, market: str) -> dict:
    """단일 종목 기본 정보 조회. market: 'KR' or 'US'.

    Returns dict:
        name, symbol, price, change_pct, change_positive,
        market_cap, div_yield, pbr, per, roe, psr, vwap, mfi,
        chart_data(List[dict]: date/종가/VWAP/MA20), error
    """
    import math
    import yfinance as yf
    from utils.indicators import TechnicalIndicators

    def _fmt(v, fmt=".2f", suffix="") -> str:
        if v is None or (isinstance(v, float) and (math.isnan(v) or math.isinf(v))):
            return "-"
        return f"{v:{fmt}}{suffix}"

    result: dict = {
        "name": "", "symbol": "", "price": 0.0, "change_pct": 0.0,
        "change_positive": False, "market_cap": "-", "div_yield": "-",
        "pbr": "-", "per": "-", "roe": "-", "psr": "-",
        "vwap": "-", "mfi": "-", "chart_data": [], "error": "",
        "buy_score": 0, "buy_score_max": 8, "buy_score_str": "-",
        "buy_opinion": "", "buy_opinion_color": "gray",
        "buy_score_items": [],
        "is_etf": False, "etf_analysis": {},
    }

    try:
        if market == "KR":
            symbol, kr_market = _search_kr_symbol(query)
            if not symbol:
                result["error"] = f"'{query}' 종목을 찾을 수 없습니다"
                return result

            # 1. NAVER polling API — 현재가·PBR·PER·배당
            naver = _fetch_kr_naver_fundamentals(symbol)
            if naver:
                nv = float(naver.get("nv") or naver.get("sv") or 0)
                sv = float(naver.get("sv") or nv)
                cr = float(naver.get("cr") or 0)
                rf = str(naver.get("rf") or "")
                change_pct = round(-cr if rf == "5" else cr, 2)
                eps = float(naver.get("eps") or 0)
                bps = float(naver.get("bps") or 0)
                dv = float(naver.get("dv") or 0)
                shares = float(naver.get("countOfListedStock") or 0)
                nm = naver.get("nm") or query

                mktcap_eok = nv * shares / 1e8 if nv and shares else None
                per_val = round(nv / eps, 2) if eps > 0 else None
                pbr_val = round(nv / bps, 2) if bps > 0 else None
                div_val = round(dv / nv * 100, 2) if dv > 0 and nv > 0 else None

                result.update({
                    "name": nm,
                    "symbol": symbol,
                    "price": nv,
                    "change_pct": change_pct,
                    "change_positive": change_pct >= 0,
                    "market_cap": f"{mktcap_eok:,.0f}억원" if mktcap_eok else "-",
                    "div_yield": _fmt(div_val, ".2f", "%"),
                    "pbr": _fmt(pbr_val),
                    "per": _fmt(per_val, ".1f"),
                })
            else:
                result.update({"name": query, "symbol": symbol})

            # 2. yfinance — ROE·PSR (NAVER에 없음)
            suffix = ".KQ" if "KOSDAQ" in kr_market.upper() else ".KS"
            try:
                yf_info = yf.Ticker(symbol + suffix).info
                roe_raw = yf_info.get("returnOnEquity")
                psr_raw = yf_info.get("priceToSalesTrailing12Months")
                result["roe"] = _fmt(roe_raw * 100 if roe_raw else None, ".1f", "%")
                result["psr"] = _fmt(psr_raw)
                if not result["name"] or result["name"] == query:
                    result["name"] = yf_info.get("longName") or yf_info.get("shortName") or query
            except Exception:
                pass

            fdr_symbol = symbol

            # ETF 여부 확인 및 구성종목 조회
            if _is_kr_etf(symbol):
                result["is_etf"] = True
                result["etf_analysis"] = fetch_etf_analysis(symbol)

        else:  # US
            symbol = query.strip().upper()
            info = yf.Ticker(symbol).info
            price = float(info.get("currentPrice") or info.get("regularMarketPrice") or 0)
            if not price:
                result["error"] = f"'{symbol}' 종목을 찾을 수 없습니다"
                return result

            prev = float(info.get("regularMarketPreviousClose") or price)
            change_pct = round((price - prev) / prev * 100, 2) if prev else 0.0
            mktcap = info.get("marketCap")
            div_raw = info.get("dividendYield")
            roe_raw = info.get("returnOnEquity")

            result.update({
                "name": info.get("shortName") or info.get("longName") or symbol,
                "symbol": symbol,
                "price": price,
                "change_pct": change_pct,
                "change_positive": change_pct >= 0,
                "market_cap": f"${mktcap / 1e9:,.1f}B" if mktcap else "-",
                "div_yield": _fmt(div_raw * 100 if div_raw else None, ".2f", "%"),
                "pbr": _fmt(info.get("priceToBook")),
                "per": _fmt(info.get("trailingPE"), ".1f"),
                "roe": _fmt(roe_raw * 100 if roe_raw else None, ".1f", "%"),
                "psr": _fmt(info.get("priceToSalesTrailing12Months")),
            })
            fdr_symbol = symbol

        # OHLCV → VWAP_20, MFI, 차트 데이터
        end = datetime.today()
        start = end - timedelta(days=150)
        df = fdr.DataReader(fdr_symbol, start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d"))
        df = df.dropna(subset=["Close", "Volume"])
        df = df[df["Volume"] > 0]
        if not df.empty and "High" in df.columns:
            df = TechnicalIndicators.calculate_all(df, windows=[20, 60])
            last = df.iloc[-1]

            def _v(val):
                return round(float(val), 0) if val is not None and not math.isnan(float(val)) else None

            price_val = result["price"] or float(last["Close"])
            vwap_val = _v(last.get("VWAP_20"))
            mfi_val = _v(last.get("MFI"))
            vwap_gap = round((price_val - vwap_val) / vwap_val * 100, 2) if vwap_val else None

            result["vwap"] = _fmt(vwap_val, ",.0f") + (f" ({vwap_gap:+.1f}%)" if vwap_gap is not None else "")
            result["mfi"] = _fmt(mfi_val, ".1f")

            # ── 매수 의견 점수 계산 ──────────────────────────────
            score = 0
            score_items = []
            vwap60_val = _v(last.get("VWAP_60"))
            obv_last = float(last.get("OBV") or 0)
            obv_sig_last = float(last.get("OBV_Sig") or 0)

            # 1. VWAP20 돌파 (최대 +2, 과열 -1)
            if vwap_val:
                if price_val > vwap_val:
                    score += 2
                    score_items.append({
                        "label": "VWAP20 돌파",
                        "detail": f"현재가 > VWAP20 ({vwap_gap:+.1f}%)",
                        "score_str": "+2", "positive": True,
                    })
                    if vwap_gap is not None:
                        if 0 < vwap_gap <= 5:
                            score += 1
                            score_items.append({
                                "label": "이격도 적정",
                                "detail": f"VWAP 이격 {vwap_gap:+.1f}% (5% 이내 진입 적정)",
                                "score_str": "+1", "positive": True,
                            })
                        elif vwap_gap > 10:
                            score -= 1
                            score_items.append({
                                "label": "VWAP 과열",
                                "detail": f"VWAP 이격 {vwap_gap:+.1f}% (10% 초과 과열)",
                                "score_str": "-1", "positive": False,
                            })
                        else:
                            score_items.append({
                                "label": "이격도 보통",
                                "detail": f"VWAP 이격 {vwap_gap:+.1f}% (5~10%)",
                                "score_str": "0", "positive": False,
                            })
                else:
                    score_items.append({
                        "label": "VWAP20 미돌파",
                        "detail": f"현재가 < VWAP20 (이격 {vwap_gap:+.1f}%)" if vwap_gap is not None else "현재가 < VWAP20",
                        "score_str": "0", "positive": False,
                    })

            # 2. VWAP 정배열 (VWAP20 > VWAP60, +1)
            if vwap_val and vwap60_val:
                if vwap_val > vwap60_val:
                    score += 1
                    score_items.append({
                        "label": "VWAP 정배열",
                        "detail": f"VWAP20({vwap_val:,.0f}) > VWAP60({vwap60_val:,.0f})",
                        "score_str": "+1", "positive": True,
                    })
                else:
                    score_items.append({
                        "label": "VWAP 역배열",
                        "detail": f"VWAP20 < VWAP60 (하락 추세)",
                        "score_str": "0", "positive": False,
                    })

            # 3. OBV 매수세: OBV > OBV_Sig (+2)
            if not (math.isnan(obv_last) or math.isnan(obv_sig_last)):
                if obv_last > obv_sig_last:
                    score += 2
                    score_items.append({
                        "label": "OBV 매수세",
                        "detail": "OBV > 신호선(20일 MA), 매수 거래량 우세",
                        "score_str": "+2", "positive": True,
                    })
                else:
                    score_items.append({
                        "label": "OBV 매도세",
                        "detail": "OBV < 신호선(20일 MA), 매도 거래량 우세",
                        "score_str": "0", "positive": False,
                    })

            # 4. OBV 5일 추세 (+1)
            obv_series = df["OBV"].dropna()
            if len(obv_series) >= 5:
                obv_trend = float(obv_series.diff().tail(5).mean())
                if obv_trend > 0:
                    score += 1
                    score_items.append({
                        "label": "OBV 5일 상승",
                        "detail": "최근 5일 OBV 평균 증가 (매집 신호)",
                        "score_str": "+1", "positive": True,
                    })
                else:
                    score_items.append({
                        "label": "OBV 5일 하락",
                        "detail": "최근 5일 OBV 평균 감소 (분산 신호)",
                        "score_str": "0", "positive": False,
                    })

            # 5. MFI 구간 (+1 or -1)
            if mfi_val is not None:
                if 40 <= mfi_val <= 75:
                    score += 1
                    score_items.append({
                        "label": "MFI 적정",
                        "detail": f"MFI {mfi_val:.0f}, 40~75 건강한 매수 구간",
                        "score_str": "+1", "positive": True,
                    })
                elif mfi_val > 80:
                    score -= 1
                    score_items.append({
                        "label": "MFI 과열",
                        "detail": f"MFI {mfi_val:.0f}, 80 초과 단기 과열",
                        "score_str": "-1", "positive": False,
                    })
                else:
                    score_items.append({
                        "label": "MFI 약세",
                        "detail": f"MFI {mfi_val:.0f}, 40 미만 (모멘텀 부족)",
                        "score_str": "0", "positive": False,
                    })

            # 의견 결정
            if score >= 7:
                opinion, color = "강력 매수", "green"
            elif score >= 5:
                opinion, color = "매수 검토", "blue"
            elif score >= 3:
                opinion, color = "중립", "gray"
            elif score >= 0:
                opinion, color = "관망", "orange"
            else:
                opinion, color = "주의", "red"

            result.update({
                "buy_score": score,
                "buy_score_str": f"{score}/8",
                "buy_opinion": opinion,
                "buy_opinion_color": color,
                "buy_score_items": score_items,
            })

            disp = df.tail(120)
            result["chart_data"] = [
                {
                    "date": str(d.date()),
                    "종가": _v(row["Close"]),
                    "VWAP20": _v(row["VWAP_20"]),
                    "VWAP60": _v(row["VWAP_60"]),
                    "MA20": _v(row["TWAP_20"]),
                    "MA60": _v(row["TWAP_60"]),
                }
                for d, row in disp.iterrows()
            ]

    except Exception as e:
        result["error"] = str(e)

    return result


def fetch_market_leaders(
    mode: str = "volume",
    market: str = "KOSPI",
    top_n: int = 25,
) -> list[dict]:
    """당일 주도주 목록 조회.

    mode   : "volume" = 거래량 상위, "rise" = 상승률 상위
    market : "KOSPI" or "KOSDAQ"
    Returns list of dicts with pre-computed bool flags for rx.foreach safety.
    """
    sosok = "0" if market == "KOSPI" else "1"
    url_map = {"volume": "sise_quant", "rise": "sise_rise"}
    url = f"https://finance.naver.com/sise/{url_map.get(mode, 'sise_quant')}.naver?sosok={sosok}"

    r = requests.get(url, headers=_HEADERS, timeout=10)
    soup = BeautifulSoup(r.content.decode("euc-kr", "replace"), "html.parser")
    rows = soup.select("table.type_2 tr")

    results = []
    for row in rows[2:]:
        tds = row.find_all("td")
        if not tds or len(tds) < 6:
            continue
        a = row.find("a", href=True)
        if not a or "code=" not in a.get("href", ""):
            continue

        code = a["href"].split("code=")[-1].strip()
        cols = [c.get_text(strip=True) for c in tds]

        name = cols[1]
        price_raw = cols[2].replace(",", "")
        change_pct_str = cols[4]  # e.g. "+9.48%" or "-10.97%"
        vol_str = cols[5]

        try:
            price = float(price_raw)
        except ValueError:
            continue

        try:
            change_pct = float(change_pct_str.replace("%", "").replace("+", ""))
        except ValueError:
            change_pct = 0.0

        try:
            today_volume = int(vol_str.replace(",", ""))
        except ValueError:
            today_volume = 0

        results.append({
            "rank": len(results) + 1,
            "code": code,
            "name": name,
            "price_str": cols[2],
            "change_pct_str": change_pct_str,
            "change_pct_val": change_pct,
            "volume_str": vol_str,
            "today_volume": today_volume,
            "change_positive": change_pct >= 0,
        })

        if len(results) >= top_n:
            break

    return results


def _get_mktcap_jo(code: str) -> tuple[str, str]:
    """NAVER polling API로 종목 시가총액을 조원 단위 문자열로 반환."""
    try:
        item = _fetch_kr_naver_fundamentals(code)
        if not item:
            return code, "-"
        nv     = float(item.get("nv") or item.get("sv") or 0)
        shares = float(item.get("countOfListedStock") or 0)
        if nv > 0 and shares > 0:
            jo = nv * shares / 1e12
            if jo >= 1.0:
                return code, f"{jo:.1f}조"
            eok = nv * shares / 1e8
            return code, f"{eok:,.0f}억"
        return code, "-"
    except Exception:
        return code, "-"


def _get_leaders_extra(code: str) -> tuple[str, str, bool]:
    """NAVER polling API로 시가총액 문자열 + 고가 근처 여부(종가/고가 ≥ 98%) 반환."""
    try:
        item = _fetch_kr_naver_fundamentals(code)
        if not item:
            return code, "-", False
        nv     = float(item.get("nv") or item.get("sv") or 0)
        hv     = float(item.get("hv") or 0)
        shares = float(item.get("countOfListedStock") or 0)
        if nv > 0 and shares > 0:
            jo = nv * shares / 1e12
            mktcap_str = f"{jo:.1f}조" if jo >= 1.0 else f"{nv * shares / 1e8:,.0f}억"
        else:
            mktcap_str = "-"
        is_near_high = hv > 0 and (nv / hv) >= 0.98
        return code, mktcap_str, is_near_high
    except Exception:
        return code, "-", False


def fetch_leaders_combined(market: str = "KOSPI", top_n: int = 30) -> list[dict]:
    """거래량 상위 + 상승률 상위를 합쳐 방법A 점수(순위 역수 합산)를 계산한다.

    market: "KOSPI" | "KOSDAQ" | "US"
    score_a = 1/거래량순위 + 1/상승률순위  (없으면 0)
    반환 목록은 score_a 내림차순 정렬.
    """
    if market == "US":
        return _fetch_leaders_combined_us(top_n)

    _NO_CACHE_HINT = "평일 장중에 한 번 조회하면 이후 주말·공휴일에도 표시됩니다."

    # 주말: NAVER 요청 없이 바로 캐시 조회
    today = datetime.today()
    if today.weekday() in (5, 6):
        day_name = "토요일" if today.weekday() == 5 else "일요일"
        cached = _load_recent_leaders_cache(market)
        if cached:
            return cached
        raise RuntimeError(f"{day_name}입니다 — {market} 이전 거래일 캐시 없음. {_NO_CACHE_HINT}")

    with ThreadPoolExecutor(max_workers=2) as ex:
        vol_fut  = ex.submit(fetch_market_leaders, "volume", market, top_n)
        rise_fut = ex.submit(fetch_market_leaders, "rise",   market, top_n)
        vol_list  = vol_fut.result()
        rise_list = rise_fut.result()

    # 장 시작 전 또는 공휴일: NAVER 빈 결과 → 직전 거래일 캐시로 대체
    if not vol_list and not rise_list:
        cached = _load_recent_leaders_cache(market)
        if cached:
            return cached
        raise RuntimeError(
            f"{market} 거래 데이터 없음 (장 시작 전 또는 공휴일) — 이전 캐시도 없습니다. {_NO_CACHE_HINT}"
        )

    vol_rank_map  = {item["code"]: item["rank"] for item in vol_list}
    rise_rank_map = {item["code"]: item["rank"] for item in rise_list}

    info_by_code: dict = {}
    for item in vol_list + rise_list:
        if item["code"] not in info_by_code:
            info_by_code[item["code"]] = item

    # KR 기준일: 한국 시간 오늘 날짜
    _today_kr = datetime.today().strftime("%Y-%m-%d")
    _dn_kr = ["월", "화", "수", "목", "금", "토", "일"][datetime.today().weekday()]
    _kr_data_date = f"{_today_kr} ({_dn_kr})"

    combined = []
    for code, base in info_by_code.items():
        vr = vol_rank_map.get(code)
        rr = rise_rank_map.get(code)
        score_a = (1 / vr if vr else 0.0) + (1 / rr if rr else 0.0)

        combined.append({
            **base,
            "vol_rank_val":  vr or 0,
            "rise_rank_val": rr or 0,
            "vol_rank_str":  str(vr) if vr else "-",
            "rise_rank_str": str(rr) if rr else "-",
            "has_vol_rank":  vr is not None,
            "has_rise_rank": rr is not None,
            "score_a":     round(score_a, 4),
            "score_a_str": f"{score_a:.3f}",
            "vol_ratio":   0.0,
            "score_b":     0.0,
            "score_b_str": "-",
            "has_score_b": False,
            "mktcap_str":  "-",
            "is_us":       False,
            "is_near_high": False,
            "data_date":   _kr_data_date,
        })

    # ETF/ETN 여부 배치 체크
    try:
        etf_listing = _get_kr_etf_listing()
        sym_col = "Symbol" if "Symbol" in etf_listing.columns else (etf_listing.columns[0] if not etf_listing.empty else "Symbol")
        etf_codes = set(etf_listing[sym_col].astype(str).tolist()) if not etf_listing.empty else set()
    except Exception:
        etf_codes = set()
    try:
        etn_listing = _get_kr_etn_listing()
        sym_col2 = "Symbol" if "Symbol" in etn_listing.columns else (etn_listing.columns[0] if not etn_listing.empty else "Symbol")
        etn_codes = set(etn_listing[sym_col2].astype(str).tolist()) if not etn_listing.empty else set()
    except Exception:
        etn_codes = set()

    for item in combined:
        item["is_etf"] = (
            item["code"] in etf_codes
            or item["code"] in etn_codes
            or "ETN" in item.get("name", "").upper()
        )

    combined.sort(key=lambda x: x["score_a"], reverse=True)
    top = combined[:top_n]
    for i, item in enumerate(top):
        item["rank"] = i + 1

    # 시가총액 + 고가 근처 여부 병렬 조회
    codes = [item["code"] for item in top]
    with ThreadPoolExecutor(max_workers=10) as ex:
        extra_results = list(ex.map(_get_leaders_extra, codes))
    extra_map = {code: (mktcap, near_high) for code, mktcap, near_high in extra_results}
    for item in top:
        mktcap, near_high = extra_map.get(item["code"], ("-", False))
        item["mktcap_str"] = mktcap
        item["is_near_high"] = near_high

    return top


# ---------------------------------------------------------------------------
# 미국 시장 당일 주도주 (Yahoo Finance 스크리너)
# ---------------------------------------------------------------------------

_YF_SCREENER_URL = (
    "https://query1.finance.yahoo.com/v1/finance/screener/predefined/saved"
    "?formatted=false&lang=en-US&region=US&count={count}&scrIds={scr_id}"
)
_YF_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "application/json",
    "Accept-Language": "en-US,en;q=0.9",
}


def _fmt_us_mktcap(raw: float) -> str:
    if raw >= 1e12:
        return f"${raw/1e12:.1f}T"
    if raw >= 1e9:
        return f"${raw/1e9:.1f}B"
    if raw >= 1e6:
        return f"${raw/1e6:.0f}M"
    return "-"


def _fetch_us_yahoo_screener(scr_id: str, top_n: int = 30) -> list[dict]:
    """Yahoo Finance 스크리너 API로 미국 시장 상위 종목 조회.

    result=null 은 미국 장 전/후에 발생할 수 있으므로 빈 리스트로 처리.
    """
    def _parse_quotes(resp) -> list:
        result_obj = resp.json().get("finance", {}).get("result")
        if not result_obj:
            return []
        return result_obj[0].get("quotes") or []

    url = _YF_SCREENER_URL.format(count=top_n, scr_id=scr_id)
    quotes: list = []
    try:
        r = requests.get(url, headers=_YF_HEADERS, timeout=10)
        r.raise_for_status()
        quotes = _parse_quotes(r)
    except Exception:
        pass

    if not quotes:
        # query2 fallback
        try:
            url2 = url.replace("query1", "query2")
            r2 = requests.get(url2, headers=_YF_HEADERS, timeout=10)
            r2.raise_for_status()
            quotes = _parse_quotes(r2)
        except Exception:
            quotes = []

    # 첫 번째 quote 의 regularMarketTime → 미국 동부시간(EDT=UTC-4) 기준 날짜 문자열
    data_date = ""
    first_ts = next((q.get("regularMarketTime") for q in quotes if q.get("regularMarketTime")), None)
    if first_ts:
        from datetime import timezone, timedelta as _td
        _edt = timezone(_td(hours=-4))
        _dt  = datetime.fromtimestamp(first_ts, tz=_edt)
        _dn  = ["월", "화", "수", "목", "금", "토", "일"][_dt.weekday()]
        data_date = f"{_dt.strftime('%Y-%m-%d')} ({_dn})"

    results = []
    for i, q in enumerate(quotes):
        symbol = q.get("symbol", "")
        if not symbol:
            continue
        name = q.get("shortName") or q.get("longName") or symbol
        price = float(q.get("regularMarketPrice") or 0)
        change_pct = float(q.get("regularMarketChangePercent") or 0)
        volume = int(q.get("regularMarketVolume") or 0)
        mkt_cap_raw = float(q.get("marketCap") or 0)
        quote_type = q.get("quoteType", "")
        day_high = float(q.get("regularMarketDayHigh") or 0)

        results.append({
            "rank": i + 1,
            "code": symbol,
            "name": name,
            "price_str": f"${price:,.2f}",
            "change_pct_str": f"{change_pct:+.2f}%",
            "change_pct_val": round(change_pct, 2),
            "volume_str": f"{volume:,}",
            "today_volume": volume,
            "change_positive": change_pct >= 0,
            "mktcap_str": _fmt_us_mktcap(mkt_cap_raw),
            "is_us": True,
            "quote_type": quote_type,
            "day_high": day_high,
            "price_raw": price,
            "data_date": data_date,
        })
        if len(results) >= top_n:
            break

    return results


def _fetch_leaders_combined_us(top_n: int = 30) -> list[dict]:
    """미국 시장 거래량 상위 + 상승률 상위 합산 (Yahoo Finance 스크리너).

    미국 장 전/후에 day_gainers 가 빈 결과를 반환할 수 있으므로
    most_actives 단독으로도 의미 있는 결과를 반환한다.
    """
    with ThreadPoolExecutor(max_workers=2) as ex:
        vol_fut  = ex.submit(_fetch_us_yahoo_screener, "most_actives", top_n)
        rise_fut = ex.submit(_fetch_us_yahoo_screener, "day_gainers",  top_n)
        vol_list  = vol_fut.result()
        rise_list = rise_fut.result()

    if not vol_list and not rise_list:
        raise RuntimeError(
            "미국 시장 데이터를 가져올 수 없습니다. "
            "미국 장이 열리지 않았거나 Yahoo Finance API 일시 오류입니다."
        )

    vol_rank_map  = {item["code"]: item["rank"] for item in vol_list}
    rise_rank_map = {item["code"]: item["rank"] for item in rise_list}

    info_by_code: dict = {}
    for item in vol_list + rise_list:
        if item["code"] not in info_by_code:
            info_by_code[item["code"]] = item

    combined = []
    for code, base in info_by_code.items():
        vr = vol_rank_map.get(code)
        rr = rise_rank_map.get(code)
        score_a = (1 / vr if vr else 0.0) + (1 / rr if rr else 0.0)

        combined.append({
            **base,
            "vol_rank_val":  vr or 0,
            "rise_rank_val": rr or 0,
            "vol_rank_str":  str(vr) if vr else "-",
            "rise_rank_str": str(rr) if rr else "-",
            "has_vol_rank":  vr is not None,
            "has_rise_rank": rr is not None,
            "score_a":     round(score_a, 4),
            "score_a_str": f"{score_a:.3f}",
            "vol_ratio":   0.0,
            "score_b":     0.0,
            "score_b_str": "-",
            "has_score_b": False,
            "is_etf":      base.get("quote_type", "") in ("ETF", "ETN"),
            "is_near_high": (
                base.get("day_high", 0) > 0
                and base.get("price_raw", 0) / base["day_high"] >= 0.98
            ),
        })

    combined.sort(key=lambda x: x["score_a"], reverse=True)
    top = combined[:top_n]
    for i, item in enumerate(top):
        item["rank"] = i + 1

    return top


# ---------------------------------------------------------------------------
# 당일 주도주 캐시 (JSON 파일, KR 시장 전용)
# ---------------------------------------------------------------------------

def _cache_path(market: str) -> str:
    date_str = datetime.today().strftime("%Y%m%d")
    os.makedirs(_CACHE_DIR, exist_ok=True)
    return os.path.join(_CACHE_DIR, f"leaders_{market}_{date_str}.json")


def save_leaders_cache(market: str, data: list[dict]) -> None:
    """당일 주도주 데이터를 JSON 파일로 캐시 저장."""
    try:
        with open(_cache_path(market), "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def load_leaders_cache(market: str) -> list[dict] | None:
    """오늘 날짜 캐시가 있으면 반환, 없으면 None."""
    path = _cache_path(market)
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _load_recent_leaders_cache(market: str, max_days: int = 14) -> list[dict] | None:
    """장 시작 전·주말·공휴일 fallback: 최근 N일 내 가장 최근 캐시 파일을 반환.

    주말/공휴일은 캐시 파일 자체가 없으므로 파일 존재 여부만으로 거래일을 자동 판별.
    각 항목의 data_date 를 해당 캐시 날짜로 업데이트한다.
    """
    from datetime import timedelta
    for i in range(1, max_days + 1):
        prev = datetime.today() - timedelta(days=i)
        date_str = prev.strftime("%Y%m%d")
        path = os.path.join(_CACHE_DIR, f"leaders_{market}_{date_str}.json")
        if not os.path.exists(path):
            continue
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if not data:
                continue
            day_kr = ["월", "화", "수", "목", "금", "토", "일"][prev.weekday()]
            prev_date_label = f"{prev.strftime('%Y-%m-%d')} ({day_kr})"
            for item in data:
                item["data_date"] = prev_date_label
            return data
        except Exception:
            continue
    return None


def compute_consecutive_days(market: str, current_data: list[dict], max_days: int = 5) -> list[dict]:
    """각 종목이 오늘 포함 며칠 연속 당일주도주에 등장했는지 계산한다.

    주말은 건너뛰고, 평일에 캐시 파일이 없으면 (공휴일·첫 실행) 연속 횟수를 끊는다.
    반환: consecutive_days(int), has_streak(bool, ≥2일) 필드가 추가된 리스트.
    """
    # 과거 max_days 거래일의 코드 집합 수집 (주말 건너뜀, 캐시 없는 평일=연속 끊김)
    past_sets: list[set] = []
    i = 1
    while len(past_sets) < max_days and i < 30:
        prev = datetime.today() - timedelta(days=i)
        i += 1
        if prev.weekday() in (5, 6):          # 토·일 건너뜀
            continue
        date_str = prev.strftime("%Y%m%d")
        path = os.path.join(_CACHE_DIR, f"leaders_{market}_{date_str}.json")
        if not os.path.exists(path):
            break                              # 평일 캐시 없음 → 연속 끊김
        try:
            with open(path, "r", encoding="utf-8") as f:
                past_data = json.load(f)
            past_sets.append({item["code"] for item in past_data})
        except Exception:
            break

    result = []
    for item in current_data:
        code = item["code"]
        streak = 1                             # 오늘 포함
        for past_set in past_sets:
            if code in past_set:
                streak += 1
            else:
                break
        result.append({
            **item,
            "consecutive_days": streak,
            "has_streak": streak >= 2,
            "streak_hot": streak >= 3,
        })
    return result


def compute_score_b(items: list[dict]) -> list[dict]:
    """각 종목의 20일 평균 거래량을 병렬 조회해 방법B 점수를 계산한다.

    score_b = (오늘거래량 / 20일평균거래량) × 상승률(%)
    """
    def _get_avg_vol(code: str) -> tuple[str, float | None]:
        try:
            end = datetime.today()
            start = end - timedelta(days=60)
            df = fdr.DataReader(code, start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d"))
            df = df[df["Volume"] > 0]
            if len(df) < 5:
                return code, None
            return code, float(df["Volume"].tail(20).mean())
        except Exception:
            return code, None

    codes = [item["code"] for item in items]
    with ThreadPoolExecutor(max_workers=8) as ex:
        avg_vols: dict[str, float | None] = dict(ex.map(_get_avg_vol, codes))

    updated = []
    for item in items:
        avg_vol = avg_vols.get(item["code"])
        today_vol = item.get("today_volume", 0)
        chg = item.get("change_pct_val", 0.0)

        if avg_vol and avg_vol > 0 and today_vol > 0 and chg > 0:
            vol_ratio = today_vol / avg_vol
            score_b   = round(vol_ratio * chg, 2)
            updated.append({
                **item,
                "vol_ratio": round(vol_ratio, 2),
                "score_b": score_b,
                "score_b_str": f"{score_b:.1f}",
                "has_score_b": True,
            })
        else:
            updated.append({**item, "has_score_b": False})

    return updated
