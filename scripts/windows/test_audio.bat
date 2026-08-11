@echo off
setlocal EnableExtensions
cd /d "%~dp0..\.."

if not defined VERBANODE_CONDA_ENV set "VERBANODE_CONDA_ENV=verbanode"
set "CONDA_BAT="
if defined VERBANODE_CONDA_BAT if exist "%VERBANODE_CONDA_BAT%" set "CONDA_BAT=%VERBANODE_CONDA_BAT%"
for /f "delims=" %%I in ('where conda.bat 2^>nul') do if not defined CONDA_BAT set "CONDA_BAT=%%I"
for %%I in (
  "%USERPROFILE%\miniconda3\condabin\conda.bat"
  "%USERPROFILE%\anaconda3\condabin\conda.bat"
  "%LOCALAPPDATA%\miniconda3\condabin\conda.bat"
  "%LOCALAPPDATA%\anaconda3\condabin\conda.bat"
  "%ProgramData%\miniconda3\condabin\conda.bat"
  "%ProgramData%\anaconda3\condabin\conda.bat"
) do if not defined CONDA_BAT if exist "%%~I" set "CONDA_BAT=%%~I"

if not defined CONDA_BAT (
  echo Conda was not found.
  pause
  exit /b 1
)

call "%CONDA_BAT%" activate "%VERBANODE_CONDA_ENV%" >nul 2>nul
if errorlevel 1 (
  echo Conda environment "%VERBANODE_CONDA_ENV%" was not found.
  pause
  exit /b 1
)

python scripts\windows\test_audio.py
echo.
pause
