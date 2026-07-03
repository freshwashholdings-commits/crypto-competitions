@echo off
REM Double-click launcher for the Tron Address Tracer & Analyzer (Windows).
REM Handles first-run setup, prompts for a case, runs ingest -> trace ->
REM attribute -> report, and opens the resulting report.html automatically.
REM See README.md for what each step does.

cd /d "%~dp0"

echo === Tron Address Tracer ^& Analyzer ===
echo.

if not exist ".venv" (
    echo First run: setting up Python environment (this happens once)...
    python -m venv .venv
    if errorlevel 1 (
        echo Failed to create the virtual environment. Is Python 3.11+ installed and on PATH?
        pause
        exit /b 1
    )
    .venv\Scripts\python -m pip install -q --upgrade pip
    .venv\Scripts\python -m pip install -q -e ".[dev]"
    echo Setup complete.
    echo.
)

set PY=.venv\Scripts\python
set CLI=%PY% -m tron_tracer.cli

set CONFIG_FILE=.tron_tracer_config.bat
if exist "%CONFIG_FILE%" call "%CONFIG_FILE%"

if "%TRONGRID_API_KEY%"=="" (
    echo No TronGrid API key saved yet. Get a free one at https://www.trongrid.io
    set /p TRONGRID_API_KEY="TronGrid API key: "
    echo @set TRONGRID_API_KEY=%TRONGRID_API_KEY%> "%CONFIG_FILE%"
)

set /p ADDRESS="Tron address to trace: "
if "%ADDRESS%"=="" (
    echo No address entered, exiting.
    pause
    exit /b 1
)

set /p ASSET="Asset (TRX / USDT / a TRC-20 contract address) [USDT]: "
if "%ASSET%"=="" set ASSET=USDT
set /p METHOD="Method (fifo/lifo) [fifo]: "
if "%METHOD%"=="" set METHOD=fifo
set /p DIRECTION="Direction (forward/backward) [forward]: "
if "%DIRECTION%"=="" set DIRECTION=forward
set /p SEED_TX="Specific inbound tx hash to trace (leave blank to trace everything currently held): "

set CASE_DB=sqlite:///case_%ADDRESS%.db
for /f "tokens=1-4 delims=/: " %%a in ("%date% %time%") do set STAMP=%%a%%b%%c%%d
set OUT_DIR=out\%STAMP%
mkdir "%OUT_DIR%" 2>nul

echo.
echo --- Ingesting %ADDRESS% (%ASSET%) ---
%CLI% ingest backfill "%ADDRESS%" --asset "%ASSET%" --db-url "%CASE_DB%"
if errorlevel 1 (
    echo.
    echo Ingestion failed -- see the error above.
    echo ^(A balance-reconciliation failure is expected for addresses with
    echo  staking/voting activity; see METHODOLOGY.md Section 7.^)
    pause
    exit /b 1
)

echo.
echo --- Tracing (%METHOD%, %DIRECTION%) ---
if "%SEED_TX%"=="" (
    %CLI% trace run --address "%ADDRESS%" --asset "%ASSET%" --method "%METHOD%" --direction "%DIRECTION%" --db-url "%CASE_DB%" --output "%OUT_DIR%\trace.json"
) else (
    %CLI% trace run --address "%ADDRESS%" --asset "%ASSET%" --method "%METHOD%" --direction "%DIRECTION%" --seed-tx "%SEED_TX%" --db-url "%CASE_DB%" --output "%OUT_DIR%\trace.json"
)
if errorlevel 1 (
    echo Trace failed -- see the error above.
    pause
    exit /b 1
)

echo.
echo --- Attributing ---
%CLI% attribute run --cluster-around "%ADDRESS%" --db-url "%CASE_DB%" --output "%OUT_DIR%\attribution.json"

echo.
echo --- Building report ---
%CLI% report generate --trace-file "%OUT_DIR%\trace.json" --attribution-file "%OUT_DIR%\attribution.json" --out-dir "%OUT_DIR%\report"

set REPORT=%OUT_DIR%\report\report.html
echo.
echo Report ready: %REPORT%
start "" "%REPORT%"

pause
