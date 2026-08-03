@echo off
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"

if not defined VERBANODE_CONDA_ENV set "VERBANODE_CONDA_ENV=verbanode"
call :find_conda
if errorlevel 1 (
  echo.
  echo Conda was not found.
  echo Install Miniconda or Anaconda, then run this file again.
  echo You can also set VERBANODE_CONDA_BAT to the full path of conda.bat.
  echo Example: set VERBANODE_CONDA_BAT=C:\Users\YourName\miniconda3\condabin\conda.bat
  echo.
  pause
  exit /b 1
)

echo Using Conda: "%CONDA_BAT%"
echo Environment: %VERBANODE_CONDA_ENV%

call "%CONDA_BAT%" run -n "%VERBANODE_CONDA_ENV%" python -c "import sys" >nul 2>nul
if errorlevel 1 (
  echo.
  echo Creating Conda environment "%VERBANODE_CONDA_ENV%" with Python 3.11...
  call "%CONDA_BAT%" create -n "%VERBANODE_CONDA_ENV%" python=3.11 pip -y
  if errorlevel 1 (
    echo Failed to create the Conda environment.
    pause
    exit /b 1
  )
) else (
  echo Existing Conda environment found.
)

call "%CONDA_BAT%" activate "%VERBANODE_CONDA_ENV%"
if errorlevel 1 (
  echo Failed to activate the Conda environment.
  pause
  exit /b 1
)

python -c "import sys; raise SystemExit(0 if sys.version_info[:2] == (3, 11) else 1)"
if errorlevel 1 (
  echo The "%VERBANODE_CONDA_ENV%" environment is not using Python 3.11.
  echo Delete it with: conda env remove -n %VERBANODE_CONDA_ENV%
  echo Then run setup_windows.bat again.
  pause
  exit /b 1
)

python -m pip install --upgrade pip wheel setuptools
if errorlevel 1 goto :install_failed

python -m pip install -r requirements.txt
if errorlevel 1 goto :install_failed

if not exist .env (
  copy .env.example .env >nul
  for /f "delims=" %%P in ('python -c "import secrets; print(str(secrets.randbelow(900000)+100000))"') do set "GENERATED_PIN=%%P"
  powershell -NoProfile -Command "(Get-Content '.env') -replace '^VERBANODE_PIN=.*$', 'VERBANODE_PIN=!GENERATED_PIN!' | Set-Content '.env'"
  echo Generated controller PIN: !GENERATED_PIN!
)

echo.
echo Setup complete.
echo Conda environment: %VERBANODE_CONDA_ENV%
echo.
echo Next steps:
echo 1. Install Ollama for Windows and pull a model:
echo    ollama pull qwen3.5:0.8b
echo 2. Create the default database:
echo    setup_database.bat
echo 3. Download the local Kokoro model:
echo    download_kokoro.bat
echo.
echo 4. Pre-download the FunASR speech model before first conversation:
echo    download_funasr.bat
echo 5. Start VerbaNode with run.bat

echo.
pause
exit /b 0

:install_failed
echo.
echo Dependency installation failed.
echo Review the error above, then run setup_windows.bat again.
pause
exit /b 1

:find_conda
set "CONDA_BAT="
if defined VERBANODE_CONDA_BAT if exist "%VERBANODE_CONDA_BAT%" set "CONDA_BAT=%VERBANODE_CONDA_BAT%"
if defined CONDA_BAT exit /b 0

for /f "delims=" %%I in ('where conda.bat 2^>nul') do if not defined CONDA_BAT set "CONDA_BAT=%%I"
if defined CONDA_BAT exit /b 0

for %%I in (
  "%USERPROFILE%\miniconda3\condabin\conda.bat"
  "%USERPROFILE%\anaconda3\condabin\conda.bat"
  "%LOCALAPPDATA%\miniconda3\condabin\conda.bat"
  "%LOCALAPPDATA%\anaconda3\condabin\conda.bat"
  "%ProgramData%\miniconda3\condabin\conda.bat"
  "%ProgramData%\anaconda3\condabin\conda.bat"
) do if not defined CONDA_BAT if exist "%%~I" set "CONDA_BAT=%%~I"

if defined CONDA_BAT exit /b 0
exit /b 1
