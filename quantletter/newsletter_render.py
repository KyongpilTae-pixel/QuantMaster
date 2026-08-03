# -*- coding: utf-8 -*-
"""뉴스레터 HTML 렌더 모듈 (주간/월간).

함수
  weekly_html(brand, asof, data, top_n, market, lookback_m, positions=None)
  monthly_html(brand, w, s, sc, sponsor=None)
"""

# ── 공통 CSS ──────────────────────────────────────────────────
CSS = """<style>
@import url('https://fonts.googleapis.com/css2?family=Noto+Sans+KR:wght@400;700;800&display=swap');
body{margin:0;background:#eef1f5;font-family:'Noto Sans KR','Apple SD Gothic Neo','Malgun Gothic',system-ui,sans-serif;color:#1c2430;line-height:1.65}
.mail{max-width:600px;margin:0 auto;background:#fff}
.hd{background:linear-gradient(135deg,#1b3a6b,#2b6fb3);color:#fff;padding:26px 28px}
.hd .brand{font-weight:800;font-size:20px}
.hd .tag{opacity:.9;font-size:13px;margin-top:2px}
.hd .issue{margin-top:10px;font-size:12.5px;opacity:.85}
.bd{padding:24px 28px}
h2{font-size:17px;margin:22px 0 10px;color:#12233b;border-left:4px solid #2b6fb3;padding-left:10px}
h2:first-child{margin-top:4px}
p{font-size:14.5px;margin:10px 0}
.lead{font-size:14.5px;color:#33475b;background:#f4f7fb;border-radius:10px;padding:13px 15px}
.pick{border:1px solid #e2e8f0;border-radius:12px;padding:14px 16px;margin:10px 0}
.pick .top{display:flex;justify-content:space-between;align-items:baseline}
.pick .tk{font-weight:800;font-size:16px;color:#12233b}
.pick .sc{font-size:12px;color:#fff;background:#2b6fb3;border-radius:20px;padding:2px 10px}
.pick .m{font-size:12.5px;color:#5a6b7e;margin-top:6px}
.pick .m b{color:#1c2430}
.pick .why{font-size:13px;color:#33475b;margin-top:7px}
table{width:100%;border-collapse:collapse;margin:12px 0;font-size:13.5px}
th,td{padding:9px 8px;border-bottom:1px solid #e6ebf1;text-align:right}
th:first-child,td:first-child{text-align:left}
th{background:#f4f7fb;color:#5a6b7e;font-size:12px;font-weight:700}
td:first-child{font-weight:700;color:#12233b}
.up{color:#c0392b}
.dn{color:#1e7e46}
.beat{color:#1b6fb3;font-weight:700}
.alloc{display:flex;gap:8px;margin:12px 0;flex-wrap:wrap}
.alloc .a{flex:1;min-width:100px;border:1px solid #e2e8f0;border-radius:12px;padding:12px;text-align:center}
.alloc .a .n{font-size:12px;color:#5a6b7e}
.alloc .a .v{font-size:22px;font-weight:800;color:#12233b}
.bar{height:14px;border-radius:7px;overflow:hidden;display:flex;margin:8px 0 2px}
.box{background:#f4f7fb;border-radius:10px;padding:13px 15px;font-size:13.5px;color:#33475b;margin:12px 0}
.kpi{display:flex;gap:10px;margin:10px 0}
.kpi .k{flex:1;background:#f4f7fb;border-radius:10px;padding:12px;text-align:center}
.kpi .k .n{font-size:11.5px;color:#5a6b7e}
.kpi .k .v{font-size:20px;font-weight:800}
.sell-badge{color:#fff;background:#c0392b;border-radius:20px;padding:2px 9px;font-size:11px;font-weight:800}
.hold-badge{color:#1e7e46;background:#eaf6ee;border-radius:20px;padding:2px 9px;font-size:11px;font-weight:800}
.ft{background:#f4f7fb;padding:18px 28px;font-size:11px;color:#8090a0;line-height:1.6}
.disc{border-top:1px solid #e0e6ee;margin-top:8px;padding-top:10px}
</style>"""

# ── 공통 면책 고지 ────────────────────────────────────────────
DISC = (
    '<div class="ft">'
    "<div>{brand} · 유사투자자문업자(신고 예정) · no-reply@quantletter.example</div>"
    '<div class="disc">본 콘텐츠는 불특정 다수를 위한 정보 제공이며 개별 투자자문이 아닙니다(1:1 상담 불가). '
    "원금손실 가능성이 있으며 과거 성과는 미래 수익을 보장하지 않습니다. · 수신거부</div>"
    "</div>"
)

# ── 자산군별 ETF 예시 상품 ─────────────────────────────────────
PRODUCTS = {
    "한국주식": [("KODEX 200", "069500"), ("TIGER 200", "102110")],
    "미국주식": [("TIGER 미국S&P500", "360750"), ("KODEX 미국S&P500", "379800")],
    "미국채권": [("TIGER 미국채10년선물", "305080"), ("KODEX 미국10년국채선물", "308620")],
    "금":       [("ACE KRX금현물", "411060"), ("KODEX 골드선물(H)", "132030")],
    "현금":     [("예수금·CMA·단기채 등", "-")],
}

COLORS = {
    "한국주식": "#2b6fb3",
    "미국주식": "#3da35d",
    "금":       "#e0a020",
    "미국채권": "#8a6fc0",
    "현금":     "#9aa7b5",
}

ORDER = ["한국주식", "미국주식", "금", "미국채권", "현금"]


# ── 보유 종목 매도 신호 섹션 ──────────────────────────────────

def positions_section(rows):
    if not rows:
        return ""
    tr = ""
    for r in rows:
        if r["signal"]:
            badge  = '<span class="sell-badge">⚠ 매도 신호</span>'
            reason = f'<div style="font-size:11.5px;color:#c0392b;margin-top:3px">사유: {r["reason"]}</div>'
        else:
            badge  = '<span class="hold-badge">보유 유지</span>'
            reason = ""
        rc = "up" if r["ret"] > 0 else "dn"
        tr += (
            f"<tr><td>{r['ticker']}"
            f'<div style="font-size:11px;color:#8090a0;font-weight:400">{r["entry_date"]} 편입</div></td>'
            f"<td>{r['entry']:,.0f}</td>"
            f"<td>{r['cur']:,.0f}</td>"
            f'<td class="{rc}">{r["ret"]:+.1f}%</td>'
            f"<td>{r['stop']:,.0f}</td>"
            f"<td>{badge}{reason}</td></tr>"
        )
    return (
        "<h2>🎯 보유 종목 관리 · 매도 신호</h2>"
        "<p>추천으로 끝나지 않습니다. 편입한 종목을 <b>보유 포지션처럼 계속 관리</b>하고,"
        " 팔 시점을 규칙으로 알려드립니다."
        " 매도 규칙: <b>종가가 100일선을 하회</b>하거나 <b>추천가 대비 -15% 손절가</b>에 닿으면 매도 신호.</p>"
        "<table><tr><th>종목</th><th>추천가</th><th>현재가</th>"
        f"<th>수익률</th><th>손절가</th><th>상태</th></tr>{tr}</table>"
        '<div class="box"><b>왜 매도 규칙인가.</b> 백테스트에서 이 추세이탈 매도 규율은'
        " <b>최대 낙폭을 -19% → -15%로 낮췄습니다.</b>"
        " 사는 것보다 파는 게 어렵기에, 감정이 아닌 규칙으로 정리합니다.</div>"
    )


# ── 주간 뉴스레터 ─────────────────────────────────────────────

def weekly_html(brand, asof, data, top_n, market, lookback_m, positions=None):
    picks = data["picks"]
    mk    = "미국주식" if market == "US" else "한국주식"
    body  = ""
    for i, p in enumerate(picks):
        body += (
            f'<div class="pick">'
            f'<div class="top">'
            f'<span class="tk">{i+1}. {p["ticker"]}</span>'
            f'<span class="sc">모멘텀 상위</span>'
            f"</div>"
            f'<div class="m">6개월 <b>{p["m6"]:+.1f}%</b>'
            f' · 3개월 <b>{p["m3"]:+.1f}%</b>'
            f' · 12개월 <b>{p["m12"]:+.1f}%</b>'
            f' · 변동성 {p["vol"]:.0f}%</div>'
            f'<div class="why">{lookback_m}개월 추세가 확인된 종목입니다.'
            " 단기 급등 추격이 아니라 중기(월 단위) 보유 대상으로 분류합니다.</div>"
            "</div>"
        )

    pos_html = positions_section(positions) if positions else ""

    return f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{brand} WEEKLY</title>
{CSS}
</head>
<body>
<div class="mail">
  <div class="hd">
    <div class="brand">{brand} <span style="font-weight:600">WEEKLY</span></div>
    <div class="tag">알고리즘이 고른 이번 주 주목 종목</div>
    <div class="issue">기준일 {data['asof']} · {mk} 편 · 매주 발송</div>
  </div>
  <div class="bd">
    <p class="lead">이번 주 시그널이 꼽은 <b>모멘텀 상위 {top_n}종목</b>입니다.
    검증된 {lookback_m}개월 추세로 선정하며 <b>보유는 월 단위(중기)</b>로 봅니다.</p>
    <h2>📊 이번 주 주목 종목</h2>
    {body}
    {pos_html}
    <div class="box"><b>읽는 법.</b> 자동 시그널로 선정된 리스트입니다.
    개별 종목 비중·매수 시점은 본인 판단으로 결정하세요.
    매월 첫 주 월간호에서 지난 추천의 성적표를 공개합니다.</div>
  </div>
  {DISC.format(brand=brand)}
</div>
</body>
</html>"""


# ── ETF 상품 표 ───────────────────────────────────────────────

def products_table(w, order, colors):
    rows = ""
    for a in order:
        if w.get(a, 0) <= 0:
            continue
        prods = PRODUCTS.get(a, [])
        main  = prods[0] if prods else ("-", "-")
        alt   = (
            f' <span style="color:#8090a0">· 대안 {prods[1][0]}({prods[1][1]})</span>'
            if len(prods) > 1 else ""
        )
        rows += (
            f"<tr><td><span style=\"color:{colors[a]}\">●</span> {a}</td>"
            f"<td>{w[a]*100:.0f}%</td>"
            f"<td>{main[0]} <b>{main[1]}</b>{alt}</td></tr>"
        )
    return (
        '<h2 style="margin-top:20px">💡 이렇게 담으세요 — 실제 상품(ETF)</h2>'
        '<p style="font-size:13.5px;color:#33475b">위 비중을 국내 상장 ETF로 그대로 구현하는 예시입니다.'
        " 증권 계좌에서 종목코드로 매수하면 됩니다.</p>"
        "<table>"
        "<tr><th>자산</th><th>비중</th><th>추천 상품(예시) · 종목코드</th></tr>"
        f"{rows}</table>"
        '<div class="box" style="font-size:12.5px">※ 특정 운용사와 무관한 <b>예시 상품</b>이며'
        " 특정 상품 매수를 권유하지 않습니다."
        " 보수·유형(현물/선물·환헤지 여부)이 다르니 확인 후 선택하세요.</div>"
    )


# ── 스폰서 광고 블록 ──────────────────────────────────────────

def sponsor_block(sp):
    """유료 광고 슬롯. sp가 None이면 자동 숨김. 중립 추천과 완전 분리·라벨링."""
    if not sp:
        return ""
    return (
        '<div style="margin-top:24px;border:1.5px dashed #c9a94a;border-radius:12px;'
        'padding:16px 18px;background:#fffdf5">'
        '<div style="font-size:11px;font-weight:800;color:#a97f10;letter-spacing:.06em">'
        "AD · 광고 (유료 노출)</div>"
        f'<div style="font-weight:800;font-size:15.5px;color:#12233b;margin-top:5px">'
        f'{sp["name"]} <span style="color:#8090a0;font-weight:600;font-size:13px">{sp.get("code","")}</span></div>'
        f'<div style="font-size:13.5px;color:#33475b;margin-top:5px">{sp.get("tagline","")}</div>'
        '<div style="font-size:11px;color:#8090a0;margin-top:10px;line-height:1.5">'
        "본 영역은 광고주가 비용을 지불한 <b>유료 광고</b>이며,"
        " 퀀트레터의 알고리즘 자산배분 추천과 무관합니다."
        " 특정 상품 매수 권유가 아니고 투자 판단·책임은 본인에게 있으며, 원금손실 위험이 있습니다.</div>"
        "</div>"
    )


# ── 월간 뉴스레터 ─────────────────────────────────────────────

def monthly_html(brand, w, s, sc, sponsor=None):
    order  = ORDER
    colors = COLORS

    bar = "".join(
        f'<div style="width:{w[a]*100:.0f}%;background:{colors[a]}"></div>'
        for a in order if w.get(a, 0) > 0
    )
    alloc = "".join(
        f'<div class="a"><div class="n">{a}</div>'
        f'<div class="v" style="color:{colors[a]}">{w[a]*100:.0f}%</div></div>'
        for a in order if w.get(a, 0) > 0
    )

    prod_html = products_table(w, order, colors)

    # 성적표 섹션
    if sc:
        scrows = "".join(
            f'<tr><td>{r["ticker"]}</td>'
            f'<td class="{"up" if r["ret"]>0 else "dn"}">{r["ret"]:+.1f}%</td>'
            f'<td class="{"beat" if r["hit"] else ""}">{"시장초과 ✓" if r["hit"] else "−"}</td></tr>'
            for r in sc["rows"]
        )
        sctext = (
            "<h2>📋 지난달 추천 종목 성적표</h2>"
            f"<p>지난달 <b>주간호 추천 종목</b>의 실제 성적입니다"
            f"({sc['from']}~{sc['to']})."
            f" 추천 평균 <b>{sc['avg']:+.1f}%</b> vs 시장(균등) <b>{sc['mkt']:+.1f}%</b>.</p>"
            '<div class="kpi">'
            f'<div class="k"><div class="n">추천 평균</div><div class="v" style="color:#12233b">{sc["avg"]:+.1f}%</div></div>'
            f'<div class="k"><div class="n">시장(균등)</div><div class="v" style="color:#12233b">{sc["mkt"]:+.1f}%</div></div>'
            f'<div class="k"><div class="n">시장 초과</div><div class="v beat">{sc["beat"]}/{sc["n"]}</div></div>'
            "</div>"
            "<table><tr><th>종목</th><th>수익률</th><th>시장 대비</th></tr>"
            f"{scrows}</table>"
            '<div class="box"><b>정직 원칙.</b> 오른 종목도 내린 종목도 그대로 공개합니다.'
            " 성적은 매달 있는 그대로 기록합니다.</div>"
        )
    else:
        sctext = (
            "<h2>📋 지난달 추천 종목 성적표</h2>"
            '<div class="box">첫 발송이라 아직 누적된 추천이 없습니다.'
            " 다음 달부터 지난달 추천 종목의 성적을 공개합니다.</div>"
        )

    # 자산 모멘텀 점수 텍스트
    score_text = " · ".join(
        f'{a} <b>{s[a]*100:.0f}</b>'
        for a in ["한국주식", "미국주식", "금", "미국채권"]
        if a in s.index
    )

    return f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{brand} MONTHLY</title>
{CSS}
</head>
<body>
<div class="mail">
  <div class="hd">
    <div class="brand">{brand} <span style="font-weight:600">MONTHLY</span></div>
    <div class="tag">이달의 자산배분 &amp; 지난달 성적표</div>
    <div class="issue">월간호 · 매월 첫 주 발송</div>
  </div>
  <div class="bd">
    <h2>🧭 이달의 자산배분 제안</h2>
    <p class="lead">4자산을 각 자산의 <b>모멘텀 점수</b>로 비중 조절합니다.
    점수가 높은 자산을 키우고, 0 이하로 꺾이면 현금으로 피합니다.</p>
    <div class="bar">{bar}</div>
    <div class="alloc">{alloc}</div>
    <div class="box">모멘텀 점수: {score_text}</div>
    {prod_html}
    {sctext}
    {sponsor_block(sponsor)}
  </div>
  {DISC.format(brand=brand)}
</div>
</body>
</html>"""
