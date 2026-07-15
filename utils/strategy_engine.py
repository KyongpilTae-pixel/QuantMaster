"""
분할 매수 플랜 계산 엔진.

calculate_pullback_plan():
  VWAP 눌림목 3분할 매수 전략을 자동으로 계산한다.
  MFI 과열 / 현재가-VWAP 밀착 조건에 따라 비중을 동적으로 조정한다.
  ATR14 제공 시 현재가 - 2.5×ATR14 로 손절선 계산 (종목별 변동성 기반).
  ATR14 없으면 VWAP × 0.96 고정 손절 fallback.
"""

from __future__ import annotations

_ATR_MULT = 2.5   # ATR 손절 배수
_KELLY_MAX = 0.25  # 켈리 분율 상한 (과베팅 방지, full Kelly의 25%)


def calc_kelly_fraction(win_rate: float, avg_win_pct: float, avg_loss_pct: float) -> float:
    """켈리 공식으로 최적 베팅 비율 계산.

    Parameters
    ----------
    win_rate    : 승률 (0~100 범위)
    avg_win_pct : 평균 수익률 % (양수)
    avg_loss_pct: 평균 손실률 % (양수, 절댓값)

    Returns
    -------
    float: 권장 투자 비율 (0~_KELLY_MAX 범위로 클리핑)
    """
    if avg_loss_pct <= 0 or win_rate <= 0 or win_rate >= 100:
        return 0.0
    p = win_rate / 100.0
    q = 1.0 - p
    b = avg_win_pct / avg_loss_pct  # 수익/손실 비율
    kelly = (b * p - q) / b
    # Half-Kelly 적용 후 상한 클리핑
    return round(max(0.0, min(kelly * 0.5, _KELLY_MAX)), 4)


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
    atr14: float | None = None,
    win_rate: float = 55.0,
    avg_win_pct: float = 8.0,
    avg_loss_pct: float = 4.0,
) -> dict:
    """
    VWAP 눌림목 분할 매수 플랜을 계산해 반환한다.

    Parameters
    ----------
    current_price : 현재 종가
    vwap_price    : 120일 VWAP 지지선
    mfi           : Money Flow Index (0~100)
    total_budget  : 총 투자 예산 (원 또는 USD)
    atr14         : ATR14 값 (제공 시 ATR 기반 손절 사용, None이면 VWAP×0.96)
    win_rate      : 백테스트 승률 % (Kelly 계산용, 기본 55%)
    avg_win_pct   : 백테스트 평균 수익률 % (기본 8%)
    avg_loss_pct  : 백테스트 평균 손실률 % 절댓값 (기본 4%)

    Returns
    -------
    {
        "plan_type"        : 플랜 유형 레이블 (str),
        "steps"            : 각 단계 리스트 (list[dict]),
        "avg_price"        : 예상 평균 단가 (float),
        "stop_loss"        : 손절 가격 (float),
        "stop_loss_pct"    : 손절 하락률 (float, 음수),
        "stop_loss_method" : 손절 계산 방식 ("ATR" | "VWAP"),
        "kelly_fraction"   : 켈리 권장 투자 비율 (0~0.25),
        "kelly_budget"     : 켈리 권장 투자금액 (float),
    }
    """
    # ── 손절선 계산 ──────────────────────────────────────────────────────────
    if atr14 and atr14 > 0:
        stop_loss = round(current_price - _ATR_MULT * atr14, 0)
        stop_loss_method = f"ATR({_ATR_MULT}×)"
    else:
        stop_loss = round(vwap_price * 0.96, 0)
        stop_loss_method = "VWAP×0.96"

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

    kelly_f = calc_kelly_fraction(win_rate, avg_win_pct, avg_loss_pct)
    kelly_budget = round(total_budget * kelly_f, 0)

    return {
        "plan_type": plan_type,
        "steps": steps,
        "avg_price": _avg_price(steps),
        "stop_loss": stop_loss,
        "stop_loss_pct": stop_loss_pct,
        "stop_loss_method": stop_loss_method,
        "kelly_fraction": kelly_f,
        "kelly_budget": kelly_budget,
    }
