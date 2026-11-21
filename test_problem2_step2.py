"""Controlled tests for Problem 2 historical recovery in the uploaded bot source.
No MT5 connection, credentials, or order execution are used.
"""
from pathlib import Path
import importlib.util
import sys
import pandas as pd

SOURCE = Path('C:\\Users\\Admin\\Documents\\SoftwareMade\\AutoTrade\\mt5_bot-testing-window-v1\\mt5_bot\\trade_bot_fixed_v3_3_1_fundingPips.py')
spec = importlib.util.spec_from_file_location('bot_under_test', SOURCE)
bot = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = bot
spec.loader.exec_module(bot)

# Use deterministic pivots to drive the real Phase 27 state machine through
# sweep -> BOS -> first OTE touch -> second OTE touch (candidate).
base_date = '2026-11-20'
tz = 'America/New_York'

def make_frame(future_rows):
    rows = [
        # London range: high=100, low=90.
        ('03:00', 95.0, 99.0, 91.0, 95.0),
        ('06:59', 95.0, 100.0, 90.0, 95.0),
        # NY: short-side liquidity sweep.
        ('07:02', 100.0, 101.0, 99.0, 99.5),
        # BOS below controlled confirmed low pivot (98).
        ('07:03', 99.0, 99.2, 96.5, 97.0),
        # Develop short OTE extreme; no touch yet.
        ('07:04', 96.0, 97.0, 95.0, 96.0),
        # First OTE touch, freezes OTE.
        ('07:05', 99.8, 100.5, 99.0, 100.2),
        # Second OTE touch -> candidate around 100.5.
        ('07:06', 100.3, 100.6, 100.1, 100.5),
    ] + future_rows
    idx = pd.DatetimeIndex([pd.Timestamp(f'{base_date} {t}', tz=tz) for t,*_ in rows])
    return pd.DataFrame([{ 'Open':o,'High':h,'Low':l,'Close':c } for _,o,h,l,c in rows], index=idx)

# The confirmed pivot maps are controlled, but all sweep/BOS/OTE/candidate,
# historical SL/TP and reset logic is the real implementation.
ph_key = pd.Timestamp(f'{base_date} 07:01', tz=tz)
pl_key = pd.Timestamp(f'{base_date} 07:01', tz=tz)
orig_pivots = bot.pivots
orig_trends = bot.causal_trends

def fake_pivots(df, k):
    return (
        {ph_key: {'center': ph_key-pd.Timedelta(minutes=1), 'confirmation': ph_key, 'value': 104.0}},
        {pl_key: {'center': pl_key-pd.Timedelta(minutes=1), 'confirmation': pl_key, 'value': 98.0}},
    )

def fake_trends(df):
    return pd.DataFrame({'1h_trend': [None] * len(df), '4h_trend': [None] * len(df)}, index=df.index)

bot.pivots = fake_pivots
bot.causal_trends = fake_trends
cfg = bot.Config(login=1, london_start='03:00:00', london_end='07:00:00', ny_start='07:00:00', ny_end='12:00:00')

cases = [
    ('no_exit', [('07:07',100.4,100.8,100.0,100.5),('07:08',100.5,101.0,100.2,100.6)], 'RECOVERY_PENDING', None),
    ('sl_only', [('07:07',102.0,104.0,101.5,103.5),('07:08',100.0,100.8,99.5,100.2)], 'WAITING_RESET', 'sl'),
    ('tp_only', [('07:07',92.0,93.0,90.0,91.0),('07:08',91.0,92.0,90.5,91.5)], 'WAITING_RESET', 'tp'),
    ('ambiguous_same_candle', [('07:07',100.0,104.0,90.0,100.0)], 'WAITING_RESET', 'ambiguous'),
    ('sl_then_reset', [('07:07',102.0,104.0,101.5,103.5),('07:08',103.0,105.0,102.0,104.0)], 'RESET_CONFIRMED', 'sl'),
    ('tp_then_reset', [('07:07',92.0,93.0,90.0,91.0),('07:08',100.0,102.0,99.5,101.5)], 'RESET_CONFIRMED', 'tp'),
]

failures=[]
try:
    for name, future, expected_state, expected_exit in cases:
        df=make_frame(future)
        result=bot.phase27_live_state(df,cfg)
        actual_state=result['state']
        actual_exit=result.get('exit_result')
        ok=(actual_state==expected_state and actual_exit==expected_exit)
        print(f'{name}: expected=({expected_state},{expected_exit}) actual=({actual_state},{actual_exit}) -> {"PASS" if ok else "FAIL"}')
        if not ok:
            failures.append((name, expected_state, expected_exit, actual_state, actual_exit, result))
finally:
    bot.pivots=orig_pivots
    bot.causal_trends=orig_trends

print(f'RESULT: {len(cases)-len(failures)}/{len(cases)} passed')
if failures:
    for f in failures:
        print('FAIL_DETAIL', f[:5])
    raise SystemExit(1)

# Mirror the same end-to-end scenarios for BUY/long recovery.
def make_long_frame(future_rows):
    rows = [
        ('03:00', 95.0, 99.0, 91.0, 95.0),
        ('06:59', 95.0, 100.0, 90.0, 95.0),
        ('07:02', 90.0, 91.0, 89.0, 89.5),  # London-low sweep
        ('07:03', 91.0, 93.0, 90.8, 93.0),  # BOS above pivot 92
        ('07:04', 94.0, 95.0, 93.0, 94.0),  # build extreme; OTE=89.6
        ('07:05', 90.0, 90.2, 89.5, 89.8),  # first OTE touch
        ('07:06', 89.9, 90.1, 89.4, 89.7),  # second touch -> candidate
    ] + future_rows
    idx = pd.DatetimeIndex([pd.Timestamp(f'{base_date} {t}', tz=tz) for t,*_ in rows])
    return pd.DataFrame([{'Open':o,'High':h,'Low':l,'Close':c} for _,o,h,l,c in rows], index=idx)

def fake_long_pivots(df, k):
    return (
        {ph_key: {'center': ph_key-pd.Timedelta(minutes=1), 'confirmation': ph_key, 'value': 92.0}},
        {pl_key: {'center': pl_key-pd.Timedelta(minutes=1), 'confirmation': pl_key, 'value': 86.0}},
    )

bot.pivots = fake_long_pivots
long_cases = [
    ('long_no_exit', [('07:07',89.7,90.0,89.2,89.6),('07:08',89.6,90.0,89.3,89.7)], 'RECOVERY_PENDING', None),
    ('long_sl_only', [('07:07',87.0,87.5,86.0,86.5),('07:08',89.2,89.8,89.1,89.5)], 'WAITING_RESET', 'sl'),
    ('long_tp_only', [('07:07',99.0,100.0,98.5,99.5),('07:08',98.5,99.0,98.0,98.5)], 'WAITING_RESET', 'tp'),
    ('long_ambiguous_same_candle', [('07:07',90.0,100.0,86.0,90.0)], 'WAITING_RESET', 'ambiguous'),
    ('long_sl_then_reset', [('07:07',87.0,87.5,86.0,86.5),('07:08',89.0,89.5,88.0,89.0)], 'RESET_CONFIRMED', 'sl'),
    ('long_tp_then_reset', [('07:07',99.0,100.0,98.5,99.5),('07:08',90.0,90.5,88.5,89.0)], 'RESET_CONFIRMED', 'tp'),
]
long_failures=[]
try:
    for name, future, expected_state, expected_exit in long_cases:
        result=bot.phase27_live_state(make_long_frame(future),cfg)
        actual_state=result['state']; actual_exit=result.get('exit_result')
        ok=(actual_state==expected_state and actual_exit==expected_exit)
        print(f'{name}: expected=({expected_state},{expected_exit}) actual=({actual_state},{actual_exit}) -> {"PASS" if ok else "FAIL"}')
        if not ok:
            long_failures.append((name,expected_state,expected_exit,actual_state,actual_exit))
finally:
    bot.pivots=orig_pivots
    bot.causal_trends=orig_trends
print(f'LONG RESULT: {len(long_cases)-len(long_failures)}/{len(long_cases)} passed')
if long_failures:
    for f in long_failures: print('LONG_FAIL_DETAIL',f)
    raise SystemExit(1)
