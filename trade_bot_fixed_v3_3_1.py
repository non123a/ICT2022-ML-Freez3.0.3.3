#!/usr/bin/env python3
"""Portable single-file frozen-strategy MT5 runner.

This file intentionally performs no simulation mode. The launcher supplies
credentials locally; passwords are never logged or persisted.
"""
from __future__ import annotations
import argparse, bisect, hashlib, json, logging, math, os, sqlite3, sys, time
from dataclasses import dataclass
from pathlib import Path
import pandas as pd

HERE = Path(__file__).resolve().parent
LOG = HERE / "trade_bot.log"
TRADE_CSV = HERE / "trade_audit.csv"
SETUP_CSV = HERE / "setup_events.csv"
SL_BUFFER_POINTS = 0.00010
LAST_EXECUTION = {'state': 'IDLE', 'reason': ''}
LAST_COMPLETED_POSITION = None

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
    london_start: str = "03:00:00"
    london_end: str = "07:00:00"
    ny_start: str = "07:00:00"
    ny_end: str = "12:00:00"
    poll_seconds: int = 5

def parse_config(argv=None):
    p = argparse.ArgumentParser("Frozen ICT XAUUSD MT5 bot")
    # Authentication mirrors the old launcher: login/password/server are
    # supplied by BAT environment variables and never accepted as CLI args.
    p.add_argument("--login", type=int, default=int(os.environ.get("MT5_LOGIN", "0") or 0)); p.add_argument("--server", default=os.environ.get("MT5_SERVER", ""))
    p.add_argument("--symbol", default="XAUUSD"); p.add_argument("--pivot", type=int, default=3); p.add_argument("--ote", type=float, default=.60); p.add_argument("--sl", type=float, default=.90); p.add_argument("--tp", type=float, default=3.0)
    p.add_argument("--lot", type=float, default=.01); p.add_argument("--risk-percent", type=float, default=0.0); p.add_argument("--magic", type=int, default=20260906)
    p.add_argument("--max-spread", type=float, default=0.0); p.add_argument("--max-daily-loss", type=float, default=0.0); p.add_argument("--max-open-positions", type=int, default=1); p.add_argument("--database", default=str(HERE / "paper_trades.sqlite3")); p.add_argument("--poll-seconds", type=int, default=5)
    p.add_argument("--timezone", default=os.environ.get("TIMEZONE", "America/New_York")); p.add_argument("--london-start", default=os.environ.get("LONDON_START", "03:00:00")); p.add_argument("--london-end", default=os.environ.get("LONDON_END", "07:00:00")); p.add_argument("--ny-start", default=os.environ.get("NY_START", "07:00:00")); p.add_argument("--ny-end", default=os.environ.get("NY_END", "12:00:00"))
    a = p.parse_args(argv); c = Config(**vars(a)); c.database = str(Path(c.database).expanduser().resolve())
    c.password = os.environ.get("MT5_PASSWORD", "")
    if c.login<=0 or not c.password or not c.server: raise SystemExit("MT5_LOGIN, MT5_PASSWORD, and MT5_SERVER environment variables are required")
    if c.pivot != 3 or c.ote != .60 or c.sl != .90 or c.tp != 3.0: raise SystemExit("Frozen strategy parameters must remain Pivot 3 / OTE 0.60 / SL 0.90 / TP 3R")
    if c.risk_percent < 0 or c.lot < 0 or c.max_spread < 0 or c.max_daily_loss < 0 or c.max_open_positions < 1: raise SystemExit("Risk and limits must be non-negative")
    if c.risk_percent == 0 and c.lot <= 0: raise SystemExit("LOT must be positive when RISK_PERCENT=0")
    try:
        london_start, london_end, ny_start, ny_end = (pd.Timedelta(x) for x in (c.london_start, c.london_end, c.ny_start, c.ny_end))
    except ValueError as e:
        raise SystemExit("Session values must be valid HH:MM[:SS] times") from e
    # if not (london_start <= london_end < ny_start <= ny_end): raise SystemExit("Sessions must satisfy London start <= end < NY start <= end")
    if not (london_start <= london_end <= ny_start <= ny_end): raise SystemExit("Sessions must satisfy London start <= end <= NY start <= end")
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
    def signal_status(self, sid, status, reason=""):
        self.cx.execute("UPDATE signals SET status=?, reason=? WHERE signal_id=?", (status, reason, sid)); self.cx.commit()
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
    def latest_closed(self): return self.cx.execute("SELECT * FROM positions WHERE close_time IS NOT NULL ORDER BY close_time DESC LIMIT 1").fetchone()
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
        if not self.symbol: raise RuntimeError(f"Requested symbol {self.c.symbol!r} does not exist; refusing substitution")
        self.info=mt5.symbol_info(self.symbol)
        if not self.info.visible and not mt5.symbol_select(self.symbol,True): raise RuntimeError("Symbol selection failed")
        tick=mt5.symbol_info_tick(self.symbol)
        for name in ("volume_min","volume_max","volume_step","trade_tick_size","trade_tick_value"):
            if float(getattr(self.info,name,0) or 0)<=0: raise RuntimeError(f"Invalid broker symbol specification: {name}")
        if tick is None or float(tick.bid)<=0 or float(tick.ask)<=0: raise RuntimeError("No valid tick data")
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
        global LAST_COMPLETED_POSITION
        risk_distance=abs(float(entry)-float(sl)); side='long' if float(tp)>float(entry) else 'short'; result_r=((price-float(entry))/risk_distance if side=='long' else (float(entry)-price)/risk_distance) if risk_distance else None
        LAST_COMPLETED_POSITION={'status':'POSITION CLOSED','broker_confirmed':True,'symbol':symbol,'direction':side,'ticket':ticket,'entry_price':entry,'entry_time':opened,'exit_price':price,'exit_time':getattr(d,'time',None),'exit_reason':reason,'realized_pnl':pnl,'result_r':result_r}
        LAST_EXECUTION.update(state='POSITION_CLOSED', reason=f'ticket={ticket}')
        r=result_r if result_r is not None else ''
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
        h=df.resample(freq).agg({'Open':'first','High':'max','Low':'min','Close':'last'}).dropna(); ph,pl=pivots(h,7); ev={}; last=None; ph_i=pl_i=0; latest_ph=latest_pl=None
        step=pd.Timedelta(freq)
        ph_events=sorted((v['confirmation']+step,v['center']) for v in ph.values()); pl_events=sorted((v['confirmation']+step,v['center']) for v in pl.values())
        for t in h.index:
            while ph_i<len(ph_events) and ph_events[ph_i][0]<=t: latest_ph=ph_events[ph_i][1]; ph_i+=1
            while pl_i<len(pl_events) and pl_events[pl_i][0]<=t: latest_pl=pl_events[pl_i][1]; pl_i+=1
            if latest_ph is not None and latest_pl is not None: last='Downtrend' if latest_ph>latest_pl else 'Uptrend' if latest_pl>latest_ph else last
            ev[t]=last
        out[f'{freq}_trend']=pd.Series(ev).reindex(df.index,method='ffill')
    return pd.DataFrame(out).ffill()
def construct_order(direction, entry, structural_level, sl_ratio=1.0, tp_ratio=3.0):
    risk=abs(float(entry)-float(structural_level))*float(sl_ratio)
    sl=float(entry)-risk if direction=='long' else float(entry)+risk
    tp=float(entry)+risk*float(tp_ratio) if direction=='long' else float(entry)-risk*float(tp_ratio)
    return sl,tp

def construct_phase27_order(direction, entry, anchor, sl_ratio=.90, tp_ratio=3.0):
    """Use the same buffered structural stop arithmetic as causal_backtest.py."""
    structural_stop = float(anchor) + SL_BUFFER_POINTS if direction=='short' else float(anchor) - SL_BUFFER_POINTS
    risk=abs(float(entry)-structural_stop)*float(sl_ratio)
    sl=float(entry)+risk if direction=='short' else float(entry)-risk
    tp=float(entry)-risk*float(tp_ratio) if direction=='short' else float(entry)+risk*float(tp_ratio)
    return sl,tp,structural_stop,risk

def phase27_ote(direction, anchor, extreme, ote_parameter):
    ratio=1.0-float(ote_parameter)
    return float(anchor)-(float(anchor)-float(extreme))*ratio if direction=='short' else float(anchor)+(float(extreme)-float(anchor))*ratio

def _setup_diagnostics(s, c=None):
    """Render the exact state-machine values without recomputing strategy data."""
    broken=s.get('broken') or {}; anchor=s.get('anchor_pivot') or {}
    parameter=s.get('ote_parameter', c.ote if c is not None else .60)
    if parameter is None: parameter=c.ote if c is not None else .60
    effective=s.get('effective_retracement', 1.0-float(parameter))
    return {'sweep': 'DETECTED' if s.get('sweep') is not None else 'NONE',
            'sweep_price': s.get('sweep_price','NONE'), 'swept_level': s.get('swept_level','NONE'),
            'sweep_time': str(s['sweep']) if s.get('sweep') is not None else 'NONE',
            'bos': 'CONFIRMED' if s.get('bos') is not None else 'NONE',
            'bos_time': str(s['bos']) if s.get('bos') is not None else 'NONE',
            'bos_price': s.get('bos_price','NONE'),
            'broken_pivot_level': broken.get('value','NONE'),
            'broken_pivot_confirmation': str(broken.get('confirmation','NONE')),
            'anchor_price': anchor.get('value','NONE'),
            'anchor_center': str(anchor.get('center','NONE')),
            'anchor_confirmation': str(anchor.get('confirmation','NONE')),
            'extreme_price': s.get('extreme','NONE'),
            'extreme_time': str(s.get('extreme_time', 'NONE')),
            'ote_method': 'phase27_anchor_extreme_retrace_frozen_at_first_touch',
            'ote_parameter': parameter,
            'effective_retracement': effective,
            'ote_price': s.get('ote','NONE'),
            # 'ote_touch': 'TOUCHED' if s.get('retrace') is not None else 'NONE',
            # 'ote_touch_time': str(s.get('retrace','NONE'))}
            'ote_touch': 'TOUCHED' if s.get('retrace') is not None else 'NONE',
            'ote_touch_time': str(s.get('retrace', 'NONE')),

            'second_touch': (
                'TOUCHED' if s.get('second_touch') else
                'NONE'
            ),
            'second_touch_time': (
                str(s.get('second_touch_time'))
                if s.get('second_touch_time') is not None
                else 'NONE'
            ),
            'trend': s.get('trend', 'NONE'),
            'risk_distance': s.get('risk_distance', 'NONE'),
            'risk_ok': s.get('risk_ok', 'NONE'),
            'entry_rejection_reason': s.get('entry_rejection_reason', ''),
            }
def first_exit(direction, candles, entry_or_sl, sl_or_tp, tp=None):
    sl, tp = (sl_or_tp, tp) if tp is not None else (entry_or_sl, sl_or_tp)
    for t,r in candles.iterrows():
        hit_sl=(float(r.High)>=sl) if direction=='short' else (float(r.Low)<=sl)
        hit_tp=(float(r.Low)<=tp) if direction=='short' else (float(r.High)>=tp)
        if hit_sl or hit_tp: return t, (sl if hit_sl else tp), ('sl' if hit_sl else 'tp')
    return None,None,None
def phase27_live_state(df,c):
    """One causal Phase 27 state machine for both status and executable signal.

    ``df`` must contain closed M1 candles only. Pivot dictionaries are keyed by
    confirmation time, and ``latest`` never exposes a pivot after its key.
    """
    if df.empty or not df.index.is_monotonic_increasing or df.index.tz is None: raise ValueError("sorted timezone-aware closed M1 data required")
    newest=df.index[-1]; ph,pl=pivots(df,c.pivot); hk,lk=sorted(ph),sorted(pl); trends=causal_trends(df)
    latest_state={'timestamp':newest,'state':'WAITING_SESSION','signal':None,'diagnostics':{'timestamp':newest,'current_price':float(df.iloc[-1].Close),'session':'BEFORE LONDON','london':{},'short':{},'long':{}}}
    def latest(items, keys, t):
        i=bisect.bisect_right(keys,t)-1
        return items[keys[i]] if i>=0 else None
    for _,dd in df.groupby(df.index.date):
        if dd.index[-1].date() != newest.date():
            continue
        lon=session(dd,c.london_start,c.london_end); ny=session(dd,c.ny_start,c.ny_end)
        if lon.empty or ny.empty:
            # Diagnostic-only presentation: London can be displayed before NY
            # candles exist; the strategy still waits for its normal NY loop.
            if lon.empty:
                session_name='BEFORE LONDON' if newest.time() < pd.Timestamp(c.london_start).time() else 'AFTER NY'
                london_diag={}
            else:
                london_diag={'high':float(lon.High.max()),'high_time':str(lon.High.idxmax()),'low':float(lon.Low.min()),'low_time':str(lon.Low.idxmin())}
                start=pd.Timestamp(c.london_start).time(); end=pd.Timestamp(c.london_end).time()
                session_name='BEFORE LONDON' if newest.time() < start else 'LONDON' if newest.time() <= end else 'BETWEEN'
            latest_state={'timestamp':newest,'state':'WAITING_SESSION','signal':None,'diagnostics':{'timestamp':newest,'current_price':float(df.iloc[-1].Close),'session':session_name,'london':london_diag,'short':_setup_diagnostics({},c),'long':_setup_diagnostics({},c)}}
            continue
        lh,ll=float(lon.High.max()),float(lon.Low.min()); lh_time=str(lon.High.idxmax()); ll_time=str(lon.Low.idxmin())
        cycle_session='BEFORE LONDON' if newest < lon.index.min() else 'LONDON' if newest <= lon.index.max() else 'BETWEEN' if newest < ny.index.min() else 'NEW YORK' if newest <= ny.index.max() else 'AFTER NY'
        side={
            'short':{'sweep':None,'bos':None,'broken':None,'anchor_pivot':None,'extreme':None,'ote':None,'retrace':None},
            'long': {'sweep':None,'bos':None,'broken':None,'anchor_pivot':None,'extreme':None,'ote':None,'retrace':None},
        }
        completed=False
        for t,row in ny.iterrows():
            if completed: break
            # Phase 27 evaluates the two sweep/BOS paths independently.
            if side['short']['sweep'] is None and float(row.High)>lh: side['short'].update(sweep=t,sweep_price=float(row.High),swept_level=lh)
            if side['long']['sweep'] is None and float(row.Low)<ll: side['long'].update(sweep=t,sweep_price=float(row.Low),swept_level=ll)
            for direction in ('short','long'):
                s=side[direction]
                if s['sweep'] is None or s['bos'] is not None: continue
                broken=latest(pl,lk,t) if direction=='short' else latest(ph,hk,t)
                anchor=latest(ph,hk,t) if direction=='short' else latest(pl,lk,t)
                broke=float(row.Close)<broken['value'] if direction=='short' and broken else float(row.Close)>broken['value'] if broken else False
                if broken and anchor and broke:
                    s.update({'bos':t,'bos_price':float(row.Close),'broken':broken,'anchor_pivot':anchor,'extreme':float(row.Low if direction=='short' else row.High),'extreme_time':t})
            candidates=[]
            for direction in ('short','long'):
                s=side[direction]
                if s['bos'] is None or t<=s['bos']: continue
                # This exact conditional is the Phase 27 freeze boundary.
                if s['retrace'] is None:
                    old_extreme=s['extreme']; s['extreme']=min(s['extreme'],float(row.Low)) if direction=='short' else max(s['extreme'],float(row.High));
                    if s['extreme'] != old_extreme: s['extreme_time']=t
                    s['ote']=phase27_ote(direction,s['anchor_pivot']['value'],s['extreme'],c.ote)
                    touched=float(row.High)>=s['ote'] if direction=='short' else float(row.Low)<=s['ote']
                    if touched:
                        s['retrace']=t
                        continue
                    continue
                if t<=s['retrace']: continue
                # touched=float(row.High)>=s['ote'] if direction=='short' else float(row.Low)<=s['ote']
                # trend=trends.at[t,'1h_trend'] if t in trends.index else None
                # trend_ok=trend=='Downtrend' if direction=='short' else trend=='Uptrend'
                # if touched and trend_ok:
                #     anchor=float(s['anchor_pivot']['value']); entry=float(max(s['ote'],min(float(row.High),max(float(row.Open),float(row.Close)))) if direction=='short' else min(s['ote'],max(float(row.Low),min(float(row.Open),float(row.Close)))))
                #     sl,tp,structural_stop,risk=construct_phase27_order(direction,entry,anchor,c.sl,c.tp)
                #     if risk>=.25: candidates.append((direction,s,entry,sl,tp,structural_stop,risk,trend))
                touched = (
                    float(row.High) >= s['ote']
                    if direction == 'short'
                    else float(row.Low) <= s['ote']
                )

                trend = trends.at[t, '1h_trend'] if t in trends.index else None


                # Store second-touch diagnostics for the dashboard.
                s['second_touch'] = touched
                s['second_touch_time'] = t if touched else s.get('second_touch_time')
                s['trend'] = trend

                if touched:
                    anchor = float(s['anchor_pivot']['value'])
                    entry = (
                        float(max(
                            s['ote'],
                            min(float(row.High), max(float(row.Open), float(row.Close)))
                        ))
                        if direction == 'short'
                        else
                        float(min(
                            s['ote'],
                            max(float(row.Low), min(float(row.Open), float(row.Close)))
                        ))
                    )

                    sl, tp, structural_stop, risk = construct_phase27_order(
                        direction, entry, anchor, c.sl, c.tp
                    )

                    s['entry_candidate'] = entry
                    s['risk_distance'] = risk
                    s['risk_ok'] = risk >= 0.25

                    if risk >= 0.25:
                        candidates.append(
                            (direction, s, entry, sl, tp, structural_stop, risk, trend)
                        )
            if candidates:
                # Phase 27 runs bearish processing before bullish processing on a shared candle.
                direction,s,entry,sl,tp,structural_stop,risk,trend=candidates[0]
                provenance={'london_high':lh,'london_high_time':lh_time,'london_low':ll,'london_low_time':ll_time,'sweep_type':'HIGH' if direction=='short' else 'LOW','sweep_price':float(row.High if direction=='short' else row.Low),'sweep_time':str(s['sweep']),'swept_level':lh if direction=='short' else ll,'bos_direction':direction,'bos_price':float(row.Close),'bos_time':str(s['bos']),'bos_broken_level':s['broken']['value'],'ote_anchor_1':s['anchor_pivot']['value'],'ote_anchor_1_time':str(s['anchor_pivot']['center']),'ote_anchor_2':s['extreme'],'ote_anchor_2_time':str(s['retrace']),'ote_calculation_method':'phase27_anchor_extreme_retrace_frozen_at_first_touch','ote_ratio':c.ote,'ote_effective_retracement':1.0-c.ote,'ote_price':s['ote'],'ote_touch_price':float(row.High if direction=='short' else row.Low),'ote_touch_time':str(s['retrace']),'pivot_confirmation':str(s['anchor_pivot']['confirmation']),'pivot_level':s['anchor_pivot']['value'],'bos_pivot_confirmation':str(s['broken']['confirmation']),'bos_pivot_level':s['broken']['value'],'structural_stop_reference':structural_stop,'trend_direction':trend,'displacement_confirmation':''}
                signal={'timestamp':t,'side':direction,'entry':entry,'sl':sl,'tp':tp,'risk_distance':risk,'provenance':provenance}
                completed=True
                diagnostics={'timestamp':newest,'current_price':float(df.iloc[-1].Close),'session':cycle_session,'london':{'high':lh,'high_time':lh_time,'low':ll,'low_time':ll_time},'short':_setup_diagnostics(side['short'],c), 'long':_setup_diagnostics(side['long'],c)}
                if t==newest: return {'timestamp':newest,'state':'ENTRY_SIGNAL','signal':signal,'diagnostics':diagnostics}
                latest_state={'timestamp':newest,'state':'SIGNAL_COMPLETED','signal':None,'diagnostics':diagnostics}
            elif t==newest:
                if not any(x['sweep'] for x in side.values()):
                    stage = 'WAITING_SWEEP'
                elif not any(x['bos'] for x in side.values()):
                    stage = 'WAITING_BOS'
                elif not any(x['retrace'] for x in side.values()):
                    stage = 'WAITING_FIRST_OTE_TOUCH'
                elif any(
                    x.get('second_touch')
                    and x.get('risk_ok') is False
                    for x in side.values()
                ):
                    stage = 'SECOND_TOUCH_RISK_FILTER_FAILED'
                else:
                    stage = 'WAITING_ENTRY_TOUCH'
                latest_state={'timestamp':newest,'state':stage,'signal':None,'diagnostics':{'timestamp':newest,'current_price':float(row.Close),'session':cycle_session,'london':{'high':lh,'high_time':lh_time,'low':ll,'low_time':ll_time},'short':_setup_diagnostics(side['short'],c), 'long':_setup_diagnostics(side['long'],c)}}
    return latest_state

def run_strategy(df,c):
    """Compatibility adapter: only return a signal made by the newest closed bar."""
    state=phase27_live_state(df,c)
    return [state['signal']] if state['signal'] is not None else []

def _fmt(v):
    if v is None or v == 'NONE': return 'NONE/WAITING'
    return f'{v:.5f}' if isinstance(v,(int,float)) else str(v)

def _setup_lines(name, s):
    return [f'{name} SETUP', f"  sweep={s.get('sweep')} time={s.get('sweep_time')} price={_fmt(s.get('sweep_price','NONE'))} level={_fmt(s.get('swept_level','NONE'))}", f"  BOS={s.get('bos')} time={s.get('bos_time')} close={_fmt(s.get('bos_price'))} broken={_fmt(s.get('broken_pivot_level'))} confirmed={s.get('broken_pivot_confirmation')}", f"  Anchor price={_fmt(s.get('anchor_price'))} center={s.get('anchor_center')} confirmation={s.get('anchor_confirmation')}", f"  Extreme price={_fmt(s.get('extreme_price'))} time={s.get('extreme_time')}", f"  OTE method={s.get('ote_method')} parameter={s.get('ote_parameter'):.2f} effective={s.get('effective_retracement'):.2f} price={_fmt(s.get('ote_price'))}", f"  OTE first touch={s.get('ote_touch')} time={s.get('ote_touch_time')}",
f"  OTE second touch={s.get('second_touch','NONE')} time={s.get('second_touch_time','NONE')}",
f"  Risk={_fmt(s.get('risk_distance'))} risk_ok={s.get('risk_ok','NONE')}",
f"  Entry rejection={s.get('entry_rejection_reason') or 'NONE'}",]

def render_dashboard(state, c, client=None, position_state=None, execution_state=None, fallback=False):
    d=state.get('diagnostics',{}); ts=state.get('timestamp'); session_name=d.get('session','UNKNOWN'); lines=['PHASE 27 LIVE DEBUG DASHBOARD',f'TIMEZONE={c.timezone}  TIMESTAMP={ts}',f'CYCLE={ts.date() if hasattr(ts,"date") else ts}  SESSION={session_name}','', 'LONDON RANGE']
    lon=d.get('london',{}); lines += [f"  High={_fmt(lon.get('high'))}  time={lon.get('high_time','NONE/WAITING')}",f"  Low ={_fmt(lon.get('low'))}  time={lon.get('low_time','NONE/WAITING')}",'']
    lines += _setup_lines('SHORT',d.get('short',{})); lines += ['']; lines += _setup_lines('LONG',d.get('long',{})); lines += ['',f"CURRENT STATE={state.get('state')}  CURRENT PRICE={_fmt(d.get('current_price'))}"]
    if state.get('signal'):
        s=state['signal']; lines += [f"ENTRY SIGNAL direction={s['side']} strategy_entry={_fmt(s['entry'])} SL={_fmt(s['sl'])} TP={_fmt(s['tp'])} risk={_fmt(s.get('risk_distance'))} OTE={_fmt(s['provenance'].get('ote_price'))}"]
    if execution_state: lines += ['EXECUTION',*[(f'  {k}={v}') for k,v in execution_state.items()]]
    if position_state: lines += ['POSITION',*[(f'  {k}={v}') for k,v in position_state.items()]]
    lines += ['',f"[M1 {ts.strftime('%H:%M') if hasattr(ts,'strftime') else ts}] Close={_fmt(d.get('current_price'))} | {state.get('state')} | {_waiting_text(state.get('state'))}"]
    text='\n'.join(lines)
    if not fallback and hasattr(sys.stdout,'isatty') and sys.stdout.isatty(): sys.stdout.write('\x1b[H\x1b[2J'+text+'\n'); sys.stdout.flush()
    else: print(text)

def _waiting_text(state):
    return {'WAITING_SESSION':'Waiting for configured session','WAITING_SWEEP':'No sweep yet','WAITING_BOS':'Sweep detected, waiting for BOS','WAITING_FIRST_OTE_TOUCH':'BOS confirmed, building OTE','WAITING_ENTRY_TOUCH':'OTE established, waiting for later touch','ENTRY_SIGNAL':'Entry conditions satisfied','SIGNAL_COMPLETED':'Signal completed'}.get(state,'Monitoring')

def position_snapshot(client, db=None):
    """Read-only broker position view for the dashboard."""
    if client is None:
        if db is not None:
            rec=db.latest_closed()
            if rec:
                sid,ticket,symbol,volume,entry,sl,tp,opened,closed,close_price,reason,pnl=rec
                distance=abs(float(entry)-float(sl)); side='long' if float(tp)>float(entry) else 'short'; result_r=((float(close_price)-float(entry))/distance if side=='long' else (float(entry)-float(close_price))/distance) if distance and close_price is not None else None
                return {'status':'POSITION CLOSED','broker_confirmed':True,'symbol':symbol,'direction':side,'ticket':ticket,'entry_price':entry,'entry_time':opened,'exit_price':close_price,'exit_time':closed,'exit_reason':reason or 'N/A','realized_pnl':pnl if pnl is not None else 'N/A','result_r':result_r if result_r is not None else 'N/A'}
        return LAST_COMPLETED_POSITION or {'status':'NONE'}
    positions=client.owned_positions()
    if not positions:
        if db is not None:
            rec=db.latest_closed()
            if rec:
                sid,ticket,symbol,volume,entry,sl,tp,opened,closed,close_price,reason,pnl=rec
                distance=abs(float(entry)-float(sl)); side='long' if float(tp)>float(entry) else 'short'; result_r=((float(close_price)-float(entry))/distance if side=='long' else (float(entry)-float(close_price))/distance) if distance and close_price is not None else None
                return {'status':'POSITION CLOSED','broker_confirmed':True,'symbol':symbol,'direction':side,'ticket':ticket,'entry_price':entry,'entry_time':opened,'exit_price':close_price,'exit_time':closed,'exit_reason':reason or 'N/A','realized_pnl':pnl if pnl is not None else 'N/A','result_r':result_r if result_r is not None else 'N/A'}
        return LAST_COMPLETED_POSITION or {'status':'NONE'}
    p=positions[0]
    return {'status':'POSITION OPEN','direction':getattr(p,'type','UNKNOWN'),'ticket':getattr(p,'ticket','NONE'),'entry_price':getattr(p,'price_open','NONE'),'sl':getattr(p,'sl','NONE'),'tp':getattr(p,'tp','NONE'),'volume':getattr(p,'volume','NONE'),'open_time':getattr(p,'time','UNKNOWN')}

def execute_signal(c,client,db,row):
    sid=signal_id(client.symbol,row)
    def reject(reason, details=""):
        LAST_EXECUTION.update(state='ENTRY_REJECTED', reason=reason)
        logging.info('[REJECTED] signal_id=%s reason=%s %s',sid,reason,details)
        db.event('WARN','signal_rejected',f'{sid} {reason} {details}')
        emit_event('REJECTED',setup_payload(row,timestamp=row['timestamp'],signal_id=sid,symbol=client.symbol,direction=row['side'],reason=reason,state='rejected'),reason)
        return None
    if db.seen(sid) or any(str(getattr(p,'comment',''))==sid for p in client.owned_positions()):
        logging.info('[EXECUTION_CHECK] duplicate=FAIL signal_id=%s',sid)
        return reject('duplicate')
    logging.info('[EXECUTION_CHECK] duplicate=PASS signal_id=%s',sid)
    owned=client.owned_positions()
    if len(owned)>=c.max_open_positions:
        logging.info('[EXECUTION_CHECK] max_positions=FAIL open=%s limit=%s',len(owned),c.max_open_positions)
        return reject('MAX_OPEN_POSITIONS')
    logging.info('[EXECUTION_CHECK] max_positions=PASS open=%s limit=%s',len(owned),c.max_open_positions)
    daily_loss=client.daily_loss()
    if c.max_daily_loss>0 and daily_loss <= -c.max_daily_loss:
        logging.info('[EXECUTION_CHECK] daily_loss=FAIL value=%s limit=%s',daily_loss,c.max_daily_loss)
        return reject('DAILY_LOSS')
    logging.info('[EXECUTION_CHECK] daily_loss=PASS value=%s limit=%s',daily_loss,c.max_daily_loss)
    tick=client.api.symbol_info_tick(client.symbol)
    if tick is None or float(getattr(tick,'bid',0) or 0)<=0 or float(getattr(tick,'ask',0) or 0)<=0:
        logging.info('[EXECUTION_CHECK] tick=FAIL')
        return reject('MISSING_TICK')
    bid,ask=float(tick.bid),float(tick.ask); spread=(ask-bid)/float(client.info.point)
    if c.max_spread>0 and spread>c.max_spread:
        logging.info('[EXECUTION_CHECK] spread=FAIL value=%s limit=%s',spread,c.max_spread)
        return reject('SPREAD',f'spread={spread}')
    logging.info('[EXECUTION_CHECK] spread=PASS value=%s limit=%s',spread,c.max_spread)
    entry=ask if row['side']=='long' else bid
    anchor=float(row['provenance']['ote_anchor_1'])
    sl,tp,structural_stop,risk_distance=construct_phase27_order(row['side'],entry,anchor,c.sl,c.tp)
    geometry_ok=(sl<entry<tp) if row['side']=='long' else (tp<entry<sl)
    if not geometry_ok:
        logging.info('[EXECUTION_CHECK] geometry=FAIL strategy_entry=%.5f execution_price=%.5f sl=%.5f tp=%.5f',row['entry'],entry,sl,tp)
        return reject('invalid_live_order_geometry')
    logging.info('[EXECUTION_CHECK] geometry=PASS structural_stop=%.5f',structural_stop)
    if risk_distance<.25:
        logging.info('[EXECUTION_CHECK] risk_distance=FAIL value=%.5f minimum=0.25000',risk_distance)
        return reject('INVALID_RISK_DISTANCE')
    logging.info('[EXECUTION_CHECK] risk_distance=PASS value=%.5f',risk_distance)
    try: volume,target,estimated=risk_volume(c,client,entry,sl)
    except (ValueError, ZeroDivisionError) as e:
        logging.info('[EXECUTION_CHECK] volume=FAIL reason=%s',e)
        return reject('INVALID_VOLUME',str(e))
    if not math.isfinite(float(volume)) or float(volume)<=0:
        logging.info('[EXECUTION_CHECK] volume=FAIL value=%s',volume)
        return reject('INVALID_VOLUME')
    logging.info('[EXECUTION_CHECK] volume=PASS value=%.4f',volume)
    logging.info('[ENTRY_SIGNAL] timestamp=%s direction=%s strategy_entry=%.5f live_bid=%.5f live_ask=%.5f live_execution_price=%.5f sl=%.5f tp=%.5f risk_distance=%.5f volume=%.4f',row['timestamp'],row['side'],row['entry'],bid,ask,entry,sl,tp,risk_distance,volume)
    LAST_EXECUTION.update(state='ENTRY_CHECKS', reason='all pre-trade checks passed')
    live_provenance={**row.get('provenance',{}),'strategy_entry':float(row['entry']),'live_bid':bid,'live_ask':ask,'live_execution_price':entry,'structural_stop_reference':structural_stop,'live_sl':sl,'live_tp':tp}
    live_row={**row,'sl':sl,'tp':tp,'provenance':live_provenance}
    audit_csv(SETUP_CSV,setup_payload(live_row,timestamp=row['timestamp'],signal_id=sid,event_type='ENTRY_ALLOWED',symbol=client.symbol,direction=row['side'],price=entry,level=sl,reason='pretrade checks passed',state='order_pending'),SETUP_COLUMNS)
    db.signal((sid,str(row['timestamp']),client.symbol,row['side'],entry,sl,tp,'PENDING',json.dumps(live_provenance,default=str)))
    typ=client.api.ORDER_TYPE_BUY if row['side']=='long' else client.api.ORDER_TYPE_SELL
    req={'action':client.api.TRADE_ACTION_DEAL,'symbol':client.symbol,'volume':volume,'type':typ,'price':entry,'sl':sl,'tp':tp,'deviation':20,'magic':c.magic,'comment':sid,'type_time':client.api.ORDER_TIME_GTC,'type_filling':client.api.ORDER_FILLING_IOC}
    logging.info('[MT5_ORDER_REQUEST] symbol=%s direction=%s volume=%.4f price=%.5f sl=%.5f tp=%.5f magic=%s deviation=%s filling=%s',client.symbol,row['side'],volume,entry,sl,tp,c.magic,req['deviation'],req['type_filling'])
    result=client.api.order_send(req)
    if result is None:
        last_error=client.api.last_error() if hasattr(client.api,'last_error') else 'unavailable'
        logging.error('[ERROR] order_send returned None last_error=%s',last_error)
        db.signal_status(sid,'ERROR','ORDER_SEND_RETURNED_NONE')
        return reject('ORDER_SEND_RETURNED_NONE',f'last_error={last_error}')
    code=int(getattr(result,'retcode',-1)); order=int(getattr(result,'order',0) or 0); deal=int(getattr(result,'deal',0) or 0); fill=float(getattr(result,'price',entry) or entry)
    logging.info('[MT5_ORDER_RESULT] retcode=%s order=%s deal=%s price=%.5f volume=%s comment=%s request_id=%s',code,order,deal,fill,getattr(result,'volume',None),getattr(result,'comment',''),getattr(result,'request_id',''))
    if code not in (client.api.TRADE_RETCODE_DONE,client.api.TRADE_RETCODE_PLACED):
        comment=str(getattr(result,'comment',''))
        db.signal_status(sid,'REJECTED',f'BROKER_RETCODE_{code}: {comment}')
        return reject(f'BROKER_RETCODE_{code}',f'comment={comment}')
    ticket=order or deal
    db.cx.execute('INSERT OR REPLACE INTO orders VALUES(?,?,?,?,?,?,datetime("now"),?)',(sid,ticket,code,entry,fill,volume,str(result))); db.cx.commit()
    found=[p for p in client.owned_positions() if str(getattr(p,'symbol',''))==client.symbol]
    position=next((p for p in found if ticket and int(getattr(p,'ticket',0))==ticket), found[0] if found else None)
    logging.info('[POSITION_VERIFY] found=%s ticket=%s symbol=%s type=%s volume=%s price_open=%s sl=%s tp=%s',bool(position),getattr(position,'ticket',None),getattr(position,'symbol',None),getattr(position,'type',None),getattr(position,'volume',None),getattr(position,'price_open',None),getattr(position,'sl',None),getattr(position,'tp',None))
    if position is None:
        logging.error('[ERROR] ORDER_ACCEPTED_BUT_POSITION_NOT_FOUND signal=%s',sid)
        db.signal_status(sid,'ERROR','ORDER_ACCEPTED_BUT_POSITION_NOT_FOUND')
        emit_event('ERROR',setup_payload(live_row,timestamp=row['timestamp'],signal_id=sid,symbol=client.symbol,direction=row['side'],reason='ORDER_ACCEPTED_BUT_POSITION_NOT_FOUND',state='error'),'ORDER_ACCEPTED_BUT_POSITION_NOT_FOUND')
        return None
    open_ticket=int(getattr(position,'ticket',ticket) or ticket)
    db.position_open(sid,open_ticket,client.symbol,float(getattr(position,'volume',volume)),float(getattr(position,'price_open',fill)),sl,tp,getattr(position,'time',row['timestamp']))
    db.signal_status(sid,'FILLED')
    logging.info('[ENTRY] ORDER_ACCEPTED signal=%s order=%s deal=%s price=%.5f',sid,order,deal,fill)
    LAST_EXECUTION.update(state='POSITION_OPEN', reason=f'ticket={open_ticket}')
    return sid

def main():
    c=parse_config(); setup_logging(); db=Database(c.database); logging.info('ACCOUNT=%s SERVER=%s SYMBOL=%s PIVOT=3 OTE=.60 SL=.90 TP=3 RISK_PERCENT=%s LOT=%s MAGIC=%s MAX_SPREAD=%s MAX_DAILY_LOSS=%s MAX_OPEN_POSITIONS=%s TIMEZONE=%s LONDON=%s-%s NY=%s-%s DB=%s',c.login,c.server,c.symbol,c.risk_percent,c.lot,c.magic,c.max_spread,c.max_daily_loss,c.max_open_positions,c.timezone,c.london_start,c.london_end,c.ny_start,c.ny_end,c.database); logging.info('OTE_PARAMETER=%.2f EFFECTIVE_RETRACEMENT=%.2f',c.ote,1.0-c.ote); logging.info('[LONDON]/[SWEEP]/[BOS]/[OTE]/[ENTRY_SIGNAL]/[ENTRY]/[EXIT]/[REJECTED]/[ERROR] event labels enabled; password intentionally omitted')
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
                state=phase27_live_state(closed,c)
                logging.info('[STATE] timestamp=%s state=%s',state['timestamp'],state['state'])
                render_dashboard(state,c,client,position_state=position_snapshot(client,db),execution_state=LAST_EXECUTION)
                if state['signal'] is not None: execute_signal(c,client,db,state['signal']); render_dashboard(state,c,client,position_state=position_snapshot(client,db),execution_state=LAST_EXECUTION)
            time.sleep(5)
        except KeyboardInterrupt: break
        except Exception as e:
            logging.exception('runtime failure; stopping new orders and reconnecting: %s',e); db.event('ERROR','runtime',str(e))
            try: client.reconnect()
            except Exception: time.sleep(10)
if __name__=='__main__': main()
