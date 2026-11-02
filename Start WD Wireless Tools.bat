@echo off
title WD Wireless Tools
cd /d "%~dp0"

REM ---- Check for Python -------------------------------------------------------
where python >nul 2>&1
if errorlevel 1 (
    echo.
    echo  Python is not installed, and WD Wireless Tools needs it to run.
    echo.
    echo  How to install Python
    echo.
    echo    Option 1 - Download from python.org
    echo      1. Go to https://www.python.org/downloads/
    echo      2. Click the big yellow "Download Python" button
    echo      3. Run the installer
    echo      4. IMPORTANT: On the first screen, tick "Add python.exe to PATH"
    echo      5. Click "Install Now"
    echo.
    echo    Option 2 - Install from a terminal
    echo      winget install --id Python.Python.3.12 -e
    echo.
    echo  After installing Python, close this window and double-click
    echo  "Start WD Wireless Tools.bat" again.
    echo.
    pause
    exit /b 1
)

REM ---- Windows Terminal -------------------------------------------------------
REM Open in a tab of the Windows Terminal window already on screen, rather than
REM a console of our own. tools/terminal_tab.py decides: it exits 0 once a tab
REM is running this launcher, and 1 for "stay here" - already inside a terminal,
REM switched off in Settings, or no wt.exe. The tab passes --in-tab back so it
REM can never open a second one from inside itself.
if /i "%~1"=="--in-tab" goto :launcher_ready
python -m tools.terminal_tab "%~f0"
if not errorlevel 1 exit /b 0
:launcher_ready

REM ---- Check for dependencies -------------------------------------------------
REM Present is not current. tools.deps compares the installed versions with the
REM floors in requirements.txt, so a package that still imports but is older
REM than its floor is upgraded too. Exit 0 is all current, 1 is something
REM missing, 2 is everything installed but something older than a floor.
python -m tools.deps >nul 2>&1
set "DEPS_STATUS=%errorlevel%"
if not "%DEPS_STATUS%"=="0" (
    echo.
    echo  Installing or updating the required Python packages...
    echo  This can take about a minute.
    echo.
    python -m pip install --disable-pip-version-check -q --upgrade -r requirements.txt
    if errorlevel 1 (
        REM An older package still runs the app, so a failed update, offline
        REM for example, starts with a warning. A missing package cannot start.
        if "%DEPS_STATUS%"=="2" (
            echo.
            echo  Could not update some packages. Starting with the versions installed.
            echo.
        ) else (
            echo.
            echo  Some packages failed to install.
            echo.
            echo  Try running this command yourself in PowerShell or Command Prompt
            echo    python -m pip install --upgrade -r "%~dp0requirements.txt"
            echo.
            echo  If pip itself is missing, run
            echo    python -m ensurepip --upgrade
            echo  then try the pip install command above again.
            echo.
            pause
            exit /b 1
        )
    ) else (
        echo.
        echo  Done. Starting WD Wireless Tools...
        echo.
    )
)

REM ---- Kill any stale instance on port 8675 -----------------------------------
for /f "tokens=5" %%p in ('netstat -ano ^| findstr "LISTENING" ^| findstr ":8675 "') do taskkill /PID %%p /F >nul 2>&1

REM ---- Launch -----------------------------------------------------------------
python server.py

REM 75 is "restarted: a new tab is already running". Leaving cleanly closes this
REM tab; killing the window leaves it open behind a non-zero exit.
if %errorlevel%==75 exit /b 0

if errorlevel 1 (
    echo.
    echo WD Wireless Tools could not start. Review the error above.
) else (
    echo.
    echo WD Wireless Tools has closed normally.
)

pause
