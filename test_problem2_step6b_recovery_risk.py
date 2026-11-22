"""Offline tests for recovered-entry risk sizing. No MT5 connection or orders."""
from pathlib import Path
import importlib.util
import sys
from types import SimpleNamespace

SOURCE = Path(__file__).with_name("trade_bot_fixed_v3_3_2_fundingPips.py")
if not SOURCE.exists():
    raise FileNotFoundError(f"Place the current bot source beside this test: {SOURCE.name}")

spec = importlib.util.spec_from_file_location("bot_step6b_test", SOURCE)
bot = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = bot
spec.loader.exec_module(bot)

class FakeAPI:
    ORDER_TYPE_BUY = 0
    ORDER_TYPE_SELL = 1

    def account_info(self):
        return SimpleNamespace(equity=10_000.0)

    def order_calc_profit(self, order_type, symbol, volume, entry, sl):
        # Deterministic test contract: $100 P/L per $1 price move per 1.00 lot.
        distance = abs(float(entry) - float(sl))
        return -(distance * float(volume) * 100.0)

    def last_error(self):
        return "fake-error"

class FakeClient:
    symbol = "XAUUSD"
    info = SimpleNamespace(volume_min=0.01, volume_max=100.0, volume_step=0.01)
    api = FakeAPI()

CONFIG = SimpleNamespace(
    risk_percent=1.0,
    max_risk_percent=1.5,
    lot=0.01,
    symbol="XAUUSD",
)

CASES = [
    # The sizing function must use the supplied live execution price and original SL.
    ("BUY recovered live price", 99.00, 98.00, 1),
    ("SELL recovered live price", 101.00, 102.00, 1),
]

passed = 0
for name, entry, sl, expected_count in CASES:
    try:
        volume, target, estimated = bot.risk_volume(CONFIG, FakeClient(), entry, sl)
        actual_risk = abs(FakeClient.api.order_calc_profit(
            FakeAPI.ORDER_TYPE_BUY if sl < entry else FakeAPI.ORDER_TYPE_SELL,
            "XAUUSD", volume, entry, sl
        ))
        ok = (
            volume > 0
            and estimated <= 10_000.0 * CONFIG.max_risk_percent / 100.0
            and abs(actual_risk - estimated) < 1e-8
        )
        passed += int(ok)
        print(
            f"{name}: {'PASS' if ok else 'FAIL'} — "
            f"entry={entry:.2f} original_sl={sl:.2f} "
            f"volume={volume:.2f} estimated_risk=${estimated:.2f} "
            f"hard_cap=$150.00"
        )
    except Exception as exc:
        print(f"{name}: FAIL — {type(exc).__name__}: {exc}")

# Verify a minimum lot that would exceed the hard cap is rejected.
too_small_config = SimpleNamespace(
    risk_percent=0.01,
    max_risk_percent=0.01,
    lot=0.01,
    symbol="XAUUSD",
)
try:
    bot.risk_volume(too_small_config, FakeClient(), 100.0, 98.0)
    print("Minimum lot above hard risk cap is rejected: FAIL — no exception")
except ValueError:
    passed += 1
    print("Minimum lot above hard risk cap is rejected: PASS")

total = len(CASES) + 1
print(f"\nTOTAL: {passed}/{total} checks passed")
print("Test only: fake account/API; no MT5 connection, credentials, database, or order execution.")
sys.exit(0 if passed == total else 1)
