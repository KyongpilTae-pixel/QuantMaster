# -*- coding: utf-8 -*-
"""
퀀트레터 · 미끼 콘텐츠유입용) 자동 생성기
==========================================
매주/매달 레터를 만들 때 함께 돌리면, 뉴스레터 본문 대신
'유입 채널'에 뿌릴 짧은 콘텐츠를 자동으로 뽑아준다.

생성물
  - threads_posts.txt : 스레드/X용 짧은 포스트 여러 변형(그대로 복붙)
  - blog_draft.md     : 네이버 블로그/티스토리용 SEO 초안(제목·본문·태그)

데이터
  - 같은 폴더에 snippets_signal.json 이 있으면 그걸 읽고,
    없으면 아래 DEFAULT_SIGNAL(7월 시범 수치)로 동작한다.
  - quantletter_pipeline.py 의 결과(자산 점수/수익률)를 이 JSON 형식으로
    저장하면 매주 자동 연동된다.

사용
  python make_snippets.py
  (KIS/실데이터가 붙으면 signal JSON만 갱신하면 됨)
"""
import json, os, datetime as dt

DEFAULT_SIGNAL = {
    "asof": "2026-07",
    "scores": {"한국주식": 0.99, "미국주식": 0.18, "금": 0.15, "미국채권": 0.04},
    "recent": {
        "1개월":  {"한국주식": 0.284, "미국주식": 0.084, "금": -0.011, "미국채권": 0.008},
        "3개월":  {"한국주식": 0.357, "미국주식": 0.123, "금": -0.046, "미국채권": 0.026},
        "6개월":  {"한국주식": 1.159, "미국주식": 0.127, "금": 0.150,  "미국채권": 0.014},
        "12개월": {"한국주식": 2.142, "미국주식": 0.389, "금": 0.510,  "미국채권": 0.130},
    },
    "weights": {"한국주식": 0.40, "미국주식": 0.30, "금": 0.20, "미국채권": 0.10},
    "scorecard": {"avg": None, "mkt": None, "beat": None, "n": None},
    "subscribe_url": "https://(구독링크)",
}

SIGNAL_FILE = "snippets_signal.json"
BRAND = "퀀트레터"

def load_signal():
    if os.path.exists(SIGNAL_FILE):
        return json.load(open(SIGNAL_FILE, encoding="utf-8"))
    return DEFAULT_SIGNAL

def pc(x):
    return f"{x*100:+.1f}%"

def sig_label(s):
    return "🟢 강세" if s > 0.12 else "🟡 중립" if s > 0.03 else "🟠 약세" if s > 0 else "🔴 회피"

def threads_posts(d):
    ym = d["asof"]
    sc = d["scores"]; rec = d["recent"]; w = d["weights"]
    order = sorted(sc, key=lambda a: -sc[a])
    lead = order[0]
    url = d.get("subscribe_url", "")
    posts = []
    line = " / ".join(f"{a} {sig_label(sc[a])}" for a in order)
    posts.append(
        f"[{ym} 자산 신호]\n{line}\n\n"
        f"이번 달 모멘텀 1위는 '{lead}'. 감이 아니라 1·3·6·12개월 추세 점수로 매깁니다.\n"
        f"전체 표와 배분 비중은 무료 뉴스레터에서 👉 {url}\n"
        f"#자산배분 #모멘텀투자 #재테크"
    )
    wtxt = ", ".join(f"{a} {w[a]*100:.0f}%" for a in order if w.get(a, 0) > 0)
    posts.append(
        f"이번 달 '참고 자산배분' 이렇게 나왔습니다.\n{wtxt}\n\n"
        f"점수 높은 자산에 더 싣고, 0 이하로 꺾이면 현금으로 피하는 규칙.\n"
        f"근거·실행 ETF까지 뉴스레터에 정리했어요 👉 {url}\n"
        f"#ETF #자산배분 #패시브투자"
    )
    a = lead
    posts.append(
        f"'{a}' 최근 흐름 한눈에\n"
        f"· 1개월 {pc(rec['1개월'][a])}\n· 3개월 {pc(rec['3개월'][a])}\n"
        f"· 6개월 {pc(rec['6개월'][a])}\n· 12개월 {pc(rec['12개월'][a])}\n\n"
        f"추세는 강하지만 그만큼 조정 폭도 큽니다. 쫓지 말고 규칙으로.\n👉 {url}"
    )
    scd = d.get("scorecard", {})
    if scd.get("avg") is not None:
        posts.append(
            f"지난달 추천, 있는 그대로 공개합니다.\n"
            f"추천 평균 {scd['avg']:+.1f}% vs 시장 {scd['mkt']:+.1f}% "
            f"(시장 초과 {scd['beat']}/{scd['n']}종목)\n\n"
            f"맞힌 것도 틀린 것도 매달 그대로 기록합니다. 그게 리딩방과 다른 점.\n👉 {url}"
        )
    else:
        posts.append(
            f"리딩방은 수익률만 자랑하고, 틀린 건 지웁니다.\n"
            f"{BRAND}는 반대로 갑니다 — 맞힌 것도 틀린 것도 매달 성적표로 공개.\n\n"
            f"검증된 알고리즘 신호를 무료로 받아보세요 👉 {url}\n"
            f"#투자 #퀀트 #뉴스레터"
        )
    return posts

def blog_draft(d):
    ym = d["asof"]
    sc = d["scores"]; rec = d["recent"]; w = d["weights"]
    order = sorted(sc, key=lambda a: -sc[a])
    lead = order[0]
    url = d.get("subscribe_url", "")
    tbl = "| 자산 | 1개월 | 3개월 | 6개월 | 12개월 | 신호 |\n|---|---|---|---|---|---|\n"
    for a in order:
        tbl += (f"| {a} | {pc(rec['1개월'][a])} | {pc(rec['3개월'][a])} | "
                f"{pc(rec['6개월'][a])} | {pc(rec['12개월'][a])} | {sig_label(sc[a])} |\n")
    wtxt = ", ".join(f"{a} {w[a]*100:.0f}%" for a in order if w.get(a, 0) > 0)
    md = f"""# {ym} 자산배분 신호 — {lead} 모멘텀 선두 (한국주식·미국주식·금·미국채권)

> 매달 알고리즘이 계산한 자산배분 신호를 정리합니다. 감이 아니라 최근 1·3·6·12개월 추세 점수로 4자산을 비교합니다. (본 글은 정보 제공이며 투자자문이 아닙니다.)

## 이번 달 자산 신호 한눈에

{tbl}
점수는 최근 1·3·6·12개월 수익률을 종합한 모멘텀 지표입니다. 높을수록 추세가 강하다는 뜻이고, 이번 달은 **{lead}**가 가장 강한 모멘텀을 보였습니다.

## 그래서 어떻게 나눠 담나

모멘텀 점수 순서대로 비중을 싣고, 점수가 0 이하로 꺾인 자산은 현금으로 회피하는 규칙입니다. 이번 달 참고 배분은 다음과 같습니다.

**{wtxt}**

핵심은 "쫓지 않고 규칙으로 움직인다"는 점입니다. 추세가 강할수록 조정 폭도 커지기 때문에, 진입 시점과 비중은 각자의 상황에 맞게 조절하세요.

## 왜 이 방식인가

이 모멘텀 자산배분은 30년(1996~2026) 백테스트에서 다섯 번의 위기(아시아 외환위기·닷컴·금융위기·코로나·인플레 베어)를 모두 플러스로 통과했습니다. 다만 이 방어력의 상당 부분은 위기 때 원화 약세로 달러자산 가치가 오르는 환율 효과에서 오며, 과거 성과가 미래를 보장하지는 않습니다.

## 매주·매달 신호를 받아보려면

전체 표와 실행 ETF, 그리고 지난달 추천의 정직한 성적표는 무료 뉴스레터로 보내드립니다. 월 1,000원(첫 달 무료)에 감이 아니라 데이터로 투자하는 습관을 시작하세요.

👉 구독하기: {url}

---
*본 콘텐츠는 불특정 다수를 위한 정보 제공이며 개별 투자자문이 아닙니다. 제시된 수치는 공개 데이터 기반이며 원금손실 가능성이 있고 과거 성과가 미래 수익을 보장하지 않습니다.*

<!-- 추천 태그: #자산배분 #모멘텀투자 #ETF #재테크 #퀀트투자 #{ym.replace('-','')}자산배분 -->
"""
    return md

def main():
    d = load_signal()
    posts = threads_posts(d)
    with open("threads_posts.txt", "w", encoding="utf-8") as f:
        f.write(f"# {BRAND} 스레드/X 유입 포스트 ({d['asof']})\n")
        f.write("# 각 블록을 그대로 복붙하세요. 하루 1개씩 뿌리는 걸 권장.\n")
        for i, p in enumerate(posts, 1):
            f.write(f"\n{'='*40}\n[포스트 {i}]\n{'='*40}\n{p}\n")
    with open("blog_draft.md", "w", encoding="utf-8") as f:
        f.write(blog_draft(d))
    print(f"[생성 완료] 기준 {d['asof']}")
    print(" - threads_posts.txt :", len(posts), "개 포스트")
    print(" - blog_draft.md     : 블로그 SEO 초안 1편")
    print("\n[미리보기] 스레드 포스트 1")
    print(posts[0])

if __name__ == "__main__":
    main()
