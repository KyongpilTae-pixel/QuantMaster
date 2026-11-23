"""
C-axis event letter generator — macro/sector/rate event commentary.

Issued on-demand when a significant market event occurs.
Color scheme: teal.
"""
from __future__ import annotations

import os
from datetime import datetime

_REPORTS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "letterService")
os.makedirs(_REPORTS_DIR, exist_ok=True)

_CSS = """
:root {
  --bg:       #F0FDFA;
  --bg2:      #CCFBF1;
  --surface:  #FFFFFF;
  --border:   #99F6E4;
  --teal:     #0F766E;
  --teal-lt:  #14B8A6;
  --teal-dk:  #134E4A;
  --text:     #0F172A;
  --text-sub: #64748B;
  --up:       #15803D;
  --dn:       #B91C1C;
  --neu-bg:   #F5F5F4;
  --neu-cl:   #78716C;
  --tag-bg:   #CCFBF1;
  --tag-cl:   #0F766E;
}
@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) {
    --bg:#0D1F1E;--bg2:#134E4A;--surface:#1A2E2D;--border:#0F766E;
    --teal:#2DD4BF;--teal-lt:#5EEAD4;--teal-dk:#CCFBF1;
    --text:#F0FDFA;--text-sub:#94A3B8;--up:#34D399;--dn:#F87171;
    --neu-bg:#1A2E2D;--neu-cl:#94A3B8;--tag-bg:#134E4A;--tag-cl:#2DD4BF;
  }
}
:root[data-theme="dark"] {
  --bg:#0D1F1E;--bg2:#134E4A;--surface:#1A2E2D;--border:#0F766E;
  --teal:#2DD4BF;--teal-lt:#5EEAD4;--teal-dk:#CCFBF1;
  --text:#F0FDFA;--text-sub:#94A3B8;--up:#34D399;--dn:#F87171;
  --neu-bg:#1A2E2D;--neu-cl:#94A3B8;--tag-bg:#134E4A;--tag-cl:#2DD4BF;
}
:root[data-theme="light"] {
  --bg:#F0FDFA;--bg2:#CCFBF1;--surface:#FFFFFF;--border:#99F6E4;
  --teal:#0F766E;--teal-lt:#14B8A6;--teal-dk:#134E4A;
  --text:#0F172A;--text-sub:#64748B;--up:#15803D;--dn:#B91C1C;
  --neu-bg:#F5F5F4;--neu-cl:#78716C;--tag-bg:#CCFBF1;--tag-cl:#0F766E;
}
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
body{
  font-family:'IBM Plex Sans KR','Noto Sans KR',sans-serif;
  background:var(--bg);color:var(--text);
  max-width:720px;margin:0 auto;padding:24px 16px 48px;
  font-size:15px;line-height:1.75;
}
.letter-header{
  border-top:4px solid var(--teal);
  background:var(--bg2);
  padding:20px 24px;border-radius:0 0 8px 8px;margin-bottom:28px;
}
.letter-header .series{
  font-size:11px;font-weight:700;letter-spacing:.12em;
  text-transform:uppercase;color:var(--teal);margin-bottom:4px;
}
.letter-header h1{font-size:1.35rem;font-weight:700;color:var(--text);margin-bottom:6px;line-height:1.3}
.letter-header .meta{font-size:12px;color:var(--text-sub)}
.tags{display:flex;flex-wrap:wrap;gap:6px;margin-top:10px}
.tag{
  background:var(--tag-bg);color:var(--tag-cl);
  font-size:11px;font-weight:700;padding:2px 8px;border-radius:12px;
}
h2{
  font-size:1rem;font-weight:700;color:var(--teal-dk);
  border-left:3px solid var(--teal);padding-left:10px;
  margin:28px 0 10px;
}
p{margin-bottom:12px;color:var(--text)}
ul,ol{padding-left:20px;margin-bottom:12px}
li{margin-bottom:6px}
.highlight{
  background:var(--bg2);border-left:3px solid var(--teal);
  padding:12px 16px;border-radius:0 6px 6px 0;margin:16px 0;
  font-size:14px;
}
.highlight strong{color:var(--teal-dk)}
table{width:100%;border-collapse:collapse;margin:12px 0;font-size:13px}
th{background:var(--bg2);color:var(--text-sub);font-weight:600;
   padding:8px 10px;text-align:left;font-size:11px;letter-spacing:.04em;
   border-bottom:2px solid var(--border)}
td{padding:9px 10px;border-bottom:1px solid var(--border)}
tr:last-child td{border-bottom:none}
.up{color:var(--up);font-weight:600}
.dn{color:var(--dn);font-weight:600}
.disclaimer{
  margin-top:40px;padding:12px 14px;border-radius:6px;
  background:var(--neu-bg);font-size:11px;color:var(--text-sub);line-height:1.5;
}
"""


def generate_c_event_letter(
    title: str,
    event_date: str,
    sections: list[tuple[str, str]],
    tags: list[str] | None = None,
    highlight: str | None = None,
    tables: dict[str, list[dict]] | None = None,
) -> str:
    """
    Generate HTML for C-axis event letter.

    title:       Letter headline
    event_date:  'YYYY-MM-DD'
    sections:    List of (heading, body_html) tuples; body_html may contain <p>, <ul>, etc.
    tags:        Topic tags e.g. ['금리', 'EWY', '게이트']
    highlight:   Optional callout box HTML (key insight)
    tables:      Optional dict of {section_heading: [row_dict, ...]}
                 Rendered after the matching section.
    """
    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M")
    tags_html = ""
    if tags:
        tags_html = '<div class="tags">' + "".join(f'<span class="tag">{t}</span>' for t in tags) + "</div>"

    highlight_html = f'<div class="highlight">{highlight}</div>' if highlight else ""

    sections_html = ""
    for heading, body in sections:
        tbl_html = ""
        if tables and heading in tables:
            rows = tables[heading]
            if rows:
                headers = list(rows[0].keys())
                tbl_html = (
                    '<div style="overflow-x:auto"><table>'
                    '<thead><tr>' + "".join(f"<th>{h}</th>" for h in headers) + "</tr></thead>"
                    "<tbody>"
                    + "".join(
                        "<tr>" + "".join(f"<td>{r.get(h,'')}</td>" for h in headers) + "</tr>"
                        for r in rows
                    )
                    + "</tbody></table></div>"
                )
        sections_html += f"<h2>{heading}</h2>\n{body}\n{tbl_html}\n"

    return f"""<!DOCTYPE html>
<html lang='ko'>
<head>
<meta charset='utf-8'>
<meta name='viewport' content='width=device-width,initial-scale=1'>
<title>QuantLetter C — {title}</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Sans+KR:wght@400;600;700&display=swap" rel="stylesheet">
<style>{_CSS}</style>
</head>
<body>

<div class="letter-header">
  <div class="series">QuantLetter · C축 매크로 해설</div>
  <h1>{title}</h1>
  <div class="meta">이벤트일: {event_date} &nbsp;|&nbsp; 발행: {generated_at}</div>
  {tags_html}
</div>

{highlight_html}

{sections_html}

<div class="disclaimer">
  과거 데이터 기반 모의결과이며 미래 수익을 보장하지 않습니다.
  본 레터는 투자자문이 아닙니다. QuantMaster Pro — 내부 검토용
</div>

</body>
</html>
"""


def save_c_event_letter(
    slug: str,
    title: str,
    event_date: str,
    sections: list[tuple[str, str]],
    tags: list[str] | None = None,
    highlight: str | None = None,
    tables: dict[str, list[dict]] | None = None,
) -> str:
    """
    Save C-axis letter. slug is used for filename: letterService/YYYY-MM-DD_C_{slug}.html
    """
    html  = generate_c_event_letter(title, event_date, sections, tags, highlight, tables)
    fname = f"{event_date}_C_{slug}.html"
    path  = os.path.join(_REPORTS_DIR, fname)
    with open(path, "w", encoding="utf-8") as f:
        f.write(html)
    return path
