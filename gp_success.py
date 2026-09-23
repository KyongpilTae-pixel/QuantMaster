import warnings; warnings.filterwarnings("ignore")
import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
import numpy as np, pandas as pd, yfinance as yf

def find_signals(ticker, name, start="2020-01-01", end="2026-09-01"):
    df = yf.download(ticker, start=start, end=end, progress=False, auto_adjust=True)
    if isinstance(df.columns, pd.MultiIndex): df.columns = [c[0] for c in df.columns]
    close = df["Close"].squeeze().dropna()
    close.index = pd.to_datetime(close.index).tz_localize(None)
    ma200 = close.rolling(200, min_periods=100).mean()
    ratio = (close - ma200) / ma200

    all_sigs = []
    LB = 500
    for i in range(LB, len(close)-60):
        r = ratio.iloc[i]
        if pd.isna(r): continue
        if 0 <= r <= 0.05:
            past_c = close.iloc[i-LB:i].values
            past_m = ma200.iloc[i-LB:i].values
            valid  = ~(np.isnan(past_c)|np.isnan(past_m))
            if valid.sum() < 200: continue
            if (past_c[valid] > past_m[valid]).mean() < 0.70: continue

            # 이후 12M 결과
            i12 = min(i+252, len(close)-1)
            ret12 = (close.iloc[i12] / close.iloc[i] - 1) * 100
            # 손절 날짜
            future_r = ratio.iloc[i:i12+1]
            stop_hit = (future_r < -0.10).any()
            if stop_hit:
                stop_idx = future_r[future_r < -0.10].index[0]
                entry_to_stop = (stop_idx - close.index[i]).days
            else:
                stop_idx = None
                entry_to_stop = None

            # 앞으로 30일 내 비슷한 신호 중복 제거
            if all_sigs and (close.index[i] - all_sigs[-1]["date"]).days < 30:
                continue

            all_sigs.append({
                "date": close.index[i],
                "price": close.iloc[i],
                "ma200": ma200.iloc[i],
                "ratio_pct": r*100,
                "ret12": ret12,
                "stop_hit": stop_hit,
                "stop_date": stop_idx,
                "stop_days": entry_to_stop,
            })

    if not all_sigs:
        return

    df_s = pd.DataFrame(all_sigs)
    success = df_s[~df_s["stop_hit"] & (df_s["ret12"] > 10)]
    fail    = df_s[df_s["stop_hit"]]

    print(f"\n{'='*58}")
    print(f"  {name} ({ticker})  |  총 신호: {len(df_s)}건  성공: {len(success)}  손절: {len(fail)}")
    print(f"{'='*58}")

    if len(success) > 0:
        print("\n  [성공 사례]")
        for _, row in success.iterrows():
            d = row["date"].strftime("%Y-%m-%d")
            p = row["price"]; m = row["ma200"]
            print(f"  진입 {d}  {p:.0f}원/$  MA200={m:.0f}  대비+{row['ratio_pct']:.1f}%  12M후+{row['ret12']:.0f}%  손절없음")

    if len(fail) > 0:
        print("\n  [실패(손절) 사례]")
        for _, row in fail.head(3).iterrows():
            d = row["date"].strftime("%Y-%m-%d")
            sd = row["stop_date"].strftime("%Y-%m-%d") if row["stop_date"] else "-"
            print(f"  진입 {d}  {row['price']:.0f}  MA200={row['ma200']:.0f}  대비+{row['ratio_pct']:.1f}%  손절일 {sd}({row['stop_days']}일후)  12M후{row['ret12']:.0f}%")

find_signals("AAPL", "Apple")
find_signals("MSFT", "Microsoft")
find_signals("NVDA", "NVIDIA")
find_signals("META", "Meta")
