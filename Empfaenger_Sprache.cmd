@echo off
cd /d "%~dp0"
set "AUDIO_PYTHON=python"
if exist "%~dp0.venv\Scripts\python.exe" set "AUDIO_PYTHON=%~dp0.venv\Scripts\python.exe"
"%AUDIO_PYTHON%" -u "%~dp0audio_receiver.py" --profile speech
pause
