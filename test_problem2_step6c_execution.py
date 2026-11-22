from pathlib import Path
import importlib.util
import sys
from types import SimpleNamespace

SOURCE = Path(__file__).with_name('trade_bot_fixed_v3_3_2_fundingPips.py')
spec = importlib.util.spec_from_file_location('bot_step6c', SOURCE)
bot = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = bot
spec.loader.exec_module(bot)

class FakeDB:
    def __init__(self):
        self.events=[]; self.signals=[]; self.status=[]; self.position=None
        self.cx=SimpleNamespace(execute=lambda *a, **k: None, commit=lambda: None)
    def seen(self, sid): return False
    def event(self, *args): self.events.append(args)
    def signal(self, row): self.signals.append(row)
    def signal_status(self, *args): self.status.append(args)
    def position_open(self, *args): self.position=args

class FakeAPI:
    ORDER_TYPE_BUY=0; ORDER_TYPE_SELL=1
    TRADE_ACTION_DEAL=1; ORDER_TIME_GTC=0; ORDER_FILLING_IOC=1
    TRADE_RETCODE_DONE=10009; TRADE_RETCODE_PLACED=10008
    def __init__(self, side, bid, ask):
        self.tick=SimpleNamespace(bid=bid, ask=ask)
        self.side=side; self.sent=[]; self.position=None
    def symbol_info_tick(self, symbol): return self.tick
    def account_info(self): return SimpleNamespace(equity=10000, margin_free=10000)
    def order_calc_profit(self, order_type, symbol, volume, entry, sl):
        return -abs(entry-sl)*100*volume
    def order_calc_margin(self, typ, symbol, volume, entry): return 100*volume
    def order_send(self, req):
        self.sent.append(dict(req))
        self.position=SimpleNamespace(symbol='XAUUSD', ticket=98765, magic=20260906,
            comment=req['comment'], volume=req['volume'], price_open=req['price'],
            sl=req['sl'], tp=req['tp'], time=123456)
        return SimpleNamespace(retcode=self.TRADE_RETCODE_DONE, order=98765,
            deal=12345, price=req['price'], volume=req['volume'], comment='done', request_id=1)

class FakeClient:
    def __init__(self, side, bid, ask):
        self.symbol='XAUUSD'; self.info=SimpleNamespace(volume_min=.01, volume_max=100,
            volume_step=.01, point=.01)
        self.api=FakeAPI(side,bid,ask); self.c=SimpleNamespace(magic=20260906)
    def owned_positions(self): return [self.api.position] if self.api.position else []
    def daily_loss(self): return 0

# Silence file output; keep actual execute_signal and risk_volume code.
bot.audit_csv=lambda *args, **kwargs: None
bot.emit_event=lambda *args, **kwargs: None
bot.setup_payload=lambda row, **kwargs: {**row, **kwargs}
bot.signal_id=lambda symbol, row: f"TEST-{row['side'].upper()}"
bot.LAST_EXECUTION.update(state='IDLE', reason='')

class Cfg:
    symbol='XAUUSD'; magic=20260906; max_open_positions=1
    max_daily_loss=0; max_spread=0; max_risk_percent=3.0; risk_percent=1.0


def make_row(side):
    if side=='long':
        return {'timestamp':'2026-11-22T09:00:00-05:00','side':'long','entry':100.0,
                'sl':99.0,'tp':103.0,'provenance':{'structural_stop_reference':99.0}}
    return {'timestamp':'2026-11-22T09:00:00-05:00','side':'short','entry':100.0,
            'sl':101.0,'tp':97.0,'provenance':{'structural_stop_reference':101.0}}

checks=[]
def run_valid(side, bid, ask, expected_type):
    db=FakeDB(); client=FakeClient(side,bid,ask)
    # Record the exact inputs passed to the actual sizing function.
    original=bot.risk_volume; sizing_calls=[]
    def traced_risk(c, cl, entry, sl):
        sizing_calls.append((entry,sl))
        return original(c,cl,entry,sl)
    bot.risk_volume=traced_risk
    try:
        sid=bot.execute_signal(Cfg(),client,db,make_row(side),fixed_levels=True)
    finally:
        bot.risk_volume=original
    req=client.api.sent[0] if client.api.sent else {}
    live=ask if side=='long' else bid
    ok=(sid is not None and len(client.api.sent)==1 and req.get('type')==expected_type
        and req.get('price')==live and req.get('sl')==make_row(side)['sl']
        and req.get('tp')==make_row(side)['tp'] and sizing_calls==[(live,make_row(side)['sl'])]
        and db.position is not None)
    checks.append((f'{side.upper()} recovered execution preserves levels and sizes at live quote',ok,
        f"sent={len(client.api.sent)} price={req.get('price')} sl={req.get('sl')} tp={req.get('tp')} sizing={sizing_calls}"))

run_valid('long',99.70,99.80,FakeAPI.ORDER_TYPE_BUY)
run_valid('short',100.20,100.30,FakeAPI.ORDER_TYPE_SELL)

# Invalid recovered BUY quote is beyond the original entry: it must not send.
db=FakeDB(); client=FakeClient('long',100.10,100.20)
result=bot.execute_signal(Cfg(),client,db,make_row('long'),fixed_levels=True)
checks.append(('BUY recovered quote beyond original entry is rejected before order_send',
    result is None and len(client.api.sent)==0,
    f'result={result} sent={len(client.api.sent)} state={bot.LAST_EXECUTION.get("state")}'))

for name,ok,detail in checks:
    print(f'{name}: {"PASS" if ok else "FAIL"} — {detail}')
print(f'\nTOTAL: {sum(ok for _,ok,_ in checks)}/{len(checks)} checks passed')
print('Test only: fake account/API/database; no MT5 connection, credentials, database file, or real order execution.')
if not all(ok for _,ok,_ in checks):
    raise SystemExit(1)
