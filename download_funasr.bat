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
echo Downloading the FunASR speech model into the local model cache...
echo This is about 936 MB and can take a long time on a slow connection.
call conda run --no-capture-output -n "%VERBANODE_CONDA_ENV%" python -u scripts\download_funasr.py
if errorlevel 1 exit /b %errorlevel%

echo.
echo FunASR model setup completed.
pause
