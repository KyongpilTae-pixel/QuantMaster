"""
NAVER Finance 기반 시장 데이터 로더.
pykrx KRX API 연결 불가 문제로 NAVER Finance 스크래핑 방식으로 대체.
"""

import time
import pandas as pd
import numpy as np
import FinanceDataReader as fdr
import requests
from bs4 import BeautifulSoup
from datetime import datetime, timedelta


# NAVER Finance 시장 코드
_MARKET_CODE = {"KOSPI": "0", "KOSDAQ": "1"}

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}


def _make_session() -> requests.Session:
    """PBR 필드가 포함된 NAVER Finance 세션 생성."""
    s = requests.Session()
    s.post(
        "https://finance.naver.com/sise/field_submit.naver",
        data={
            "menu": "market_sum",
            "returnUrl": "http://finance.naver.com/sise/sise_market_sum.naver",
            "fieldIds": ["pbr", "per", "roe"],
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
        # 컬럼 순서(field_submit 이후): N, 종목명, 현재가, 등락폭, 시가총액, 상한가, PER, ROE, PBR, ...
        if len(texts) < 9:
            continue
        try:
            per = float(texts[6]) if texts[6] not in ("", "N/A", "-") else np.nan
            roe = float(texts[7]) if texts[7] not in ("", "N/A", "-") else np.nan
            pbr = float(texts[8]) if texts[8] not in ("", "N/A", "-") else np.nan
            price = float(texts[2]) if texts[2] else np.nan
        except ValueError:
            continue

        if np.isnan(pbr) or pbr <= 0:
            continue

        records.append(
            {
                "Symbol": code,
                "Name": name,
                "Close": price,
                "PBR": pbr,
                "PER": per,
                "ROE": roe,
            }
        )
    return records


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
        NAVER Finance 시가총액 상위 종목의 PBR/ROE 데이터를 가져옴.
        max_pages × ~50종목 = 최대 300종목 처리.
        GPA_Score = ROE 백분위 (Novy-Marx GP/A 프록시).
        """
        sosok = _MARKET_CODE.get(market, "0")
        session = self._get_session()

        all_records: list[dict] = []
        for page in range(1, max_pages + 1):
            try:
                records = _parse_page(session, sosok, page)
                all_records.extend(records)
                time.sleep(0.3)  # 서버 부하 방지
            except Exception as e:
                print(f"[DataLoader] page {page} 오류: {e}")
                break

        if not all_records:
            return pd.DataFrame(
                columns=["Symbol", "Name", "Close", "PBR", "PER", "ROE", "GPA_Score"]
            )

        df = pd.DataFrame(all_records)
        df["GPA_Score"] = df["ROE"].rank(pct=True)
        return df.reset_index(drop=True)

    def get_ohlcv(self, symbol: str, lookback_days: int = 400) -> pd.DataFrame:
        """FinanceDataReader로 OHLCV 데이터 반환."""
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
