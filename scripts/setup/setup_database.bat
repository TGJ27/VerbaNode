@echo off
setlocal EnableExtensions
cd /d "%~dp0..\.."

if defined PYTHONPATH (
  set "PYTHONPATH=%CD%;%PYTHONPATH%"
) else (
  set "PYTHONPATH=%CD%"
)

if not defined VERBANODE_CONDA_ENV set "VERBANODE_CONDA_ENV=verbanode"
call :find_conda
if errorlevel 1 (
  echo Conda was not found. Run scripts\setup\setup_windows.bat first.
  pause
  exit /b 1
)

call "%CONDA_BAT%" run -n "%VERBANODE_CONDA_ENV%" python -c "import sys" >nul 2>nul
if errorlevel 1 (
  echo Conda environment "%VERBANODE_CONDA_ENV%" does not exist.
  echo Run scripts\setup\setup_windows.bat first.
  pause
  exit /b 1
)

if /I "%~1"=="--reset" goto :reset
call "%CONDA_BAT%" run --no-capture-output -n "%VERBANODE_CONDA_ENV%" python -u scripts\setup\setup_database.py
if errorlevel 1 goto :failed
pause
exit /b 0

:reset
echo.
echo WARNING: This deletes all agents, scripts, settings, conversations, and memory.
set /p CONFIRM=Type RESET to continue: 
if /I not "%CONFIRM%"=="RESET" (
  echo Cancelled.
  pause
  exit /b 0
)
call "%CONDA_BAT%" run --no-capture-output -n "%VERBANODE_CONDA_ENV%" python -u scripts\setup\setup_database.py --reset
if errorlevel 1 goto :failed
pause
exit /b 0

:failed
echo Database setup failed.
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
