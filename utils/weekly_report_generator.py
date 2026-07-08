"""
주간 HTML 리포트 생성.

quantReports/YYYY-WXX.html 에 저장한다.
- 주간 시장 요약 (5거래일 지수 수익률)
- 기간모멘텀 1W TOP30
- 주도주 주간 누적 (지난 5거래일 캐시 집계)
- 포트폴리오 주간 리뷰
"""

import json
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta

_REPORTS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "quantReports")
_CACHE_DIR   = os.path.join(os.path.dirname(os.path.dirname(__file__)), "cache")

# CSS 공유 (report_generator와 동일)
from utils.report_generator import _CSS, _fetch_index, _fetch_current_price, _INDEX_CODES
from utils.market_regime import generate_regime_section


# ---------------------------------------------------------------------------
# 주간 시장 요약 섹션
# ---------------------------------------------------------------------------

def _fetch_weekly_index(args: tuple) -> tuple:
    """(code, label, ccy) → (label, weekly_pct | None)"""
    code, label, ccy = args
    try:
        import FinanceDataReader as fdr
        end   = datetime.today()
        start = end - timedelta(days=14)
        df = fdr.DataReader(code, start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d"))
        df = df[df["Close"] > 0].dropna(subset=["Close"])
        if len(df) < 6:
            return label, None
        close_now  = float(df["Close"].iloc[-1])
        close_5ago = float(df["Close"].iloc[-6])   # 5거래일 전
        weekly_pct = (close_now - close_5ago) / close_5ago * 100
        daily_pct  = (close_now - float(df["Close"].iloc[-2])) / float(df["Close"].iloc[-2]) * 100
        return label, {"weekly_pct": weekly_pct, "daily_pct": daily_pct,
                       "close_now": close_now, "currency": ccy}
    except Exception:
        return label, None


def generate_weekly_market_section(generated_at: str | None = None) -> str:
    """지난 5거래일 지수 수익률 HTML 섹션."""
    if generated_at is None:
        generated_at = datetime.now().strftime("%H:%M")

    with ThreadPoolExecutor(max_workers=4) as ex:
        results = dict(ex.map(_fetch_weekly_index, _INDEX_CODES))

    rows_html = []
    for _, label, ccy in _INDEX_CODES:
        d = results.get(label)
        if d:
            weekly_cls = "up" if d["weekly_pct"] >= 0 else "dn"
            daily_cls  = "up" if d["daily_pct"]  >= 0 else "dn"
            rows_html.append(
                f"<tr>"
                f"<td><strong>{label}</strong></td>"
                f"<td>{d['close_now']:,.2f}</td>"
                f'<td class="{weekly_cls}">{d["weekly_pct"]:+.2f}%</td>'
                f'<td class="{daily_cls}">{d["daily_pct"]:+.2f}%</td>'
                f"</tr>"
            )
        else:
            rows_html.append(f"<tr><td><strong>{label}</strong></td><td>-</td><td>-</td><td>-</td></tr>")

    return (
        f'<!-- SECTION:weekly_market -->\n'
        f'<section id="section-weekly_market">\n'
        f'<h2>주간 시장 요약</h2>\n'
        f'<p class="meta">{generated_at} 기준 · 5거래일 기준</p>\n'
        f'<table>\n'
        f'<thead><tr><th>지수</th><th>현재값</th><th>주간 수익률</th><th>전일 대비</th></tr></thead>\n'
        f'<tbody>{"".join(rows_html)}</tbody>\n'
        f'</table>\n'
        f'</section>\n'
        f'<!-- /SECTION:weekly_market -->'
    )


# ---------------------------------------------------------------------------
# 기간모멘텀 1W TOP30 섹션
# ---------------------------------------------------------------------------

def _load_latest_momentum_cache(market: str) -> "list[dict] | None":
    """가장 최근 기간모멘텀 캐시 파일 로드 (flat list 포맷만 수락)."""
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


def generate_weekly_momentum_section(generated_at: str | None = None) -> str:
    """기간모멘텀 1W 기준 TOP30 HTML 섹션 (KR + US 통합)."""
    if generated_at is None:
        generated_at = datetime.now().strftime("%H:%M")

    try:
        from utils.stock_scanner import apply_sort_and_cols
    except Exception:
        return '<section><h2>기간모멘텀 1W TOP30</h2><p>모듈 로드 실패</p></section>'

    rows_html = []
    for market in ("KOSPI", "KOSDAQ", "SP500"):
        cached = _load_latest_momentum_cache(market)
        if not cached:
            continue
        sorted_rows, labels = apply_sort_and_cols(cached, "1W", top_n=10)
        for r in sorted_rows:
            is_us    = r.get("is_us", False)
            code_str = r.get("code", "")
            rows_html.append(
                f"<tr>"
                f"<td>{market}</td>"
                f"<td><strong>{r.get('name','')}</strong></td>"
                f"<td>{code_str}</td>"
                f'<td class="{"up" if r.get("col1_pos") else "dn"}">{r.get("col1_str","-")}</td>'
                f'<td class="{"up" if r.get("col2_pos") else "dn"}">{r.get("col2_str","-")}</td>'
                f'<td class="{"up" if r.get("col3_pos") else "dn"}">{r.get("col3_str","-")}</td>'
                f'<td class="{"up" if r.get("col4_pos") else "dn"}">{r.get("col4_str","-")}</td>'
                f"</tr>"
            )

    if not rows_html:
        return (
            f'<!-- SECTION:weekly_momentum -->\n'
            f'<section id="section-weekly_momentum">'
            f'<h2>기간모멘텀 1W TOP10</h2>'
            f'<p class="meta">캐시 없음 — fetch_momentum_daily.py 실행 후 재시도</p>'
            f'</section>\n<!-- /SECTION:weekly_momentum -->'
        )

    return (
        f'<!-- SECTION:weekly_momentum -->\n'
        f'<section id="section-weekly_momentum">\n'
        f'<h2>기간모멘텀 1W TOP10 (시장별)</h2>\n'
        f'<p class="meta">{generated_at} 기준 · 1W 수익률 내림차순</p>\n'
        f'<table>\n'
        f'<thead><tr>'
        f'<th>시장</th><th>종목명</th><th>코드</th>'
        f'<th>1W</th><th>1M</th><th>2M</th><th>3M</th>'
        f'</tr></thead>\n'
        f'<tbody>{"".join(rows_html)}</tbody>\n'
        f'</table>\n'
        f'</section>\n'
        f'<!-- /SECTION:weekly_momentum -->'
    )


# ---------------------------------------------------------------------------
# 주도주 주간 누적 섹션 (지난 5거래일 캐시 집계)
# ---------------------------------------------------------------------------

def _load_leaders_for_week(market: str, n_days: int = 5) -> list[dict]:
    """지난 n거래일의 주도주 캐시를 모아 반환. 각 행에 _date 필드 추가."""
    results: list[dict] = []
    dates_found: set[str] = set()

    for i in range(14):
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
                item = {**item, "_date": day_label}
                results.append(item)
            dates_found.add(day_label)
            if len(dates_found) >= n_days:
                break
        except Exception:
            pass

    return results


def _build_leaders_rows(market: str, entries: list, min_count: int = 2) -> tuple:
    """leaders 엔트리 → (stock_rows, etf_rows) HTML 리스트"""
    from collections import Counter
    counter  = Counter(item["code"] for item in entries)
    info_map: dict = {}
    for item in entries:
        c = item["code"]
        if c not in info_map:
            info_map[c] = item

    top = sorted(
        [(c, cnt) for c, cnt in counter.items() if cnt >= min_count],
        key=lambda x: -x[1],
    )[:20]

    stock_rows, etf_rows = [], []
    for code, cnt in top:
        info    = info_map.get(code, {})
        is_etf  = info.get("is_etf", False)
        badge   = "🔥" if cnt >= 4 else ("⚡" if cnt >= 3 else "")
        row = (
            f"<tr>"
            f"<td>{market}</td>"
            f"<td><strong>{info.get('name','')}</strong></td>"
            f"<td>{code}</td>"
            f"<td>{cnt}일 {badge}</td>"
            f"<td>{info.get('change_pct_str','')}</td>"
            f"<td>{info.get('score_a_str','')}</td>"
            f"</tr>"
        )
        (etf_rows if is_etf else stock_rows).append(row)

    return stock_rows, etf_rows


_LEADERS_TABLE_HEAD = (
    '<thead><tr>'
    '<th>시장</th><th>종목명</th><th>코드</th>'
    '<th>등장 횟수</th><th>최근 등락률</th><th>A점수</th>'
    '</tr></thead>'
)

_TAB_JS = """
<script>
function switchLeadersTab(el, tabId) {
  var sec = el.closest('.leaders-tabs');
  sec.querySelectorAll('.tab-btn').forEach(function(b){b.classList.remove('active')});
  sec.querySelectorAll('.tab-pane').forEach(function(p){p.style.display='none'});
  el.classList.add('active');
  sec.querySelector('#'+tabId).style.display='';
}
</script>
<style>
.tab-btn{background:#f0f0f0;border:1px solid #ccc;padding:4px 12px;cursor:pointer;border-radius:4px 4px 0 0;margin-right:4px;font-size:13px}
.tab-btn.active{background:#fff;border-bottom-color:#fff;font-weight:bold}
.tab-pane{border:1px solid #ccc;padding:8px;border-radius:0 4px 4px 4px}
</style>
"""


def generate_weekly_leaders_section(generated_at: str | None = None) -> str:
    """지난 5거래일에 2회 이상 등장한 주도주 HTML 섹션 (일반주/ETF 탭 분리)."""
    if generated_at is None:
        generated_at = datetime.now().strftime("%H:%M")

    all_stock_rows, all_etf_rows = [], []
    for market in ("KOSPI", "KOSDAQ"):
        entries = _load_leaders_for_week(market, 5)
        if not entries:
            continue
        s, e = _build_leaders_rows(market, entries, min_count=2)
        all_stock_rows.extend(s)
        all_etf_rows.extend(e)

    if not all_stock_rows and not all_etf_rows:
        return (
            f'<!-- SECTION:weekly_leaders -->\n'
            f'<section id="section-weekly_leaders">'
            f'<h2>주도주 주간 누적</h2>'
            f'<p class="meta">이번 주 캐시 없음</p>'
            f'</section>\n<!-- /SECTION:weekly_leaders -->'
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
        f'<!-- SECTION:weekly_leaders -->\n'
        f'<section id="section-weekly_leaders">\n'
        f'<h2>주도주 주간 누적 (2회 이상 등장)</h2>\n'
        f'<p class="meta">{generated_at} 기준 · 지난 5거래일</p>\n'
        f'{_TAB_JS}\n'
        f'<div class="leaders-tabs">\n'
        f'<button class="tab-btn active" onclick="switchLeadersTab(this,\'lw-stock\')">일반주 ({len(all_stock_rows)})</button>'
        f'<button class="tab-btn" onclick="switchLeadersTab(this,\'lw-etf\')">ETF ({len(all_etf_rows)})</button>\n'
        f'<div id="lw-stock" class="tab-pane">{stock_table}</div>\n'
        f'<div id="lw-etf" class="tab-pane" style="display:none">{etf_table}</div>\n'
        f'</div>\n'
        f'</section>\n'
        f'<!-- /SECTION:weekly_leaders -->'
    )


# ---------------------------------------------------------------------------
# 포트폴리오 주간 리뷰 섹션
# ---------------------------------------------------------------------------

def _fetch_price_n_days_ago(args: tuple) -> tuple:
    """(symbol, n_days) → (symbol, price_n_days_ago | None)"""
    symbol, n_days = args
    try:
        import FinanceDataReader as fdr
        end   = datetime.today()
        start = end - timedelta(days=n_days + 10)
        df = fdr.DataReader(symbol, start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d"))
        df = df[df["Close"] > 0].dropna(subset=["Close"])
        if len(df) < n_days + 1:
            return symbol, None
        close_n_ago = float(df["Close"].iloc[-(n_days + 1)])
        close_now   = float(df["Close"].iloc[-1])
        return symbol, (close_n_ago, close_now)
    except Exception:
        return symbol, None


def generate_weekly_portfolio_section(generated_at: str | None = None) -> str:
    """보유종목 주간(5거래일) 손익 HTML 섹션."""
    if generated_at is None:
        generated_at = datetime.now().strftime("%H:%M")

    try:
        from utils.scan_db import load_holdings
        holdings = load_holdings()
    except Exception as e:
        return f'<section><h2>포트폴리오 주간 리뷰</h2><p>DB 오류: {e}</p></section>'

    if not holdings:
        return (
            f'<!-- SECTION:weekly_portfolio -->\n'
            f'<section id="section-weekly_portfolio">'
            f'<h2>포트폴리오 주간 리뷰</h2>'
            f'<p class="meta">보유 종목 없음</p>'
            f'</section>\n<!-- /SECTION:weekly_portfolio -->'
        )

    unique_syms = list({h["symbol"] for h in holdings})
    with ThreadPoolExecutor(max_workers=10) as ex:
        raw = dict(ex.map(_fetch_price_n_days_ago, [(s, 5) for s in unique_syms]))

    rows_html = []
    total_weekly_pnl = 0.0
    has_data = False

    for h in holdings:
        sym       = h["symbol"]
        qty       = h.get("quantity", 0.0) or 0.0
        buy_price = h.get("buy_price", 0.0) or 0.0
        is_us     = h.get("currency", "KRW") == "USD"
        prices    = raw.get(sym)

        if prices:
            p_ago, p_now = prices
            weekly_pct  = (p_now - p_ago) / p_ago * 100 if p_ago else None
            weekly_pnl  = (p_now - p_ago) * qty if qty and p_ago else None
            chg_cls     = "up" if (weekly_pct or 0) >= 0 else "dn"
            pct_str     = f"{weekly_pct:+.2f}%" if weekly_pct is not None else "-"
            pnl_str     = f"{weekly_pnl:+,.0f}" if weekly_pnl is not None else "-"
            now_str     = f"{p_now:,.2f}" if is_us else f"{p_now:,.0f}"
            if weekly_pnl is not None:
                total_weekly_pnl += weekly_pnl
                has_data = True
        else:
            chg_cls = "pnl-na"
            pct_str = "-"
            pnl_str = "-"
            now_str = "-"

        pnl_cls = "pnl-pos" if (weekly_pnl := (prices and (prices[1] - prices[0]) * qty or 0)) >= 0 else "pnl-neg" if has_data else "pnl-na"

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
        cls = "pnl-pos" if total_weekly_pnl >= 0 else "pnl-neg"
        summary_html = (
            f'<div class="highlight-box">'
            f'주간 합계 손익: <strong class="{cls}">{total_weekly_pnl:+,.0f}</strong>'
            f'</div>'
        )

    return (
        f'<!-- SECTION:weekly_portfolio -->\n'
        f'<section id="section-weekly_portfolio">\n'
        f'<h2>포트폴리오 주간 리뷰</h2>\n'
        f'<p class="meta">{generated_at} 기준 · 5거래일 대비</p>\n'
        f'{summary_html}\n'
        f'<table>\n'
        f'<thead><tr>'
        f'<th>종목명</th><th>코드</th><th>현재가</th>'
        f'<th>주간 등락</th><th>주간 손익</th><th>메모</th>'
        f'</tr></thead>\n'
        f'<tbody>{"".join(rows_html)}</tbody>\n'
        f'</table>\n'
        f'</section>\n'
        f'<!-- /SECTION:weekly_portfolio -->'
    )


# ---------------------------------------------------------------------------
# 전체 주간 리포트 생성
# ---------------------------------------------------------------------------

def _week_label() -> str:
    today = datetime.today()
    year, week, _ = today.isocalendar()
    return f"{year}-W{week:02d}"


def _weekly_report_path() -> str:
    os.makedirs(_REPORTS_DIR, exist_ok=True)
    return os.path.join(_REPORTS_DIR, f"{_week_label()}.html")


def generate_full_weekly_report() -> str:
    """주간 전체 리포트 생성.
    반환: 저장된 파일 경로.
    """
    week_str     = _week_label()
    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M")
    path         = _weekly_report_path()

    sections = [
        generate_weekly_market_section(generated_at),
        generate_regime_section(generated_at),
        generate_weekly_momentum_section(generated_at),
        generate_weekly_leaders_section(generated_at),
        generate_weekly_portfolio_section(generated_at),
    ]

    content = (
        f"<!DOCTYPE html>\n<html lang='ko'>\n<head>\n"
        f"<meta charset='utf-8'>\n"
        f"<title>Weekly Report — {week_str}</title>\n"
        f"<style>{_CSS}</style>\n"
        f"</head>\n<body>\n"
        f"<h1>Weekly Report — {week_str}</h1>\n\n"
        + "\n\n".join(sections)
        + "\n</body>\n</html>\n"
    )

    with open(path, "w", encoding="utf-8") as f:
        f.write(content)

    return path
