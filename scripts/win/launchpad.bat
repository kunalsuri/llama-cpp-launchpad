@echo off
rem llama-cpp-launchpad: the one launcher (double-click it). Opens the setup page in your browser, where you can
rem get llama.cpp, pick and download a model, and start chatting. Closing this window stops the page.
call "%~dp0model-setup.bat" --ui %*
exit /b %errorlevel%
