"""
분할 매수 플랜 계산 엔진.

calculate_pullback_plan():
  VWAP 눌림목 3분할 매수 전략을 자동으로 계산한다.
  MFI 과열 / 현재가-VWAP 밀착 조건에 따라 비중을 동적으로 조정한다.
"""

from __future__ import annotations


# ---------------------------------------------------------------------------
# 내부 헬퍼
# ---------------------------------------------------------------------------

def _build_step(level: str, price: float, weight: float, budget: float) -> dict:
    amount = budget * weight
    shares = amount / price if price > 0 else 0
    return {
        "level": level,
        "price": round(price, 0),
        "weight_pct": round(weight * 100, 0),   # % 표시용 정수
        "amount": round(amount, 0),
        "shares": round(shares, 2),
    }


def _avg_price(steps: list[dict]) -> float:
    total_amount = sum(s["amount"] for s in steps)
    total_shares = sum(s["shares"] for s in steps)
    if total_shares == 0:
        return 0.0
    return round(total_amount / total_shares, 0)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def calculate_pullback_plan(
    current_price: float,
    vwap_price: float,
    mfi: float,
    total_budget: float,
) -> dict:
    """
    VWAP 눌림목 분할 매수 플랜을 계산해 반환한다.

    Parameters
    ----------
    current_price : 현재 종가
    vwap_price    : 120일 VWAP 지지선
    mfi           : Money Flow Index (0~100)
    total_budget  : 총 투자 예산 (원 또는 USD)

    Returns
    -------
    {
        "plan_type"  : 플랜 유형 레이블 (str),
        "steps"      : 각 단계 리스트 (list[dict]),
        "avg_price"  : 예상 평균 단가 (float),
        "stop_loss"  : 손절 가격 (float),
        "stop_loss_pct": 손절 하락률 (float, 음수),
    }
    """
    stop_loss = round(vwap_price * 0.96, 0)
    mid_price = round((current_price + vwap_price) / 2, 0)
    gap_pct = (current_price - vwap_price) / vwap_price * 100 if vwap_price > 0 else 0
    stop_loss_pct = round((stop_loss - current_price) / current_price * 100, 1)

    # ── 조건 B: 밀착 상태 (gap ≤ 2%) → 2분할 ──────────────────────────────
    if abs(gap_pct) <= 2:
        steps = [
            _build_step("1차 매수 (현재가)", current_price, 0.50, total_budget),
            _build_step("2차 매수 (VWAP)", vwap_price,   0.50, total_budget),
        ]
        plan_type = "2분할 (현재가-VWAP 밀착)"

    # ── 조건 A: 과열 상태 (MFI ≥ 80) → 방어적 3분할 ──────────────────────
    elif mfi >= 80:
        steps = [
            _build_step("1차 매수 (현재가)",   current_price, 0.10, total_budget),
            _build_step("2차 매수 (중간가)",   mid_price,     0.30, total_budget),
            _build_step("3차 매수 (VWAP)",    vwap_price,    0.60, total_budget),
        ]
        plan_type = "방어적 3분할 (MFI 과열)"

    # ── 기본: VWAP 눌림목 3분할 ────────────────────────────────────────────
    else:
        steps = [
            _build_step("1차 매수 (현재가)",   current_price, 0.30, total_budget),
            _build_step("2차 매수 (중간가)",   mid_price,     0.30, total_budget),
            _build_step("3차 매수 (VWAP)",    vwap_price,    0.40, total_budget),
        ]
        plan_type = "기본 3분할 (VWAP 눌림목)"

    return {
        "plan_type": plan_type,
        "steps": steps,
        "avg_price": _avg_price(steps),
        "stop_loss": stop_loss,
        "stop_loss_pct": stop_loss_pct,
    }
