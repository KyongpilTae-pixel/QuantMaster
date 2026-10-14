import os, sys, numpy as np, pandas as pd, yfinance as yf
from datetime import datetime

TOP_US=6; LOOKBACK_DAYS=126; MA_DAYS=100; STOP_PCT=0.15
DATA_START='2018-01-01'; SIGNAL_START=pd.Timestamp('2019-01-01')
TODAY=datetime.today().strftime('%Y-%m-%d')
US_UNIVERSE=['AAPL','MSFT','NVDA','AMZN','META','GOOGL','AVGO','TSLA',
             'JPM','V','LLY','UNH','XOM','MA','COST','HD','NFLX','AMD','CRM','ADBE']
OUT_CSV=os.path.join(os.path.dirname(os.path.abspath(__file__)),'us_momentum_trades.csv')

def fetch_prices():
    print('[1/4] yfinance 개별 다운로드...')
    sm={}
    for tk in US_UNIVERSE:
        try:
            df=yf.Ticker(tk).history(start=DATA_START,end=TODAY,auto_adjust=True)
            if df.empty: print(f'  {tk}: empty'); continue
            s=df['Close'].copy(); s.index=s.index.tz_localize(None); s.name=tk
            sm[tk]=s; print(f'  {tk}: {len(s)} rows')
        except Exception as e: print(f'  {tk}: FAIL {e}')
    px=pd.DataFrame(sm).sort_index()
    snips={c:tuple(px[c].dropna().iloc[:8].round(4).tolist()) for c in px.columns}
    uc=len(set(snips.values())); tc=len(px.columns)
    print(f'[검증] 고유시계열 {uc}/{tc}')
    if uc!=tc:
        d={}
        for c,v in snips.items(): d.setdefault(v,[]).append(c)
        for v,cs in d.items():
            if len(cs)>1: print(f'  중복: {cs}')
        sys.exit(1)
    return px

def picks_us_mom(prices, cutoff, top_n=TOP_US):
    h=prices[prices.index<=cutoff].dropna(axis=1,how='all')
    if len(h)<LOOKBACK_DAYS+5: return []
    m6=h.iloc[-1]/h.iloc[-LOOKBACK_DAYS]-1
    m12=h.iloc[-1]/h.iloc[min(-252,-len(h))]-1
    score=m6.rank(pct=True)*0.6+m12.rank(pct=True).fillna(0.5)*0.4
    return list(pd.DataFrame({'s':score}).dropna().sort_values('s',ascending=False).head(top_n).index)

def run_simulation(prices):
    daily_idx=prices[prices.index>=SIGNAL_START].index
    month_ends=set(prices[prices.index>=SIGNAL_START].resample('ME').last().index)
    ma100=prices.rolling(MA_DAYS,min_periods=MA_DAYS).mean()
    positions={}; trades=[]
    print(f'[2/4] 시뮬 {SIGNAL_START.date()}~{daily_idx[-1].date()} {len(daily_idx)}일')
    for date in daily_idx:
        to_exit=[]
        for tk,info in list(positions.items()):
            if tk not in prices.columns: continue
            cur=prices.at[date,tk] if date in prices.index else float('nan')
            if cur!=cur: continue
            entry=info['entry_price']; stop=entry*(1-STOP_PCT)
            ma=(ma100.at[date,tk] if(date in ma100.index and tk in ma100.columns) else float('nan'))
            reason=None
            if (ma==ma) and cur<ma: reason='ma100_break'
            elif cur<stop: reason='stop_-15'
            if reason: to_exit.append((tk,reason,date,cur))
        for tk,reason,ed,ep in to_exit:
            info=positions.pop(tk); ets=pd.Timestamp(info['entry_date'])
            hd=(ed-ets).days; ret=round((ep/info['entry_price']-1)*100,4)
            trades.append({'strategy':'us_mom','ticker':tk,
                'entry_date':info['entry_date'],'entry_price':round(info['entry_price'],4),
                'exit_date':str(ed.date()),'exit_price':round(ep,4),
                'holding_days':hd,'return_pct':ret,'exit_reason':reason,'entry_year':ets.year})
        if date in month_ends:
            for tk in picks_us_mom(prices,date):
                if tk not in positions and tk in prices.columns:
                    p=prices.at[date,tk]
                    if p==p: positions[tk]={'entry_date':str(date.date()),'entry_price':float(p)}
    last=daily_idx[-1]
    print(f'[3/4] still_open {len(positions)}종목')
    for tk,info in positions.items():
        if tk not in prices.columns: continue
        s=prices[tk].dropna(); cur=float(s.iloc[-1]) if len(s)>0 else float('nan')
        ets=pd.Timestamp(info['entry_date']); hd=(last-ets).days
        ret=round((cur/info['entry_price']-1)*100,4) if cur==cur else None
        trades.append({'strategy':'us_mom','ticker':tk,
            'entry_date':info['entry_date'],'entry_price':round(info['entry_price'],4),
            'exit_date':str(last.date()),'exit_price':round(cur,4) if cur==cur else None,
            'holding_days':hd,'return_pct':ret,'exit_reason':'still_open','entry_year':ets.year})
    return trades

def main():
    print('=== US Momentum 매매이력 cloud-052 ===')
    prices=fetch_prices(); trades=run_simulation(prices)
    cols=['strategy','ticker','entry_date','entry_price',
          'exit_date','exit_price','holding_days','return_pct','exit_reason','entry_year']
    df=pd.DataFrame(trades,columns=cols)
    df=df.sort_values(['entry_date','ticker']).reset_index(drop=True)
    df.to_csv(OUT_CSV,index=False,encoding='utf-8-sig')
    print(f'[4/4] {OUT_CSV}')
    print(f'  거래수: {len(df)}')
    print(f'  기간: {df.entry_date.min()} ~ {df.exit_date.max()}')
    print(f'  종목수: {df.ticker.nunique()}')
    print(df.exit_reason.value_counts().to_string())
    print(df.entry_year.value_counts().sort_index().to_string())

if __name__=='__main__':
    main()
