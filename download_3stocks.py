import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
import pandas as pd
import FinanceDataReader as fdr

STOCKS = [
    ("000810", "samsungfire"),
    ("032830", "samsunglife"),
    ("010130", "koreazinc"),
]

for code, name in STOCKS:
    print(f"다운로드: {code} {name} ...", flush=True)
    df = fdr.DataReader(code, "2016-01-01", "2025-12-31")
    df.index = pd.to_datetime(df.index)
    df.index.name = "date"
    # 컬럼 소문자 정규화
    df.columns = [c.lower() for c in df.columns]
    # 필요한 컬럼만
    cols = [c for c in ["open","high","low","close","volume"] if c in df.columns]
    df = df[cols]
    # NaN 행 제거
    df = df.dropna(subset=["close"])
    out = rf"C:\project\quant\data_{code}_{name}.csv"
    df.to_csv(out, encoding="utf-8-sig")
    print(f"  -> {out}  {len(df)}행  {df.index[0].date()} ~ {df.index[-1].date()}  (수정주가: FinanceDataReader 기본 = 수정주가)", flush=True)

print("완료")
