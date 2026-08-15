@echo off
setlocal EnableExtensions

echo ===================================================
echo   MigrateKit 1.1.0 PyInstaller Build Utility
echo ===================================================
echo.

cd /d "%~dp0"

echo [1/6] Installing dependencies...
python -m pip install -r requirements.txt
if %ERRORLEVEL% neq 0 exit /b 1
python -m pip install pyinstaller
if %ERRORLEVEL% neq 0 exit /b 1

echo.
echo [2/6] Selecting MigrateKit 1.1.0 source...
if not exist migratekit_v2.py (
  echo ERROR: migratekit_v2.py is missing.
  exit /b 1
)
copy /Y migratekit_v2.py migratekit.py >nul
if %ERRORLEVEL% neq 0 (
  echo ERROR: Could not stage migratekit.py.
  exit /b 1
)

echo [3/6] Running Python syntax validation...
python -m py_compile migratekit.py
if %ERRORLEVEL% neq 0 (
  echo ERROR: migratekit.py failed syntax validation.
  exit /b 1
)

echo [4/6] Locating CustomTkinter...
for /f "delims=" %%i in ('python -c "import customtkinter, os; print(os.path.dirname(customtkinter.__file__))"') do set "CTK_PATH=%%i"
if "%CTK_PATH%"=="" exit /b 1

if exist build rmdir /s /q build
if exist dist rmdir /s /q dist
if exist MigrateKit.spec del MigrateKit.spec

echo [5/6] Compiling MigrateKit 1.1.0...
pyinstaller --clean --noconfirm --onefile --windowed ^
  --add-data "%CTK_PATH%;customtkinter/" ^
  --hidden-import=darkdetect ^
  --name=MigrateKit ^
  migratekit.py
if %ERRORLEVEL% neq 0 (
  echo ERROR: PyInstaller compilation failed.
  exit /b 1
)

echo [6/6] Verifying executable...
if not exist "%CD%\dist\MigrateKit.exe" (
  echo ERROR: MigrateKit.exe was not produced.
  exit /b 1
)
for %%A in ("%CD%\dist\MigrateKit.exe") do echo Built: %%~fA && echo Size: %%~zA bytes
echo Build completed successfully.
exit /b 0
