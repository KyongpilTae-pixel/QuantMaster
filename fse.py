import yfinance as yf
import FinanceDataReader as fdr
import pandas as pd
from datetime import datetime
start="2018-01-01"
end=datetime.today().strftime("%Y-%m-%d")
syms=["XLK","XLF","XLE","XLV","XLI","XLY","XLP","XLU","XLB","XLRE","XLC","SPY"]
rows=[]
for s in syms:
    tk=yf.Ticker(s)
    h=tk.history(start=start,end=end,auto_adjust=True)
    if h.empty: print(s+":nodata");continue
    h=h.reset_index()
    h["Date"]=pd.to_datetime(h["Date"]).dt.date
    for _,r in h.iterrows(): rows.append({"name":s,"date":r["Date"],"open":round(float(r["Open"]),4),"high":round(float(r["High"]),4),"low":round(float(r["Low"]),4),"close":round(float(r["Close"]),4),"adj_close":round(float(r["Close"]),4)})
    print(s+":"+str(len(h)))
df=pd.DataFrame(rows)
df.to_csv("C:/project/quant/sector_daily_us.csv",index=False)
print("US_DONE rows="+str(len(df))+" syms="+str(df["name"].nunique()))
for s,c in df.groupby("name")["close"].nunique().items(): print("USVFY "+s+" "+str(c))
print("US_PRD "+str(df["date"].min())+" "+str(df["date"].max()))
kr_codes=["091160","091180","091170","102970","117700","117460","117680","140700","143860","305720","069500"]
kr_name={"091160":"KODEX-semicon","091180":"KODEX-auto","091170":"KODEX-bank","102970":"KODEX-sec","117700":"KODEX-const","117460":"KODEX-energy","117680":"KODEX-steel","140700":"KODEX-ins","143860":"TIGER-health","305720":"KODEX-battery","069500":"KODEX200"}
kr_name_kr={"091160":"KODEX 반도체","091180":"KODEX 자동차","091170":"KODEX 은행","102970":"KODEX 증권","117700":"KODEX 건설","117460":"KODEX 에너지화학","117680":"KODEX 철강","140700":"KODEX 보험","143860":"TIGER 헬스케어","305720":"KODEX 2차전지산업","069500":"KODEX 200"}
kr_rows=[]
kr_meta=[]
for code in kr_codes:
    try:
        d=fdr.DataReader(code,start=start,end=end)
        if d is None or d.empty: print(code+":nodata");kr_meta.append({"c":code,"n":kr_name[code],"nk":kr_name_kr[code],"ld":"N/A","r":0,"note":"nodata"});continue
        d=d.reset_index()
        d.columns=[x.lower() for x in d.columns]
        dc="date" if "date" in d.columns else d.columns[0]
        d[dc]=pd.to_datetime(d[dc]).dt.date
        cc="close" if "close" in d.columns else d.columns[4]
        co="open" if "open" in d.columns else cc
        ch="high" if "high" in d.columns else cc
        cl="low" if "low" in d.columns else cc
        ca="adj close" if "adj close" in d.columns else cc
        for _,r in d.iterrows(): kr_rows.append({"name":code,"date":r[dc],"open":round(float(r[co]),2),"high":round(float(r[ch]),2),"low":round(float(r[cl]),2),"close":round(float(r[cc]),2),"adj_close":round(float(r[ca]),2),"etf_name":kr_name_kr[code]})
        print(code+"|"+kr_name[code]+"|"+str(len(d))+"|rows|"+str(d[dc].min())+"~"+str(d[dc].max()))
        kr_meta.append({"c":code,"n":kr_name[code],"nk":kr_name_kr[code],"ld":str(d[dc].min()),"r":len(d),"note":"OK"})
    except Exception as e: print(code+" ERR:"+str(e));kr_meta.append({"c":code,"n":kr_name[code],"nk":kr_name_kr.get(code,""),"ld":"ERR","r":0,"note":str(e)[:80]})
kr_df=pd.DataFrame(kr_rows)
kr_df.to_csv("C:/project/quant/sector_daily_kr.csv",index=False,encoding="utf-8-sig")
print("KR_DONE rows="+str(len(kr_df))+" syms="+str(kr_df["name"].nunique()))
for c,n in kr_df.groupby("name")["close"].nunique().items(): print("KRVFY "+c+" "+str(n))
print("KR_PRD "+str(kr_df["date"].min())+" "+str(kr_df["date"].max()))
for m in kr_meta: print("KRMETA "+m["c"]+"|"+m["n"]+"|ld="+m["ld"]+"|rows="+str(m["r"])+"|"+m["note"])
