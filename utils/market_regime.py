"""
시장 장세 판단 (상승 / 하락 / 횡보)

ADX(평균방향지수)로 추세 강도 판별 + 20MA 방향으로 상승/하락 구분.

판정 로직:
  ADX > 25 AND +DI > -DI AND 가격 > 20MA  → 상승
  ADX > 25 AND -DI > +DI AND 가격 < 20MA  → 하락
  ADX <= 25 (또는 혼합)                   → 횡보
"""

from __future__ import annotations
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import FinanceDataReader as fdr

# ---------------------------------------------------------------------------
# 파라미터
# ---------------------------------------------------------------------------
_ADX_PERIOD   = 14    # ADX/DMI 계산 기간
_ADX_TREND    = 25.0  # ADX 이 값 이상 = 추세장
_MA_SHORT     = 20
_MA_LONG      = 60

# 분석 대상 지수 (code, label)
INDEX_CODES = [
    ("KS11",  "KOSPI"),
    ("KQ11",  "KOSDAQ"),
    ("US500", "S&P500"),
    ("IXIC",  "NASDAQ"),
]


# ---------------------------------------------------------------------------
# ADX / +DI / -DI 계산
# ---------------------------------------------------------------------------

def _calc_adx(high: np.ndarray, low: np.ndarray, close: np.ndarray,
              period: int = 14) -> tuple[float, float, float]:
    """
    Returns (ADX, +DI, -DI) — 마지막 값 기준.
    최소 2*period 개 데이터 필요.
    """
    n = len(close)
    if n < period * 2 + 1:
        return 0.0, 0.0, 0.0

    # True Range
    tr = np.maximum(high[1:] - low[1:],
         np.maximum(np.abs(high[1:] - close[:-1]),
                    np.abs(low[1:]  - close[:-1])))

    # Directional Movement
    up   = high[1:] - high[:-1]
    down = low[:-1] - low[1:]
    pdm = np.where((up > down) & (up > 0), up, 0.0)
    ndm = np.where((down > up) & (down > 0), down, 0.0)

    # Wilder 평활화 (EMA 방식)
    def _wilder(arr: np.ndarray, p: int) -> np.ndarray:
        out = np.empty(len(arr))
        out[:] = np.nan
        out[p - 1] = arr[:p].sum()
        for i in range(p, len(arr)):
            out[i] = out[i - 1] - out[i - 1] / p + arr[i]
        return out

    atr14  = _wilder(tr,  period)
    pdi14  = _wilder(pdm, period)
    ndi14  = _wilder(ndm, period)

    with np.errstate(divide="ignore", invalid="ignore"):
        pdi = np.where(atr14 > 0, pdi14 / atr14 * 100, 0.0)
        ndi = np.where(atr14 > 0, ndi14 / atr14 * 100, 0.0)
        dx  = np.where((pdi + ndi) > 0,
                       np.abs(pdi - ndi) / (pdi + ndi) * 100, 0.0)

    adx_arr = _wilder(dx[period - 1:], period)

    return float(adx_arr[-1]), float(pdi[-1]), float(ndi[-1])


# ---------------------------------------------------------------------------
# 장세 판단
# ---------------------------------------------------------------------------

def detect_regime(code: str, lookback: int = 150) -> dict:
    """
    단일 지수의 장세를 분석한다.

    Returns
    -------
    dict:
        regime      : "상승" | "하락" | "횡보"
        color       : "green" | "red" | "gray"
        adx         : float
        pdi         : float  (+DI)
        ndi         : float  (-DI)
        above_ma20  : bool
        above_ma60  : bool
        ma20_slope  : float  (20MA 20일 변화율 %)
        signal      : str
        error       : str | None
    """
    _empty = dict(regime="알수없음", color="gray", adx=0.0, pdi=0.0, ndi=0.0,
                  above_ma20=False, above_ma60=False, ma20_slope=0.0,
                  signal="-", error=None)
    try:
        end   = datetime.today()
        start = end - timedelta(days=lookback + 30)
        df = fdr.DataReader(code, start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d"))
        df = df[df["Close"] > 0].dropna(subset=["Close", "High", "Low"])
        if len(df) < 70:
            return {**_empty, "error": "데이터 부족"}

        high  = df["High"].values.astype(float)
        low   = df["Low"].values.astype(float)
        close = df["Close"].values.astype(float)

        adx, pdi, ndi = _calc_adx(high, low, close, _ADX_PERIOD)

        close_s = df["Close"]
        ma20 = close_s.rolling(_MA_SHORT).mean()
        ma60 = close_s.rolling(_MA_LONG).mean()

        cur  = float(close_s.iloc[-1])
        m20  = float(ma20.iloc[-1])
        m60  = float(ma60.iloc[-1])

        above_ma20 = cur > m20
        above_ma60 = cur > m60

        # 20MA 20일 기울기 (보조 정보)
        m20_ago = float(ma20.iloc[-21]) if len(ma20) >= 21 else float(ma20.iloc[0])
        ma20_slope = (m20 - m20_ago) / m20_ago * 100 if m20_ago else 0.0

        # ── 장세 판정 ──
        is_trend = adx >= _ADX_TREND
        if is_trend and pdi > ndi and above_ma20:
            regime, color = "상승", "green"
        elif is_trend and ndi > pdi and not above_ma20:
            regime, color = "하락", "red"
        else:
            regime, color = "횡보", "gray"

        # 요약 텍스트
        pos   = "MA20 위" if above_ma20 else "MA20 아래"
        cross = "골든크로스" if m20 > m60 else "데드크로스"
        signal = (
            f"ADX {adx:.1f} · +DI {pdi:.1f} / -DI {ndi:.1f} · "
            f"{pos} · {cross}"
        )

        return dict(regime=regime, color=color,
                    adx=round(adx, 1), pdi=round(pdi, 1), ndi=round(ndi, 1),
                    above_ma20=above_ma20, above_ma60=above_ma60,
                    ma20_slope=round(ma20_slope, 2),
                    signal=signal, error=None)

    except Exception as e:
        return {**_empty, "error": str(e)}


def fetch_all_regimes() -> dict[str, dict]:
    """{label: regime_dict} 병렬 조회."""
    def _fetch(item):
        code, label = item
        return label, detect_regime(code)

    with ThreadPoolExecutor(max_workers=4) as ex:
        return dict(ex.map(_fetch, INDEX_CODES))


# ---------------------------------------------------------------------------
# HTML 렌더링
# ---------------------------------------------------------------------------

_BADGE = {
    "green": "background:#dcfce7;color:#15803d;",
    "red":   "background:#fee2e2;color:#b91c1c;",
    "gray":  "background:#f3f4f6;color:#374151;",
}


def regime_badge_html(regime: str, color: str) -> str:
    s = _BADGE.get(color, _BADGE["gray"])
    return (
        f'<span style="{s}font-size:11px;font-weight:700;'
        f'padding:2px 8px;border-radius:4px;">{regime}</span>'
    )


def generate_regime_section(generated_at: str | None = None) -> str:
    """주요 지수 장세 판단 HTML 섹션."""
    if generated_at is None:
        generated_at = datetime.now().strftime("%H:%M")

    regimes = fetch_all_regimes()

    rows = ""
    for _, label in INDEX_CODES:
        r = regimes.get(label, {})
        if r.get("error"):
            rows += (
                f"<tr><td><strong>{label}</strong></td>"
                f'<td colspan="5" style="color:#9ca3af;">{r["error"]}</td></tr>\n'
            )
            continue

        badge  = regime_badge_html(r["regime"], r["color"])
        slope  = f'{r["ma20_slope"]:+.1f}%'
        adx_s  = f'{r["adx"]:.1f}'
        di_s   = f'+DI {r["pdi"]:.1f} / -DI {r["ndi"]:.1f}'
        pos    = "▲ MA20 위" if r["above_ma20"] else "▼ MA20 아래"

        rows += (
            f"<tr>"
            f"<td><strong>{label}</strong></td>"
            f"<td>{badge}</td>"
            f"<td style='text-align:center;'>{adx_s}</td>"
            f"<td style='text-align:center;font-size:11px;'>{di_s}</td>"
            f"<td style='text-align:center;'>{slope}</td>"
            f"<td style='color:#6b7280;font-size:11px;'>{pos}</td>"
            f"</tr>\n"
        )

    return (
        f'<!-- SECTION:market_regime -->\n'
        f'<section id="section-market_regime">\n'
        f'<h2>주요 시장 장세 판단</h2>\n'
        f'<p style="color:#6b7280;font-size:12px;">'
        f'ADX≥25 = 추세장 · +DI>-DI+MA20위 = 상승 · -DI>+DI+MA20아래 = 하락 · 나머지 = 횡보'
        f'&nbsp;|&nbsp;{generated_at} 기준</p>\n'
        f'<table>\n'
        f'<thead><tr>'
        f'<th>지수</th><th>장세</th>'
        f'<th>ADX</th><th>DMI</th>'
        f'<th>20MA기울기</th><th>포지션</th>'
        f'</tr></thead>\n'
        f'<tbody>\n{rows}</tbody>\n'
        f'</table>\n'
        f'</section>\n'
        f'<!-- /SECTION:market_regime -->'
    )
