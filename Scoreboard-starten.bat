@echo off
rem =====================================================================
rem  Street Hockey Scoreboard - Ein-Klick-Start fuer Windows
rem
rem  Einfach doppelklicken. Beim ALLERERSTEN Mal:
rem    - wird bei Bedarf Python automatisch installiert (Internet noetig,
rem      evtl. einmal "Ja" bei der Windows-Abfrage klicken)
rem    - werden die benoetigten Pakete geladen
rem  Das dauert ein paar Minuten. Jeder weitere Start geht in Sekunden
rem  und ohne Internet.
rem =====================================================================
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"
title Street Hockey Scoreboard  (Fenster offen lassen!)

set "PYEXE="
call :find_python
if not defined PYEXE (
    echo.
    echo   Python wird benoetigt und ist noch nicht installiert.
    echo   Ich versuche, es jetzt automatisch zu installieren ...
    echo.

    rem --- Weg 1: Windows-Paketmanager (winget) -------------------------
    where winget >nul 2>nul
    if not errorlevel 1 (
        echo   [1/2] Installation ueber winget ... bitte evtl. "Ja" klicken.
        winget install --exact --id Python.Python.3.12 --scope user --silent ^
              --accept-package-agreements --accept-source-agreements
    )
    call :find_python
)

if not defined PYEXE (
    rem --- Weg 2: offizielles Installationsprogramm herunterladen -------
    echo   [2/2] Lade Python-Installer von python.org ...
    set "PYINST=%TEMP%\python-scoreboard-setup.exe"
    powershell -NoProfile -Command ^
      "try { [Net.ServicePointManager]::SecurityProtocol=[Net.SecurityProtocolType]::Tls12; Invoke-WebRequest 'https://www.python.org/ftp/python/3.12.7/python-3.12.7-amd64.exe' -OutFile '%PYINST%' } catch { exit 1 }"
    if exist "%PYINST%" (
        echo   Installiere Python ^(nur fuer diesen Benutzer, ohne Adminrechte^) ...
        "%PYINST%" /quiet InstallAllUsers=0 PrependPath=1 Include_launcher=1 Include_test=0
        del "%PYINST%" >nul 2>nul
    )
    call :find_python
)

if not defined PYEXE (
    echo.
    echo   [!] Automatische Installation hat nicht geklappt.
    echo       Bitte Python einmal von Hand installieren:
    echo       https://www.python.org/downloads/   ^(Haken bei "Add Python to PATH"^)
    echo       Danach diese Datei erneut doppelklicken.
    echo.
    pause
    exit /b 1
)

echo   Python gefunden:  "%PYEXE%"
echo.

rem --- Beim ersten Start: Umgebung + Pakete einrichten -----------------
if not exist ".venv\Scripts\python.exe" (
    echo   Erstinstallation der Pakete laeuft ... bitte kurz warten.
    echo.
    "%PYEXE%" -m venv .venv
    if errorlevel 1 ( echo   [!] Konnte die Umgebung nicht anlegen. & pause & exit /b 1 )
    ".venv\Scripts\python.exe" -m pip install --upgrade pip >nul 2>nul
    ".venv\Scripts\python.exe" -m pip install -r requirements.txt
    if errorlevel 1 ( echo   [!] Installation der Pakete fehlgeschlagen ^(Internet noetig^). & pause & exit /b 1 )
)

rem --- Browser-Tabs kurz nach dem Start automatisch oeffnen ------------
start "" cmd /c "timeout /t 4 >nul & start http://localhost:8000/control & start http://localhost:8000/board"

echo.
echo   ============================================================
echo     Scoreboard laeuft!
echo.
echo     Bedienfeld (Zeitnehmer):  http://localhost:8000/control
echo     Grossanzeige (Beamer/TV): http://localhost:8000/board
echo.
echo     Dieses schwarze Fenster BITTE OFFEN LASSEN.
echo     Zum Beenden am Spielende einfach das Fenster schliessen.
echo   ============================================================
echo.

".venv\Scripts\python.exe" -m uvicorn main:app --host 0.0.0.0 --port 8000

echo.
echo   Server beendet.
pause
exit /b 0

rem ===================================================================
:find_python
rem  Sucht eine nutzbare python.exe und legt sie in PYEXE ab.
set "PYEXE="
for %%C in (py.exe python.exe) do (
    for /f "delims=" %%P in ('where %%C 2^>nul') do (
        if not defined PYEXE (
            "%%P" -c "import sys;raise SystemExit(0 if sys.version_info[:2]>=(3,9) else 1)" >nul 2>nul
            if not errorlevel 1 set "PYEXE=%%P"
        )
    )
)
if defined PYEXE goto :eof
for %%D in (
    "%LocalAppData%\Programs\Python"
    "%ProgramFiles%\Python312" "%ProgramFiles%\Python311" "%ProgramFiles%\Python310"
) do (
    if not defined PYEXE (
        for /f "delims=" %%P in ('dir /b /s "%%~D\python.exe" 2^>nul') do (
            if not defined PYEXE set "PYEXE=%%P"
        )
    )
)
goto :eof
