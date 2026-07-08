"""
장세 기반 최적 스캔 전략 선택 + 종목 추천.

장세(상승/하락/횡보) → 추천 전략 매핑 → TOP N 종목 추출.
주간/월간 리포트의 "이번 주 투자 전략 추천" 섹션에 사용.
"""

from __future__ import annotations
import json
import os
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor

# ---------------------------------------------------------------------------
# 장세 → 전략 매핑
# ---------------------------------------------------------------------------

_STRATEGY_MAP: dict[str, dict] = {
    "상승": {
        "name":    "추세추종 (모멘텀 집중)",
        "desc":    "상승 추세 확인된 장세. RS(상대강도) 상위 + 최근 수익률 높은 모멘텀 종목에 집중합니다.",
        "tip":     "손절선: VWAP×0.96 / 분할 매수: 현재가 30% → 눌림 30% → VWAP 40%",
        "scan":    "momentum",
        "color":   "green",
    },
    "횡보": {
        "name":    "눌림목 저점 매수",
        "desc":    "방향성 없는 박스권 장세. 상승추세 유지 종목의 단기 급락(눌림목) 구간을 노립니다.",
        "tip":     "진입 기준: 60일선 위 + 1주일 낙폭 ≥5% / 빠른 익절 목표 +5~8%",
        "scan":    "pullback",
        "color":   "orange",
    },
    "하락": {
        "name":    "하락방어 (Beta 낮음 + RS>1)",
        "desc":    "하락 추세 확인된 장세. 시장 대비 덜 빠지는 저베타 + 상대강도 강한 종목만 보유합니다.",
        "tip":     "현금 비중 확대 권장 / 편입 시 포지션 축소 (평소 대비 50% 이하)",
        "scan":    "defensive",
        "color":   "blue",
    },
    "알수없음": {
        "name":    "관망 (데이터 부족)",
        "desc":    "장세 데이터가 충분하지 않아 판단이 어렵습니다. 관망을 권장합니다.",
        "tip":     "—",
        "scan":    None,
        "color":   "gray",
    },
}

_TOP_N = 5
_CACHE_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "cache")


# ---------------------------------------------------------------------------
# 종목 소스별 로더
# ---------------------------------------------------------------------------

def _load_momentum_cache(market: str) -> list[dict]:
    """모멘텀 캐시 flat list → 최신 파일 반환."""
    prefix = f"momentum_{market}_"
    try:
        files = [f for f in os.listdir(_CACHE_DIR) if f.startswith(prefix) and f.endswith(".json")]
        if not files:
            return []
        latest = sorted(files)[-1]
        with open(os.path.join(_CACHE_DIR, latest), encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


def _load_leaders_cache(market: str) -> list[dict]:
    """당일주도주 캐시 최신 파일 반환."""
    prefix = f"leaders_{market}_"
    try:
        files = [f for f in os.listdir(_CACHE_DIR) if f.startswith(prefix) and f.endswith(".json")]
        if not files:
            return []
        latest = sorted(files)[-1]
        with open(os.path.join(_CACHE_DIR, latest), encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, list) else []
    except Exception:
        return []


def _picks_momentum(market: str, top_n: int = _TOP_N) -> list[dict]:
    """상승장 종목 추천: 모멘텀 캐시 → 3M 수익률 상위."""
    rows = _load_momentum_cache(market)
    if not rows:
        # 폴백: 당일주도주 캐시
        rows = _load_leaders_cache(market)

    if not rows:
        return []

    # 수익률 내림차순 (ret_3m → ret_1m → change_pct 순 폴백)
    def sort_key(r):
        for k in ("ret_3m", "ret_1m", "change_pct", "score_a"):
            v = r.get(k)
            if v is not None:
                try:
                    return float(v)
                except (TypeError, ValueError):
                    pass
        return 0.0

    sorted_rows = sorted(rows, key=sort_key, reverse=True)
    result = []
    for r in sorted_rows:
        name = r.get("name") or r.get("종목명", "")
        code = r.get("code") or r.get("종목코드", "")
        if not name and not code:
            continue
        ret3m = r.get("ret_3m")
        ret1m = r.get("ret_1m")
        pct   = r.get("change_pct")
        detail_parts = []
        if ret3m is not None:
            detail_parts.append(f"3M {ret3m:+.1f}%")
        if ret1m is not None:
            detail_parts.append(f"1M {ret1m:+.1f}%")
        if pct is not None:
            detail_parts.append(f"당일 {pct:+.1f}%")
        result.append({
            "name":   name,
            "code":   code,
            "detail": " · ".join(detail_parts) if detail_parts else "-",
            "is_us":  r.get("is_us", market in ("SP500", "NASDAQ")),
        })
        if len(result) >= top_n:
            break
    return result


def _picks_pullback(market: str, top_n: int = _TOP_N) -> list[dict]:
    """횡보장 종목 추천: 모멘텀 캐시에서 단기 급락(1W<-3%) + 중기 상승(3M>0) 종목 필터링."""
    rows = _load_momentum_cache(market)
    if not rows:
        rows = _load_leaders_cache(market)
    if not rows:
        return []

    # 눌림목 조건: 1W 하락 + 3M 양수 (상승추세 내 단기 조정)
    candidates = []
    for r in rows:
        ret1w = r.get("ret_1w") or r.get("ret_1W")
        ret3m = r.get("ret_3m") or r.get("ret_3M")
        if ret1w is not None and ret3m is not None:
            try:
                if float(ret1w) < -2.0 and float(ret3m) > 0:
                    candidates.append((r, float(ret1w)))
            except (TypeError, ValueError):
                pass

    # 낙폭 큰 순 (더 많이 빠진 것 = 더 좋은 눌림목 후보)
    candidates.sort(key=lambda x: x[1])

    result = []
    for r, ret1w in candidates[:top_n]:
        name  = r.get("name") or r.get("종목명", "")
        code  = r.get("code") or r.get("종목코드", "")
        ret3m = r.get("ret_3m") or r.get("ret_3M")
        detail_parts = [f"1W {ret1w:+.1f}%"]
        if ret3m is not None:
            detail_parts.append(f"3M {float(ret3m):+.1f}%")
        result.append({
            "name":   name,
            "code":   code,
            "detail": " · ".join(detail_parts),
            "is_us":  r.get("is_us", market in ("SP500", "NASDAQ")),
        })
    return result


def _picks_defensive(market: str, top_n: int = _TOP_N) -> list[dict]:
    """하락장 종목 추천: 모멘텀 캐시에서 하락장 방어 후보 (3M 수익률 양수 + 1W 선방)."""
    rows = _load_momentum_cache(market)
    if not rows:
        rows = _load_leaders_cache(market)
    if not rows:
        return []

    # 하락방어 조건: 3M 수익률 양수 (상대강도 유지) + 1W 낙폭 최소
    candidates = []
    for r in rows:
        ret3m = r.get("ret_3m") or r.get("ret_3M")
        ret1w = r.get("ret_1w") or r.get("ret_1W", 0)
        if ret3m is not None:
            try:
                if float(ret3m) > 0:
                    candidates.append((r, float(ret3m), float(ret1w) if ret1w is not None else 0))
            except (TypeError, ValueError):
                pass

    # 3M 수익률 높은 순 (상대강도 기준)
    candidates.sort(key=lambda x: x[1], reverse=True)

    result = []
    for r, ret3m, ret1w in candidates[:top_n]:
        name = r.get("name") or r.get("종목명", "")
        code = r.get("code") or r.get("종목코드", "")
        detail_parts = [f"3M {ret3m:+.1f}%"]
        if ret1w is not None:
            detail_parts.append(f"1W {float(ret1w):+.1f}%")
        result.append({
            "name":   name,
            "code":   code,
            "detail": " · ".join(detail_parts),
            "is_us":  r.get("is_us", market in ("SP500", "NASDAQ")),
        })
    return result


def _picks_defensive_UNUSED(market: str, top_n: int = _TOP_N) -> list[dict]:
    """(리포트에서 미사용) 실시간 하락방어 스캐너 — 앱에서 직접 실행."""
    try:
        if market not in ("KOSPI", "KOSDAQ"):
            return []
        from utils.defensive_scanner import scan_defensive_stocks
        raw = scan_defensive_stocks(market, period_days=60, max_beta=0.8,
                                    min_mktcap_eok=10_000, top_n=top_n)
        result = []
        for r in raw[:top_n]:
            name = r.get("name", "")
            code = r.get("code", "")
            beta = r.get("beta")
            rs   = r.get("rs")
            detail_parts = []
            if beta is not None:
                detail_parts.append(f"Beta {beta:.2f}")
            if rs is not None:
                detail_parts.append(f"RS {rs:.2f}")
            result.append({
                "name":   name,
                "code":   code,
                "detail": " · ".join(detail_parts) if detail_parts else "-",
                "is_us":  False,
            })
        return result
    except Exception:
        return []


def get_regime_picks(market: str, regime: str, top_n: int = _TOP_N) -> list[dict]:
    """장세에 따라 적절한 스캔 방법으로 종목 추출."""
    if regime == "상승":
        return _picks_momentum(market, top_n)
    elif regime == "횡보":
        return _picks_pullback(market, top_n)
    elif regime == "하락":
        return _picks_defensive(market, top_n)
    return []


# ---------------------------------------------------------------------------
# HTML 섹션 생성
# ---------------------------------------------------------------------------

_SECTION_COLOR = {
    "green":  ("#dcfce7", "#15803d"),
    "orange": ("#fff7ed", "#c2410c"),
    "blue":   ("#eff6ff", "#1d4ed8"),
    "gray":   ("#f3f4f6", "#374151"),
}


def generate_regime_picks_section(
    regimes: "dict[str, dict]",
    generated_at: str | None = None,
) -> str:
    """
    장세별 투자 전략 추천 HTML 섹션.

    Parameters
    ----------
    regimes : {label: regime_dict}  — market_regime.fetch_all_regimes() 결과
    """
    if generated_at is None:
        generated_at = datetime.now().strftime("%H:%M")

    # KR: KOSPI 기준 / US: S&P500 기준
    kr_regime = regimes.get("KOSPI", {}).get("regime", "알수없음")
    us_regime = regimes.get("S&P500", {}).get("regime", "알수없음")

    def _market_block(label: str, market: str, regime: str) -> str:
        strat  = _STRATEGY_MAP.get(regime, _STRATEGY_MAP["알수없음"])
        color  = strat["color"]
        bg, fg = _SECTION_COLOR.get(color, _SECTION_COLOR["gray"])

        picks = get_regime_picks(market, regime)

        badge = (
            f'<span style="background:{bg};color:{fg};font-size:11px;font-weight:700;'
            f'padding:2px 8px;border-radius:4px;">{regime}</span>'
        )

        picks_html = ""
        if picks:
            rows_html = "".join(
                f"<tr>"
                f"<td style='font-weight:600;'>{p['name']}</td>"
                f"<td style='color:#6b7280;font-size:11px;'>{p['code']}</td>"
                f"<td style='font-size:11px;'>{p['detail']}</td>"
                f"</tr>"
                for p in picks
            )
            picks_html = (
                f"<table style='margin-top:8px;width:100%;'>"
                f"<thead><tr>"
                f"<th>종목명</th><th>코드</th><th>주요 지표</th>"
                f"</tr></thead>"
                f"<tbody>{rows_html}</tbody></table>"
            )
        else:
            picks_html = '<p style="color:#9ca3af;font-size:12px;">캐시 데이터 없음 — 앱에서 직접 스캔하세요.</p>'

        return (
            f'<div style="border:1px solid {bg};border-radius:8px;padding:14px;margin-bottom:16px;">'
            f'<h3 style="margin:0 0 6px 0;">{label} {badge}</h3>'
            f'<p style="margin:2px 0;font-weight:600;color:{fg};">{strat["name"]}</p>'
            f'<p style="margin:2px 0;font-size:12px;color:#6b7280;">{strat["desc"]}</p>'
            f'<p style="margin:4px 0;font-size:11px;color:#9ca3af;">💡 {strat["tip"]}</p>'
            f'{picks_html}'
            f'</div>'
        )

    kr_block = _market_block("KR 시장", "KOSPI",  kr_regime)
    us_block = _market_block("US 시장", "SP500",   us_regime)

    return (
        f'<!-- SECTION:regime_picks -->\n'
        f'<section id="section-regime_picks">\n'
        f'<h2>이번 주 투자 전략 추천</h2>\n'
        f'<p style="color:#6b7280;font-size:12px;">'
        f'장세 판단 기반으로 이번 주 최적 스캔 전략과 후보 종목을 제시합니다.'
        f'&nbsp;|&nbsp;{generated_at} 기준</p>\n'
        f'{kr_block}'
        f'{us_block}'
        f'</section>\n'
        f'<!-- /SECTION:regime_picks -->'
    )
