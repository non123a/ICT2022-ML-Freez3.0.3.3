#!/usr/bin/env python3
"""
Offline regression tests for trade_bot_fixed_v3_3_2_fundingPips.py

SAFE BY DESIGN:
- Does not call main()
- Does not import/connect MetaTrader5
- Does not send orders
- Uses fake ticks and a temporary SQLite database
- Reads the bot source and imports its functions only

Run:
    python test_gold_autobot_v10.py
or:
    python test_gold_autobot_v10.py "trade_bot_fixed_v3_3_2_fundingPips.py"

This is an initial executable regression suite, not a substitute for full
broker/demo validation. Static tests inspect the main-loop source structure.
"""

from __future__ import annotations

import ast
import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

DEFAULT_BOT = Path(__file__).with_name(
    "trade_bot_fixed_v3_3_2_fundingPips.py"
)
BOT_PATH = Path(sys.argv[1]).expanduser().resolve() if len(sys.argv) > 1 else DEFAULT_BOT

if not BOT_PATH.is_file():
    raise SystemExit(
        f"Bot file not found: {BOT_PATH}\n"
        "Pass the bot path as the first argument."
    )

# Load the module without invoking its main() function or MT5 connection.
spec = importlib.util.spec_from_file_location("gold_autobot_under_test", BOT_PATH)
bot = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = bot
spec.loader.exec_module(bot)

SOURCE = BOT_PATH.read_text(encoding="utf-8")
TREE = ast.parse(SOURCE)


class FakeTick:
    def __init__(self, bid, ask):
        self.bid = bid
        self.ask = ask


class FakeAPI:
    def __init__(self, tick):
        self.tick = tick
        self.tick_calls = 0

    def symbol_info_tick(self, symbol):
        self.tick_calls += 1
        return self.tick


class FakeClient:
    def __init__(self, tick):
        self.symbol = "XAUUSD"
        self.api = FakeAPI(tick)


def find_function(name):
    for node in TREE.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return node
    raise AssertionError(f"Function {name!r} not found")


def function_source(name):
    node = find_function(name)
    return ast.get_source_segment(SOURCE, node)


class TestSourceAndSafety(unittest.TestCase):
    def test_01_source_compiles(self):
        compile(SOURCE, str(BOT_PATH), "exec")

    def test_02_main_is_guarded(self):
        guards = [
            node for node in TREE.body
            if isinstance(node, ast.If)
            and ast.unparse(node.test) == "__name__ == '__main__'"
        ]
        self.assertTrue(guards, "main() is not protected by the __main__ guard")
        self.assertTrue(
            any(
                isinstance(stmt, ast.Expr)
                and isinstance(stmt.value, ast.Call)
                and isinstance(stmt.value.func, ast.Name)
                and stmt.value.func.id == "main"
                for stmt in guards[0].body
            ),
            "__main__ guard does not call main()"
        )

    def test_03_main_does_not_fetch_rates_before_pending_entry_check(self):
        main_src = function_source("main")
        pending_pos = main_src.find("if pending_entry is not None:")
        rates_pos = main_src.find("rates=client.rates()")
        self.assertGreaterEqual(pending_pos, 0, "pending_entry branch missing")
        self.assertGreaterEqual(rates_pos, 0, "client.rates() call missing")
        self.assertGreater(
            rates_pos, pending_pos,
            "REGRESSION: client.rates() occurs before pending-entry monitoring"
        )

    def test_04_pending_entry_wait_path_skips_normal_loop(self):
        main_src = function_source("main")
        pending_block_start = main_src.find("if pending_entry is not None:")
        rates_pos = main_src.find("rates=client.rates()", pending_block_start)
        pending_block = main_src[pending_block_start:rates_pos]
        self.assertIn("time.sleep(0.25)", pending_block)
        self.assertIn("continue", pending_block)

    def test_05_immediate_continue_after_signal_dashboard_is_present(self):
        main_src = function_source("main")
        signal_pos = main_src.find("if state['signal'] is not None:")
        dashboard_pos = main_src.find("render_dashboard(", signal_pos)
        rates_pos = main_src.find("rates=client.rates()", dashboard_pos)
        self.assertGreaterEqual(signal_pos, 0)
        self.assertGreaterEqual(dashboard_pos, 0)
        segment = main_src[dashboard_pos:rates_pos]
        # The immediate continue must be after rendering the dashboard and
        # before the next normal history fetch.
        self.assertRegex(
            segment,
            r"render_dashboard\([\s\S]*?\)\s*if pending_entry is not None:\s*continue",
            "The first fast quote check may still be delayed by the normal 5-second sleep."
        )

    def test_06_entry_poll_interval_is_250ms(self):
        self.assertIn("time.sleep(0.25)", function_source("main"))

    def test_07_strategy_uses_closed_m1_candles(self):
        main_src = function_source("main")
        self.assertIn("closed=x.iloc[:-1]", main_src)
        self.assertIn("phase27_live_state(closed, c)", main_src)


class TestEntryQuoteLogic(unittest.TestCase):
    BUY = {"side": "long", "entry": 2000.0, "sl": 1995.0, "tp": 2015.0}
    SELL = {"side": "short", "entry": 2000.0, "sl": 2005.0, "tp": 1985.0}

    def check(self, row, bid, ask):
        return bot.recovery_entry_status(row, bid, ask)

    def test_10_buy_above_entry_waits(self):
        self.assertEqual(self.check(self.BUY, 2000.0, 2000.2)[0], "WAITING")

    def test_11_buy_at_entry_ready(self):
        self.assertEqual(self.check(self.BUY, 1999.8, 2000.0)[0], "READY")

    def test_12_buy_between_sl_and_entry_ready(self):
        self.assertEqual(self.check(self.BUY, 1997.0, 1997.2)[0], "READY")

    def test_13_buy_at_sl_invalid(self):
        self.assertEqual(self.check(self.BUY, 1994.8, 1995.0), ("INVALID", "original_sl_reached"))

    def test_14_buy_at_tp_invalid(self):
        self.assertEqual(self.check(self.BUY, 2014.8, 2015.0), ("INVALID", "original_tp_reached"))

    def test_15_sell_below_entry_waits(self):
        self.assertEqual(self.check(self.SELL, 1999.8, 2000.0)[0], "WAITING")

    def test_16_sell_at_entry_ready(self):
        self.assertEqual(self.check(self.SELL, 2000.0, 2000.2)[0], "READY")

    def test_17_sell_between_entry_and_sl_ready(self):
        self.assertEqual(self.check(self.SELL, 2003.0, 2003.2)[0], "READY")

    def test_18_sell_at_sl_invalid(self):
        self.assertEqual(self.check(self.SELL, 2005.0, 2005.2), ("INVALID", "original_sl_reached"))

    def test_19_sell_at_tp_invalid(self):
        self.assertEqual(self.check(self.SELL, 1984.8, 1985.0), ("INVALID", "original_tp_reached"))

    def test_20_invalid_prices_rejected(self):
        self.assertEqual(self.check(self.BUY, 0, 0)[0], "INVALID")

    def test_21_invalid_direction_rejected(self):
        row = {**self.BUY, "side": "sideways"}
        self.assertEqual(self.check(row, 2000, 2000.2)[0], "INVALID")

    def test_22_invalid_buy_level_geometry_rejected(self):
        row = {**self.BUY, "sl": 2001.0}
        self.assertEqual(self.check(row, 2000, 2000.2), ("INVALID", "invalid_buy_levels"))

    def test_23_invalid_sell_level_geometry_rejected(self):
        row = {**self.SELL, "tp": 2001.0}
        self.assertEqual(self.check(row, 2000, 2000.2), ("INVALID", "invalid_sell_levels"))


class TestTickMonitor(unittest.TestCase):
    ROW = {"side": "long", "entry": 2000.0, "sl": 1995.0, "tp": 2015.0}

    def test_30_missing_tick_waits(self):
        client = FakeClient(None)
        result = bot.monitor_recovery_entry(client, self.ROW)
        self.assertEqual(result[0:2], ("WAITING", "missing_tick"))

    def test_31_bad_tick_waits(self):
        client = FakeClient(FakeTick(2001.0, 2000.0))
        result = bot.monitor_recovery_entry(client, self.ROW)
        self.assertEqual(result[0:2], ("WAITING", "invalid_tick"))

    def test_32_monitor_reads_one_live_tick(self):
        client = FakeClient(FakeTick(1999.8, 2000.0))
        result = bot.monitor_recovery_entry(client, self.ROW)
        self.assertEqual(result[0], "READY")
        self.assertEqual(client.api.tick_calls, 1)


class TestRecoveryHistoryHelpers(unittest.TestCase):
    def test_40_same_candle_sl_and_tp_is_ambiguous(self):
        import pandas as pd
        idx = pd.DatetimeIndex(["2026-11-20 10:00:00"], tz="America/New_York")
        candles = pd.DataFrame(
            {"Open": [2000], "High": [2020], "Low": [1990], "Close": [2005]},
            index=idx,
        )
        result = bot.first_exit("long", candles, sl=1995, tp=2015)
        self.assertEqual(result[2], "ambiguous")

    def test_41_long_sl_is_detected(self):
        import pandas as pd
        idx = pd.DatetimeIndex(["2026-11-20 10:00:00"], tz="America/New_York")
        candles = pd.DataFrame(
            {"Open": [2000], "High": [2005], "Low": [1990], "Close": [1998]},
            index=idx,
        )
        result = bot.first_exit("long", candles, sl=1995, tp=2015)
        self.assertEqual(result[2], "sl")

    def test_42_long_tp_is_detected(self):
        import pandas as pd
        idx = pd.DatetimeIndex(["2026-11-20 10:00:00"], tz="America/New_York")
        candles = pd.DataFrame(
            {"Open": [2000], "High": [2020], "Low": [1998], "Close": [2010]},
            index=idx,
        )
        result = bot.first_exit("long", candles, sl=1995, tp=2015)
        self.assertEqual(result[2], "tp")

    def test_43_reset_crossing_must_be_after_exit_candle(self):
        import pandas as pd
        idx = pd.DatetimeIndex(
            ["2026-11-20 10:00:00", "2026-11-20 10:01:00"],
            tz="America/New_York",
        )
        candles = pd.DataFrame(
            {"Open": [2000, 1990], "High": [2005, 1998],
             "Low": [1980, 1975], "Close": [1990, 1985]},
            index=idx,
        )
        reset = bot.find_reset_crossing(
            "long", candles, sweep_price=1985, exit_time=idx[0]
        )
        self.assertEqual(reset, idx[1])


if __name__ == "__main__":
    print(f"BOT UNDER TEST: {BOT_PATH}")
    print("MODE: OFFLINE MOCK/STATIC TESTS ONLY — NO MT5 CONNECTION OR ORDERS")
    unittest.main(argv=[sys.argv[0]], verbosity=2)
