@echo off
rem Starts the certificate app with the project's own Python (in .venv).
rem A plain "streamlit run app.py" may use another Python installed on the
rem computer, which does not have the project's libraries.

rem Work from this file's folder, wherever it is double-clicked from.
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo The .venv folder is missing. Follow the "Installation" steps in README.md first.
    pause
    exit /b 1
)

rem %* passes on any extra options, e.g. run.bat --server.port 8502
".venv\Scripts\python.exe" -m streamlit run app.py %*

rem Keeps the window open if the app stops, so any message can be read.
pause
