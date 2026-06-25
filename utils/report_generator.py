"""
일별 HTML 리포트 자동 생성.

quantReports/YYYY-MM-DD.html 에 당일주도주 요약을 추가(append)한다.
이미 파일이 있으면 해당 마켓 섹션만 교체하고, 없으면 새로 생성한다.

generate_full_daily_report() 로 전체 리포트(시장개요+주도주+섹터+포트폴리오)를
한번에 생성할 수도 있다.
"""

import json
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta

_REPORTS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "quantReports")

_CSS = """
body{font-family:'Noto Sans KR',sans-serif;max-width:960px;margin:0 auto;padding:24px;background:#f8f9fa;color:#212529}
h1{color:#1a1a2e;border-bottom:3px solid #0d6efd;padding-bottom:8px}
h2{color:#0d6efd;margin-top:40px;border-left:4px solid #0d6efd;padding-left:12px}
h3{color:#495057;margin-top:24px}
table{width:100%;border-collapse:collapse;margin:12px 0;background:#fff;border-radius:8px;overflow:hidden;box-shadow:0 1px 4px rgba(0,0,0,.08)}
th{background:#0d6efd;color:#fff;padding:10px 12px;text-align:left;font-size:.85rem}
td{padding:9px 12px;border-bottom:1px solid #e9ecef;font-size:.875rem}
tr:last-child td{border-bottom:none}
tr:hover td{background:#f1f3f5}
.badge-hot{background:#dc3545;color:#fff;padding:2px 7px;border-radius:4px;font-size:.75rem;font-weight:600}
.badge-warm{background:#fd7e14;color:#fff;padding:2px 7px;border-radius:4px;font-size:.75rem;font-weight:600}
.badge-ok{background:#198754;color:#fff;padding:2px 7px;border-radius:4px;font-size:.75rem;font-weight:600}
.up{color:#dc3545;font-weight:600}
.dn{color:#0d6efd;font-weight:600}
.highlight-box{background:#fff3cd;border:1px solid #ffc107;border-radius:6px;padding:12px 16px;margin:12px 0}
.candidate-box{background:#d1e7dd;border:1px solid #198754;border-radius:6px;padding:12px 16px;margin:12px 0}
.meta{font-size:.8rem;color:#6c757d;margin-bottom:4px}
.overview-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(160px,1fr));gap:12px;margin:16px 0}
.overview-card{background:#fff;border-radius:8px;padding:14px 16px;box-shadow:0 1px 4px rgba(0,0,0,.08)}
.overview-card .label{font-size:.75rem;color:#6c757d;margin-bottom:4px}
.overview-card .value{font-size:1.1rem;font-weight:700;margin-bottom:2px}
.overview-card .chg{font-size:.85rem;font-weight:600}
.pnl-pos{color:#dc3545;font-weight:700}
.pnl-neg{color:#0d6efd;font-weight:700}
.pnl-na{color:#adb5bd}
"""


def _report_path(date: datetime | None = None) -> str:
    d = date or datetime.today()
    os.makedirs(_REPORTS_DIR, exist_ok=True)
    return os.path.join(_REPORTS_DIR, d.strftime("%Y-%m-%d") + ".html")


def _streak_label(days: int) -> str:
    if days >= 3:
        return f"{days}일 🔥"
    if days >= 2:
        return f"{days}일 ⚡"
    return "-"


def _streak_badge(days: int) -> str:
    if days >= 3:
        return f'<span class="badge-hot">{days}일 🔥</span>'
    if days >= 2:
        return f'<span class="badge-warm">{days}일 ⚡</span>'
    return "-"


def _close_buy_candidate(item: dict) -> bool:
    return (
        item.get("change_pct_val", 0) >= 5.0
        and item.get("is_near_high", False)
        and item.get("has_vol_rank", False)
        and item.get("has_rise_rank", False)
    )


def generate_market_section(market: str, data: list[dict], generated_at: str) -> str:
    """마켓 하나의 HTML 섹션 문자열 반환."""
    data_date = data[0].get("data_date", datetime.today().strftime("%Y-%m-%d")) if data else "-"
    streaks = [item for item in data if item.get("consecutive_days", 1) >= 2]
    close_buys = [item for item in data if _close_buy_candidate(item)]

    rows = []
    for item in data[:20]:
        pct_str = item.get("change_pct_str", "")
        pct_cls = "up" if item.get("change_pct_val", 0) >= 0 else "dn"
        streak_html = _streak_badge(item.get("consecutive_days", 1))
        close_html = '<span class="badge-ok">✅ 후보</span>' if _close_buy_candidate(item) else ""
        rows.append(
            f"<tr>"
            f"<td>{item.get('rank','')}</td>"
            f"<td><strong>{item.get('name','')}</strong></td>"
            f"<td>{item.get('code','')}</td>"
            f"<td class='{pct_cls}'>{pct_str}</td>"
            f"<td>{item.get('vol_rank_str','-')}</td>"
            f"<td>{item.get('rise_rank_str','-')}</td>"
            f"<td>{item.get('score_a_str','')}</td>"
            f"<td>{streak_html}</td>"
            f"<td>{close_html}</td>"
            f"</tr>"
        )

    streak_html_block = ""
    if streaks:
        items_html = "".join(
            f"<li><strong>{i['name']}</strong> ({i['code']}) — "
            f"{_streak_label(i['consecutive_days'])} 연속 &nbsp; "
            f"등락률 {i.get('change_pct_str','')} &nbsp; "
            f"A점수 {i.get('score_a_str','')}</li>"
            for i in sorted(streaks, key=lambda x: -x.get("consecutive_days", 1))
        )
        streak_html_block = (
            f'<div class="highlight-box">'
            f"<h3>연속 등장 하이라이트</h3><ul>{items_html}</ul>"
            f"</div>"
        )

    candidate_html_block = ""
    if close_buys:
        items_html = "".join(
            f"<li><strong>{i['name']}</strong> ({i['code']}) &nbsp; "
            f"등락률 {i.get('change_pct_str','')} &nbsp; "
            f"A점수 {i.get('score_a_str','')}</li>"
            for i in close_buys
        )
        candidate_html_block = (
            f'<div class="candidate-box">'
            f"<h3>종가매매 후보</h3><ul>{items_html}</ul>"
            f"</div>"
        )

    section = (
        f'<!-- SECTION:{market} -->\n'
        f'<section id="section-{market}">\n'
        f"<h2>당일주도주 — {market}</h2>\n"
        f'<p class="meta">{data_date} 기준 &nbsp;|&nbsp; {generated_at} 생성</p>\n'
        f"<table>\n"
        f"<thead><tr>"
        f"<th>순위</th><th>종목명</th><th>코드</th><th>등락률</th>"
        f"<th>거래량순위</th><th>상승률순위</th><th>A점수</th><th>연속</th><th>종가매매</th>"
        f"</tr></thead>\n"
        f"<tbody>{''.join(rows)}</tbody>\n"
        f"</table>\n"
        f"{streak_html_block}\n"
        f"{candidate_html_block}\n"
        f"</section>\n"
        f"<!-- /SECTION:{market} -->"
    )
    return section


def append_to_daily_report(market: str, data: list[dict]) -> str:
    """quantReports/YYYY-MM-DD.html 에 마켓 섹션을 추가(이미 있으면 교체)한다.

    반환: 저장된 파일 경로.
    """
    path = _report_path()
    generated_at = datetime.now().strftime("%H:%M")
    new_section = generate_market_section(market, data, generated_at)

    begin_marker = f"<!-- SECTION:{market} -->"
    end_marker = f"<!-- /SECTION:{market} -->"
    today_str = datetime.today().strftime("%Y-%m-%d")

    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()

        if begin_marker in content and end_marker in content:
            # 기존 섹션 교체
            start = content.index(begin_marker)
            end = content.index(end_marker) + len(end_marker)
            content = content[:start] + new_section + content[end:]
        else:
            # </body> 직전에 삽입, 없으면 끝에 추가
            if "</body>" in content:
                content = content.replace("</body>", f"\n{new_section}\n</body>")
            else:
                content = content.rstrip() + f"\n\n{new_section}\n"
    else:
        content = (
            f"<!DOCTYPE html>\n<html lang='ko'>\n<head>\n"
            f"<meta charset='utf-8'>\n"
            f"<title>Daily Report — {today_str}</title>\n"
            f"<style>{_CSS}</style>\n"
            f"</head>\n<body>\n"
            f"<h1>Daily Report — {today_str}</h1>\n\n"
            f"{new_section}\n"
            f"</body>\n</html>\n"
        )

    with open(path, "w", encoding="utf-8") as f:
        f.write(content)

    return path


# ---------------------------------------------------------------------------
# 시장 지수 개요 섹션
# ---------------------------------------------------------------------------

_INDEX_CODES = [
    ("KS11",  "KOSPI",  "KRW"),
    ("KQ11",  "KOSDAQ", "KRW"),
    ("US500", "S&P500", "USD"),
    ("IXIC",  "NASDAQ", "USD"),
]


def _fetch_index(args: tuple) -> tuple:
    """(code, label, ccy) → (label, data_dict | None)"""
    code, label, ccy = args
    try:
        import FinanceDataReader as fdr
        end   = datetime.today()
        start = end - timedelta(days=10)
        df = fdr.DataReader(code, start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d"))
        df = df[df["Close"] > 0].dropna(subset=["Close"])
        if len(df) < 2:
            return label, None
        close_now  = float(df["Close"].iloc[-1])
        close_prev = float(df["Close"].iloc[-2])
        chg_pct    = (close_now - close_prev) / close_prev * 100
        chg_abs    = close_now - close_prev
        return label, {"value": close_now, "chg_pct": chg_pct,
                       "chg_abs": chg_abs, "currency": ccy}
    except Exception:
        return label, None


def _fetch_usdkrw() -> "dict | None":
    try:
        import FinanceDataReader as fdr
        end   = datetime.today()
        start = end - timedelta(days=10)
        df = fdr.DataReader("USD/KRW", start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d"))
        df = df[df["Close"] > 0].dropna(subset=["Close"])
        if len(df) < 2:
            return None
        close_now  = float(df["Close"].iloc[-1])
        close_prev = float(df["Close"].iloc[-2])
        return {"value": close_now, "chg_abs": close_now - close_prev,
                "chg_pct": (close_now - close_prev) / close_prev * 100}
    except Exception:
        return None


def _fmt_index_value(v: float, ccy: str) -> str:
    if ccy == "USD" and v >= 1000:
        return f"{v:,.2f}"
    if ccy == "KRW" and v >= 100:
        return f"{v:,.2f}"
    return f"{v:.2f}"


def generate_market_overview_section(generated_at: str | None = None) -> str:
    """KOSPI/KOSDAQ/S&P500/NASDAQ/환율 개요 HTML 섹션."""
    if generated_at is None:
        generated_at = datetime.now().strftime("%H:%M")

    with ThreadPoolExecutor(max_workers=5) as ex:
        fx_fut       = ex.submit(_fetch_usdkrw)
        index_result = dict(ex.map(_fetch_index, _INDEX_CODES))
        fx_data      = fx_fut.result()

    cards = []
    for _, label, ccy in _INDEX_CODES:
        d = index_result.get(label)
        if d:
            val_str = _fmt_index_value(d["value"], ccy)
            chg_cls = "up" if d["chg_pct"] >= 0 else "dn"
            chg_str = f"{d['chg_pct']:+.2f}%"
        else:
            val_str = "-"
            chg_cls = "pnl-na"
            chg_str = "-"
        cards.append(
            f'<div class="overview-card">'
            f'<div class="label">{label}</div>'
            f'<div class="value">{val_str}</div>'
            f'<div class="chg {chg_cls}">{chg_str}</div>'
            f'</div>'
        )

    if fx_data:
        chg_cls = "up" if fx_data["chg_abs"] >= 0 else "dn"
        chg_str = f"{fx_data['chg_abs']:+.2f}원"
        cards.append(
            f'<div class="overview-card">'
            f'<div class="label">USD/KRW</div>'
            f'<div class="value">{fx_data["value"]:,.2f}</div>'
            f'<div class="chg {chg_cls}">{chg_str}</div>'
            f'</div>'
        )

    return (
        f'<!-- SECTION:market_overview -->\n'
        f'<section id="section-market_overview">\n'
        f'<h2>시장 지수 개요</h2>\n'
        f'<p class="meta">{generated_at} 기준</p>\n'
        f'<div class="overview-grid">{"".join(cards)}</div>\n'
        f'</section>\n'
        f'<!-- /SECTION:market_overview -->'
    )


# ---------------------------------------------------------------------------
# 섹터 모멘텀 섹션
# ---------------------------------------------------------------------------

def generate_sector_section(
    region: str = "KR",
    top_n: int = 10,
    generated_at: str | None = None,
) -> str:
    """KR 또는 US 섹터 모멘텀 HTML 섹션 (1M 기준 상위 top_n)."""
    if generated_at is None:
        generated_at = datetime.now().strftime("%H:%M")

    try:
        from utils.sector_scanner import fetch_sector_momentum
        data = fetch_sector_momentum(region)
    except Exception as e:
        return f'<section><h2>섹터 모멘텀 ({region})</h2><p>데이터 없음: {e}</p></section>'

    rows_html = []
    for row in data[:top_n]:
        def _cell(key: str) -> str:
            s = row.get(f"ret_{key}_str", "-")
            pos = row.get(f"ret_{key}_positive", False)
            cls = "up" if pos else "dn"
            return f'<td class="{cls}">{s}</td>'

        rows_html.append(
            f"<tr>"
            f"<td>{row.get('rank', '')}</td>"
            f"<td><strong>{row.get('sector', row.get('name', ''))}</strong></td>"
            f"<td>{row.get('code', '')}</td>"
            f"{_cell('5d')}{_cell('1m')}{_cell('3m')}{_cell('6m')}{_cell('12m')}"
            f"</tr>"
        )

    title = "국내 섹터 모멘텀 (KODEX ETF)" if region == "KR" else "미국 섹터 모멘텀 (SPDR ETF)"
    section_key = f"sector_{region}"

    return (
        f'<!-- SECTION:{section_key} -->\n'
        f'<section id="section-{section_key}">\n'
        f'<h2>{title}</h2>\n'
        f'<p class="meta">{generated_at} 기준 · 1M 기준 내림차순</p>\n'
        f'<table>\n'
        f'<thead><tr>'
        f'<th>#</th><th>섹터</th><th>코드</th>'
        f'<th>5일</th><th>1M</th><th>3M</th><th>6M</th><th>12M</th>'
        f'</tr></thead>\n'
        f'<tbody>{"".join(rows_html)}</tbody>\n'
        f'</table>\n'
        f'</section>\n'
        f'<!-- /SECTION:{section_key} -->'
    )


# ---------------------------------------------------------------------------
# 포트폴리오 손익 섹션
# ---------------------------------------------------------------------------

def _fetch_current_price(args: tuple) -> tuple:
    """(symbol, is_us) → (symbol, price | None)"""
    symbol, is_us = args
    try:
        import FinanceDataReader as fdr
        end   = datetime.today()
        start = end - timedelta(days=7)
        df = fdr.DataReader(symbol, start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d"))
        df = df[df["Close"] > 0].dropna(subset=["Close"])
        if df.empty:
            return symbol, None
        return symbol, float(df["Close"].iloc[-1])
    except Exception:
        return symbol, None


def generate_portfolio_section(generated_at: str | None = None) -> str:
    """보유종목 현재가 기준 손익 HTML 섹션."""
    if generated_at is None:
        generated_at = datetime.now().strftime("%H:%M")

    try:
        from utils.scan_db import load_holdings
        holdings = load_holdings()
    except Exception as e:
        return f'<section><h2>포트폴리오 손익</h2><p>DB 로드 오류: {e}</p></section>'

    if not holdings:
        return (
            f'<!-- SECTION:portfolio -->\n'
            f'<section id="section-portfolio"><h2>포트폴리오 손익</h2>'
            f'<p class="meta">보유 종목 없음</p></section>\n'
            f'<!-- /SECTION:portfolio -->'
        )

    unique_symbols = list({
        h["symbol"]: (h["symbol"], h.get("currency", "KRW") == "USD")
        for h in holdings
    }.values())

    with ThreadPoolExecutor(max_workers=10) as ex:
        price_map = dict(ex.map(_fetch_current_price, unique_symbols))

    total_invest   = 0.0
    total_pnl      = 0.0
    has_any_buy    = False
    rows_html      = []

    for h in holdings:
        symbol      = h["symbol"]
        buy_price   = h.get("buy_price", 0.0) or 0.0
        quantity    = h.get("quantity", 0.0) or 0.0
        cur_price   = price_map.get(symbol)
        has_buy     = buy_price > 0 and quantity > 0
        is_us       = h.get("currency", "KRW") == "USD"

        cur_str  = f"{cur_price:,.0f}" if cur_price and not is_us else (f"{cur_price:.2f}" if cur_price else "-")
        buy_str  = f"{buy_price:,.0f}" if buy_price and not is_us else (f"{buy_price:.2f}" if buy_price else "-")

        if has_buy and cur_price:
            invest  = buy_price * quantity
            pnl     = (cur_price - buy_price) * quantity
            pct     = (cur_price - buy_price) / buy_price * 100
            invest_str = f"{invest:,.0f}"
            pnl_str    = f"{pnl:+,.0f}"
            pct_str    = f"{pct:+.2f}%"
            pnl_cls    = "pnl-pos" if pnl >= 0 else "pnl-neg"
            total_invest += invest
            total_pnl    += pnl
            has_any_buy   = True
        else:
            invest_str = "-"
            pnl_str    = "-"
            pct_str    = "-"
            pnl_cls    = "pnl-na"

        rows_html.append(
            f"<tr>"
            f"<td><strong>{h.get('name','')}</strong></td>"
            f"<td>{symbol}</td>"
            f"<td>{buy_str}</td>"
            f"<td>{cur_str}</td>"
            f"<td>{quantity if quantity else '-'}</td>"
            f"<td>{invest_str}</td>"
            f'<td class="{pnl_cls}">{pnl_str}</td>'
            f'<td class="{pnl_cls}">{pct_str}</td>'
            f"<td>{h.get('memo','')}</td>"
            f"</tr>"
        )

    summary_html = ""
    if has_any_buy:
        total_pct = total_pnl / total_invest * 100 if total_invest > 0 else 0
        pnl_cls   = "pnl-pos" if total_pnl >= 0 else "pnl-neg"
        summary_html = (
            f'<div class="highlight-box">'
            f'총 투자금 <strong>{total_invest:,.0f}</strong> &nbsp;|&nbsp; '
            f'예상 손익 <strong class="{pnl_cls}">{total_pnl:+,.0f}</strong> &nbsp;|&nbsp; '
            f'손익률 <strong class="{pnl_cls}">{total_pct:+.2f}%</strong>'
            f'</div>'
        )

    return (
        f'<!-- SECTION:portfolio -->\n'
        f'<section id="section-portfolio">\n'
        f'<h2>포트폴리오 손익</h2>\n'
        f'<p class="meta">{generated_at} 현재가 기준</p>\n'
        f'{summary_html}\n'
        f'<table>\n'
        f'<thead><tr>'
        f'<th>종목명</th><th>코드</th><th>매수가</th><th>현재가</th>'
        f'<th>수량</th><th>투자금</th><th>손익</th><th>손익률</th><th>메모</th>'
        f'</tr></thead>\n'
        f'<tbody>{"".join(rows_html)}</tbody>\n'
        f'</table>\n'
        f'</section>\n'
        f'<!-- /SECTION:portfolio -->'
    )


# ---------------------------------------------------------------------------
# 전체 일별 리포트 생성
# ---------------------------------------------------------------------------

def generate_full_daily_report() -> str:
    """시장개요 + 당일주도주(KR) + 섹터모멘텀 + 포트폴리오를 한 파일에 생성.

    기존 파일이 있으면 덮어쓴다.
    반환: 저장된 파일 경로.
    """
    today_str    = datetime.today().strftime("%Y-%m-%d")
    generated_at = datetime.now().strftime("%H:%M")
    path         = _report_path()

    from utils.data_loader import (
        load_leaders_cache,
        fetch_leaders_combined,
        save_leaders_cache,
        compute_consecutive_days,
    )

    sections: list[str] = []

    # 1. 시장 지수 개요
    sections.append(generate_market_overview_section(generated_at))

    # 2. 당일주도주 (KOSPI / KOSDAQ)
    for market in ("KOSPI", "KOSDAQ"):
        data = load_leaders_cache(market)
        if data is None:
            try:
                data = fetch_leaders_combined(market, top_n=30)
                save_leaders_cache(market, data)
                data = compute_consecutive_days(market, data)
            except Exception:
                data = []
        sections.append(generate_market_section(market, data, generated_at))

    # 3. 섹터 모멘텀 (KR + US)
    sections.append(generate_sector_section("KR", 10, generated_at))
    sections.append(generate_sector_section("US", 10, generated_at))

    # 4. 포트폴리오 손익
    sections.append(generate_portfolio_section(generated_at))

    content = (
        f"<!DOCTYPE html>\n<html lang='ko'>\n<head>\n"
        f"<meta charset='utf-8'>\n"
        f"<title>Daily Report — {today_str}</title>\n"
        f"<style>{_CSS}</style>\n"
        f"</head>\n<body>\n"
        f"<h1>Daily Report — {today_str}</h1>\n\n"
        + "\n\n".join(sections)
        + "\n</body>\n</html>\n"
    )

    with open(path, "w", encoding="utf-8") as f:
        f.write(content)

    return path
