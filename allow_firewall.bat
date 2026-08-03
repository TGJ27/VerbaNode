@echo off
setlocal
cd /d "%~dp0"
for /f "tokens=2 delims==" %%A in ('findstr /b "VERBANODE_PORT=" .env 2^>nul') do set PORT=%%A
if not defined PORT set PORT=8002
net session >nul 2>&1
if errorlevel 1 (
  echo This helper must be run as Administrator.
  echo Right-click allow_firewall.bat and choose "Run as administrator".
  pause
  exit /b 1
)
netsh advfirewall firewall delete rule name="VerbaNode" >nul 2>&1
netsh advfirewall firewall add rule name="VerbaNode" dir=in action=allow protocol=TCP localport=%PORT% profile=private
if errorlevel 1 (
  echo Could not create the firewall rule.
  pause
  exit /b 1
)
echo Private-network access allowed on TCP port %PORT%.
pause
endlocal
