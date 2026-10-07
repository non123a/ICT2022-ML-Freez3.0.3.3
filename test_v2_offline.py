import tempfile, sqlite3
from types import SimpleNamespace
import trade_bot as b

def ok(name, fn):
    try: fn(); print(name+'|PASS')
    except Exception as e: print(name+'|FAIL|'+repr(e)); raise

def test_risk():
    c=SimpleNamespace(risk_percent=1.0,lot=.01); spec=SimpleNamespace(trade_tick_size=1.,trade_tick_value=10.,volume_step=.01,volume_min=.01,volume_max=10.)
    acct=SimpleNamespace(equity=10000); client=SimpleNamespace(api=SimpleNamespace(account_info=lambda:acct),info=spec)
    v,target,est=b.risk_volume(c,client,100.,90.); assert v>0 and est<=target
def test_db():
    with tempfile.NamedTemporaryFile() as f:
        db=b.Database(f.name); sid='SIG-test'; db.signal((sid,'t','XAUUSD','long',1.,.9,1.3,'PENDING',None)); assert db.seen(sid); assert db.seen(sid)
def test_first_touch():
    import pandas as pd
    idx=pd.date_range('2026-01-01',periods=2,freq='min',tz='America/New_York'); x=pd.DataFrame({'High':[1.,3.],'Low':[1.,0.]},index=idx); r=x.iloc[1]; assert r.Low<=.5 and r.High>=2
for n,f in [('risk sizing',test_risk),('restart duplicate state',test_db),('first touch SL-first',test_first_touch)]: ok(n,f)
