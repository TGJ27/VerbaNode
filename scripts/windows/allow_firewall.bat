@echo off
setlocal
cd /d "%~dp0..\.."
for /f "tokens=2 delims==" %%A in ('findstr /b "VERBANODE_PORT=" .env 2^>nul') do set PORT=%%A
if not defined PORT set PORT=8002
for /f "tokens=2 delims==" %%A in ('findstr /b "VERBANODE_LAN_DISCOVERY_UDP_PORT=" .env 2^>nul') do set DISCOVERY_PORT=%%A
if not defined DISCOVERY_PORT set DISCOVERY_PORT=8002
net session >nul 2>&1
if errorlevel 1 (
  echo This helper must be run as Administrator.
  echo Right-click scripts\windows\allow_firewall.bat and choose "Run as administrator".
  pause
  exit /b 1
)
netsh advfirewall firewall delete rule name="VerbaNode Standalone" >nul 2>&1
netsh advfirewall firewall delete rule name="VerbaNode Discovery" >nul 2>&1
netsh advfirewall firewall delete rule name="VerbaNode Active Discovery" >nul 2>&1
netsh advfirewall firewall add rule name="VerbaNode Standalone" dir=in action=allow protocol=TCP localport=%PORT% profile=private
if errorlevel 1 (
  echo Could not create the VerbaNode TCP firewall rule.
  pause
  exit /b 1
)
netsh advfirewall firewall add rule name="VerbaNode Discovery" dir=in action=allow protocol=UDP localport=5353 profile=private
if errorlevel 1 (
  echo Could not create the VerbaNode mDNS firewall rule.
  pause
  exit /b 1
)
netsh advfirewall firewall add rule name="VerbaNode Active Discovery" dir=in action=allow protocol=UDP localport=%DISCOVERY_PORT% profile=private
if errorlevel 1 (
  echo Could not create the VerbaNode active-discovery UDP firewall rule.
  pause
  exit /b 1
)
echo Private-network access allowed on TCP port %PORT%, active discovery UDP port %DISCOVERY_PORT%, and mDNS UDP port 5353.
pause
endlocal
