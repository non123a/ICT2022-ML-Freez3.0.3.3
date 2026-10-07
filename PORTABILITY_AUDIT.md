# Portability audit

## Scope

Audited `trade_bot.py`, `run_bot.bat`, and `README.md` without connecting to MetaTrader 5. No source files outside this package are imported.

## Findings

No `/Users/...`, `/Users`, `C:\Users...`, `~/Documents`, or `backtest_gold/...` absolute machine paths were found in the package. No hard-coded username or development working directory was found. The Python default database is anchored with `Path(__file__).resolve().parent`; the BAT now passes an explicitly quoted package-local database path and explicitly quoted script path.

`run_bot.bat` uses `cd /d "%~dp0"` and invokes `"%~dp0trade_bot.py"`, so double-clicking works independently of the caller's current directory and supports spaces in the installation path.

## External dependencies

The Windows machine still requires Python, `MetaTrader5`, `pandas`, and `numpy`; a locally installed/running MT5 terminal and a visible configured gold symbol are required for actual monitoring. Credentials are not in the BAT. The optional terminal/account/server settings are supplied through environment variables in the documented package, not development paths.

## Validation

`python -m py_compile trade_bot.py` passes. Static path/import search found no project dependency. A Windows runtime cannot be executed in this macOS environment, so actual MT5 initialization and double-click behavior remain untested here; the launcher path expansion is deterministic from the BAT source.
