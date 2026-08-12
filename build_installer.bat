@echo off
setlocal EnableExtensions
cd /d "%~dp0"

echo ============================================================
for /f "tokens=2 delims== " %%V in ('findstr /B /C:"APP_VERSION =" app\version.py') do set "APP_VERSION=%%~V"
if not defined APP_VERSION set "APP_VERSION=unknown"

echo VerbaNode v%APP_VERSION% online Windows installer build
echo ============================================================
echo.

if not exist "dist\VerbaNode\VerbaNode.exe" (
  echo ERROR: dist\VerbaNode\VerbaNode.exe was not found.
  echo Run build_windows.bat first. The v%APP_VERSION% app build contains the
  echo installer setup commands and final application icon.
  echo.
  pause
  exit /b 1
)

if not exist "packaging\assets\VerbaNode.ico" (
  echo ERROR: packaging\assets\VerbaNode.ico was not found.
  echo.
  pause
  exit /b 1
)

for /f "tokens=1" %%P in ('tasklist /FI "IMAGENAME eq VerbaNode.exe" /NH 2^>nul') do (
  if /I "%%P"=="VerbaNode.exe" (
    echo ERROR: VerbaNode.exe is still running.
    echo Exit VerbaNode completely before building the installer.
    echo.
    pause
    exit /b 1
  )
)

set "ISCC="
for /f "delims=" %%I in ('where ISCC.exe 2^>nul') do if not defined ISCC set "ISCC=%%I"
if not defined ISCC if exist "%ProgramFiles%\Inno Setup 7\ISCC.exe" set "ISCC=%ProgramFiles%\Inno Setup 7\ISCC.exe"
if not defined ISCC if exist "%ProgramFiles(x86)%\Inno Setup 7\ISCC.exe" set "ISCC=%ProgramFiles(x86)%\Inno Setup 7\ISCC.exe"

if not defined ISCC (
  echo ERROR: Inno Setup 7 compiler ISCC.exe was not found.
  echo Install the 64-bit Inno Setup 7 release, then run this file again.
  echo.
  pause
  exit /b 1
)

echo Using Inno Setup:
echo   "%ISCC%"
echo.

if exist "dist-installer" rmdir /s /q "dist-installer"
mkdir "dist-installer" >nul 2>&1

echo Building online VerbaNode installer...
"%ISCC%" /DMyAppVersion=%APP_VERSION% "packaging\VerbaNode.iss"
if errorlevel 1 (
  echo.
  echo ============================================================
  echo Installer build failed.
  echo ============================================================
  pause
  exit /b 1
)

echo.
echo ============================================================
echo Installer build complete
echo ============================================================
echo Output:
echo   %CD%\dist-installer\VerbaNode-Setup-%APP_VERSION%.exe
echo.
echo The Setup EXE contains the VerbaNode application runtime. Selected AI
echo models and Ollama are downloaded online during installation if needed.
echo.
pause
endlocal
