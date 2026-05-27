"""글로벌 시장 모멘텀 스캐너 — 한국/미국/채권 3·6·12개월 수익률 비교."""

from datetime import datetime, timedelta

import FinanceDataReader as fdr
import pandas as pd

_ASSETS = [
    {"key": "kr",   "name": "한국 (KOSPI)", "code": "KS11",      "currency": "KRW"},
    {"key": "us",   "name": "미국 (S&P500)", "code": "SPY",      "currency": "USD"},
    {"key": "cn",   "name": "중국 (상하이)", "code": "SSEC",       "currency": "CNY"},
    {"key": "bond", "name": "채권 (TLT)",    "code": "TLT",      "currency": "USD"},
]

_PERIODS = [
    {"label": "3개월", "days": 63},
    {"label": "6개월", "days": 126},
    {"label": "12개월", "days": 252},
]


def _fetch_return(code: str, trading_days: int) -> float | None:
    """N 거래일 누적 수익률(%) 반환."""
    try:
        end = datetime.today()
        # 충분한 버퍼(2배)로 달력일 기준 조회
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
          "rows": [
            {"key": "kr", "name": "한국 (KOSPI)",
             "ret_3m": 2.5, "ret_6m": -1.2, "ret_12m": 8.3,
             "ret_3m_str": "+2.50%", ..., "win_3m": True, ...},
            ...
            {"key": "cash", "name": "현금", "ret_3m": 0.0, ...},
          ],
          "recommendation": "미국 (S&P500)",   # or "현금"
          "rec_key": "us",                      # "kr"|"us"|"bond"|"cash"
          "rec_reason": "3개 기간 모두 1위",
          "period_winners": {
            "3개월": "us", "6개월": "us", "12개월": "kr"
          },
          "error": "",
        }
    """
    rows = []
    for asset in _ASSETS:
        row = {"key": asset["key"], "name": asset["name"]}
        for p in _PERIODS:
            ret = _fetch_return(asset["code"], p["days"])
            key = f"ret_{p['label'][0]}m" if p["label"][0].isdigit() else p["label"]
            label_key = p["label"].replace("개월", "m")  # "3m","6m","12m"
            row[f"ret_{label_key}"] = ret
            row[f"ret_{label_key}_str"] = (
                f"{ret:+.2f}%" if ret is not None else "-"
            )
            row[f"pos_{label_key}"] = ret is not None and ret > 0
        rows.append(row)

    # 현금 행 (수익률 항상 0)
    cash_row = {"key": "cash", "name": "현금 (보유)"}
    for p in _PERIODS:
        label_key = p["label"].replace("개월", "m")
        cash_row[f"ret_{label_key}"] = 0.0
        cash_row[f"ret_{label_key}_str"] = "0.00%"
        cash_row[f"pos_{label_key}"] = False
    rows.append(cash_row)

    # 기간별 1위 결정 (현금 포함, 전부 음수면 현금이 1위)
    period_winners = {}
    for p in _PERIODS:
        label_key = p["label"].replace("개월", "m")
        best_key = "cash"
        best_ret = 0.0  # 현금 기준치
        for r in rows[:-1]:  # 현금 제외하고 비교
            val = r.get(f"ret_{label_key}")
            if val is not None and val > best_ret:
                best_ret = val
                best_key = r["key"]
        period_winners[p["label"]] = best_key

    # 종합 추천: 각 기간 1위 횟수 집계
    win_counts: dict[str, int] = {}
    for winner in period_winners.values():
        win_counts[winner] = win_counts.get(winner, 0) + 1

    # 최다 승 자산 (동률 시 12개월 우선)
    max_wins = max(win_counts.values())
    candidates = [k for k, v in win_counts.items() if v == max_wins]
    if len(candidates) == 1:
        rec_key = candidates[0]
    else:
        # 12개월 기준으로 최종 결정
        rec_key = period_winners.get("12개월", candidates[0])

    # 추천 이름/이유
    rec_name_map = {r["key"]: r["name"] for r in rows}
    rec_name = rec_name_map.get(rec_key, "현금")
    wins = win_counts.get(rec_key, 0)
    if rec_key == "cash":
        rec_reason = "전 기간 전 자산 수익률 마이너스"
    elif wins == 3:
        rec_reason = "3개 기간 모두 1위"
    elif wins == 2:
        rec_reason = "3개 기간 중 2회 1위"
    else:
        rec_reason = "12개월 기준 1위"

    # bool 플래그 — rx.foreach 내 비교 불가 우회
    for r in rows:
        for p in _PERIODS:
            label_key = p["label"].replace("개월", "m")
            pk = p["label"]
            r[f"win_{label_key}"] = (period_winners.get(pk) == r["key"])
        r["is_recommended"] = (r["key"] == rec_key)

    return {
        "rows": rows,
        "recommendation": rec_name,
        "rec_key": rec_key,
        "rec_reason": rec_reason,
        "period_winners": period_winners,
        "error": "",
    }
