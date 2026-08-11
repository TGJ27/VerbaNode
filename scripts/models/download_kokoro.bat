@echo off
setlocal EnableExtensions
cd /d "%~dp0..\.."

if not defined VERBANODE_CONDA_ENV set "VERBANODE_CONDA_ENV=verbanode"
call :find_conda
if errorlevel 1 (
    echo.
    echo Conda was not found.
    echo Install Miniconda or Anaconda, or run this file from Anaconda Prompt.
    echo You can also set VERBANODE_CONDA_BAT to the full path of conda.bat.
    echo Example:
    echo   set VERBANODE_CONDA_BAT=C:\Users\YourName\miniconda3\condabin\conda.bat
    echo.
    pause
    exit /b 1
)

echo ================================================================
echo VerbaNode - Kokoro Local TTS Model Downloader
echo ================================================================
echo Conda environment: %VERBANODE_CONDA_ENV%
echo Model: kokoro-int8-multi-lang-v1_1
echo Destination: models\kokoro\kokoro-int8-multi-lang-v1_1
echo.

call "%CONDA_BAT%" run -n "%VERBANODE_CONDA_ENV%" python -c "import sys" >nul 2>nul
if errorlevel 1 (
    echo The Conda environment "%VERBANODE_CONDA_ENV%" does not exist.
    echo Run scripts\setup\setup_windows.bat first.
    echo.
    pause
    exit /b 1
)

call "%CONDA_BAT%" run --no-capture-output -n "%VERBANODE_CONDA_ENV%" python -u scripts\models\download_kokoro.py
set "RESULT=%ERRORLEVEL%"
if not "%RESULT%"=="0" (
    echo.
    echo Kokoro download or extraction failed with error code %RESULT%.
    echo Check your internet connection, then run this file again.
    pause
    exit /b %RESULT%
)

echo.
echo Kokoro model setup completed successfully.
echo You can now select Kokoro in the Agent TTS settings.
echo.
pause
exit /b 0

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
