"""Offline tests for recovered-entry quote logic. No MT5 connection or orders."""
from pathlib import Path
import importlib.util
import sys

SOURCE = Path(__file__).with_name("trade_bot_fixed_v3_3_2_fundingPips.py")
if not SOURCE.exists():
    raise FileNotFoundError(f"Place the current bot source beside this test: {SOURCE.name}")

spec = importlib.util.spec_from_file_location("bot_step6_test", SOURCE)
bot = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = bot
spec.loader.exec_module(bot)

# Prices are deliberately simple and only test direction/entry boundaries.
CASES = [
    ("BUY above entry waits", {"side": "long", "entry": 100.0, "sl": 98.0, "tp": 106.0}, 100.9, 101.0, "WAITING", "waiting_for_buy_retrace"),
    ("BUY at entry is ready", {"side": "long", "entry": 100.0, "sl": 98.0, "tp": 106.0}, 99.9, 100.0, "READY", "original_entry_reached"),
    ("BUY between SL and entry is ready", {"side": "long", "entry": 100.0, "sl": 98.0, "tp": 106.0}, 99.0, 99.1, "READY", "original_entry_reached"),
    ("BUY at SL is invalid", {"side": "long", "entry": 100.0, "sl": 98.0, "tp": 106.0}, 97.9, 98.0, "INVALID", "original_sl_reached"),
    ("BUY at TP is invalid", {"side": "long", "entry": 100.0, "sl": 98.0, "tp": 106.0}, 106.0, 106.1, "INVALID", "original_tp_reached"),
    ("SELL below entry waits", {"side": "short", "entry": 100.0, "sl": 102.0, "tp": 94.0}, 99.0, 99.1, "WAITING", "waiting_for_sell_retrace"),
    ("SELL at entry is ready", {"side": "short", "entry": 100.0, "sl": 102.0, "tp": 94.0}, 100.0, 100.1, "READY", "original_entry_reached"),
    ("SELL between entry and SL is ready", {"side": "short", "entry": 100.0, "sl": 102.0, "tp": 94.0}, 101.0, 101.1, "READY", "original_entry_reached"),
    ("SELL at SL is invalid", {"side": "short", "entry": 100.0, "sl": 102.0, "tp": 94.0}, 102.0, 102.1, "INVALID", "original_sl_reached"),
    ("SELL at TP is invalid", {"side": "short", "entry": 100.0, "sl": 102.0, "tp": 94.0}, 93.9, 94.0, "INVALID", "original_tp_reached"),
]

passed = 0
for name, row, bid, ask, expected_status, expected_reason in CASES:
    actual_status, actual_reason = bot.recovery_entry_status(row, bid, ask)
    ok = (actual_status, actual_reason) == (expected_status, expected_reason)
    passed += int(ok)
    print(f"{name}: {'PASS' if ok else 'FAIL'} — actual={actual_status}/{actual_reason}; expected={expected_status}/{expected_reason}")

print(f"\nTOTAL: {passed}/{len(CASES)} checks passed")
print("Test only: no MT5 connection, credentials, database, or order execution.")
sys.exit(0 if passed == len(CASES) else 1)
