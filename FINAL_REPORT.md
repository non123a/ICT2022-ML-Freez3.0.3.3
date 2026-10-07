# Single-file MT5 Bot Report

## Deliverables

* `trade_bot.py`: self-contained MT5 connector, M1 loader, causal strategy, SQLite, paper/live execution, risk checks, logging, and CLI.
* `run_bot.bat`: Windows parameter control panel, defaulting to `MODE=PAPER`.
* `README.md`: installation and operating instructions.

## Safety

Paper mode is the default and never calls `mt5.order_send`. LIVE requires both `--mode LIVE` and `--allow-real-orders`, plus symbol/tick/volume/spread/duplicate checks. No credentials are hard-coded. SQLite signal/order/position/event tables provide persistent IDs and restart deduplication.

## Frozen contract

Defaults are Pivot 3, OTE 0.60, SL 0.90, TP 3R, M1, causal Phase 27-style state, Phase 17D realism filters, and `$0` historical cost. Parameters can be supplied by the BAT file as requested; changing them is outside this validation.

## Verification status

Syntax/import checks: PASS. SQLite initialization and restart: PASS. Paper startup prints `PAPER TRADING — NO REAL ORDERS`: PASS. The real `mt5.order_send` branch exists only in LIVE mode and is guarded: STATICALLY PRESENT, NOT EXECUTED. Historical replay equivalence of the fully embedded single-file strategy was not accepted as verified because the self-contained transcription requires a dedicated long-running comparison and has not been proven equal to all Phase 27 fields. MT5 connection and live order execution were not tested because no terminal/account was available.

## Final status

* STRATEGY ENGINE VERIFIED: NOT CLAIMED
* PAPER MODE VERIFIED: PARTIAL
* LIVE MT5 CONNECTION VERIFIED: NO
* LIVE ORDER EXECUTION VERIFIED: NO

Final verdict: **PAPER SYSTEM VERIFIED WITH LIMITATIONS**. Do not enable LIVE mode until the embedded engine passes a complete Phase 27 replay comparison and a read-only MT5 dry run validates broker symbol, timezone, closed-candle timing, reconnection, and position reconciliation.
