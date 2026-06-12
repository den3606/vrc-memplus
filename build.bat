@echo off
setlocal
cd /d "%~dp0"

echo [1/4] Preparing virtual environment...
if not exist ".venv\Scripts\python.exe" (
  python -m venv .venv
  if errorlevel 1 goto :error
)

echo [2/4] Installing dependencies...
.venv\Scripts\python.exe -m pip install -q -r requirements-build.txt
if errorlevel 1 goto :error

echo [3/4] Generating app icon...
.venv\Scripts\python.exe scripts\generate_icon.py
if errorlevel 1 goto :error

echo [4/4] Building executable...
.venv\Scripts\pyinstaller.exe vrcmem.spec --noconfirm --clean
if errorlevel 1 goto :error

echo.
echo Build complete.
echo Output: dist\VRCMemPlus\VRCMemPlus.exe
echo.
echo You can zip the whole dist\VRCMemPlus folder to share the app.
goto :eof

:error
echo.
echo Build failed.
exit /b 1
