"""KR 성장주 눌림목(touch) 이벤트스터디 — cloud-012 요청
파라미터: MA200, 성장게이트(ratio250>=70%+MA200상승), touch 0~+5%,
         cooldown 30일, stop -10%, hold 12M(252일)
제외: 삼성화재(000810)·삼성생명(032830)·고려아연(010130)
"""
import sys, io, json, warnings
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
warnings.filterwarnings("ignore")

import pandas as pd
import numpy as np
import yfinance as yf

# KR 성장주 유니버스 (종목코드 → 종목명)
KR_UNIVERSE = {
    # 반도체/IT
    "005930": "삼성전자", "000660": "SK하이닉스", "009150": "삼성전기",
    "066570": "LG전자",  "035420": "NAVER",       "035720": "카카오",
    "036570": "엔씨소프트","259960": "크래프톤",   "112040": "위메이드",
    "263750": "펄어비스",
    # 2차전지/에너지
    "373220": "LG에너지솔루션","006400": "삼성SDI","051910": "LG화학",
    "096770": "SK이노베이션","003670": "포스코퓨처엠","247540": "에코프로비엠",
    "086520": "에코프로",    "011790": "SKC",
    # 바이오/헬스케어
    "207940": "삼성바이오로직스","068270": "셀트리온","000100": "유한양행",
    "326030": "SK바이오팜","091990": "셀트리온헬스케어","145020": "휴젤",
    "214450": "파마리서치", "041960": "동화약품",
    # 자동차/방산
    "005380": "현대차",  "000270": "기아",      "086280": "현대글로비스",
    "012450": "한화에어로스페이스","047810": "한국항공우주","064350": "현대로템",
    "009540": "한국조선해양","010140": "삼성중공업",
    # 금융/증권
    "105560": "KB금융",  "055550": "신한지주",  "086790": "하나금융지주",
    "316140": "우리금융지주","024110": "기업은행","006800": "미래에셋증권",
    "016360": "삼성증권",
    # 통신/플랫폼
    "017670": "SK텔레콤","032640": "LG유플러스","030200": "KT",
    "035250": "강원랜드",
    # 소비재/유통
    "097950": "CJ제일제당","033780": "KT&G",    "004370": "농심",
    "271560": "오리온",   "282330": "BGF리테일",
    # 화학/소재
    "011170": "롯데케미칼","010130": "고려아연", # 제외 처리됨
    "004490": "세방전지", "010950": "S-Oil",    "001940": "KISCO홀딩스",
    # 반도체 장비/부품
    "042700": "한미반도체","240810": "원익IPS",  "036830": "솔브레인",
    "102120": "어보브반도체","108320": "LX세미콘",
    # 기타 성장
    "068760": "셀트리온제약","196170": "알테오젠","357780": "솔루스첨단소재",
    "051600": "한전KPS",  "036460": "한국가스공사",
    # 추가
    "138040": "메리츠금융지주","175330": "JB금융지주",
    "001430": "세아베스틸지주","012330": "현대모비스",
    "161390": "한국타이어앤테크놀로지",
}

# 제외 종목
EXCLUDE = {"000810", "032830", "010130"}

UNIVERSE = {k: v for k, v in KR_UNIVERSE.items() if k not in EXCLUDE}

MA_WINDOW       = 200
RATIO250_WINDOW = 250
MA_SLOPE_LAG    = 20
MIN_RATIO250    = 0.70
STOP            = -0.10
COOLDOWN        = 30
HOLD_12M        = 252
START_DATE      = "2019-01-01"
DOWNLOAD_START  = "2015-01-01"

# yfinance 티커: KOSPI → .KS
tickers_yf = [f"{code}.KS" for code in UNIVERSE]
print(f"배치 다운로드: {len(tickers_yf)}종목 ...", flush=True)

raw = yf.download(
    tickers_yf,
    start=DOWNLOAD_START,
    end="2026-01-01",
    auto_adjust=True,
    progress=True,
    group_by="ticker",
    threads=True,
)
print("다운로드 완료.", flush=True)


def get_close(ticker_yf):
    try:
        close = raw[ticker_yf]["Close"].dropna()
        if hasattr(close, "columns"):
            close = close.iloc[:, 0]
        close.index = pd.to_datetime(close.index).tz_localize(None)
        return close.sort_index() if len(close) >= 400 else None
    except:
        return None


def growth_gate(close, ma200, i):
    start_i = max(0, i - RATIO250_WINDOW + 1)
    window   = close.iloc[start_i:i + 1]
    ma_win   = ma200.iloc[start_i:i + 1]
    valid    = ma_win.dropna()
    if len(valid) < RATIO250_WINDOW * 0.8:
        return False
    ratio250 = (window > ma_win).sum() / len(window)
    if ratio250 < MIN_RATIO250:
        return False
    if i < MA_SLOPE_LAG or pd.isna(ma200.iloc[i]) or pd.isna(ma200.iloc[i - MA_SLOPE_LAG]):
        return False
    return ma200.iloc[i] > ma200.iloc[i - MA_SLOPE_LAG]


def find_touch_signals(close):
    ma200     = close.rolling(MA_WINDOW, min_periods=MA_WINDOW).mean()
    ratio     = close / ma200
    start     = pd.Timestamp(START_DATE)
    n         = len(close)
    signals   = []
    last_touch = -9999

    for i in range(len(close)):
        if close.index[i] < start:
            continue
        r = ratio.iloc[i]
        if pd.isna(r):
            continue
        if i + HOLD_12M >= n:
            continue  # 12M 미완성 제외
        if 1.00 <= r <= 1.05 and i - last_touch >= COOLDOWN:
            if growth_gate(close, ma200, i):
                signals.append(i)
                last_touch = i
    return signals


def calc_forward(close, idx, entry_price):
    n           = len(close)
    stop_price  = entry_price * (1 + STOP)
    stop_day    = None
    for k in range(1, HOLD_12M + 1):
        if idx + k >= n:
            break
        if close.iloc[idx + k] <= stop_price:
            stop_day = k
            break
    exit_idx = idx + HOLD_12M
    if stop_day is not None:
        ret12m = STOP
    elif exit_idx < n:
        ret12m = (close.iloc[exit_idx] / entry_price) - 1
    else:
        ret12m = None
    mdd = 0.0
    end_k = stop_day if stop_day else min(HOLD_12M, n - idx - 1)
    for k in range(1, end_k + 1):
        if idx + k >= n:
            break
        r = (close.iloc[idx + k] / entry_price) - 1
        if r < mdd:
            mdd = r
    return {"ret12m": ret12m, "stop_hit": stop_day is not None, "mdd": mdd}


all_trades = []
failed = []

for code, name in UNIVERSE.items():
    tk_yf = f"{code}.KS"
    close  = get_close(tk_yf)
    if close is None:
        failed.append(code)
        print(f"  {name}({code}): 실패", flush=True)
        continue

    idxs = find_touch_signals(close)
    rows = []
    for idx in idxs:
        ep  = float(close.iloc[idx])
        fwd = calc_forward(close, idx, ep)
        if fwd["ret12m"] is None:
            continue
        rows.append({
            "code":        code,
            "name":        name,
            "date":        close.index[idx].strftime("%Y-%m-%d"),
            "type":        "touch",
            "entry_price": round(ep, 0),
            "ret12m":      round(fwd["ret12m"] * 100, 2),
            "stop_hit":    fwd["stop_hit"],
            "mdd":         round(fwd["mdd"] * 100, 2),
        })
    all_trades.extend(rows)
    print(f"  {name}({code}): touch={len(rows)}", flush=True)

print(f"\n실패: {failed}", flush=True)
print(f"전체 touch 신호: {len(all_trades)}건", flush=True)

# 요약
ret12_all = [t["ret12m"] for t in all_trades]
stop_n    = sum(1 for t in all_trades if t["stop_hit"])
win_n     = sum(1 for r in ret12_all if r > 0)
n         = len(all_trades)

print(f"\n[요약] 신호수={n} 승률={round(win_n/n*100,1) if n else 0}% "
      f"평균={round(np.mean(ret12_all),2) if n else 0}% "
      f"중앙값={round(float(np.median(ret12_all)),2) if n else 0}% "
      f"손절율={round(stop_n/n*100,1) if n else 0}%", flush=True)

# 성공 상위 5 / 실패 하위 5
sorted_trades = sorted(all_trades, key=lambda x: x["ret12m"], reverse=True)
top5    = sorted_trades[:5]
bottom5 = sorted_trades[-5:]

print("\n[성공 상위 5]")
for t in top5:
    print(f"  {t['name']}({t['code']}) {t['date']} 진입 {t['entry_price']:,.0f}원 "
          f"12M={t['ret12m']:+.1f}% MDD={t['mdd']:.1f}%")

print("\n[실패 하위 5]")
for t in bottom5:
    stop_s = "손절O" if t["stop_hit"] else "손절X"
    print(f"  {t['name']}({t['code']}) {t['date']} 진입 {t['entry_price']:,.0f}원 "
          f"12M={t['ret12m']:+.1f}% MDD={t['mdd']:.1f}% {stop_s}")

# 저장
out_json = r"C:\project\quant\kr_eventstudy_results_v1.json"
output = {
    "version": "v1",
    "universe_size": len(UNIVERSE),
    "failed": failed,
    "total_signals": n,
    "summary": {
        "win_rate": round(win_n/n*100, 1) if n else 0,
        "avg_ret12m": round(float(np.mean(ret12_all)), 2) if n else 0,
        "median_ret12m": round(float(np.median(ret12_all)), 2) if n else 0,
        "stop_rate": round(stop_n/n*100, 1) if n else 0,
    },
    "top5_success": top5,
    "bottom5_failure": bottom5,
    "trades": all_trades,
}
with open(out_json, "w", encoding="utf-8") as f:
    json.dump(output, f, ensure_ascii=False, indent=2)
print(f"\n저장: {out_json}")
print("완료")
