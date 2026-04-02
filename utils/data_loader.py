"""
NAVER Finance 기반 시장 데이터 로더 (한국 + 미국).
한국: NAVER Finance 스크래핑 (pykrx KRX API 연결 불가로 대체)
미국: FinanceDataReader + yfinance 병렬 조회
"""

import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta

import FinanceDataReader as fdr
import numpy as np
import pandas as pd
import requests
from bs4 import BeautifulSoup


# ---------------------------------------------------------------------------
# 한국 시장 (NAVER Finance)
# ---------------------------------------------------------------------------

_MARKET_CODE = {"KOSPI": "0", "KOSDAQ": "1"}

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
            mktcap   = float(texts[6])  if texts[6]  not in ("", "N/A", "-") else np.nan
            sales    = float(texts[7])  if texts[7]  not in ("", "N/A", "-") else np.nan
            div_yld  = float(texts[8])  if texts[8]  not in ("", "N/A", "-") else np.nan
            per      = float(texts[9])  if texts[9]  not in ("", "N/A", "-") else np.nan
            roe      = float(texts[10]) if texts[10] not in ("", "N/A", "-") else np.nan
            pbr      = float(texts[11]) if texts[11] not in ("", "N/A", "-") else np.nan
            price    = float(texts[2])  if texts[2]  else np.nan
        except ValueError:
            continue

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
        if market in _US_MARKET_FDR:
            return self._get_us_snapshot(market, max_pages)
        return self._get_kr_snapshot(market, max_pages)

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
