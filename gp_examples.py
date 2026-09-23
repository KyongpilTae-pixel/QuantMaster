import warnings; warnings.filterwarnings("ignore")
import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

import numpy as np
import pandas as pd
import yfinance as yf

def show_example(ticker, name, start="2020-01-01", end="2026-01-01"):
    df = yf.download(ticker, start=start, end=end, progress=False, auto_adjust=True)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [c[0] for c in df.columns]
    close = df["Close"].squeeze()
    close.index = pd.to_datetime(close.index).tz_localize(None)
    ma200 = close.rolling(200, min_periods=100).mean()
    ratio = (close - ma200) / ma200

    # Touch 신호 찾기: 0 <= ratio <= 5% (성장주 조건도 근사 체크)
    touch_signals = []
    lookback = 500
    for i in range(lookback, len(close)):
        r = ratio.iloc[i]
        if pd.isna(r):
            continue
        if 0 <= r <= 0.05:
            # 성장주 조건 근사 체크 (과거 500일 중 MA200 위 비율)
            past_c = close.iloc[i-lookback:i].values
            past_m = ma200.iloc[i-lookback:i].values
            valid = ~(np.isnan(past_c) | np.isnan(past_m))
            if valid.sum() >= 200 and (past_c[valid] > past_m[valid]).mean() >= 0.70:
                touch_signals.append(close.index[i])

    if not touch_signals:
        print(f"{name}({ticker}): Touch 신호 없음\n")
        return

    print(f"\n{'='*55}")
    print(f"  {name} ({ticker})")
    print(f"{'='*55}")

    for sig_date in touch_signals[:5]:  # 최대 5개 신호
        idx = close.index.get_loc(sig_date)
        entry_price = close.iloc[idx]
        ma200_val   = ma200.iloc[idx]
        entry_ratio = ratio.iloc[idx]

        # 이후 성과
        forward = {}
        for months, days in [(3, 63), (6, 126), (12, 252)]:
            fut_idx = idx + days
            if fut_idx < len(close):
                fut_price = close.iloc[fut_idx]
                fut_r = close.iloc[idx:fut_idx+1]
                fut_ma = ma200.iloc[idx:fut_idx+1]
                # 손절 발생 여부
                below_stop = ((fut_r - fut_ma) / fut_ma < -0.10)
                stop_hit = below_stop.any()
                stop_date = fut_r[below_stop].index[0].strftime("%Y-%m-%d") if stop_hit else "-"
                ret = (fut_price / entry_price - 1) * 100
                forward[months] = {"ret": ret, "stop": stop_hit, "stop_date": stop_date}

        # 결과 판정
        outcome = "불명"
        if 12 in forward:
            r12 = forward[12]["ret"]
            s10 = forward.get(3, {}).get("stop", False) or forward.get(6, {}).get("stop", False)
            if s10:
                outcome = "FAIL (손절)"
            elif r12 > 20:
                outcome = "SUCCESS (+강)"
            elif r12 > 5:
                outcome = "SUCCESS (+중)"
            elif r12 > 0:
                outcome = "보통 (+약)"
            else:
                outcome = "FAIL (손실)"

        print(f"\n  진입일: {sig_date.strftime('%Y-%m-%d')}  [{outcome}]")
        print(f"  진입가: {entry_price:.1f}  MA200: {ma200_val:.1f}  MA200대비: +{entry_ratio*100:.1f}%")
        for m, v in forward.items():
            stop_tag = f" ← 손절({v['stop_date']})" if v["stop"] else ""
            ret_s = f"+{v['ret']:.1f}%" if v["ret"] >= 0 else f"{v['ret']:.1f}%"
            print(f"  {m:>2}M 후: {ret_s:>8}{stop_tag}")

# 성공 사례
show_example("NVDA", "엔비디아")   # AI 수혜 대표 성장주
show_example("MSFT", "마이크로소프트")

# 실패 사례
show_example("META", "메타 플랫폼")   # 2022 폭락
show_example("TSLA", "테슬라")
