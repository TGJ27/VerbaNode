@echo off
setlocal
cd /d "%~dp0"

if not defined VERBANODE_CONDA_ENV set "VERBANODE_CONDA_ENV=verbanode"

where conda >nul 2>nul
if errorlevel 1 (
    for %%D in ("%USERPROFILE%\miniconda3" "%USERPROFILE%\anaconda3" "%LOCALAPPDATA%\miniconda3" "%ProgramData%\miniconda3" "%ProgramData%\anaconda3") do (
        if exist "%%~D\Scripts\activate.bat" (
            call "%%~D\Scripts\activate.bat"
            goto :conda_ready
        )
    )
    echo Conda was not found. Install Miniconda or run this from Anaconda Prompt.
    exit /b 1
)

:conda_ready
echo Downloading Whisper Base for Indonesian speech recognition...
echo This model is downloaded once and reused by the isolated AI Engine.
call conda run --no-capture-output -n "%VERBANODE_CONDA_ENV%" python -u scripts\download_whisper.py
if errorlevel 1 exit /b %errorlevel%

echo.
echo Whisper Base setup completed.
pause
