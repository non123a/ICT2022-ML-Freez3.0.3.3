import pandas as pd
import trade_bot as b
def run(name,fn):
 try: fn(); print(name+'|PASS')
 except Exception as e: print(name+'|FAIL|'+repr(e)); raise
idx=pd.date_range('2024-01-01',periods=40,freq='min',tz='America/New_York')
def frame(): return pd.DataFrame({'Open':1.,'High':1.,'Low':0.,'Close':1.},index=idx)
def pivot():
 x=frame(); x.iloc[10,x.columns.get_loc('High')]=2; ph,_=b.pivots(x,3); assert idx[10] not in ph and idx[13] in ph
def future():
 x=frame(); x.iloc[10,x.columns.get_loc('High')]=2; ph,_=b.pivots(x.iloc[:13],3); assert idx[13] not in ph
def htf():
 x=frame(); assert b.session(x,'00:00:00','00:10:00').index.max()==idx[10]
def orders():
 sl,tp=b.construct_order('long',100,99); assert tp==100+(100-sl)*3; sl2,tp2=b.construct_order('short',100,101); assert tp2==100-(sl2-100)*3
def exits():
 x=pd.DataFrame({'High':[1,3],'Low':[1,0]},index=idx[:2]); t,p,r=b.first_exit('long',x,1,0.5,2); assert t==idx[1] and r=='sl'
for n,f in [('pivot confirmation',pivot),('future rejection',future),('HTF closed boundary',htf),('entry construction',orders),('SL-first first-touch',exits)]: run(n,f)
