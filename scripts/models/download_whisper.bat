@echo off
setlocal
cd /d "%~dp0..\.."

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
set "WHISPER_MODEL=%~1"
if "%WHISPER_MODEL%"=="" set "WHISPER_MODEL=base"

echo Preparing Whisper %WHISPER_MODEL% for Indonesian speech recognition...
echo Usage: download_whisper.bat [base^|small^|both]
call conda run --no-capture-output -n "%VERBANODE_CONDA_ENV%" python -u scripts\models\download_whisper.py --model "%WHISPER_MODEL%"
if errorlevel 1 exit /b %errorlevel%

echo.
echo Whisper setup completed.
pause
