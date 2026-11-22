"""Problem 2 Step 5 edge-case tests for post-reset continuation.

Run beside trade_bot_fixed_v3_3_2_fundingPips(4).py.
This test imports the bot module but does NOT connect to MT5, read credentials,
create a database, or send orders.
"""
from pathlib import Path
import importlib.util
import sys
import pandas as pd

SOURCE = Path(__file__).with_name("trade_bot_fixed_v3_3_2_fundingPips.py")
if not SOURCE.exists():
    raise FileNotFoundError(f"Place the source beside this test: {SOURCE.name}")

spec = importlib.util.spec_from_file_location("bot_step5_test", SOURCE)
bot = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = bot
spec.loader.exec_module(bot)

DATE = "2026-11-20"
TZ = "America/New_York"
RESET = pd.Timestamp(f"{DATE} 07:08", tz=TZ)
CONFIG = bot.Config(
    login=1,
    london_start="03:00:00", london_end="07:00:00",
    ny_start="07:00:00", ny_end="12:00:00",
)


def ts(clock):
    return pd.Timestamp(f"{DATE} {clock}", tz=TZ)


def frame(rows):
    idx = pd.DatetimeIndex([ts(r[0]) for r in rows])
    return pd.DataFrame(
        [{"Open": r[1], "High": r[2], "Low": r[3], "Close": r[4]} for r in rows],
        index=idx,
    )


def pivots(direction):
    # Pivot keys are confirmation times and are available by the 07:09 BOS bar.
    if direction == "short":
        ph = {ts("07:08"): {"center": ts("07:07"), "confirmation": ts("07:08"), "value": 110.0}}
        pl = {ts("07:08"): {"center": ts("07:07"), "confirmation": ts("07:08"), "value": 98.0}}
    else:
        ph = {ts("07:08"): {"center": ts("07:07"), "confirmation": ts("07:08"), "value": 102.0}}
        pl = {ts("07:08"): {"center": ts("07:07"), "confirmation": ts("07:08"), "value": 90.0}}
    return ph, pl


def trends(index):
    return pd.DataFrame({"1h_trend": [None] * len(index), "4h_trend": [None] * len(index)}, index=index)


# def call_helper(direction, data, all_data=None):
#     ph, pl = pivots(direction)
#     history = all_data if all_data is not None else data
#     return bot.find_post_reset_candidate(
#         df=data,
#         c=CONFIG,
#         direction=direction,
#         reset_time=RESET,
#         original_sweep_price=101.0 if direction == "short" else 89.0,
#         original_sweep_time=ts("07:02"),
#         lh=100.0,
#         ll=90.0,
#         lh_time=str(ts("06:59")),
#         ll_time=str(ts("06:59")),
#         ph=ph,
#         pl=pl,
#         trends=trends(history.index),
#         all_candles=history,
#     )

def call_helper(direction, data, all_data=None):
    ph, pl = pivots(direction)
    history = all_data if all_data is not None else data

    # Supply deterministic pivot and trend fixtures to the actual helper.
    bot.pivots = lambda df, k: (ph, pl)
    bot.causal_trends = lambda df: trends(df.index)

    original_provenance = {
        "sweep_price": 101.0 if direction == "short" else 89.0,
        "sweep_time": str(ts("07:02")),
        "sweep_type": "HIGH" if direction == "short" else "LOW",
    }

    diagnostics = {}

    return bot.find_post_reset_candidate(
        df=data,
        c=CONFIG,
        direction=direction,
        reset_time=RESET,
        original_provenance=original_provenance,
        diagnostics=diagnostics,
    )
results = []
def check(name, condition, detail=""):
    ok = bool(condition)
    results.append((name, ok))
    print(f"{name}: {'PASS' if ok else 'FAIL'}{(' — ' + detail) if detail else ''}")


# 1-2: after reset, no new BOS yet -> wait for BOS.
for direction in ("short", "long"):
    if direction == "short":
        rows = [("07:09", 99, 100, 98.5, 99.5)]  # close remains above broken low 98
    else:
        rows = [("07:09", 101, 101.5, 100.5, 101)]  # close remains below broken high 102
    result = call_helper(direction, frame(rows))
    check(f"{direction} waits when no post-reset BOS exists",
          result.get("state") == "WAITING_BOS_AFTER_RESET",
          result.get("state"))


# 3-4: new BOS exists, but price has not made the first OTE touch.
for direction in ("short", "long"):
    if direction == "short":
        rows = [
            ("07:09", 99, 100, 96, 97),   # BOS below 98
            ("07:10", 97, 100, 94, 98),   # lower extreme; OTE about 103.6
            ("07:11", 98, 100, 95, 99),   # remains below OTE
        ]
    else:
        rows = [
            ("07:09", 101, 104, 100, 103), # BOS above 102
            ("07:10", 103, 106, 101, 102), # higher extreme; OTE about 96.4
            ("07:11", 102, 105, 98, 100),  # remains above OTE
        ]
    result = call_helper(direction, frame(rows))
    check(f"{direction} waits after BOS until first OTE touch",
          result.get("state") == "WAITING_OTE_AFTER_RESET",
          result.get("state"))


# Build a valid post-reset setup, then test offline TP, SL and same-candle ambiguity.
def valid_setup_rows(direction):
    if direction == "short":
        return [
            ("07:09", 99, 100, 96, 97),
            ("07:10", 97, 100, 94, 98),
            ("07:11", 98, 100, 95, 99),
            ("07:12", 100, 104, 96, 103),  # first OTE touch
            ("07:13", 103, 104.2, 100, 104), # second OTE touch
        ]
    return [
        ("07:09", 101, 104, 100, 103),
        ("07:10", 103, 106, 101, 102),
        ("07:11", 102, 105, 98, 100),
        ("07:12", 98, 104, 96, 97),       # first OTE touch
        ("07:13", 97, 100, 95.8, 96),     # second OTE touch
    ]


for direction in ("short", "long"):
    if direction == "short":
        neutral = ("07:14", 104, 104.5, 103, 104)
    else:
        neutral = ("07:14", 96, 97, 95, 96)
    base = frame(valid_setup_rows(direction) + [neutral])
    candidate = call_helper(direction, base)
    signal = candidate.get("recovery")
    check(f"{direction} fixture creates a recoverable post-reset setup",
          candidate.get("state") == "RECOVERY_PENDING" and signal is not None,
          candidate.get("state"))
    if signal is None:
        continue

    sl = float(signal["sl"])
    tp = float(signal["tp"])

    if direction == "short":
        exit_rows = {
            "TP": ("07:14", tp, tp + 0.5, tp - 0.5, tp),
            "SL": ("07:14", sl, sl + 0.5, sl - 0.5, sl),
            "AMBIGUOUS": ("07:14", sl, sl + 0.5, tp - 0.5, tp),
        }
    else:
        exit_rows = {
            "TP": ("07:14", tp, tp + 0.5, tp - 0.5, tp),
            "SL": ("07:14", sl, sl + 0.5, sl - 0.5, sl),
            "AMBIGUOUS": ("07:14", tp, tp + 0.5, sl - 0.5, sl),
        }

    for exit_kind, exit_row in exit_rows.items():
        full = frame(valid_setup_rows(direction) + [exit_row])
        result = call_helper(direction, full)
        expected = "WAITING_RESET"
        actual_reason = result.get("exit_result")
        check(f"{direction} offline {exit_kind} invalidates post-reset setup",
              result.get("state") == expected and actual_reason == exit_kind.lower(),
              f"state={result.get('state')} exit_result={actual_reason}")


passed = sum(ok for _, ok in results)
print(f"\nTOTAL: {passed}/{len(results)} edge-case checks passed")
print("Test only: no MT5 connection, credentials, database, or order execution.")
