@echo off
rem Thin wrapper: detect-tools is implemented once, in Python (utils\detect_tools.py), for every OS.
where py >nul 2>nul && ( py -3 "%~dp0..\..\utils\detect_tools.py" %* & goto :done )
where python >nul 2>nul && ( python "%~dp0..\..\utils\detect_tools.py" %* & goto :done )
echo detect-tools needs Python 3 (standard library only, nothing to pip install).
echo Install it with:  winget install Python.Python.3.12   (or https://www.python.org/downloads/)
exit /b 1
:done
exit /b %errorlevel%
