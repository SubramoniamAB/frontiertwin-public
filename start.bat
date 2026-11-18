@echo off
REM FrontierTwin launcher for Windows
REM Developer: Subramoniam AB (SAB)
cd /d "%~dp0"
where py >nul 2>nul && (py -3 ft.py serve %* & goto :eof)
where python >nul 2>nul && (python ft.py serve %* & goto :eof)
echo Python 3.8+ is required: https://www.python.org/downloads/  (or: winget install Python.Python.3.12)
pause
