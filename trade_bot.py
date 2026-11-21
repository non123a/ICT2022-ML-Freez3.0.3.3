#!/usr/bin/env python3
"""Portable single-file frozen-strategy MT5 runner.

This file intentionally performs no simulation mode. The launcher supplies
credentials locally; passwords are never logged or persisted.
"""
from __future__ import annotations
import argparse, hashlib, json, logging, math, os, sqlite3, sys, time
from dataclasses import dataclass
from pathlib import Path
import pandas as pd

HERE = Path(__file__).resolve().parent
LOG = HERE / "trade_bot.log"
TRADE_CSV = HERE / "trade_audit.csv"
SETUP_CSV = HERE / "setup_events.csv"
SL_BUFFER_POINTS = 0.00010

@dataclass
class Config:
    login: int
    password: str = ""
    server: str = ""
    symbol: str = "XAUUSD"
    pivot: int = 3
    ote: float = .60
    sl: float = .90
    tp: float = 3.0
    lot: float = .01
    risk_percent: float = 0.0
    magic: int = 20260906
    max_spread: float = 0.0
    max_daily_loss: float = 0.0
    max_open_positions: int = 1
    database: str = str(HERE / "paper_trades.sqlite3")
    timezone: str = "America/New_York"
    poll_seconds: int = 5

def parse_config(argv=None):
    p = argparse.ArgumentParser("Frozen ICT XAUUSD MT5 bot")
    # Authentication mirrors the old launcher: login/password/server are
    # supplied by BAT environment variables and never accepted as CLI args.
    p.add_argument("--login", type=int, default=int(os.environ.get("MT5_LOGIN", "0") or 0)); p.add_argument("--server", default=os.environ.get("MT5_SERVER", ""))
    p.add_argument("--symbol", default="XAUUSD"); p.add_argument("--pivot", type=int, default=3); p.add_argument("--ote", type=float, default=.60); p.add_argument("--sl", type=float, default=.90); p.add_argument("--tp", type=float, default=3.0)
    p.add_argument("--lot", type=float, default=.01); p.add_argument("--risk-percent", type=float, default=0.0); p.add_argument("--magic", type=int, default=20260906)
    p.add_argument("--max-spread", type=float, default=0.0); p.add_argument("--max-daily-loss", type=float, default=0.0); p.add_argument("--max-open-positions", type=int, default=1); p.add_argument("--database", default=str(HERE / "paper_trades.sqlite3")); p.add_argument("--poll-seconds", type=int, default=5)
    a = p.parse_args(argv); c = Config(**vars(a)); c.database = str(Path(c.database).expanduser().resolve())
    c.password = os.environ.get("MT5_PASSWORD", "")
    if c.login<=0 or not c.password or not c.server: raise SystemExit("MT5_LOGIN, MT5_PASSWORD, and MT5_SERVER environment variables are required")
    if c.pivot != 3 or c.ote != .60 or c.sl != .90 or c.tp != 3.0: raise SystemExit("Frozen strategy parameters must remain Pivot 3 / OTE 0.60 / SL 0.90 / TP 3R")
    if c.risk_percent < 0 or c.lot < 0 or c.max_spread < 0 or c.max_daily_loss < 0 or c.max_open_positions < 1: raise SystemExit("Risk and limits must be non-negative")
    if c.risk_percent == 0 and c.lot <= 0: raise SystemExit("LOT must be positive when RISK_PERCENT=0")
    return c

def setup_logging():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", handlers=[logging.FileHandler(LOG, encoding="utf-8"), logging.StreamHandler(sys.stdout)])

def audit_csv(path, row, columns):
    """Append an audit row with a stable header; never stores credentials."""
    exists=path.exists()
    frame=pd.DataFrame([{k:row.get(k,"") for k in columns}], columns=columns)
    frame.to_csv(path, mode="a", header=not exists, index=False)
def emit_event(event_type, row, message=""):
    payload=dict(row); payload['event_type']=event_type
    audit_csv(SETUP_CSV,payload,SETUP_COLUMNS)
    logging.info('[%s] %s',event_type,message)
def setup_payload(row, **extra):
    payload=dict(row); payload.update(extra)
    prov=payload.get('provenance') or {}
    if isinstance(prov, str):
        try: prov=json.loads(prov)
        except Exception: prov={}
    payload.update({k:v for k,v in prov.items() if k in SETUP_COLUMNS})
    payload['provenance']=json.dumps(prov, default=str) if prov else payload.get('provenance','')
    return payload

TRADE_COLUMNS=['signal_id','trade_id','symbol','magic_number','direction','london_high_time','london_low_time','sweep_time','bos_time','ote_touch_time','entry_time','exit_time','london_high','london_low','sweep_type','sweep_price','swept_level','bos_direction','bos_price','bos_broken_level','ote_start_price','ote_end_price','ote_calculation_method','ote_ratio','ote_price','ote_touch_price','ote_touch_time','entry_price','sl_price','tp_price','volume','risk_percent','configured_risk_percent','risk_amount','actual_estimated_risk_money','equity_before','balance_before','equity_after','balance_after','exit_price','exit_reason','realized_profit','commission','swap','result_r','result_money','pivot_confirmation','pivot_level','trend_direction','displacement_confirmation']
SETUP_COLUMNS=['timestamp','signal_id','event_type','symbol','direction','price','level','london_high','london_high_time','london_low','london_low_time','sweep_type','sweep_price','sweep_time','swept_level','bos_direction','bos_price','bos_time','bos_broken_level','ote_anchor_1','ote_anchor_1_time','ote_anchor_2','ote_anchor_2_time','ote_calculation_method','ote_ratio','ote_price','ote_touch_price','ote_touch_time','pivot_confirmation','pivot_level','trend_direction','displacement_confirmation','reason','state','provenance']

class Database:
    def __init__(self, path):
        self.cx = sqlite3.connect(path, timeout=30); self.cx.execute("PRAGMA journal_mode=WAL")
        self.cx.executescript("""CREATE TABLE IF NOT EXISTS signals(signal_id TEXT PRIMARY KEY,timestamp TEXT,symbol TEXT,direction TEXT,entry REAL,sl REAL,tp REAL,status TEXT,reason TEXT,provenance TEXT,created_at TEXT DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS orders(signal_id TEXT PRIMARY KEY,ticket INTEGER,retcode INTEGER,requested_price REAL,fill_price REAL,volume REAL,order_time TEXT,details TEXT);
        CREATE TABLE IF NOT EXISTS positions(signal_id TEXT PRIMARY KEY,ticket INTEGER,symbol TEXT,volume REAL,entry REAL,sl REAL,tp REAL,open_time TEXT,close_time TEXT,close_price REAL,exit_reason TEXT,pnl REAL);
        CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY,event_time TEXT,level TEXT,event TEXT,details TEXT);""");
        try: self.cx.execute("ALTER TABLE signals ADD COLUMN provenance TEXT")
        except sqlite3.OperationalError: pass
        self.cx.commit()
    def event(self, level, event, details=""): self.cx.execute("INSERT INTO events(event_time,level,event,details) VALUES(datetime('now'),?,?,?)", (level,event,details)); self.cx.commit()
    def seen(self, sid): return self.cx.execute("SELECT 1 FROM signals WHERE signal_id=?", (sid,)).fetchone() is not None
    def signal(self, row):
        vals=list(row)
        if len(vals)==8: vals.append("")
        self.cx.execute("INSERT OR IGNORE INTO signals(signal_id,timestamp,symbol,direction,entry,sl,tp,status,reason,provenance) VALUES(?,?,?,?,?,?,?,?,?,?)", (vals[0],vals[1],vals[2],vals[3],vals[4],vals[5],vals[6],vals[7],"",vals[8])); self.cx.commit()
    def signal_provenance(self, sid):
        r=self.cx.execute("SELECT provenance FROM signals WHERE signal_id=?",(sid,)).fetchone()
        try: return json.loads(r[0]) if r and r[0] else {}
        except Exception: return {}
    def trade_audit_exists(self, sid):
        return self.cx.execute("SELECT 1 FROM events WHERE event='trade_audit_written' AND details LIKE ?",(f"%{sid}%",)).fetchone() is not None
    def position_open(self, signal_id, ticket, symbol, volume, entry, sl, tp, opened):
        self.cx.execute("INSERT OR REPLACE INTO positions(signal_id,ticket,symbol,volume,entry,sl,tp,open_time) VALUES(?,?,?,?,?,?,?,?)",(signal_id,ticket,symbol,volume,entry,sl,tp,str(opened))); self.cx.commit()
    def position_close(self, signal_id, closed, price, reason, pnl):
        self.cx.execute("UPDATE positions SET close_time=?,close_price=?,exit_reason=?,pnl=? WHERE signal_id=?",(str(closed),price,reason,pnl,signal_id)); self.cx.commit()
    def open_records(self): return self.cx.execute("SELECT * FROM positions WHERE close_time IS NULL").fetchall()
MT5_TERMINAL_PATH = r"C:\Program Files\MetaTrader 5\terminal64.exe"
class MT5Client:
    def __init__(self, c): self.c=c; self.api=None; self.symbol=None; self.info=None
    def connect(self):
        try: import MetaTrader5 as mt5
        except ImportError as e: raise RuntimeError("MetaTrader5 package is missing") from e
        self.api=mt5
        if not mt5.initialize(path=MT5_TERMINAL_PATH): raise RuntimeError(f"MT5 initialize failed: {mt5.last_error()}")
        if not mt5.login(self.c.login, password=self.c.password, server=self.c.server): raise RuntimeError(f"MT5 login failed: {mt5.last_error()}")
        acct=mt5.account_info()
        if acct is None or int(acct.login)!=self.c.login: raise RuntimeError("Connected account does not match --login")
        if not bool(getattr(acct,"trade_allowed",True)) or not bool(getattr(acct,"trade_expert",True)): raise RuntimeError("Account trading is not permitted")
        if getattr(acct,"server",self.c.server) != self.c.server: raise RuntimeError("Connected account server does not match --server")
        self.symbol=self.c.symbol if mt5.symbol_info(self.c.symbol) else None
        if not self.symbol:
            raise RuntimeError(f"Requested symbol {self.c.symbol!r} does not exist; refusing substitution")

        self.info=mt5.symbol_info(self.symbol)
        logging.info(
            "[MT5] symbol_info name=%s visible=%s select=%s trade_mode=%s "
            "digits=%s point=%s",
            getattr(self.info, "name", self.symbol),
            getattr(self.info, "visible", None),
            getattr(self.info, "select", None),
            getattr(self.info, "trade_mode", None),
            getattr(self.info, "digits", None),
            getattr(self.info, "point", None),
        )

        # Make XAUUSD visible in Market Watch even when the terminal did not
        # already have it selected. Do not substitute another symbol.
        if not bool(getattr(self.info, "visible", False)):
            selected=mt5.symbol_select(self.symbol, True)
            logging.info("[MT5] symbol_select(%s)=%s last_error=%s", self.symbol, selected, mt5.last_error())
            if not selected:
                raise RuntimeError(f"Symbol selection failed for {self.symbol!r}: {mt5.last_error()}")

            self.info=mt5.symbol_info(self.symbol)
            if self.info is None:
                raise RuntimeError(f"Symbol disappeared after selection: {self.symbol!r}")

        for name in ("volume_min","volume_max","volume_step","trade_tick_size","trade_tick_value"):
            if float(getattr(self.info,name,0) or 0)<=0:
                raise RuntimeError(f"Invalid broker symbol specification: {name}")

        # A successful login does not guarantee that the terminal has already
        # delivered a quote for the selected symbol. Wait briefly for a real
        # broker tick instead of failing immediately. No synthetic/previous
        # OHLC price is ever used as a substitute.
        tick=None
        deadline=time.monotonic()+15.0
        while time.monotonic() < deadline:
            tick=mt5.symbol_info_tick(self.symbol)
            bid=float(getattr(tick, "bid", 0) or 0) if tick is not None else 0.0
            ask=float(getattr(tick, "ask", 0) or 0) if tick is not None else 0.0
            if bid>0 and ask>0:
                logging.info("[MT5] live tick received symbol=%s bid=%.5f ask=%.5f spread_points=%.2f",
                             self.symbol, bid, ask,
                             (ask-bid)/float(self.info.point) if float(self.info.point)>0 else 0.0)
                break
            logging.warning(
                "[MT5] waiting for live tick symbol=%s tick=%r last_error=%s",
                self.symbol, tick, mt5.last_error()
            )
            time.sleep(1)

        if tick is None or float(getattr(tick, "bid", 0) or 0)<=0 or float(getattr(tick, "ask", 0) or 0)<=0:
            raise RuntimeError(
                f"No valid live tick data for {self.symbol!r} after 15 seconds; "
                f"MT5 last_error={mt5.last_error()}"
            )

        logging.info("MT5 account=%s server=%s symbol=%s equity=%s",acct.login,acct.server,self.symbol,acct.equity)
    def rates(self, n=3000): return self.api.copy_rates_from_pos(self.symbol,self.api.TIMEFRAME_M1,0,n)
    def positions(self): return list(self.api.positions_get(symbol=self.symbol) or [])
    def owned_positions(self): return [p for p in self.positions() if int(getattr(p,'magic',-1))==self.c.magic]
    def reconnect(self):
        try: self.api.shutdown()
        except Exception: pass
        time.sleep(2); self.connect()
    def daily_loss(self):
        now=pd.Timestamp.now(tz=self.c.timezone); start=now.normalize().to_pydatetime(); deals=self.api.history_deals_get(start,now.to_pydatetime()) or []
        return sum(float(getattr(d,'profit',0))+float(getattr(d,'commission',0))+float(getattr(d,'swap',0)) for d in deals if int(getattr(d,'magic',-1))==self.c.magic and getattr(d,'symbol','')==self.symbol)
    def closed_deals(self, since):
        now=pd.Timestamp.now(tz=self.c.timezone); return list(self.api.history_deals_get(since.to_pydatetime(),now.to_pydatetime(),group=self.symbol) or [])

def reconcile_closed(client, db):
    """Use broker history to close local records; never infer a close."""
    for rec in db.open_records():
        sid,ticket,symbol,volume,entry,sl,tp,opened,*_=rec
        deals=client.closed_deals(pd.Timestamp(opened))
        exits=[d for d in deals if int(getattr(d,'position_id',0))==int(ticket) and int(getattr(d,'entry',0))==1]
        if not exits: continue
        d=sorted(exits,key=lambda x:getattr(x,'time',0))[-1]; price=float(getattr(d,'price',0)); pnl=float(getattr(d,'profit',0)); reason=str(getattr(d,'reason','UNKNOWN')).upper(); db.position_close(sid,getattr(d,'time',None),price,reason,pnl)
        risk_distance=abs(float(entry)-float(sl)); side='long' if float(tp)>float(entry) else 'short'; r=((price-float(entry))/risk_distance if side=='long' else (float(entry)-price)/risk_distance) if risk_distance else ''
        if db.trade_audit_exists(sid): continue
        prov=db.signal_provenance(sid)
        audit_row={'signal_id':sid,'trade_id':str(ticket),'symbol':symbol,'magic_number':client.c.magic,'direction':side,'entry_price':entry,'sl_price':sl,'tp_price':tp,'volume':volume,'entry_time':opened,'exit_time':getattr(d,'time',None),'exit_price':price,'exit_reason':reason,'realized_profit':pnl,'result_money':pnl,'result_r':r}
        audit_row.update(prov); audit_csv(TRADE_CSV,audit_row,TRADE_COLUMNS); db.event('INFO','trade_audit_written',sid)
        logging.info('[EXIT] signal=%s time=%s price=%.5f reason=%s PnL=%.2f',sid,getattr(d,'time',None),price,reason,pnl)

def risk_volume(c, client, entry, sl):
    if c.risk_percent == 0: return c.lot, None, None
    acct=client.api.account_info(); equity=float(acct.equity); distance=abs(float(entry)-float(sl)); spec=client.info; tick_size=float(spec.trade_tick_size); tick_value=float(spec.trade_tick_value)
    target=equity*c.risk_percent/100.0; raw=target/(distance/tick_size*tick_value); step=float(spec.volume_step); volume=math.floor(raw/step+1e-12)*step
    if volume < float(spec.volume_min): raise ValueError("Risk-based volume is below broker minimum")
    volume=min(volume,float(spec.volume_max)); estimated=volume*(distance/tick_size*tick_value)
    logging.info("risk sizing equity=%.2f requested_pct=%.4f requested_money=%.2f entry=%.5f sl=%.5f distance=%.5f volume=%.4f estimated_money=%.2f",equity,c.risk_percent,target,entry,sl,distance,volume,estimated)
    return volume,target,estimated

def signal_id(symbol, row): return "SIG-" + hashlib.sha256(f"{symbol}|{row['timestamp']}|{row['side']}|P3-O60-S090-T300".encode()).hexdigest()[:24]
def load_csv(path):
    d=pd.read_csv(path,header=None,names=['Date','Time','Open','High','Low','Close','Volume']); t=pd.to_datetime(d.Date+' '+d.Time,format='%Y.%m.%d %H:%M',errors='coerce').dt.tz_localize('America/New_York',nonexistent='shift_forward',ambiguous='NaT'); return d.assign(ts=t).dropna(subset=['ts']).set_index('ts')[['Open','High','Low','Close']].astype(float)

def pivots(df,k):
    w=2*k+1; hi=df.High.rolling(w,center=True,min_periods=w).max(); lo=df.Low.rolling(w,center=True,min_periods=w).min(); ph={}; pl={}
    for i in range(len(df)):
        if i+k<len(df) and pd.notna(hi.iloc[i]) and df.High.iloc[i]==hi.iloc[i]: ph[df.index[i+k]]={'center':df.index[i],'confirmation':df.index[i+k],'value':float(df.High.iloc[i])}
        if i+k<len(df) and pd.notna(lo.iloc[i]) and df.Low.iloc[i]==lo.iloc[i]: pl[df.index[i+k]]={'center':df.index[i],'confirmation':df.index[i+k],'value':float(df.Low.iloc[i])}
    return ph,pl
def session(d,s,e):
    n=d.index[0].normalize(); return d.loc[(d.index>=n+pd.Timedelta(s))&(d.index<=n+pd.Timedelta(e))]
def causal_trends(df):
    out={}
    for freq in ('1h','4h'):
        h=df.resample(freq).agg({'Open':'first','High':'max','Low':'min','Close':'last'}).dropna(); ph,pl=pivots(h,7); ev={}; last=None
        for t in h.index:
            highs=[v for v in ph.values() if v['confirmation']+pd.Timedelta(freq)<=t]; lows=[v for v in pl.values() if v['confirmation']+pd.Timedelta(freq)<=t]
            if highs and lows: last='Downtrend' if highs[-1]['center']>lows[-1]['center'] else 'Uptrend'
            ev[t]=last
        out[f'{freq}_trend']=pd.Series(ev).reindex(df.index,method='ffill')
    return pd.DataFrame(out).ffill()
def construct_order(direction, entry, structural_level, sl_ratio=1.0, tp_ratio=3.0):
    risk=abs(float(entry)-float(structural_level))*float(sl_ratio)
    sl=float(entry)-risk if direction=='long' else float(entry)+risk
    tp=float(entry)+risk*float(tp_ratio) if direction=='long' else float(entry)-risk*float(tp_ratio)
    return sl,tp
def first_exit(direction, candles, entry_or_sl, sl_or_tp, tp=None):
    sl, tp = (sl_or_tp, tp) if tp is not None else (entry_or_sl, sl_or_tp)
    for t,r in candles.iterrows():
        hit_sl=(float(r.High)>=sl) if direction=='short' else (float(r.Low)<=sl)
        hit_tp=(float(r.Low)<=tp) if direction=='short' else (float(r.High)>=tp)
        if hit_sl or hit_tp: return t, (sl if hit_sl else tp), ('sl' if hit_sl else 'tp')
    return None,None,None
def run_strategy(df,c):
    if not df.index.is_monotonic_increasing or df.index.tz is None: raise ValueError("sorted timezone-aware data required")
    out=[]; import bisect
    for day,dd in df.groupby(df.index.date):
        lon=session(dd,'03:00:00','07:00:00'); ny=session(dd,'07:00:00','12:00:00')
        if lon.empty or ny.empty: continue
        lh,ll=float(lon.High.max()),float(lon.Low.min()); lh_time=str(lon.High.idxmax()); ll_time=str(lon.Low.idxmin()); sweep=None; direction=None; bos=None; pivot=None; retrace=None; extreme=None; done=False
        for t,row in ny.iterrows():
            if done: break
            prefix=df.loc[:t]; assert prefix.index.max()<=t; ph,pl=pivots(prefix,c.pivot); hk,lk=sorted(ph),sorted(pl)
            def latest(x,k):
                i=bisect.bisect_right(k,t)-1; return x[k[i]] if i>=0 else None
            if sweep is None:
                if row.High>lh: sweep=t; direction='short'
                elif row.Low<ll: sweep=t; direction='long'
            if sweep is None: continue
            if bos is None:
                p=latest(pl if direction=='short' else ph,lk if direction=='short' else hk)
                if p and ((direction=='short' and row.Close<p['value']) or (direction=='long' and row.Close>p['value'])): bos=t; pivot=p; extreme=float(row.Low if direction=='short' else row.High)
            if bos is None or t<=bos: continue
            extreme=min(extreme,float(row.Low)) if direction=='short' else max(extreme,float(row.High)); anchor=pivot['value']; ote=anchor-(anchor-extreme)*(1-c.ote) if direction=='short' else anchor+(extreme-anchor)*(1-c.ote)
            if retrace is None and ((direction=='short' and row.High>=ote) or (direction=='long' and row.Low<=ote)): retrace=t; continue
            if retrace is None or t<=retrace: continue
            if not ((direction=='short' and row.High>=ote) or (direction=='long' and row.Low<=ote)): continue
            e=float(max(ote,min(row.High,max(row.Open,row.Close)))) if direction=='short' else float(min(ote,max(row.Low,min(row.Open,row.Close)))); sl,tp=construct_order(direction,e,anchor,c.sl,c.tp)
            if abs(e-sl)<.25: continue
            provenance={'london_high':lh,'london_high_time':lh_time,'london_low':ll,'london_low_time':ll_time,'sweep_type':'HIGH' if direction=='short' else 'LOW','sweep_price':float(row.High if direction=='short' else row.Low),'sweep_time':str(sweep),'swept_level':lh if direction=='short' else ll,'bos_direction':direction,'bos_price':float(row.Close),'bos_time':str(bos),'bos_broken_level':pivot.get('value') if pivot else '','ote_anchor_1':anchor,'ote_anchor_1_time':str(pivot.get('center')) if pivot else '','ote_anchor_2':extreme,'ote_anchor_2_time':str(t),'ote_calculation_method':'anchor_extreme_retrace','ote_ratio':c.ote,'ote_price':ote,'ote_touch_price':float(row.High if direction=='short' else row.Low),'ote_touch_time':str(retrace),'pivot_confirmation':str(pivot.get('confirmation')) if pivot else '','pivot_level':pivot.get('value') if pivot else '','trend_direction':'','displacement_confirmation':''}
            for xt,x in df.loc[df.index>t].iterrows():
                hit_sl=x.High>=sl if direction=='short' else x.Low<=sl; hit_tp=x.Low<=tp if direction=='short' else x.High>=tp
                if hit_sl or hit_tp: out.append({'timestamp':t,'side':direction,'entry':e,'sl':sl,'tp':tp,'pivot':pivot,'bos':bos,'ote':ote,'provenance':provenance,'exit_timestamp':xt,'exit_price':sl if hit_sl else tp,'exit_reason':'sl' if hit_sl else 'tp','R':-1 if hit_sl else c.tp}); break
            done=True
    return out

def execute_signal(c,client,db,row):
    sid=signal_id(client.symbol,row)
    if db.seen(sid) or any(str(getattr(p,'comment',''))==sid for p in client.owned_positions()):
        logging.info('[REJECT] duplicate signal_id=%s',sid); audit_csv(SETUP_CSV,{'timestamp':row['timestamp'],'signal_id':sid,'event_type':'REJECTED','symbol':client.symbol,'direction':row['side'],'reason':'duplicate','state':'already_processed'},SETUP_COLUMNS); return
    owned=client.owned_positions()
    if len(owned)>=c.max_open_positions: db.event('WARN','rejected_max_positions',sid); emit_event('REJECTED',{'timestamp':row['timestamp'],'signal_id':sid,'symbol':client.symbol,'direction':row['side'],'reason':'MAX_OPEN_POSITIONS','state':'rejected'}); return
    if c.max_daily_loss>0 and client.daily_loss() <= -c.max_daily_loss: db.event('WARN','rejected_daily_loss',sid); emit_event('REJECTED',{'timestamp':row['timestamp'],'signal_id':sid,'symbol':client.symbol,'direction':row['side'],'reason':'DAILY_LOSS','state':'rejected'}); return
    tick=client.api.symbol_info_tick(client.symbol); spread=(float(tick.ask)-float(tick.bid))/float(client.info.point)
    if c.max_spread>0 and spread>c.max_spread: db.event('WARN','rejected_spread',f'{sid} spread={spread}'); emit_event('REJECTED',{'timestamp':row['timestamp'],'signal_id':sid,'symbol':client.symbol,'direction':row['side'],'reason':'SPREAD','state':'rejected'}); return
    entry=float(tick.ask) if row['side']=='long' else float(tick.bid)
    try: volume,target,estimated=risk_volume(c,client,entry,row['sl'])
    except ValueError as e: emit_event('REJECTED',{'timestamp':row['timestamp'],'signal_id':sid,'symbol':client.symbol,'direction':row['side'],'reason':str(e),'state':'rejected'}); return
    logging.info('[ENTRY] signal_id=%s direction=%s entry=%.5f sl=%.5f tp=%.5f volume=%.4f risk_percent=%.4f risk_amount=%s',sid,row['side'],entry,row['sl'],row['tp'],volume,c.risk_percent,target)
    audit_csv(SETUP_CSV,setup_payload(row,timestamp=row['timestamp'],signal_id=sid,event_type='ENTRY_ALLOWED',symbol=client.symbol,direction=row['side'],price=entry,level=row['sl'],reason='pretrade checks passed',state='order_pending'),SETUP_COLUMNS)
    db.signal((sid,str(row['timestamp']),client.symbol,row['side'],entry,row['sl'],row['tp'],'PENDING',json.dumps(row.get('provenance',{}),default=str)))
    typ=client.api.ORDER_TYPE_BUY if row['side']=='long' else client.api.ORDER_TYPE_SELL
    req={'action':client.api.TRADE_ACTION_DEAL,'symbol':client.symbol,'volume':volume,'type':typ,'price':entry,'sl':row['sl'],'tp':row['tp'],'deviation':20,'magic':c.magic,'comment':sid,'type_time':client.api.ORDER_TIME_GTC,'type_filling':client.api.ORDER_FILLING_IOC}
    result=client.api.order_send(req); code=int(getattr(result,'retcode',-1)); ticket=int(getattr(result,'order',0) or getattr(result,'deal',0) or 0)
    if code not in (client.api.TRADE_RETCODE_DONE,client.api.TRADE_RETCODE_PLACED): db.event('ERROR','order_rejected',f'{sid} retcode={code} result={result}'); emit_event('REJECTED',{'timestamp':row['timestamp'],'signal_id':sid,'symbol':client.symbol,'direction':row['side'],'reason':f'BROKER_RETCODE_{code}','state':'rejected'}); return
    fill=float(getattr(result,'price',entry)); db.cx.execute('INSERT OR REPLACE INTO orders VALUES(?,?,?,?,?,?,datetime("now"),?)',(sid,ticket,code,entry,fill,volume,str(result))); db.position_open(sid,ticket,client.symbol,volume,fill,row['sl'],row['tp'],getattr(result,'time',row['timestamp'])); db.cx.execute('UPDATE signals SET status=? WHERE signal_id=?',('FILLED',sid)); db.cx.commit(); logging.info('[ENTRY] ORDER ACCEPTED signal=%s ticket=%s',sid,ticket)

def main():
    c=parse_config(); setup_logging(); db=Database(c.database); logging.info('ACCOUNT=%s SERVER=%s SYMBOL=%s PIVOT=3 OTE=.60 SL=.90 TP=3 RISK_PERCENT=%s LOT=%s MAGIC=%s MAX_SPREAD=%s MAX_DAILY_LOSS=%s MAX_OPEN_POSITIONS=%s TIMEZONE=%s DB=%s',c.login,c.server,c.symbol,c.risk_percent,c.lot,c.magic,c.max_spread,c.max_daily_loss,c.max_open_positions,c.timezone,c.database); logging.info('[LONDON]/[SWEEP]/[BOS]/[OTE]/[ENTRY]/[EXIT]/[REJECT]/[ERROR] event labels enabled; password intentionally omitted')
    client=MT5Client(c); client.connect(); reconcile_closed(client,db); logging.info('LIVE MT5 BOT ENABLED — REAL ORDERS MAY BE SENT')
    last=None
    while True:
        try:
            rates=client.rates()
            if rates is None or len(rates)<3: raise RuntimeError('M1 data unavailable')
            x=pd.DataFrame(rates); x['time']=pd.to_datetime(x.time,unit='s',utc=True).dt.tz_convert(c.timezone); x=x.set_index('time').rename(columns={'open':'Open','high':'High','low':'Low','close':'Close'})[['Open','High','Low','Close']].astype(float); closed=x.iloc[:-1]; newest=closed.index[-1]
            if newest!=last:
                last=newest
                reconcile_closed(client,db)
                for row in run_strategy(closed,c): execute_signal(c,client,db,row)
            time.sleep(5)
        except KeyboardInterrupt: break
        except Exception as e:
            logging.exception('runtime failure; stopping new orders and reconnecting: %s',e); db.event('ERROR','runtime',str(e))
            try: client.reconnect()
            except Exception: time.sleep(10)
if __name__=='__main__': main()