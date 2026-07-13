"""
월간 HTML 리포트 생성.

quantReports/YYYY-MM.html 에 저장한다.
- 월간 시장 요약 (20거래일 지수 수익률)
- 기간모멘텀 1M TOP10 (시장별)
- 주도주 월간 누적 (지난 20거래일 캐시 집계)
- 포트폴리오 월간 리뷰
- 섹터모멘텀 월간 변화
"""

import json
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta

_REPORTS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "quantReports")
_CACHE_DIR   = os.path.join(os.path.dirname(os.path.dirname(__file__)), "cache")

from utils.report_generator import _CSS, _fetch_index, _fetch_current_price, _INDEX_CODES
from utils.market_regime import generate_regime_section, fetch_all_regimes
from utils.regime_picks import generate_regime_picks_section


# ---------------------------------------------------------------------------
# 월간 시장 요약 섹션
# ---------------------------------------------------------------------------

def _fetch_monthly_index(args: tuple) -> tuple:
    """(code, label, ccy) → (label, monthly_pct | None)"""
    code, label, ccy = args
    try:
        import FinanceDataReader as fdr
        end   = datetime.today()
        start = end - timedelta(days=40)
        df = fdr.DataReader(code, start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d"))
        df = df[df["Close"] > 0].dropna(subset=["Close"])
        if len(df) < 22:
            return label, None
        close_now   = float(df["Close"].iloc[-1])
        close_20ago = float(df["Close"].iloc[-21])   # ~20거래일 전
        monthly_pct = (close_now - close_20ago) / close_20ago * 100
        weekly_pct  = (close_now - float(df["Close"].iloc[-6])) / float(df["Close"].iloc[-6]) * 100
        return label, {
            "monthly_pct": monthly_pct,
            "weekly_pct":  weekly_pct,
            "close_now":   close_now,
            "currency":    ccy,
        }
    except Exception:
        return label, None


def generate_monthly_market_section(generated_at: str | None = None) -> str:
    """지난 20거래일 지수 수익률 HTML 섹션."""
    if generated_at is None:
        generated_at = datetime.now().strftime("%H:%M")

    with ThreadPoolExecutor(max_workers=8) as ex:
        results = dict(ex.map(_fetch_monthly_index, _WEEKLY_INDEX_CODES))

    rows_html = []
    for _, label, ccy in _WEEKLY_INDEX_CODES:
        d = results.get(label)
        if d:
            m_cls = "up" if d["monthly_pct"] >= 0 else "dn"
            w_cls = "up" if d["weekly_pct"]  >= 0 else "dn"
            rows_html.append(
                f"<tr>"
                f"<td><strong>{label}</strong></td>"
                f"<td>{d['close_now']:,.2f}</td>"
                f'<td class="{m_cls}">{d["monthly_pct"]:+.2f}%</td>'
                f'<td class="{w_cls}">{d["weekly_pct"]:+.2f}%</td>'
                f"</tr>"
            )
        else:
            rows_html.append(f"<tr><td><strong>{label}</strong></td><td>-</td><td>-</td><td>-</td></tr>")

    return (
        f'<!-- SECTION:monthly_market -->\n'
        f'<section id="section-monthly_market">\n'
        f'<h2>월간 시장 요약</h2>\n'
        f'<p class="meta">{generated_at} 기준 · 약 20거래일 기준</p>\n'
        f'<table>\n'
        f'<thead><tr><th>지수</th><th>현재값</th><th>월간 수익률</th><th>주간 수익률</th></tr></thead>\n'
        f'<tbody>{"".join(rows_html)}</tbody>\n'
        f'</table>\n'
        f'</section>\n'
        f'<!-- /SECTION:monthly_market -->'
    )


# ---------------------------------------------------------------------------
# 기간모멘텀 1M TOP10 섹션
# ---------------------------------------------------------------------------

def _load_latest_momentum_cache(market: str) -> "list[dict] | None":
    if not os.path.isdir(_CACHE_DIR):
        return None
    prefix = f"momentum_{market}_"
    files  = sorted(
        [f for f in os.listdir(_CACHE_DIR) if f.startswith(prefix) and f.endswith(".json")],
        reverse=True,
    )
    for fn in files[:3]:
        try:
            with open(os.path.join(_CACHE_DIR, fn), encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, list) and data:
                return data
        except Exception:
            pass
    return None


def generate_monthly_momentum_section(generated_at: str | None = None) -> str:
    """기간모멘텀 1M 기준 TOP10 HTML 섹션 (KR + US 통합)."""
    if generated_at is None:
        generated_at = datetime.now().strftime("%H:%M")

    try:
        from utils.stock_scanner import apply_sort_and_cols
    except Exception:
        return '<section><h2>기간모멘텀 1M TOP10</h2><p>모듈 로드 실패</p></section>'

    rows_html = []
    for market in ("KOSPI", "KOSDAQ", "SP500"):
        cached = _load_latest_momentum_cache(market)
        if not cached:
            continue
        sorted_rows, labels = apply_sort_and_cols(cached, "1M", top_n=10)
        for r in sorted_rows:
            rows_html.append(
                f"<tr>"
                f"<td>{market}</td>"
                f"<td><strong>{r.get('name','')}</strong></td>"
                f"<td>{r.get('code','')}</td>"
                f'<td class="{"up" if r.get("col1_pos") else "dn"}">{r.get("col1_str","-")}</td>'
                f'<td class="{"up" if r.get("col2_pos") else "dn"}">{r.get("col2_str","-")}</td>'
                f'<td class="{"up" if r.get("col3_pos") else "dn"}">{r.get("col3_str","-")}</td>'
                f'<td class="{"up" if r.get("col4_pos") else "dn"}">{r.get("col4_str","-")}</td>'
                f"</tr>"
            )

    if not rows_html:
        return (
            f'<!-- SECTION:monthly_momentum -->\n'
            f'<section id="section-monthly_momentum">'
            f'<h2>기간모멘텀 1M TOP10</h2>'
            f'<p class="meta">캐시 없음 — fetch_momentum_daily.py 실행 후 재시도</p>'
            f'</section>\n<!-- /SECTION:monthly_momentum -->'
        )

    return (
        f'<!-- SECTION:monthly_momentum -->\n'
        f'<section id="section-monthly_momentum">\n'
        f'<h2>기간모멘텀 1M TOP10 (시장별)</h2>\n'
        f'<p class="meta">{generated_at} 기준 · 1M 수익률 내림차순</p>\n'
        f'<table>\n'
        f'<thead><tr>'
        f'<th>시장</th><th>종목명</th><th>코드</th>'
        f'<th>1W</th><th>1M</th><th>2M</th><th>3M</th>'
        f'</tr></thead>\n'
        f'<tbody>{"".join(rows_html)}</tbody>\n'
        f'</table>\n'
        f'</section>\n'
        f'<!-- /SECTION:monthly_momentum -->'
    )


# ---------------------------------------------------------------------------
# 주도주 월간 누적 섹션 (지난 20거래일 캐시 집계)
# ---------------------------------------------------------------------------

def _load_leaders_for_month(market: str, n_days: int = 20) -> list:
    results: list = []
    dates_found: set = set()

    for i in range(35):
        d = datetime.today() - timedelta(days=i)
        if d.weekday() in (5, 6):
            continue
        date_str = d.strftime("%Y%m%d")
        path     = os.path.join(_CACHE_DIR, f"leaders_{market}_{date_str}.json")
        if not os.path.exists(path):
            continue
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            day_label = d.strftime("%Y-%m-%d")
            for item in data:
                results.append({**item, "_date": day_label})
            dates_found.add(day_label)
            if len(dates_found) >= n_days:
                break
        except Exception:
            pass

    return results


from utils.weekly_report_generator import (
    _build_leaders_rows, _LEADERS_TABLE_HEAD, _TAB_JS, _WEEKLY_INDEX_CODES,
)


def generate_monthly_leaders_section(generated_at: str | None = None) -> str:
    """지난 20거래일에 3회 이상 등장한 주도주 HTML 섹션 (일반주/ETF 탭 분리)."""
    if generated_at is None:
        generated_at = datetime.now().strftime("%H:%M")

    all_stock_rows, all_etf_rows = [], []
    for market in ("KOSPI", "KOSDAQ"):
        entries = _load_leaders_for_month(market, 20)
        if not entries:
            continue
        s, e = _build_leaders_rows(market, entries, min_count=3)
        all_stock_rows.extend(s)
        all_etf_rows.extend(e)

    if not all_stock_rows and not all_etf_rows:
        return (
            f'<!-- SECTION:monthly_leaders -->\n'
            f'<section id="section-monthly_leaders">'
            f'<h2>주도주 월간 누적</h2>'
            f'<p class="meta">이번 달 캐시 없음</p>'
            f'</section>\n<!-- /SECTION:monthly_leaders -->'
        )

    stock_table = (
        f'<table>\n{_LEADERS_TABLE_HEAD}\n'
        f'<tbody>{"".join(all_stock_rows) or "<tr><td colspan=6>해당 없음</td></tr>"}</tbody>\n</table>'
    )
    etf_table = (
        f'<table>\n{_LEADERS_TABLE_HEAD}\n'
        f'<tbody>{"".join(all_etf_rows) or "<tr><td colspan=6>해당 없음</td></tr>"}</tbody>\n</table>'
    )

    return (
        f'<!-- SECTION:monthly_leaders -->\n'
        f'<section id="section-monthly_leaders">\n'
        f'<h2>주도주 월간 누적 (3회 이상 등장)</h2>\n'
        f'<p class="meta">{generated_at} 기준 · 지난 20거래일</p>\n'
        f'{_TAB_JS}\n'
        f'<div class="leaders-tabs">\n'
        f'<button class="tab-btn active" onclick="switchLeadersTab(this,\'lm-stock\')">일반주 ({len(all_stock_rows)})</button>'
        f'<button class="tab-btn" onclick="switchLeadersTab(this,\'lm-etf\')">ETF ({len(all_etf_rows)})</button>\n'
        f'<div id="lm-stock" class="tab-pane">{stock_table}</div>\n'
        f'<div id="lm-etf" class="tab-pane" style="display:none">{etf_table}</div>\n'
        f'</div>\n'
        f'</section>\n'
        f'<!-- /SECTION:monthly_leaders -->'
    )


# ---------------------------------------------------------------------------
# 포트폴리오 월간 리뷰 섹션
# ---------------------------------------------------------------------------

def _fetch_price_n_days_ago(args: tuple) -> tuple:
    """(symbol, n_days) → (symbol, (price_n_ago, price_now) | None)"""
    symbol, n_days = args
    try:
        import FinanceDataReader as fdr
        end   = datetime.today()
        start = end - timedelta(days=n_days + 15)
        df = fdr.DataReader(symbol, start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d"))
        df = df[df["Close"] > 0].dropna(subset=["Close"])
        if len(df) < n_days + 1:
            return symbol, None
        close_n_ago = float(df["Close"].iloc[-(n_days + 1)])
        close_now   = float(df["Close"].iloc[-1])
        return symbol, (close_n_ago, close_now)
    except Exception:
        return symbol, None


def generate_monthly_portfolio_section(generated_at: str | None = None) -> str:
    """보유종목 월간(20거래일) 손익 HTML 섹션."""
    if generated_at is None:
        generated_at = datetime.now().strftime("%H:%M")

    try:
        from utils.scan_db import load_holdings
        holdings = load_holdings()
    except Exception as e:
        return f'<section><h2>포트폴리오 월간 리뷰</h2><p>DB 오류: {e}</p></section>'

    if not holdings:
        return (
            f'<!-- SECTION:monthly_portfolio -->\n'
            f'<section id="section-monthly_portfolio">'
            f'<h2>포트폴리오 월간 리뷰</h2>'
            f'<p class="meta">보유 종목 없음</p>'
            f'</section>\n<!-- /SECTION:monthly_portfolio -->'
        )

    unique_syms = list({h["symbol"] for h in holdings})
    with ThreadPoolExecutor(max_workers=10) as ex:
        raw = dict(ex.map(_fetch_price_n_days_ago, [(s, 20) for s in unique_syms]))

    rows_html = []
    total_monthly_pnl = 0.0
    has_data = False

    for h in holdings:
        sym       = h["symbol"]
        qty       = h.get("quantity", 0.0) or 0.0
        is_us     = h.get("currency", "KRW") == "USD"
        prices    = raw.get(sym)

        if prices:
            p_ago, p_now = prices
            monthly_pct  = (p_now - p_ago) / p_ago * 100 if p_ago else None
            monthly_pnl  = (p_now - p_ago) * qty if qty and p_ago else None
            chg_cls      = "up" if (monthly_pct or 0) >= 0 else "dn"
            pct_str      = f"{monthly_pct:+.2f}%" if monthly_pct is not None else "-"
            pnl_str      = f"{monthly_pnl:+,.0f}" if monthly_pnl is not None else "-"
            now_str      = f"{p_now:,.2f}" if is_us else f"{p_now:,.0f}"
            pnl_cls      = "pnl-pos" if (monthly_pnl or 0) >= 0 else "pnl-neg"
            if monthly_pnl is not None:
                total_monthly_pnl += monthly_pnl
                has_data = True
        else:
            chg_cls = pnl_cls = "pnl-na"
            pct_str = pnl_str = now_str = "-"

        rows_html.append(
            f"<tr>"
            f"<td><strong>{h.get('name','')}</strong></td>"
            f"<td>{sym}</td>"
            f"<td>{now_str}</td>"
            f'<td class="{chg_cls}">{pct_str}</td>'
            f'<td class="{pnl_cls}">{pnl_str}</td>'
            f"<td>{h.get('memo','')}</td>"
            f"</tr>"
        )

    summary_html = ""
    if has_data:
        cls = "pnl-pos" if total_monthly_pnl >= 0 else "pnl-neg"
        summary_html = (
            f'<div class="highlight-box">'
            f'월간 합계 손익: <strong class="{cls}">{total_monthly_pnl:+,.0f}</strong>'
            f'</div>'
        )

    return (
        f'<!-- SECTION:monthly_portfolio -->\n'
        f'<section id="section-monthly_portfolio">\n'
        f'<h2>포트폴리오 월간 리뷰</h2>\n'
        f'<p class="meta">{generated_at} 기준 · 20거래일 대비</p>\n'
        f'{summary_html}\n'
        f'<table>\n'
        f'<thead><tr>'
        f'<th>종목명</th><th>코드</th><th>현재가</th>'
        f'<th>월간 등락</th><th>월간 손익</th><th>메모</th>'
        f'</tr></thead>\n'
        f'<tbody>{"".join(rows_html)}</tbody>\n'
        f'</table>\n'
        f'</section>\n'
        f'<!-- /SECTION:monthly_portfolio -->'
    )


# ---------------------------------------------------------------------------
# 섹터모멘텀 월간 변화 섹션
# ---------------------------------------------------------------------------

def generate_monthly_sector_section(generated_at: str | None = None) -> str:
    """KR/US 섹터 ETF 1M 수익률 테이블."""
    if generated_at is None:
        generated_at = datetime.now().strftime("%H:%M")

    try:
        from utils.sector_scanner import fetch_sector_momentum
    except Exception:
        return '<section><h2>섹터모멘텀 월간</h2><p>모듈 로드 실패</p></section>'

    rows_html = []
    for region in ("KR", "US"):
        try:
            sectors = fetch_sector_momentum(region)
        except Exception:
            continue
        for s in sectors:
            r1m = s.get("ret_1m") or 0
            cls = "up" if r1m >= 0 else "dn"
            rows_html.append(
                f"<tr>"
                f"<td>{region}</td>"
                f"<td><strong>{s.get('name','')}</strong></td>"
                f"<td>{s.get('code','')}</td>"
                f'<td class="{cls}">{s.get("ret_1m_str","-")}</td>'
                f'<td class="{"up" if (s.get("ret_3m") or 0)>=0 else "dn"}">{s.get("ret_3m_str","-")}</td>'
                f'<td class="{"up" if (s.get("ret_6m") or 0)>=0 else "dn"}">{s.get("ret_6m_str","-")}</td>'
                f'<td class="{"up" if (s.get("ret_12m") or 0)>=0 else "dn"}">{s.get("ret_12m_str","-")}</td>'
                f"</tr>"
            )

    if not rows_html:
        return (
            f'<!-- SECTION:monthly_sector -->\n'
            f'<section id="section-monthly_sector">'
            f'<h2>섹터모멘텀 월간</h2>'
            f'<p class="meta">데이터 없음</p>'
            f'</section>\n<!-- /SECTION:monthly_sector -->'
        )

    return (
        f'<!-- SECTION:monthly_sector -->\n'
        f'<section id="section-monthly_sector">\n'
        f'<h2>섹터모멘텀 월간 변화</h2>\n'
        f'<p class="meta">{generated_at} 기준 · 1M 수익률 기준</p>\n'
        f'<table>\n'
        f'<thead><tr>'
        f'<th>국가</th><th>섹터</th><th>ETF코드</th>'
        f'<th>1M</th><th>3M</th><th>6M</th><th>12M</th>'
        f'</tr></thead>\n'
        f'<tbody>{"".join(rows_html)}</tbody>\n'
        f'</table>\n'
        f'</section>\n'
        f'<!-- /SECTION:monthly_sector -->'
    )


# ---------------------------------------------------------------------------
# 전체 월간 리포트 생성
# ---------------------------------------------------------------------------

def _prev_month_label() -> str:
    today = datetime.today()
    first_of_month = today.replace(day=1)
    last_month = first_of_month - timedelta(days=1)
    return last_month.strftime("%Y-%m")


def _monthly_report_path() -> str:
    os.makedirs(_REPORTS_DIR, exist_ok=True)
    return os.path.join(_REPORTS_DIR, f"{_prev_month_label()}.html")


def generate_full_monthly_report() -> str:
    """월간 전체 리포트 생성.
    반환: 저장된 파일 경로.
    """
    month_str    = _prev_month_label()
    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M")
    path         = _monthly_report_path()

    regimes = fetch_all_regimes()
    sections = [
        generate_monthly_market_section(generated_at),
        generate_regime_section(generated_at, regimes=regimes),
        generate_regime_picks_section(regimes, generated_at),
        generate_monthly_sector_section(generated_at),
        generate_monthly_momentum_section(generated_at),
        generate_monthly_leaders_section(generated_at),
        generate_monthly_portfolio_section(generated_at),
    ]

    content = (
        f"<!DOCTYPE html>\n<html lang='ko'>\n<head>\n"
        f"<meta charset='utf-8'>\n"
        f"<title>Monthly Report — {month_str}</title>\n"
        f"<style>{_CSS}</style>\n"
        f"</head>\n<body>\n"
        f"<h1>Monthly Report — {month_str}</h1>\n"
        f"<p style='color:#888;font-size:0.85em;margin:0 0 24px;'>발행일: {generated_at}</p>\n\n"
        + "\n\n".join(sections)
        + "\n\n"
        + f'<footer><p class="meta">QuantMaster Pro — {generated_at} 자동 생성</p></footer>\n'
        + "</body>\n</html>\n"
    )

    with open(path, "w", encoding="utf-8") as f:
        f.write(content)

    return path
