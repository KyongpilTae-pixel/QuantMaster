"""
섹터 모멘텀 스캐너.

KOSPI 업종 ETF(KODEX) + 미국 섹터 ETF(SPDR) 의 1개월 수익률을 조회해
섹터 로테이션 현황을 반환한다.
"""

import FinanceDataReader as fdr
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor

# ---------------------------------------------------------------------------
# 섹터 정의
# ---------------------------------------------------------------------------

KR_SECTORS = [
    ("069500", "KODEX 200",        "시장 전체"),
    ("091160", "KODEX 반도체",      "반도체"),
    ("091170", "KODEX 은행",        "은행"),
    ("091180", "KODEX 자동차",      "자동차"),
    ("102110", "KODEX 삼성그룹",    "대형주"),
    ("102780", "KODEX 인버스",      "인버스"),
    ("117700", "KODEX 건설",        "건설"),
    ("139240", "KODEX 운송",        "운송"),
    ("140710", "KODEX 헬스케어",    "헬스케어"),
    ("228790", "KODEX 바이오",      "바이오"),
    ("244580", "KODEX 2차전지산업", "2차전지"),
    ("261270", "KODEX 200IT레버리지", "IT레버리지"),
    ("305720", "KODEX 2차전지핵심소재10", "소재"),
    ("364980", "KODEX 반도체MV",    "반도체MV"),
]

US_SECTORS = [
    ("SPY",  "S&P 500 ETF",     "시장 전체"),
    ("XLK",  "Technology",      "기술"),
    ("XLF",  "Financials",      "금융"),
    ("XLV",  "Health Care",     "헬스케어"),
    ("XLE",  "Energy",          "에너지"),
    ("XLY",  "Cons. Discret.",  "경기소비재"),
    ("XLP",  "Cons. Staples",   "필수소비재"),
    ("XLI",  "Industrials",     "산업재"),
    ("XLB",  "Materials",       "소재"),
    ("XLU",  "Utilities",       "유틸리티"),
    ("XLRE", "Real Estate",     "리츠"),
    ("XLC",  "Communication",   "커뮤니케이션"),
    ("SMH",  "Semiconductors",  "반도체"),
    ("IBB",  "Biotech",         "바이오"),
]


# ---------------------------------------------------------------------------
# 수익률 계산
# ---------------------------------------------------------------------------

def _fetch_return(code: str, period_days: int) -> tuple[str, float | None]:
    """단일 종목 수익률(%) 계산. 실패 시 None 반환."""
    try:
        end   = datetime.today()
        start = end - timedelta(days=period_days + 10)   # 주말 여유
        df = fdr.DataReader(code, start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d"))
        df = df[df["Volume"] > 0].dropna(subset=["Close"])
        if len(df) < 2:
            return code, None
        ret = (df["Close"].iloc[-1] - df["Close"].iloc[0]) / df["Close"].iloc[0] * 100
        return code, round(float(ret), 2)
    except Exception:
        return code, None


def fetch_sector_momentum(region: str = "KR", period_days: int = 20) -> list[dict]:
    """섹터 ETF 수익률 목록을 내림차순으로 반환.

    region: "KR" | "US"
    period_days: 수익률 계산 기간(거래일 기준이 아닌 달력일)
    반환 필드: code, name, sector, ret_pct, ret_str, ret_positive, rank
    """
    sectors = KR_SECTORS if region == "KR" else US_SECTORS

    with ThreadPoolExecutor(max_workers=8) as ex:
        results = dict(ex.map(lambda s: _fetch_return(s[0], period_days), sectors))

    rows = []
    for code, name, sector in sectors:
        ret = results.get(code)
        rows.append({
            "code":         code,
            "name":         name,
            "sector":       sector,
            "ret_pct":      ret if ret is not None else 0.0,
            "ret_str":      f"{ret:+.2f}%" if ret is not None else "-",
            "ret_positive": (ret or 0.0) >= 0,
            "has_data":     ret is not None,
        })

    rows.sort(key=lambda x: x["ret_pct"] if x["has_data"] else -999, reverse=True)
    for i, row in enumerate(rows):
        row["rank"] = i + 1

    return rows
