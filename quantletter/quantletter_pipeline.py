# -*- coding: utf-8 -*-
"""
퀀트레터 통합 파이프라인
========================
실행 한 번으로:
 - 주간 뉴스레터(모멘텀 종목 시그널) -> out_weekly.html
 - 월간 뉴스레터(자산배분 비중 + 지난달 추천 성적표) -> out_monthly.html
을 자동 생성합니다.

모드
 - SAMPLE : KIS 키가 없으면 로컬 공개 데이터로 동작(형식·로직 검증용).
   필요한 로컬 파일: all_stocks_5yr.csv, d_gold.csv, d_spx.csv,
                    d_bond.csv, d_usdkrw.csv, d_kospi.csv
   → fetch_sample_data.py 를 먼저 실행하면 자동 다운로드됩니다.
 - LIVE : KIS_APP_KEY/KIS_APP_SECRET 환경변수 입력 시 실데이터로 전환.

사용
 1) python fetch_sample_data.py     # 처음 한 번만
 2) python quantletter_pipeline.py  # 뉴스레터 HTML 생성
 3) out_weekly.html / out_monthly.html 확인
픽 히스토리(picks_history.json)를 누적하여 다음 달 성적표를 자동 계산합니다.
"""
import os, json, time, datetime as dt
import pandas as pd
import numpy as np

# ============================ CONFIG ============================
APP_KEY    = os.environ.get("KIS_APP_KEY", "")
APP_SECRET = os.environ.get("KIS_APP_SECRET", "")
IS_PAPER   = False
MARKET     = "US"   # 주간 종목 대상: "US" 또는 "KR"
TOP_N      = 6      # 주간 추천 종목 수
LOOKBACK_M = 6      # 검증된 형성기간(개월): 6이 기본 (3·6·12 중)
BRAND      = "퀀트레터"
HISTORY    = "picks_history.json"
TILT4      = [0.40, 0.30, 0.20, 0.10]
MODE       = "LIVE" if APP_KEY and APP_SECRET else "SAMPLE"
# ===============================================================

US_UNIVERSE = [
    "AAPL","MSFT","NVDA","AMZN","META","GOOGL","AVGO","TSLA","JPM","V",
    "LLY","UNH","XOM","MA","COST","HD","NFLX","AMD","CRM","ADBE",
]

# 40 major KOSPI stocks — same list as fetch_kr_stocks.py
KR_UNIVERSE = [
    "005930","000660","009150","066570","035420","035720","036570",
    "373220","006400","051910","096770","010950","015760",
    "207940","068270","000100",
    "005380","000270","086280","004020","012450","047810",
    "105560","055550","086790","316140","032830","000810","024110",
    "017670","032640","030200",
    "097950","033780","028260","003550",
    "009540","042660","003490","010130",
]


def momentum_rank(prices, lookback_days):
    p = prices.dropna(axis=1, how="all")
    last = p.index[-1]

    def ret(days):
        if len(p) <= days:
            return pd.Series(dtype=float)
        return p.loc[last] / p.iloc[-1 - days] - 1

    m6  = ret(126)
    m3  = ret(63)
    m12 = ret(252)
    vol = p.pct_change().iloc[-252:].std() * np.sqrt(252)
    tbl = pd.DataFrame({"m6": m6, "m3": m3, "m12": m12, "vol": vol}).dropna(subset=["m6"])
    tbl["score"] = (
        tbl["m6"].rank(pct=True) * 0.6
        + tbl["m12"].rank(pct=True).fillna(0.5) * 0.4
    )
    return tbl.sort_values("score", ascending=False), last


def alloc_weights(macro_returns):
    R  = macro_returns.dropna()
    px = (1 + R).cumprod()
    sc = sum((px / px.shift(lb) - 1) for lb in [1, 3, 6, 12]) / 4.0
    s  = sc.iloc[-1]
    order = s.sort_values(ascending=False).index
    w = {a: TILT4[i] for i, a in enumerate(order)}
    cash = 0.0
    for a in R.columns:
        if s[a] <= 0:
            cash += w[a]
            w[a] = 0.0
    w["현금"] = cash
    return w, s


# ── SAMPLE 모드: 로컬 CSV 읽기 ──────────────────────────────────

def sample_stock_prices():
    csv = "kr_stocks_5yr.csv" if MARKET == "KR" else "all_stocks_5yr.csv"
    if not os.path.exists(csv):
        missing = "fetch_kr_stocks.py" if MARKET == "KR" else "fetch_sample_data.py"
        raise FileNotFoundError(f"{csv} 없음 — python {missing} 를 먼저 실행하세요")
    df = pd.read_csv(csv, parse_dates=["date"])
    return df.pivot(index="date", columns="Name", values="close").sort_index()


def sample_macro():
    def msi(s):
        s = s.copy()
        s.index = s.index.to_period("M").to_timestamp()
        return s[~s.index.duplicated(keep="last")]

    gold  = msi(pd.read_csv("d_gold.csv",    index_col=0, parse_dates=True)["gold"])
    spx   = pd.read_csv("d_spx.csv",         index_col=0, parse_dates=True)
    spx.index = spx.index.to_period("M").to_timestamp()
    spx   = spx[~spx.index.duplicated(keep="last")]
    bond  = msi(pd.read_csv("d_bond.csv",    index_col=0, parse_dates=True)["y10"])
    fx    = msi(pd.read_csv("d_usdkrw.csv",  index_col=0, parse_dates=True)["usdkrw"])
    kospi = msi(pd.read_csv("d_kospi.csv",   index_col=0, parse_dates=True)["kospi"])

    # 미국주식 월간 토탈리턴 (조정종가 기준이면 div=0 가능)
    us_stk = (spx["spx"] + spx["div"].fillna(0) / 12) / spx["spx"].shift(1) - 1

    # 미국 10년 국채 듀레이션 근사 월간 수익률
    y  = bond / 100.0
    br = pd.Series(index=y.index, dtype=float)
    N  = 20
    n  = np.arange(1, N + 1)
    for i in range(1, len(y)):
        y0, y1 = y.iloc[i - 1], y.iloc[i]
        c  = y0 / 2
        cf = np.full(N, c)
        cf[-1] += 1
        br.iloc[i] = y0 / 12 + ((cf / (1 + y1 / 2) ** n).sum() - 1)

    fxr = fx.pct_change()

    def krw(r):
        return (1 + r) * (1 + fxr) - 1

    R = pd.DataFrame({
        "한국주식": kospi.pct_change(),
        "미국주식": krw(us_stk),
        "미국채권": krw(br),
        "금":       krw(gold.pct_change()),
    }).dropna()
    return R


# ── LIVE 모드: KIS OpenAPI ────────────────────────────────────

class KIS:
    def __init__(self):
        import requests
        self.r    = requests
        self.base = (
            "https://openapivts.koreainvestment.com:29443"
            if IS_PAPER
            else "https://openapi.koreainvestment.com:9443"
        )
        self.tok = None

    def token(self):
        if self.tok:
            return self.tok
        r = self.r.post(
            f"{self.base}/oauth2/tokenP",
            headers={"content-type": "application/json"},
            data=json.dumps({
                "grant_type": "client_credentials",
                "appkey":     APP_KEY,
                "appsecret":  APP_SECRET,
            }),
        )
        r.raise_for_status()
        self.tok = r.json()["access_token"]
        return self.tok

    def _h(self, tr):
        return {
            "content-type":  "application/json",
            "authorization": f"Bearer {self.token()}",
            "appkey":        APP_KEY,
            "appsecret":     APP_SECRET,
            "tr_id":         tr,
            "custtype":      "P",
        }

    def daily_kr(self, code, start, end):
        u = f"{self.base}/uapi/domestic-stock/v1/quotations/inquire-daily-itemchartprice"
        p = {
            "FID_COND_MRKT_DIV_CODE": "J",
            "FID_INPUT_ISCD":         code,
            "FID_INPUT_DATE_1":       start,
            "FID_INPUT_DATE_2":       end,
            "FID_PERIOD_DIV_CODE":    "D",
            "FID_ORG_ADJ_PRC":        "0",
        }
        j = self.r.get(u, headers=self._h("FHKST03010100"), params=p).json()
        o = j.get("output2") or []
        s = pd.Series({x["stck_bsop_date"]: float(x["stck_clpr"]) for x in o if x.get("stck_bsop_date")})
        s.index = pd.to_datetime(s.index)
        return s.sort_index()

    def daily_us(self, code, start, end, exch="NAS"):
        u = f"{self.base}/uapi/overseas-price/v1/quotations/dailyprice"
        p = {"AUTH": "", "EXCD": exch, "SYMB": code, "GUBN": "0", "BYMD": end, "MODP": "1"}
        j = self.r.get(u, headers=self._h("HHDFS76240000"), params=p).json()
        o = j.get("output2") or []
        s = pd.Series({x["xymd"]: float(x["clos"]) for x in o if x.get("xymd")})
        s.index = pd.to_datetime(s.index)
        return s.sort_index()


def live_stock_prices(universe, market):
    k   = KIS()
    end = dt.date.today().strftime("%Y%m%d")
    start = (dt.date.today() - dt.timedelta(days=420)).strftime("%Y%m%d")
    ser = {}
    for c in universe:
        try:
            s = k.daily_kr(c, start, end) if market == "KR" else k.daily_us(c, start, end)
            if len(s) > 50:
                ser[c] = s
            time.sleep(0.08)
        except Exception as e:
            print("skip", c, e)
    return pd.DataFrame(ser).sort_index()


# ── 히스토리 관리 ─────────────────────────────────────────────

def load_history():
    if os.path.exists(HISTORY):
        return json.load(open(HISTORY, encoding="utf-8"))
    return {"weekly": []}


def save_pick(hist, asof, picks):
    hist["weekly"].append({
        "asof":    str(asof.date() if hasattr(asof, "date") else asof),
        "tickers": [p["ticker"] for p in picks],
    })
    json.dump(hist, open(HISTORY, "w", encoding="utf-8"), ensure_ascii=False, indent=1)


def scorecard(prices, hist, weeks_ago=4):
    if len(hist["weekly"]) < 1:
        return None
    prev = hist["weekly"][max(0, len(hist["weekly"]) - 1 - weeks_ago)]
    tks  = [t for t in prev["tickers"] if t in prices.columns]
    if not tks:
        return None
    base = pd.to_datetime(prev["asof"])
    p    = prices[prices.index >= base]
    if len(p) < 2:
        return None
    fwd = (p[tks].iloc[-1] / p[tks].iloc[0] - 1) * 100
    mkt = (prices[prices.index >= base].iloc[-1] / prices[prices.index >= base].iloc[0] - 1).mean() * 100
    rows = [{"ticker": t, "ret": round(float(fwd[t]), 1), "hit": bool(fwd[t] > mkt)} for t in tks]
    rows.sort(key=lambda r: -r["ret"])
    return {
        "from": prev["asof"],
        "to":   str(p.index[-1].date()),
        "rows": rows,
        "avg":  round(float(fwd.mean()), 2),
        "mkt":  round(float(mkt), 2),
        "beat": int((fwd > mkt).sum()),
        "up":   int((fwd > 0).sum()),
        "n":    len(tks),
    }


# ── 렌더 ──────────────────────────────────────────────────────

def render(weekly_tbl, asof, alloc_w, alloc_s, sc, positions=None):
    from newsletter_render import weekly_html, monthly_html
    with open("out_weekly.html", "w", encoding="utf-8") as f:
        f.write(weekly_html(BRAND, asof, weekly_tbl, TOP_N, MARKET, LOOKBACK_M, positions))
    with open("out_monthly.html", "w", encoding="utf-8") as f:
        f.write(monthly_html(BRAND, alloc_w, alloc_s, sc))
    print("생성 완료: out_weekly.html, out_monthly.html")


# ── 메인 ──────────────────────────────────────────────────────

def main():
    print(f"[모드] {MODE} / 주간대상 {MARKET} / 룩백 {LOOKBACK_M}개월")

    if MODE == "LIVE":
        uni    = US_UNIVERSE if MARKET == "US" else KR_UNIVERSE
        prices = live_stock_prices(uni, MARKET)
        macro  = sample_macro()          # 매크로는 항상 로컬 CSV 사용
    else:
        prices = sample_stock_prices()
        macro  = sample_macro()

    tbl, asof = momentum_rank(prices, LOOKBACK_M * 21)
    picks = [
        {
            "ticker": t,
            "m6":  round(r.m6  * 100, 1),
            "m3":  round(r.m3  * 100, 1),
            "m12": round(r.m12 * 100, 1),
            "vol": round(r.vol * 100, 1),
        }
        for t, r in tbl.head(TOP_N).iterrows()
    ]

    w, s   = alloc_weights(macro)
    hist   = load_history()
    sc     = scorecard(prices, hist)
    save_pick(hist, asof, picks)

    asof_str = str(asof.date() if hasattr(asof, "date") else asof)
    render({"picks": picks, "asof": asof_str}, asof, w, s, sc)

    print("추천비중:", {k: f"{v*100:.0f}%" for k, v in w.items() if v > 0})
    print("이번주 픽:", [p["ticker"] for p in picks])
    if sc:
        print(f"성적표: 추천 {sc['avg']}% vs 시장 {sc['mkt']}% (시장초과 {sc['beat']}/{sc['n']})")
    else:
        print("성적표: 히스토리 부족 (다음 실행부터 생성)")


if __name__ == "__main__":
    main()
