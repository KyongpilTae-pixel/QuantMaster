"""
일별 마크다운 리포트 자동 생성.

reports/YYYY-MM-DD.md 에 당일주도주 요약을 추가(append)한다.
이미 파일이 있으면 해당 마켓 섹션만 교체하고, 없으면 새로 생성한다.
"""

import os
from datetime import datetime

_REPORTS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "reports")


def _report_path(date: datetime | None = None) -> str:
    d = date or datetime.today()
    os.makedirs(_REPORTS_DIR, exist_ok=True)
    return os.path.join(_REPORTS_DIR, d.strftime("%Y-%m-%d") + ".md")


def _streak_label(days: int) -> str:
    if days >= 3:
        return f"{days}일 🔥"
    if days >= 2:
        return f"{days}일 ⚡"
    return "-"


def _close_buy_candidate(item: dict) -> bool:
    return (
        item.get("change_pct_val", 0) >= 5.0
        and item.get("is_near_high", False)
        and item.get("has_vol_rank", False)
        and item.get("has_rise_rank", False)
    )


def generate_market_section(market: str, data: list[dict], generated_at: str) -> str:
    """마켓 하나의 마크다운 섹션 문자열 반환."""
    data_date = data[0].get("data_date", datetime.today().strftime("%Y-%m-%d")) if data else "-"
    lines = [
        f"## 당일주도주 — {market} ({data_date} 기준, {generated_at} 생성)",
        "",
        "| 순위 | 종목명 | 코드 | 등락률 | 거래량순위 | 상승률순위 | A점수 | 연속 | 종가매매 |",
        "|------|--------|------|--------|-----------|-----------|-------|------|---------|",
    ]
    for item in data[:20]:
        streak = _streak_label(item.get("consecutive_days", 1))
        close = "✅" if _close_buy_candidate(item) else ""
        lines.append(
            f"| {item.get('rank', '')} "
            f"| {item.get('name', '')} "
            f"| {item.get('code', '')} "
            f"| {item.get('change_pct_str', '')} "
            f"| {item.get('vol_rank_str', '-')} "
            f"| {item.get('rise_rank_str', '-')} "
            f"| {item.get('score_a_str', '')} "
            f"| {streak} "
            f"| {close} |"
        )

    # 연속 하이라이트
    streaks = [item for item in data if item.get("consecutive_days", 1) >= 2]
    if streaks:
        lines += ["", "### 연속 등장 하이라이트", ""]
        for item in sorted(streaks, key=lambda x: -x.get("consecutive_days", 1)):
            lines.append(
                f"- **{item['name']}** ({item['code']}): "
                f"{_streak_label(item['consecutive_days'])} 연속  "
                f"등락률 {item.get('change_pct_str', '')}  "
                f"A점수 {item.get('score_a_str', '')}"
            )

    # 종가매매 후보
    close_buys = [item for item in data if _close_buy_candidate(item)]
    if close_buys:
        lines += ["", "### 종가매매 후보", ""]
        for item in close_buys:
            lines.append(
                f"- **{item['name']}** ({item['code']})  "
                f"등락률 {item.get('change_pct_str', '')}  "
                f"A점수 {item.get('score_a_str', '')}"
            )

    lines.append("")
    return "\n".join(lines)


def append_to_daily_report(market: str, data: list[dict]) -> str:
    """reports/YYYY-MM-DD.md 에 마켓 섹션을 추가(이미 있으면 교체)한다.

    반환: 저장된 파일 경로.
    """
    path = _report_path()
    generated_at = datetime.now().strftime("%H:%M")
    new_section = generate_market_section(market, data, generated_at)
    section_header = f"## 당일주도주 — {market}"

    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
        # 기존 마켓 섹션 교체
        if section_header in content:
            parts = content.split(section_header)
            # parts[0] = 섹션 이전, parts[1] = 섹션 내용
            # 다음 ## 섹션 이전까지 제거
            after = parts[1]
            next_section = after.find("\n## ", 1)
            if next_section != -1:
                after = after[next_section:]
            else:
                after = ""
            content = parts[0].rstrip() + "\n\n" + new_section + after
        else:
            content = content.rstrip() + "\n\n" + new_section
    else:
        today_str = datetime.today().strftime("%Y-%m-%d")
        content = f"# Daily Report — {today_str}\n\n" + new_section

    with open(path, "w", encoding="utf-8") as f:
        f.write(content)

    return path
