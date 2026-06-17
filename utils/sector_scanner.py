"""
섹터 모멘텀 스캐너.

KOSPI 업종 ETF(KODEX) + 미국 섹터 ETF(SPDR) 의
1개월/3개월/6개월/12개월 수익률을 한 번에 조회해 반환한다.
"""

import pandas as pd
import FinanceDataReader as fdr
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor

# ---------------------------------------------------------------------------
# 기간 정의
# ---------------------------------------------------------------------------

PERIODS = [
    ("1m",  "1개월",   20),
    ("3m",  "3개월",   60),
    ("6m",  "6개월",  120),
    ("12m", "12개월", 240),
]

# ---------------------------------------------------------------------------
# 섹터 정의
# ---------------------------------------------------------------------------

KR_SECTORS = [
    ("069500", "KODEX 200",              "한국 (KOSPI)"),
    ("091160", "KODEX 반도체",            "반도체"),
    ("091170", "KODEX 은행",              "은행"),
    ("091180", "KODEX 자동차",            "자동차"),
    ("102110", "KODEX 삼성그룹",          "대형주"),
    ("117700", "KODEX 건설",              "건설"),
    ("139240", "KODEX 운송",              "운송"),
    ("140710", "KODEX 헬스케어",          "헬스케어"),
    ("228790", "KODEX 바이오",            "바이오"),
    ("244580", "KODEX 2차전지산업",       "2차전지"),
    ("305720", "KODEX 2차전지핵심소재10", "소재"),
    ("364980", "KODEX 반도체MV",          "반도체MV"),
    ("395160", "TIGER 조선TOP10",         "조선"),
    ("425420", "KODEX K방산&우주",        "방산·우주"),
]

US_SECTORS = [
    ("SPY",  "S&P 500 ETF",    "미국 (S&P500)"),
    ("XLK",  "Technology",     "기술"),
    ("XLF",  "Financials",     "금융"),
    ("XLV",  "Health Care",    "헬스케어"),
    ("XLE",  "Energy",         "에너지"),
    ("XLY",  "Cons. Discret.", "경기소비재"),
    ("XLP",  "Cons. Staples",  "필수소비재"),
    ("XLI",  "Industrials",    "산업재"),
    ("XLB",  "Materials",      "소재"),
    ("XLU",  "Utilities",      "유틸리티"),
    ("XLRE", "Real Estate",    "리츠"),
    ("XLC",  "Communication",  "커뮤니케이션"),
    ("SMH",  "Semiconductors", "반도체"),
    ("IBB",  "Biotech",        "바이오"),
]

# ---------------------------------------------------------------------------
# 수익률 계산
# ---------------------------------------------------------------------------

def _fetch_all_returns(code: str) -> tuple[str, dict]:
    """단일 종목의 1M/3M/6M/12M 수익률(%)을 한 번에 계산. 실패 시 None."""
    try:
        end   = datetime.today()
        start = end - timedelta(days=260 + 20)   # 12개월 + 여유
        df = fdr.DataReader(code, start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d"))
        df = df[df["Volume"] > 0].dropna(subset=["Close"])

        rets: dict[str, float | None] = {}
        for key, _, days in PERIODS:
            cutoff  = end - timedelta(days=days + 10)
            subset  = df[df.index >= pd.Timestamp(cutoff)]
            if len(subset) >= 2:
                ret = (subset["Close"].iloc[-1] - subset["Close"].iloc[0]) / subset["Close"].iloc[0] * 100
                rets[key] = round(float(ret), 2)
            else:
                rets[key] = None
        return code, rets
    except Exception:
        return code, {key: None for key, _, _ in PERIODS}


def fetch_sector_momentum(region: str = "KR") -> list[dict]:
    """섹터 ETF 의 1M/3M/6M/12M 수익률 목록을 반환.

    region: "KR" | "US"
    반환 필드 (기간별): ret_{key}, ret_{key}_str, ret_{key}_positive, ret_{key}_has_data
    공통 필드: code, name, sector, rank
    """
    sectors = KR_SECTORS if region == "KR" else US_SECTORS

    with ThreadPoolExecutor(max_workers=8) as ex:
        results = dict(ex.map(lambda s: _fetch_all_returns(s[0]), sectors))

    rows = []
    for code, name, sector in sectors:
        rets = results.get(code, {key: None for key, _, _ in PERIODS})
        row: dict = {"code": code, "name": name, "sector": sector}
        for key, _, _ in PERIODS:
            ret = rets.get(key)
            row[f"ret_{key}"]          = ret if ret is not None else 0.0
            row[f"ret_{key}_str"]      = f"{ret:+.2f}%" if ret is not None else "-"
            row[f"ret_{key}_positive"] = (ret or 0.0) >= 0
            row[f"ret_{key}_has_data"] = ret is not None
        rows.append(row)

    # 1M 기준 내림차순 정렬
    rows.sort(
        key=lambda x: x["ret_1m"] if x["ret_1m_has_data"] else -999,
        reverse=True,
    )
    for i, row in enumerate(rows):
        row["rank"] = i + 1

    return rows
