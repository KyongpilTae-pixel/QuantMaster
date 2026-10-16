import json, pandas as pd, yfinance as yf
from datetime import datetime, timedelta

with open("taa_fullcycle_032.json") as f:
    taa = json.load(f)
monthly = taa["best_variant_monthly"]

SYMBOLS = ["EWY", "SPY", "AGG", "GLD", "BIL"]
START = "2019-01-01"
END = (datetime.today() + timedelta(days=1)).strftime("%Y-%m-%d")

prices = {}
for sym in SYMBOLS:
    tk = yf.Ticker(sym)
    df = tk.history(start=START, end=END, auto_adjust=True)
    if df.empty:
        print("WARN: " + sym + " empty")
        continue
    df.index = pd.to_datetime(df.index).tz_localize(None).normalize()
    p = df[["Open","High","Low","Close"]].copy()
    p.columns = ["open","high","low","close"]
    p["adj_close"] = p["close"]
    p.index.name = "date"
    prices[sym] = p
    print("  " + sym + ": " + str(len(df)) + " rows " + str(df.index[0].date()) + "~" + str(df.index[-1].date()))

print("Self-check: " + str(len(prices)) + "/5 symbols, aliasing=none (individual download)")

rows = []
for sym in SYMBOLS:
    if sym not in prices: continue
    d = prices[sym].reset_index()
    d.insert(0, "name", sym)
    rows.append(d)
asset_df = pd.concat(rows, ignore_index=True)
asset_df["date"] = asset_df["date"].dt.strftime("%Y-%m-%d")
asset_df = asset_df[["name","date","open","high","low","close","adj_close"]]
asset_df.to_csv("asset_daily.csv", index=False)
dmin = asset_df["date"].min()
dmax = asset_df["date"].max()
nsyms = asset_df["name"].nunique()
print("asset_daily.csv: " + str(len(asset_df)) + " rows, " + str(nsyms) + " syms, " + dmin + "~" + dmax)

adj = pd.DataFrame({s: prices[s]["adj_close"] for s in SYMBOLS if s in prices}).sort_index()
ret = adj.pct_change().fillna(0)

month_weights = {}
for row in monthly:
    ym = row["month"]
    w = {s: row["weights"].get(s,0)/100.0 for s in SYMBOLS}
    month_weights[ym] = w

nav_start = pd.Timestamp("2020-01-02")
trade_dates = ret.loc[nav_start:].index
neq = len([s for s in SYMBOLS if s in prices])
w_eq = {s: 1.0/neq for s in SYMBOLS if s in prices}

nv, ne, ns = {}, {}, {}
c_v, c_e, c_s = 100.0, 100.0, 100.0
first = True
for dt in trade_dates:
    ym = dt.strftime("%Y-%m")
    wv = month_weights.get(ym, {s:0 for s in SYMBOLS})
    if first:
        nv[dt]=c_v; ne[dt]=c_e; ns[dt]=c_s; first=False; continue
    r = ret.loc[dt]
    c_v *= 1+sum(wv.get(s,0)*float(r.get(s,0)) for s in SYMBOLS)
    c_e *= 1+sum(w_eq.get(s,0)*float(r.get(s,0)) for s in SYMBOLS if s in prices)
    c_s *= 1+float(r.get("SPY",0))
    nv[dt]=c_v; ne[dt]=c_e; ns[dt]=c_s

nav_df = pd.DataFrame({"V3":nv,"EW5":ne,"SPY":ns}).round(4)
nav_df.index.name = "date"
nav_df.index = nav_df.index.strftime("%Y-%m-%d")
nav_df.to_csv("taa_daily_nav.csv")
print("taa_daily_nav.csv: " + str(len(nav_df)) + " rows " + nav_df.index[0] + "~" + nav_df.index[-1])
last = nav_df.iloc[-1]
print("Final NAV V3=" + str(round(last["V3"],2)) + " EW5=" + str(round(last["EW5"],2)) + " SPY=" + str(round(last["SPY"],2)))
print("NOTE: BASE/V1 monthly weights not in taa_fullcycle_032.json, omitted")
