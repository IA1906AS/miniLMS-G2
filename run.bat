@echo off
setlocal EnableExtensions
chcp 65001 >nul
cd /d "%~dp0"

set "PGBIN=D:\Setup\Postgre SQL\bin"
set "PGDATA=D:\Setup\Postgre SQL\data"
set "VENV=%~dp0.venv\Scripts\python.exe"
set "PORT=8888"
set "URL=http://127.0.0.1:%PORT%"

echo ============================================
echo   miniLMS - khoi dong FE + BE + PostgreSQL
echo ============================================
echo.

REM ---------- 1. PostgreSQL ----------
echo [1/3] PostgreSQL...
if exist "%PGBIN%\pg_ctl.exe" goto pg_check
echo    [CANH BAO] Khong thay PostgreSQL tai "%PGBIN%".
echo    Sua lai bien PGBIN o dau file run.bat.
goto pg_done

:pg_check
"%PGBIN%\pg_ctl.exe" status -D "%PGDATA%" >nul 2>&1
if errorlevel 1 (
    echo    - Dang khoi dong PostgreSQL...
    "%PGBIN%\pg_ctl.exe" start -D "%PGDATA%" -l "%PGDATA%\log\run.log" -w
    if errorlevel 1 (
        echo    [LOI] Khong khoi dong duoc PostgreSQL.
        echo    Xem log: "%PGDATA%\log\run.log"
        pause
        exit /b 1
    )
) else (
    echo    - PostgreSQL dang chay.
)
:pg_done

REM ---------- 2. Python venv + dependencies ----------
echo.
echo [2/3] Python venv...
if not exist "%VENV%" (
    echo    [LOI] Khong thay .venv.
    echo    Tao moi:  py -3.12 -m venv .venv
    echo    Cai dat:  .venv\Scripts\python.exe -m pip install -r requirements.txt
    pause
    exit /b 1
)
"%VENV%" -c "import flask, sqlalchemy, psycopg, dotenv" >nul 2>&1
if errorlevel 1 (
    echo    - Thieu thu vien, dang cai dat...
    "%VENV%" -m pip install -r requirements.txt
    if errorlevel 1 (
        echo    [LOI] Cai dat thu vien that bai.
        pause
        exit /b 1
    )
) else (
    echo    - Thu vien day du.
)

REM Dong bo bang/cot moi (idempotent)
"%VENV%" tools\migrate.py

REM ---------- 3. Web server (FE + BE cung mot Flask app) ----------
echo.
netstat -ano | findstr ":%PORT% " | findstr "LISTENING" >nul
if not errorlevel 1 (
    echo [3/3] Port %PORT% da co tien trinh dang chay.
    echo       Mo trinh duyet: %URL%
    start "" "%URL%"
    timeout /t 2 /nobreak >nul
    exit /b 0
)

echo [3/3] Khoi dong web tai %URL%
echo       (FE + BE chay cung Flask; nhan Ctrl+C de dung web)
echo.

REM Mo trinh duyet sau 3 giay, trong khi server khoi dong
start "" /min cmd /c "timeout /t 3 /nobreak >nul & start "" "%URL%""

"%VENV%" webapp.py

echo.
echo Web da dung. PostgreSQL van chay nen.
pause
