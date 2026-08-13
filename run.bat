@echo off
setlocal EnableExtensions
cd /d "%~dp0"

rem Keep the repository root importable for launcher.py and any nested helper.
if defined PYTHONPATH (
  set "PYTHONPATH=%CD%;%PYTHONPATH%"
) else (
  set "PYTHONPATH=%CD%"
)

if not defined VERBANODE_CONDA_ENV set "VERBANODE_CONDA_ENV=verbanode"
call :find_conda
if errorlevel 1 (
  echo.
  echo Conda was not found.
  echo Install Miniconda or Anaconda, then run scripts\setup\setup_windows.bat.
  echo You can also set VERBANODE_CONDA_BAT to the full path of conda.bat.
  echo.
  pause
  exit /b 1
)

call "%CONDA_BAT%" activate "%VERBANODE_CONDA_ENV%" >nul 2>nul
if errorlevel 1 (
  echo.
  echo Conda environment "%VERBANODE_CONDA_ENV%" was not found or could not be activated.
  echo Run scripts\setup\setup_windows.bat first.
  echo.
  pause
  exit /b 1
)

rem Fail early with a clear source-tree error instead of a nested ModuleNotFoundError.
python -c "import app" >nul 2>nul
if errorlevel 1 (
  echo.
  echo VerbaNode source modules could not be imported from:
  echo   %CD%
  echo Make sure this is the complete VerbaNode source tree.
  echo.
  pause
  exit /b 1
)

rem launcher.py owns local HTTPS certificate creation/refresh in source mode.
python launcher.py
set "APP_EXIT_CODE=%ERRORLEVEL%"
if not "%APP_EXIT_CODE%"=="0" (
  echo.
  echo VerbaNode exited with error code %APP_EXIT_CODE%.
  pause
)
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
