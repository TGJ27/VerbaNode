@echo off
setlocal
cd /d "%~dp0"
call "%~dp0run_https.bat"
exit /b %ERRORLEVEL%
