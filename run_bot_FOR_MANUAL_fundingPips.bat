@echo off

setlocal

cd /d "%~dp0"

rem ACCOUNT SETTINGS - keep this file private; it contains a password.

set MT5_LOGIN=21273768
set MT5_PASSWORD=Xy[dyITF9
set MT5_SERVER=FundingPips-SIM1

rem FROZEN STRATEGY

set PIVOT=3
set OTE=0.60
set SL=0.90
set TP=3.0

rem RISK: RISK_PERCENT=0 uses LOT; positive values use equity risk sizing.

set RISK_PERCENT=1
set LOT=0.01
set TIMEZONE=America/New_York

set LONDON_START=03:00:00
set LONDON_END=07:00:00

set NY_START=07:00:00
set NY_END=12:00:00
rem TRADING CONTROLS

set SYMBOL=XAUUSD
set MAGIC_NUMBER=20260907
set MAX_SPREAD=0
set MAX_DAILY_LOSS=0
set MAX_OPEN_POSITIONS=1

where python >nul 2>&1

if errorlevel 1 (
    echo ERROR: Python was not found on PATH.
    pause
    exit /b 1
)



python "%~dp0trade_bot_fixed_v3_3_1_fundingPips.py" ^
    --login "%MT5_LOGIN%" ^
    --server "%MT5_SERVER%" ^
    --pivot "%PIVOT%" ^
    --ote "%OTE%" ^
    --sl "%SL%" ^
    --tp "%TP%" ^
    --lot "%LOT%" ^
    --risk-percent "%RISK_PERCENT%" ^
    --symbol "%SYMBOL%" ^
    --magic "%MAGIC_NUMBER%" ^
    --max-spread "%MAX_SPREAD%" ^
    --max-daily-loss "%MAX_DAILY_LOSS%" ^
    --max-open-positions "%MAX_OPEN_POSITIONS%" ^
    --database "%~dp0paper_trades.sqlite3"

if errorlevel 1 echo ERROR: Bot exited with code %errorlevel%.

pause