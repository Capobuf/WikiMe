@echo off
setlocal

cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo Ambiente virtuale non trovato.
    echo Esegui prima: python -m venv .venv
    echo Poi installa le dipendenze: .venv\Scripts\python.exe -m pip install -r requirements.txt
    pause
    exit /b 1
)

echo Riavvio WikiMe POC su http://127.0.0.1:5000
echo Arresto l'eventuale istanza precedente...

taskkill /FI "WINDOWTITLE eq WikiMe Server*" /T /F >nul 2>&1
taskkill /FI "WINDOWTITLE eq WikiMi Server*" /T /F >nul 2>&1

powershell -NoProfile -Command "$connection = Get-NetTCPConnection -LocalPort 5000 -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1; if (-not $connection) { exit 0 }; try { $response = Invoke-WebRequest -UseBasicParsing -Uri 'http://127.0.0.1:5000' -TimeoutSec 2 } catch { exit 2 }; if ($response.Content -notmatch 'WikiM(e|i)') { exit 3 }; Stop-Process -Id $connection.OwningProcess -Force -ErrorAction SilentlyContinue"
if errorlevel 3 (
    echo La porta 5000 e' utilizzata da un'altra applicazione.
    pause
    exit /b 1
)

for /l %%I in (1,1,10) do (
    powershell -NoProfile -Command "if (Get-NetTCPConnection -LocalPort 5000 -State Listen -ErrorAction SilentlyContinue) { Start-Sleep -Milliseconds 500; exit 1 } else { exit 0 }"
    if not errorlevel 1 goto :start_server
)

echo Non e' stato possibile arrestare la precedente istanza di WikiMe.
pause
exit /b 1

:start_server
if exist "instance\wikimi.db" if not exist "instance\wikime.db" (
    echo Rinomino il database esistente in wikime.db...
    move /Y "instance\wikimi.db" "instance\wikime.db" >nul
)

start "WikiMe Server" ".venv\Scripts\python.exe" run.py

echo Attendo l'avvio del server...
for /l %%I in (1,1,20) do (
    powershell -NoProfile -Command "try { Invoke-WebRequest -UseBasicParsing -Uri 'http://127.0.0.1:5000' -TimeoutSec 1 | Out-Null; exit 0 } catch { Start-Sleep -Seconds 1; exit 1 }"
    if not errorlevel 1 goto :open_browser
)

echo Il server non ha risposto entro 20 secondi.
echo Controlla la finestra "WikiMe Server" per i dettagli dell'errore.
pause
exit /b 1

:open_browser
echo Apro WikiMe nel browser predefinito...
start "" "http://127.0.0.1:5000"

endlocal
