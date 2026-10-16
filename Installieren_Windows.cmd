@echo off
cd /d "%~dp0"
python -m venv "%~dp0.venv"
if errorlevel 1 goto failure
"%~dp0.venv\Scripts\python.exe" -m pip install -r "%~dp0requirements.txt"
if errorlevel 1 goto failure
echo Installation abgeschlossen. Empfaenger_Sprache.cmd starten.
pause
exit /b 0
:failure
echo Installation fehlgeschlagen. Die Fehlermeldung oben pruefen.
pause
exit /b 1
