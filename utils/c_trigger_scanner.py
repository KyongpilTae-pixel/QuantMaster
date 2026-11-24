"""
C-axis trigger scanner — detects market events, generates draft letter content.

Trigger types (cloud-065 spec):
  rates     US 10Y ±20bp/day, or round-level (4.5%, 5.0%) breach
  taa_gate  Any of EWY/SPY/AGG/GLD/BIL gate ON<->OFF
  sector    Current month's MTD #1 US sector differs from yesterday's
  macro     FOMC/CPI/NFP/BOK calendar event today
  fx        KRW/USD ±1.5%/day, or key level (1,350/1,400) breach
  vix       VIX 25/30 upward breach

Usage:
    from utils.c_trigger_scanner import scan_triggers
    fired = scan_triggers("2026-11-24")  # None = today
"""
from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from datetime import date

import pandas as pd

# ---- Thresholds ----------------------------------------------------------------

_RATES_BP_THRESHOLD = 20
_RATES_ROUND_LEVELS = [3.5, 4.0, 4.5, 5.0, 5.5]
_FX_PCT_THRESHOLD   = 1.5                        # %/day
_FX_KEY_LEVELS      = [1300, 1350, 1400, 1450]   # KRW/USD
_VIX_KEY_LEVELS     = [20, 25, 30]

_TAA_ASSETS = ["EWY", "SPY", "AGG", "GLD", "BIL"]
_TAA_NAMES  = {
    "EWY": "한국(EWY)", "SPY": "미국(SPY)", "AGG": "채권(AGG)",
    "GLD": "금(GLD)",   "BIL": "현금(BIL)",
}

_US_SECTORS = {
    "XLK": "기술",    "XLF": "금융",       "XLV": "헬스케어", "XLE": "에너지",
    "XLI": "산업재",  "XLU": "유틸리티",   "XLRE": "리츠",    "XLB": "소재",
    "XLP": "필수소비재", "XLY": "경기소비재", "XLC": "통신",
}

_MACRO_CALENDAR: dict[str, str] = {
    # FOMC 2026
    "2026-01-29": "FOMC", "2026-03-19": "FOMC", "2026-05-07": "FOMC",
    "2026-06-18": "FOMC", "2026-07-30": "FOMC", "2026-09-17": "FOMC",
    "2026-11-05": "FOMC", "2026-12-17": "FOMC",
    # US CPI 2026
    "2026-01-15": "미국 CPI", "2026-02-12": "미국 CPI", "2026-03-12": "미국 CPI",
    "2026-04-10": "미국 CPI", "2026-05-13": "미국 CPI", "2026-06-11": "미국 CPI",
    "2026-07-15": "미국 CPI", "2026-08-13": "미국 CPI", "2026-09-11": "미국 CPI",
    "2026-10-15": "미국 CPI", "2026-11-13": "미국 CPI", "2026-12-11": "미국 CPI",
    # US NFP 2026 (first Friday of each month)
    "2026-01-09": "미국 고용(NFP)", "2026-02-06": "미국 고용(NFP)", "2026-03-06": "미국 고용(NFP)",
    "2026-04-03": "미국 고용(NFP)", "2026-05-08": "미국 고용(NFP)", "2026-06-05": "미국 고용(NFP)",
    "2026-07-10": "미국 고용(NFP)", "2026-08-07": "미국 고용(NFP)", "2026-09-04": "미국 고용(NFP)",
    "2026-10-02": "미국 고용(NFP)", "2026-11-06": "미국 고용(NFP)", "2026-12-04": "미국 고용(NFP)",
    # BOK 2026
    "2026-01-16": "한은 금통위", "2026-02-26": "한은 금통위", "2026-04-17": "한은 금통위",
    "2026-05-28": "한은 금통위", "2026-07-16": "한은 금통위", "2026-08-27": "한은 금통위",
    "2026-10-16": "한은 금통위", "2026-11-27": "한은 금통위",
}


# ---- Data fetching -------------------------------------------------------------

def _fetch_close(tickers: list[str], start: str, end: str) -> dict[str, pd.Series]:
    """Parallel yfinance download. Returns {ticker: Close price Series}."""
    import yfinance as yf

    def _one(t: str) -> tuple[str, pd.Series]:
        try:
            df = yf.download(t, start=start, end=end, progress=False, auto_adjust=True)
            if df.empty:
                return t, pd.Series(dtype=float)
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
            s = df["Close"].dropna()
            s.index = pd.to_datetime(s.index)
            return t, s
        except Exception:
            return t, pd.Series(dtype=float)

    result: dict[str, pd.Series] = {}
    with ThreadPoolExecutor(max_workers=min(len(tickers), 12)) as pool:
        for ticker, s in pool.map(_one, tickers):
            if not s.empty:
                result[ticker] = s
    return result


def _all_tickers() -> list[str]:
    return _TAA_ASSETS + ["^TNX", "^VIX", "KRW=X"] + list(_US_SECTORS.keys())


# ---- Gate computation ----------------------------------------------------------

def _gate(s: pd.Series, cutoff: pd.Timestamp) -> bool:
    col = s[s.index <= cutoff].dropna()
    if len(col) < 200:
        return False
    price = float(col.iloc[-1])
    ma200 = float(col.iloc[-200:].mean())
    mom12 = float(col.iloc[-1] / col.iloc[-252] - 1) if len(col) >= 252 else float(col.iloc[-1] / col.iloc[0] - 1)
    return (price > ma200) and (mom12 > 0)


# ---- Trigger checks ------------------------------------------------------------

def _check_rates(data: dict[str, pd.Series], target: pd.Timestamp) -> dict | None:
    s = data.get("^TNX")
    if s is None:
        return None
    s_cut = s[s.index <= target].dropna()
    if len(s_cut) < 2:
        return None

    curr     = float(s_cut.iloc[-1])
    prev     = float(s_cut.iloc[-2])
    move_bp  = (curr - prev) * 100
    fired_move = abs(move_bp) >= _RATES_BP_THRESHOLD

    breached = None
    for lvl in _RATES_ROUND_LEVELS:
        if (prev < lvl <= curr) or (prev > lvl >= curr):
            breached = lvl
            break

    if not fired_move and breached is None:
        return None

    up = move_bp > 0
    slug = f"us10y-{target.strftime('%Y%m%d')}"
    title = (
        f"미국 10년물 {breached:.1f}% {'돌파' if up else '하향'} ({curr:.2f}%)"
        if breached else
        f"미국 10년물 금리 {'상승' if up else '하락'} {abs(move_bp):.0f}bp — {curr:.2f}%"
    )
    highlight = (
        f"<strong>미10Y 금리</strong>가 {prev:.2f}% → <strong>{curr:.2f}%</strong> "
        f"({'+' if up else ''}{move_bp:.0f}bp)."
        + (f" <strong>{breached:.1f}%</strong> 레벨을 {'상향 돌파' if up else '하향 이탈'}." if breached else "")
    )
    sections = [
        ("무슨 일이 있었나",
         f"<p>미국 10년물 국채 금리가 {prev:.2f}% → <strong>{curr:.2f}%</strong>로 {abs(move_bp):.0f}bp {'상승' if up else '하락'}했습니다.</p>"),
        ("왜 중요한가",
         "<p>미10Y는 글로벌 자산가격의 기준선입니다. 금리 상승은 채권 가격 하락·고PER 주식 압박, "
         "하락은 위험자산 선호를 높입니다.</p>"),
        ("A·B에 어떤 의미인가",
         "<ul>"
         "<li><strong>A축</strong>: AGG 게이트 상태 점검. 금리 " + ("상승은 AGG MA200 압박 요인." if up else "하락은 AGG MA200 지지 요인.") + "</li>"
         "<li><strong>B축</strong>: 고PER 성장주 비중 주의. 손절 규율 그대로.</li>"
         "<li>[편집] 월말 리밸런싱 전 조치 불필요.</li>"
         "</ul>"),
    ]
    return {
        "type": "rates", "slug": slug, "title": title,
        "event_date": target.strftime("%Y-%m-%d"),
        "tags": ["금리", "미10Y", "채권", "AGG"],
        "highlight": highlight, "sections": sections, "tables": None,
    }


def _check_vix(data: dict[str, pd.Series], target: pd.Timestamp) -> dict | None:
    s = data.get("^VIX")
    if s is None:
        return None
    s_cut = s[s.index <= target].dropna()
    if len(s_cut) < 2:
        return None

    curr = float(s_cut.iloc[-1])
    prev = float(s_cut.iloc[-2])

    breached = None
    for lvl in _VIX_KEY_LEVELS:
        if prev < lvl <= curr:  # upward breach only
            breached = lvl
            break

    if breached is None:
        return None

    slug = f"vix{breached}-{target.strftime('%Y%m%d')}"
    title = f"VIX {breached} 돌파 — 변동성 급등 ({curr:.1f})"
    highlight = (
        f"공포지수 VIX가 {prev:.1f} → <strong>{curr:.1f}</strong>로 "
        f"<strong>{breached}</strong> 레벨을 상향 돌파했습니다."
    )
    sections = [
        ("무슨 일이 있었나",
         f"<p>VIX가 {prev:.1f} → <strong>{curr:.1f}</strong>로 {breached} 레벨을 돌파했습니다.</p>"),
        ("왜 중요한가",
         "<p>VIX 20↑ 경계 / 25↑ 공포 / 30↑ 극도 공포 구간. 변동성 급등기에는 위험자산 전반이 압박받습니다.</p>"),
        ("A·B에 어떤 의미인가",
         "<ul>"
         "<li><strong>A축</strong>: SPY·EWY MA200 괴리율 모니터링 강화. 게이트 OFF 가능성 점검.</li>"
         "<li><strong>B축</strong>: 신규 진입 보수적 접근. 기존 포지션 손절선 준수.</li>"
         "<li>[편집] 현재 포지션 구체 조치 작성 권장.</li>"
         "</ul>"),
    ]
    return {
        "type": "vix", "slug": slug, "title": title,
        "event_date": target.strftime("%Y-%m-%d"),
        "tags": ["VIX", "변동성", "공포지수"],
        "highlight": highlight, "sections": sections, "tables": None,
    }


def _check_fx(data: dict[str, pd.Series], target: pd.Timestamp) -> dict | None:
    s = data.get("KRW=X")
    if s is None:
        return None
    s_cut = s[s.index <= target].dropna()
    if len(s_cut) < 2:
        return None

    # KRW=X = USD per 1 KRW (small number ~0.00072) → invert to get KRW/USD
    raw_curr = float(s_cut.iloc[-1])
    raw_prev = float(s_cut.iloc[-2])
    curr = 1.0 / raw_curr if raw_curr < 1.0 else raw_curr
    prev = 1.0 / raw_prev if raw_prev < 1.0 else raw_prev

    pct = (curr / prev - 1) * 100  # positive = KRW weakening
    fired_move = abs(pct) >= _FX_PCT_THRESHOLD

    breached = None
    for lvl in _FX_KEY_LEVELS:
        if (prev < lvl <= curr) or (prev > lvl >= curr):
            breached = lvl
            break

    if not fired_move and breached is None:
        return None

    up = pct > 0
    slug = f"usdkrw-{target.strftime('%Y%m%d')}"
    title = (
        f"원/달러 {breached:,}원 {'돌파' if up else '하향'} ({curr:,.0f}원)"
        if breached else
        f"원/달러 환율 {'약세' if up else '강세'} {abs(pct):.1f}% — {curr:,.0f}원"
    )
    highlight = (
        f"원/달러 환율이 {prev:,.0f}원 → <strong>{curr:,.0f}원</strong> "
        f"({'+' if up else ''}{pct:.1f}%)."
        + (f" <strong>{breached:,}원</strong> 레벨을 {'상향 돌파' if up else '하향 이탈'}." if breached else "")
    )
    sections = [
        ("무슨 일이 있었나",
         f"<p>원/달러 환율이 {prev:,.0f}원 → <strong>{curr:,.0f}원</strong>으로 이동했습니다.</p>"),
        ("왜 중요한가",
         "<p>원화 약세(환율↑)는 외국인 원화자산 수익률 감소 → 외국인 매도 압력. "
         "EWY 등 한국 ETF 수익률에 직접 영향.</p>"),
        ("A·B에 어떤 의미인가",
         "<ul>"
         "<li><strong>A축</strong>: EWY 성과에 환율 반영됨. 현재 EWY 게이트 상태 확인.</li>"
         "<li><strong>B축</strong>: 한국 종목 보유 시 환율 방향성 주의. 조치 불필요(시스템 그대로).</li>"
         "</ul>"),
    ]
    return {
        "type": "fx", "slug": slug, "title": title,
        "event_date": target.strftime("%Y-%m-%d"),
        "tags": ["환율", "원달러", "KRW", "EWY"],
        "highlight": highlight, "sections": sections, "tables": None,
    }


def _check_taa_gate(data: dict[str, pd.Series], target: pd.Timestamp) -> dict | None:
    changes = []
    for ticker in _TAA_ASSETS:
        s = data.get(ticker)
        if s is None:
            continue
        s_cut = s[s.index <= target].dropna()
        if len(s_cut) < 202:
            continue
        # Compare last two actual trading days
        gate_curr = _gate(s, s_cut.index[-1])
        gate_prev = _gate(s, s_cut.index[-2])
        if gate_curr != gate_prev:
            changes.append({
                "ticker": ticker,
                "name": _TAA_NAMES[ticker],
                "prev": "ON" if gate_prev else "OFF",
                "curr": "ON" if gate_curr else "OFF",
                "price": float(s_cut.iloc[-1]),
            })

    if not changes:
        return None

    asset_names = "·".join(c["name"] for c in changes)
    slug   = f"taa-gate-{'_'.join(c['ticker'].lower() for c in changes)}-{target.strftime('%Y%m%d')}"
    title  = f"TAA 게이트 변경: {asset_names}"
    highlight = " ".join(
        f"<strong>{c['name']}</strong> 게이트 <strong>{c['prev']} → {c['curr']}</strong>."
        for c in changes
    )
    rows = [{"자산": c["name"], "전일": c["prev"], "당일": c["curr"], "현재가": f"${c['price']:.2f}"} for c in changes]
    sections = [
        ("게이트 전환 내용",
         "<p>아래 자산의 TAA V3 게이트 상태가 변경됐습니다. 다음 월말 리밸런싱에 비중 조정됩니다.</p>"),
        ("전환 원인",
         "<p>[편집] MA200 대비 가격 위치, 12M 모멘텀 방향 등 구체 원인 작성.</p>"),
        ("A·B에 어떤 의미인가",
         "<ul>"
         "<li><strong>A축</strong>: 월말 리밸런싱 시 해당 자산 비중 변경 예정.</li>"
         "<li><strong>B축</strong>: 직접 영향 없음. 종목별 MA200 위치는 B축 주간 레터 참고.</li>"
         "</ul>"),
    ]
    return {
        "type": "taa_gate", "slug": slug, "title": title,
        "event_date": target.strftime("%Y-%m-%d"),
        "tags": ["TAA", "게이트"] + [c["ticker"] for c in changes],
        "highlight": highlight, "sections": sections,
        "tables": {"게이트 전환 내용": rows},
    }


def _check_sector(data: dict[str, pd.Series], target: pd.Timestamp) -> dict | None:
    cur_ret: dict[str, float] = {}
    prev_ret: dict[str, float] = {}

    for ticker, name in _US_SECTORS.items():
        s = data.get(ticker)
        if s is None:
            continue
        s_cut = s[s.index <= target].dropna()
        if len(s_cut) < 3:
            continue

        # MTD return as of last available day
        month_start = s_cut.index[-1].replace(day=1)
        s_mtd = s_cut[s_cut.index >= month_start]
        if len(s_mtd) >= 2:
            cur_ret[name] = float(s_mtd.iloc[-1] / s_mtd.iloc[0] - 1)

        # MTD return as of one day earlier
        s_prev = s_cut.iloc[:-1]
        s_mtd_prev = s_prev[s_prev.index >= month_start]
        if len(s_mtd_prev) >= 2:
            prev_ret[name] = float(s_mtd_prev.iloc[-1] / s_mtd_prev.iloc[0] - 1)

    if not cur_ret or not prev_ret:
        return None

    top_cur  = max(cur_ret,  key=lambda k: cur_ret[k])
    top_prev = max(prev_ret, key=lambda k: prev_ret[k])

    if top_cur == top_prev:
        return None

    slug = f"sector-{target.strftime('%Y%m%d')}"
    title = f"주도 섹터 교체: {top_prev} → {top_cur}"
    highlight = (
        f"이번 달 주도 섹터가 <strong>{top_prev}</strong> → <strong>{top_cur}</strong>로 바뀌었습니다. "
        f"{top_cur}: MTD <strong>{cur_ret[top_cur]*100:.1f}%</strong>."
    )
    rows = sorted(
        [{"섹터": n, "이번달 수익률": f"{v*100:.1f}%"} for n, v in cur_ret.items()],
        key=lambda r: float(r["이번달 수익률"].replace("%", "")),
        reverse=True,
    )
    sections = [
        ("주도 섹터 교체",
         f"<p>전일 1위 섹터 <strong>{top_prev}</strong>에서 <strong>{top_cur}</strong>으로 주도권이 이동했습니다.</p>"),
        ("배경 분석",
         "<p>[편집] 섹터 교체 배경(금리·실적·수급) 작성.</p>"),
        ("A·B에 어떤 의미인가",
         "<ul>"
         "<li><strong>A축</strong>: 섹터 직접 반영 없음(자산 클래스 기준). 참고 지표로 활용.</li>"
         "<li><strong>B축</strong>: 해당 섹터 종목 비중 점검. [편집]</li>"
         "</ul>"),
    ]
    return {
        "type": "sector", "slug": slug, "title": title,
        "event_date": target.strftime("%Y-%m-%d"),
        "tags": ["섹터", "섹터로테이션", top_cur, top_prev],
        "highlight": highlight, "sections": sections,
        "tables": {"주도 섹터 교체": rows},
    }


def _check_macro_calendar(target: pd.Timestamp) -> dict | None:
    event = _MACRO_CALENDAR.get(target.strftime("%Y-%m-%d"))
    if not event:
        return None

    slug  = f"macro-{event.replace(' ', '-').replace('(', '').replace(')', '')}-{target.strftime('%Y%m%d')}"
    title = f"[오늘] {event} — 주목 포인트"
    highlight = f"오늘 <strong>{event}</strong>이 예정되어 있습니다. 발표 전후 시장 변동에 주의하세요."
    sections = [
        ("오늘의 이벤트",
         f"<p><strong>{event}</strong> 발표일입니다. 아래 체크포인트를 확인하세요.</p>"),
        ("무엇을 볼 것인가",
         "<p>[편집] 예상치, 이전값, 시장 컨센서스 등 작성.</p>"),
        ("A·B에 어떤 의미인가",
         "<ul>"
         "<li><strong>A축</strong>: [편집] 발표 결과에 따른 TAA 신호 영향 작성.</li>"
         "<li><strong>B축</strong>: [편집] 발표 결과에 따른 B축 포지션 영향 작성.</li>"
         "</ul>"),
    ]
    return {
        "type": "macro", "slug": slug, "title": title,
        "event_date": target.strftime("%Y-%m-%d"),
        "tags": ["매크로", event],
        "highlight": highlight, "sections": sections, "tables": None,
    }


# ---- Main scan -----------------------------------------------------------------

def scan_triggers(as_of: str | None = None) -> list[dict]:
    """
    Run all 6 trigger checks. Returns list of fired trigger dicts.
    Each dict: {type, slug, title, event_date, tags, highlight, sections, tables}.
    """
    target = pd.Timestamp(as_of) if as_of else pd.Timestamp.now().normalize()

    results: list[dict] = []

    # Calendar check (no network needed)
    r = _check_macro_calendar(target)
    if r:
        results.append(r)

    # Fetch market data
    start = (target - pd.Timedelta(days=400)).strftime("%Y-%m-%d")
    end   = (target + pd.Timedelta(days=2)).strftime("%Y-%m-%d")
    print(f"[c_scanner] fetching market data ({start} → {end})...")
    try:
        data = _fetch_close(_all_tickers(), start, end)
        print(f"[c_scanner] {len(data)}/{len(_all_tickers())} tickers fetched")
    except Exception as e:
        print(f"[c_scanner] fetch error: {e}")
        data = {}

    for fn in [_check_rates, _check_vix, _check_fx, _check_taa_gate, _check_sector]:
        try:
            r = fn(data, target)
            if r:
                results.append(r)
        except Exception as e:
            print(f"[c_scanner] {fn.__name__} error: {e}")

    return results
