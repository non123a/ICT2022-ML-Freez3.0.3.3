"""Problem 2 Steps 3/4 acceptance test for the user's current source.

Run this file beside:
  trade_bot_fixed_v3_3_2_fundingPips(2).py

No MT5 connection, credentials, database, or order execution is used.

Interpretation:
- RESET tests should PASS on the current source.
- POST-RESET BOS+OTE tests are acceptance tests for the missing continuation.
  They are expected to FAIL on a source that returns RESET_CONFIRMED and stops.
"""
from pathlib import Path
import importlib.util
import sys
import pandas as pd

SOURCE = Path(__file__).with_name("trade_bot_fixed_v3_3_2_fundingPips.py")
if not SOURCE.exists():
    raise FileNotFoundError(f"Place the source beside this test script: {SOURCE.name}")

spec = importlib.util.spec_from_file_location("bot_under_test", SOURCE)
bot = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = bot
spec.loader.exec_module(bot)

BASE_DATE = "2026-11-20"
TZ = "America/New_York"

def make_case(direction):
    if direction == "short":
        rows = [
            ("03:00",95,99,91,95), ("06:59",95,100,90,95),
            ("07:02",100,101,99,99.5), ("07:03",99,99.2,96.5,97),
            ("07:04",96,97,95,96), ("07:05",99.8,100.5,99,100.2),
            ("07:06",100.3,100.6,100.1,100.5),
            # Original SL, then reset above original sweep extreme 101.
            ("07:07",102,104,101.5,103.5), ("07:08",103,105,102,104),
            # Fresh pivots and a possible post-reset bearish setup.
            ("07:09",99,100,98,99), ("07:10",96,97,95,96),
            ("07:11",95,96,94,95), ("07:12",98,99.6,94.5,99),
            ("07:13",99,100,98.5,99.5), ("07:14",99.2,99.5,98.8,99.1),
        ]
        high_pivots = [("07:01",104.0), ("07:09",103.0)]
        low_pivots = [("07:01",98.0), ("07:09",97.0)]
        sweep_price = 101.0
    else:
        rows = [
            ("03:00",95,99,91,95), ("06:59",95,100,90,95),
            ("07:02",90,91,89,89.5), ("07:03",91,93,90.8,93),
            ("07:04",94,95,93,94), ("07:05",90,90.2,89.5,89.8),
            ("07:06",89.9,90.1,89.4,89.7),
            # Original SL, then reset below original sweep extreme 89.
            ("07:07",87,87.5,86,86.5), ("07:08",89,89.5,88,89),
            # Fresh pivots and a possible post-reset bullish setup.
            ("07:09",91,92,90,91), ("07:10",94,95,93.5,94),
            ("07:11",95,96,94,95), ("07:12",91,91.5,90,90.5),
            ("07:13",90.5,91,89.8,90), ("07:14",90.1,90.4,89.9,90.2),
        ]
        high_pivots = [("07:01",92.0), ("07:09",93.0)]
        low_pivots = [("07:01",86.0), ("07:09",87.0)]
        sweep_price = 89.0

    idx = pd.DatetimeIndex(
        [pd.Timestamp(f"{BASE_DATE} {t}", tz=TZ) for t, *_ in rows]
    )
    frame = pd.DataFrame(
        [{"Open":o, "High":h, "Low":l, "Close":c} for _,o,h,l,c in rows],
        index=idx,
    )

    def fake_pivots(_df, _k):
        def build(items):
            result = {}
            for time_text, value in items:
                key = pd.Timestamp(f"{BASE_DATE} {time_text}", tz=TZ)
                result[key] = {
                    "center": key - pd.Timedelta(minutes=1),
                    "confirmation": key,
                    "value": value,
                }
            return result
        return build(high_pivots), build(low_pivots)

    return frame, fake_pivots, sweep_price

original_pivots = bot.pivots
original_trends = bot.causal_trends
bot.causal_trends = lambda frame: pd.DataFrame(
    {"1h_trend":[None]*len(frame), "4h_trend":[None]*len(frame)},
    index=frame.index,
)
config = bot.Config(
    login=1,
    london_start="03:00:00", london_end="07:00:00",
    ny_start="07:00:00", ny_end="12:00:00",
)

results = []
try:
    for direction in ("short", "long"):
        frame, pivot_fn, sweep_price = make_case(direction)
        bot.pivots = pivot_fn
        # result = bot.phase27_live_state(frame, config)
        # Test reset detection using candles available only through 07:08.
        reset_frame = frame.loc[
            :pd.Timestamp(f"{BASE_DATE} 07:08", tz=TZ)
        ]
        reset_result = bot.phase27_live_state(reset_frame, config)

        # Test post-reset continuation using the complete dataset.
        result = bot.phase27_live_state(frame, config)

        # Existing behavior: current source detects reset and returns.
        # reset_ok = (
        #     result.get("state") == "RESET_CONFIRMED"
        #     and result.get("reset_time") == pd.Timestamp(f"{BASE_DATE} 07:08", tz=TZ)
        #     and result.get("reset_price") == sweep_price
        # )
        reset_ok = (
            reset_result.get("state") in (
                "RESET_CONFIRMED",
                "WAITING_BOS_AFTER_RESET",
                "WAITING_OTE_AFTER_RESET",
                "RECOVERY_PENDING",
                "ENTRY_SIGNAL",
            )
            and reset_result.get("reset_time")
                == pd.Timestamp(f"{BASE_DATE} 07:08", tz=TZ)
            and reset_result.get("reset_price") == sweep_price
        )
        print(
            f"{direction} reset detection: expected RESET_CONFIRMED at 07:08; "
            f"actual={result.get('state')} reset_time={result.get('reset_time')} "
            f"-> {'PASS' if reset_ok else 'FAIL'}"
        )
        results.append(("reset_" + direction, reset_ok))

        # Required behavior: after reset, continue scanning and recover the
        # new post-reset setup formed at 07:13. Current source is expected to
        # fail this until continuation logic is implemented.
        recovery = result.get("recovery")
        post_reset_ok = (
            result.get("state") == "RECOVERY_PENDING"
            and recovery is not None
            and recovery.get("timestamp") == pd.Timestamp(f"{BASE_DATE} 07:13", tz=TZ)
            and recovery.get("side") == direction
            and recovery.get("provenance", {}).get("post_reset") is True
            and pd.Timestamp(recovery["provenance"]["bos_time"])
                > pd.Timestamp(recovery["provenance"]["reset_time"])
            and pd.Timestamp(recovery["provenance"]["ote_touch_time"])
                > pd.Timestamp(recovery["provenance"]["bos_time"])
            and recovery["provenance"]["sweep_price"] == sweep_price
        )
        print(
            f"{direction} post-reset recovery: expected RECOVERY_PENDING at 07:13; "
            f"actual={result.get('state')} "
            f"recovery_time={(recovery or {}).get('timestamp')} "
            f"-> {'PASS' if post_reset_ok else 'FAIL (continuation not implemented)'}"
        )
        results.append(("post_reset_" + direction, post_reset_ok))

        # Same condition, but the new setup is on the latest closed candle:
        # it must be exposed as ENTRY_SIGNAL rather than offline recovery.
        live_frame = frame.iloc[:-1]
        live_result = bot.phase27_live_state(live_frame, config)
        live_signal = live_result.get("signal")
        live_ok = (
            live_result.get("state") == "ENTRY_SIGNAL"
            and live_signal is not None
            and live_signal.get("timestamp") == pd.Timestamp(f"{BASE_DATE} 07:13", tz=TZ)
            and live_signal.get("provenance", {}).get("post_reset") is True
            and pd.Timestamp(live_signal["provenance"]["bos_time"])
                > pd.Timestamp(live_signal["provenance"]["reset_time"])
            and pd.Timestamp(live_signal["provenance"]["ote_touch_time"])
                > pd.Timestamp(live_signal["provenance"]["bos_time"])
            and live_signal["provenance"]["sweep_price"] == sweep_price
        )
        print(
            f"{direction} reset detection: expected RESET_CONFIRMED at 07:08; "
            f"actual={reset_result.get('state')} "
            f"reset_time={reset_result.get('reset_time')} "
            f"-> {'PASS' if reset_ok else 'FAIL'}"
        )
        results.append(("live_post_reset_" + direction, live_ok))
finally:
    bot.pivots = original_pivots
    bot.causal_trends = original_trends

passed = sum(ok for _, ok in results)
print(f"\nTOTAL: {passed}/{len(results)} acceptance checks passed")
print("Expected on the current source: reset checks pass; post-reset checks fail.")
print("Do NOT run the trading bot for this test; this script never connects to MT5.")
