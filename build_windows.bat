@echo off
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"

if not defined VERBANODE_CONDA_ENV set "VERBANODE_CONDA_ENV=verbanode"

echo ============================================================
echo VerbaNode v0.7.6 Windows application build
echo ============================================================
echo.

echo [1/7] Locating Conda...
call :find_conda
if errorlevel 1 (
  echo.
  echo Conda was not found.
  echo Install Miniconda or Anaconda, then run this file again.
  echo You can also set VERBANODE_CONDA_BAT to the full path of conda.bat.
  echo Example:
  echo   set VERBANODE_CONDA_BAT=C:\Users\YourName\miniconda3\condabin\conda.bat
  echo.
  pause
  exit /b 1
)

echo Using Conda: "%CONDA_BAT%"
echo Target environment: %VERBANODE_CONDA_ENV%
echo.

echo [2/7] Checking Conda environment...
call "%CONDA_BAT%" run -n "%VERBANODE_CONDA_ENV%" python -c "import sys" >nul 2>nul
if errorlevel 1 (
  echo Environment "%VERBANODE_CONDA_ENV%" was not found.
  echo Creating it with Python 3.11 and pip...
  call "%CONDA_BAT%" create -n "%VERBANODE_CONDA_ENV%" python=3.11 pip -y
  if errorlevel 1 (
    echo.
    echo Failed to create Conda environment "%VERBANODE_CONDA_ENV%".
    goto :fail
  )
) else (
  echo Existing Conda environment found.
)

echo.
echo [3/7] Activating Conda environment...
call "%CONDA_BAT%" activate "%VERBANODE_CONDA_ENV%"
if errorlevel 1 (
  echo Failed to activate Conda environment "%VERBANODE_CONDA_ENV%".
  goto :fail
)

set "PYTHON_EXE="
for /f "usebackq delims=" %%P in (`python -c "import sys; print(sys.executable)"`) do set "PYTHON_EXE=%%P"
if not defined PYTHON_EXE (
  echo Python could not be resolved after Conda activation.
  goto :fail
)

echo Using Python: "!PYTHON_EXE!"
python -c "import sys; raise SystemExit(0 if sys.version_info[:2] == (3, 11) else 1)"
if errorlevel 1 (
  echo.
  echo The "%VERBANODE_CONDA_ENV%" environment is not using Python 3.11.
  echo Current interpreter: "!PYTHON_EXE!"
  echo Remove it with:
  echo   conda env remove -n %VERBANODE_CONDA_ENV%
  echo Then run build_windows.bat again so it can create a clean Python 3.11 environment.
  goto :fail
)

echo.
echo [4/7] Updating build tools...
python -m pip install --upgrade pip wheel setuptools
if errorlevel 1 goto :fail

echo.
echo [5/7] Installing VerbaNode and packaging dependencies...
python -m pip install -r requirements.txt
if errorlevel 1 goto :fail
python -m pip install -r requirements-packaging.txt
if errorlevel 1 goto :fail

echo.
echo [6/7] Cleaning previous build output...
tasklist /FI "IMAGENAME eq VerbaNode.exe" 2^>nul | find /I "VerbaNode.exe" >nul
if not errorlevel 1 (
  echo.
  echo VerbaNode.exe is still running.
  echo Use the launcher Exit button and wait for it to close before rebuilding.
  echo If it remains stuck, run: taskkill /F /IM VerbaNode.exe
  goto :fail
)
if exist build rmdir /s /q build
if exist dist\VerbaNode rmdir /s /q dist\VerbaNode
if exist dist\VerbaNode (
  echo.
  echo Previous dist\VerbaNode could not be removed.
  echo A process or antivirus scanner may still be locking the folder.
  goto :fail
)

echo.
echo [7/7] Building VerbaNode.exe...
python -m PyInstaller --noconfirm --clean VerbaNode.spec
if errorlevel 1 goto :fail

if not exist dist\VerbaNode\VerbaNode.exe (
  echo Build finished without the expected executable.
  goto :fail
)

echo.
echo ============================================================
echo Build complete
echo ============================================================
echo Environment: %VERBANODE_CONDA_ENV%
echo Python:      !PYTHON_EXE!
echo Executable:  %CD%\dist\VerbaNode\VerbaNode.exe
echo.
echo Test it by double-clicking VerbaNode.exe.
echo The packaged app stores mutable data under:
echo   %%LOCALAPPDATA%%\VerbaNode
echo.
pause
exit /b 0

:fail
echo.
echo ============================================================
echo VerbaNode Windows build failed.
echo ============================================================
echo Environment: %VERBANODE_CONDA_ENV%
if defined PYTHON_EXE echo Python: !PYTHON_EXE!
echo Review the error above, then run build_windows.bat again.
echo.
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
