@echo off
setlocal

cd /d "%~dp0"

rem ============================================================
rem MT5 ACCOUNT SETTINGS
rem Demo account - keep this file private.
rem ============================================================

set MT5_LOGIN=279751842
set MT5_PASSWORD=Non1590$$$
set MT5_SERVER=Exness-MT5Trial8

rem ============================================================
rem FROZEN STRATEGY
rem ============================================================
set TIMEZONE=America/New_York

set LONDON_START=03:00:00
set LONDON_END=07:00:00

set NY_START=07:00:00
set NY_END=12:00:00
set PIVOT=3
set OTE=0.60
set SL=0.90
set TP=3.0

rem ============================================================
rem RISK
rem RISK_PERCENT=0 uses fixed LOT.
rem Positive values use equity-risk sizing.
rem ============================================================

set RISK_PERCENT=1
set LOT=0.01

rem ============================================================
rem TRADING CONTROLS
rem ============================================================

set SYMBOL=XAUUSD
set MAGIC_NUMBER=20260906
set MAX_SPREAD=0
set MAX_DAILY_LOSS=0
set MAX_OPEN_POSITIONS=1

rem ============================================================
rem TIMEZONE / TRADING SESSIONS
rem ============================================================

set TIMEZONE=America/New_York

set LONDON_START=03:00:00
set LONDON_END=07:00:00

set NY_START=07:00:00
set NY_END=12:00:00

rem ============================================================
rem CHECK PYTHON
rem ============================================================

where python >nul 2>&1

if errorlevel 1 (
    echo ERROR: Python was not found on PATH.
    exit /b 1
)

rem ============================================================
rem START BOT
rem ============================================================

echo ============================================================
echo Gold AutoBOT - Automatic Start
echo ============================================================
echo MT5 Login: %MT5_LOGIN%
echo MT5 Server: %MT5_SERVER%
echo Symbol: %SYMBOL%
echo Strategy: P%PIVOT% OTE%OTE% SL%SL% TP%TP%R
echo Risk: %RISK_PERCENT%%%
echo London: %LONDON_START% - %LONDON_END%
echo New York: %NY_START% - %NY_END%
echo Magic: %MAGIC_NUMBER%
echo ============================================================

python "%~dp0trade_bot_fixed_v3_2.py" ^
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

if errorlevel 1 (
    echo ERROR: Bot exited with code %errorlevel%.
    exit /b %errorlevel%
)

endlocal
exit /b 0