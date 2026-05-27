"""글로벌 시장 모멘텀 스캐너 — 한국/미국/중국/일본/채권/금 3·6·12개월 수익률 비교."""

from datetime import datetime, timedelta

import FinanceDataReader as fdr

_ASSETS = [
    {"key": "kr",   "name": "한국 (KOSPI)", "code": "KS11", "currency": "KRW"},
    {"key": "us",   "name": "미국 (S&P500)", "code": "SPY",  "currency": "USD"},
    {"key": "cn",   "name": "중국 (상하이)", "code": "SSEC", "currency": "CNY"},
    {"key": "jp",   "name": "일본 (닛케이)", "code": "N225", "currency": "JPY"},
    {"key": "bond", "name": "채권 (TLT)",    "code": "TLT",  "currency": "USD"},
    {"key": "gold", "name": "금 (GLD)",      "code": "GLD",  "currency": "USD"},
]

_PERIODS = [
    {"label": "3개월",  "days": 63},
    {"label": "6개월",  "days": 126},
    {"label": "12개월", "days": 252},
]


def _fetch_return(code: str, trading_days: int) -> float | None:
    """N 거래일 누적 수익률(%) 반환."""
    try:
        end = datetime.today()
        start = end - timedelta(days=trading_days * 2 + 30)
        df = fdr.DataReader(code, start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d"))
        if df.empty or "Close" not in df.columns:
            return None
        closes = df["Close"].dropna()
        if len(closes) < trading_days + 1:
            return None
        ret = float(closes.iloc[-1] / closes.iloc[-(trading_days + 1)] - 1) * 100
        return round(ret, 2)
    except Exception:
        return None


def fetch_momentum_data() -> dict:
    """
    Returns:
        {
          "rows": [...],
          "recommendation": "미국 (S&P500)",
          "rec_key": "us",
          "rec_reason": "3개 기간 모두 1위",
          "all_negative": False,   # 전 자산 마이너스 여부
          "error": "",
        }
    """
    rows = []
    for asset in _ASSETS:
        row = {"key": asset["key"], "name": asset["name"]}
        for p in _PERIODS:
            label_key = p["label"].replace("개월", "m")
            ret = _fetch_return(asset["code"], p["days"])
            row[f"ret_{label_key}"] = ret
            row[f"ret_{label_key}_str"] = f"{ret:+.2f}%" if ret is not None else "-"
            row[f"pos_{label_key}"] = ret is not None and ret > 0
        rows.append(row)

    # 기간별 1위 결정 — 전부 마이너스(또는 None)면 "cash" 반환
    period_winners = {}
    all_negative = True
    for p in _PERIODS:
        label_key = p["label"].replace("개월", "m")
        best_key = "cash"
        best_ret = 0.0  # 현금(0%) 기준치
        for r in rows:
            val = r.get(f"ret_{label_key}")
            if val is not None and val > best_ret:
                best_ret = val
                best_key = r["key"]
                all_negative = False
        period_winners[p["label"]] = best_key

    # 전 기간 전 자산 마이너스 재확인
    all_negative = all(
        pw == "cash" for pw in period_winners.values()
    )

    # 종합 추천: 각 기간 1위 횟수 집계
    win_counts: dict[str, int] = {}
    for winner in period_winners.values():
        win_counts[winner] = win_counts.get(winner, 0) + 1

    max_wins = max(win_counts.values())
    candidates = [k for k, v in win_counts.items() if v == max_wins]
    rec_key = candidates[0] if len(candidates) == 1 else period_winners.get("12개월", candidates[0])

    rec_name_map = {r["key"]: r["name"] for r in rows}
    rec_name = rec_name_map.get(rec_key, "현금 보유")
    wins = win_counts.get(rec_key, 0)

    if rec_key == "cash":
        rec_reason = "전 기간 전 자산 수익률 마이너스"
        rec_name = "현금 보유"
    elif wins == 3:
        rec_reason = "3개 기간 모두 1위"
    elif wins == 2:
        rec_reason = "3개 기간 중 2회 1위"
    else:
        rec_reason = "12개월 기준 1위"

    # bool 플래그 (rx.foreach 내 비교 불가 우회)
    for r in rows:
        for p in _PERIODS:
            label_key = p["label"].replace("개월", "m")
            r[f"win_{label_key}"] = (period_winners.get(p["label"]) == r["key"])
        r["is_recommended"] = (r["key"] == rec_key)

    return {
        "rows": rows,
        "recommendation": rec_name,
        "rec_key": rec_key,
        "rec_reason": rec_reason,
        "all_negative": all_negative,
        "error": "",
    }
