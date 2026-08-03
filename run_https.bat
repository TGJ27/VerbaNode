@echo off
setlocal EnableExtensions
cd /d "%~dp0"

if not defined VERBANODE_CONDA_ENV set "VERBANODE_CONDA_ENV=verbanode"
call :find_conda
if errorlevel 1 (
  echo Conda was not found. Run setup_windows.bat first.
  pause
  exit /b 1
)
call "%CONDA_BAT%" activate "%VERBANODE_CONDA_ENV%" >nul 2>nul
if errorlevel 1 (
  echo Conda environment "%VERBANODE_CONDA_ENV%" could not be activated.
  pause
  exit /b 1
)

python scripts\generate_local_cert.py
if errorlevel 1 (
  echo Could not generate the local HTTPS certificate.
  pause
  exit /b 1
)

set "VERBANODE_SSL_CERTFILE=certs\verbanode-local-ca.crt"
set "VERBANODE_SSL_KEYFILE=certs\verbanode-local-ca.key"
python launcher.py
set "APP_EXIT_CODE=%ERRORLEVEL%"
if not "%APP_EXIT_CODE%"=="0" pause
exit /b %APP_EXIT_CODE%

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
