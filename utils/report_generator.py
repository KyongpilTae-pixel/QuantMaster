"""
일별 HTML 리포트 자동 생성.

quantReports/YYYY-MM-DD.html 에 당일주도주 요약을 추가(append)한다.
이미 파일이 있으면 해당 마켓 섹션만 교체하고, 없으면 새로 생성한다.
"""

import os
from datetime import datetime

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
