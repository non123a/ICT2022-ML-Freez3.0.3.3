# Portability, credential, and risk audit

## Scope

Inspected the complete `trade_bot.py`, `run_bot.bat`, and `README.md`. No MT5 initialization or order was performed on macOS.

## Portable paths

PASS: the BAT uses `cd /d "%~dp0"` and invokes quoted `%~dp0trade_bot.py` and `%~dp0paper_trades.sqlite3`. Python anchors its default database and log to `Path(__file__).resolve().parent`. No development-machine path, username, project import, or hard-coded terminal path remains.

## Account and security

The BAT now has editable `MT5_LOGIN`, `MT5_PASSWORD`, and `MT5_SERVER` placeholders. The password is passed to MT5 login but never logged, included in startup summaries, or written to SQLite. The BAT is sensitive and must remain private. Account login and server are verified after initialization. Exact symbol resolution is required; the bot refuses silent fallback.

## Risk and controls

`RISK_PERCENT=0` uses fixed LOT. Positive risk percentage uses equity, entry-to-SL distance, tick size/value, and broker min/max/step, flooring volume conservatively. Magic number identifies ownership. Spread, daily-loss, and maximum-open-position settings are parsed and checked in the order path; zero disables spread/daily-loss limits.

## Execution and recovery

The live path uses ask for buys and bid for sells, checks MT5 retcodes, records accepted orders, and reconnects after runtime failures. Current implementation still requires a Windows broker test for actual position-history closure reconciliation and complete strategy signal generation; these are not claimed tested here.

## Checklist

- [PASS] Portable paths (static inspection)
- [PASS] BAT launcher quoting and own-directory change (static inspection)
- [PASS] Credential placeholders/no logging or persistence of password (static inspection)
- [PASS] MT5 initialization/login path (code inspection; not broker-tested)
- [PASS] Account verification (code inspection; not broker-tested)
- [PASS] Symbol verification (code inspection; not broker-tested)
- [PASS] Risk-per-trade calculation (local unit inspection; broker values unavailable)
- [PASS] Fixed-lot branch (code inspection)
- [PASS] Magic number filtering (code inspection)
- [PARTIAL] Duplicate protection (SQLite plus owned-position comment check; restart broker test unavailable)
- [PARTIAL] Restart recovery (startup state exists, full history reconciliation not broker-tested)
- [PARTIAL] Position tracking (accepted order persistence; closure history not tested)
- [PASS] Order-result rejection path (code inspection)
- [PASS] Spread control (code inspection)
- [PASS] Daily-loss control (history_deals_get filtered by symbol/magic before new orders; broker test unavailable)
- [PASS] Max-position control (code inspection)
- [PASS] Closed-candle data selection (code inspection)
- [PASS] Explicit timezone handling (code inspection)
- [PARTIAL] Reconnection handling (code inspection; MT5 disconnect not tested)
- [PASS] Credential secrecy (static inspection)
- [PASS] Python syntax (local `py_compile`)

The frozen strategy engine remains a separate known limitation from this deployment audit and has not been certified for live trading.

## V2 strategy and reconciliation update

## Authentication update

Authentication now mirrors the old working deployment flow. The BAT exposes editable login, password, and server variables. Login and server are passed as arguments, while the password is supplied through `MT5_PASSWORD`; the Python client calls `mt5.initialize()` followed by `mt5.login(login, password=password, server=server)`. The password is not accepted as a command-line argument and is not logged or stored.

The bot now includes a causal higher-timeframe trend function, prefix-bounded Pivot 3 state, explicit sweep/BOS/OTE transitions, structural SL/TP construction, minimum-risk gating, and chronological first-touch exits. No centered future series is precomputed.

Offline tests in `test_v2_offline.py` passed: risk sizing uses conservative broker-step flooring; SQLite signal identity survives repeated insertion/restart; and first-touch exit selection is SL-first when both levels are touched. Python syntax compilation passes.

MT5 connection, broker account verification, position-history reconciliation, and order execution were intentionally not run on macOS. These remain untested operational paths and must be validated on Windows with a controlled account before any live use.

## Live debug and audit trail update

Added package-local append-only `trade_audit.csv` and `setup_events.csv` writers. Signal entry/rejection/order events now use labeled console messages and stable signal IDs; password data is not included in either CSV writer. Startup logs display the effective non-secret configuration. A complete broker-confirmed EXIT row still requires the pending position-history monitor and has not been claimed tested.

## Final provenance propagation update

The `signals` table now persists a JSON `provenance` column (with migration for existing databases). Provenance is captured from the strategy signal and survives order persistence, restart, and broker-close reconciliation. The final `trade_audit.csv` row merges that stored state with broker-confirmed entry/exit values and result data; repeated reconciliation is guarded by a persisted `trade_audit_written` event.

Persisted strategy fields include London high/low and timestamps, sweep type/price/time/level, BOS direction/price/time/broken level, OTE anchors/times/method/ratio/price/touch values, pivot confirmation/level, and available trend/displacement fields. Fields not produced by the current strategy remain empty rather than being reconstructed. `setup_events.csv` now has columns for the same provenance values and entry events carry the signal provenance JSON.

Offline verification: `py_compile` passed; `test_strategy_engine.py` passed (pivot confirmation, future rejection, closed-boundary, entry construction, SL-first); `test_v2_offline.py` passed (risk sizing, duplicate persistence, first-touch); and a temporary SQLite provenance round-trip passed. No MT5 connection, login, or order was performed. Broker-specific history fields and Windows integration remain untested until the controlled MT5 test.
