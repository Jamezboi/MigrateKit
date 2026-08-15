@echo off
setlocal EnableExtensions

echo ===================================================
echo   MigrateKit PyInstaller Executable Build Utility
echo ===================================================
echo.

cd /d "%~dp0"

echo [1/5] Installing dependencies...
python -m pip install -r requirements.txt
if %ERRORLEVEL% neq 0 (
    echo ERROR: Failed to install Python dependencies.
    exit /b 1
)
python -m pip install pyinstaller
if %ERRORLEVEL% neq 0 (
    echo ERROR: Failed to install PyInstaller.
    exit /b 1
)


echo.
echo [2/5] Applying source compatibility fix...
python -c "from pathlib import Path; p=Path('migratekit.py'); s=p.read_text(encoding='utf-8'); old='        self.user_profile = os.environ.get(\"USERPROFILE\", \"\")\n        self.engine = MigrationEngine(self.msg_queue, self.cancel_event)'; new='        self.user_profile = os.environ.get(\"USERPROFILE\", \"\")\n        self.appdata_roaming = os.environ.get(\"APPDATA\", \"\")\n        self.appdata_local = os.environ.get(\"LOCALAPPDATA\", \"\")\n        self.engine = MigrationEngine(self.msg_queue, self.cancel_event)'; assert old in s, 'Expected MigrateKitApp initialization block was not found'; p.write_text(s.replace(old,new,1),encoding='utf-8')"
if %ERRORLEVEL% neq 0 (
    echo ERROR: Could not apply compatibility fix.
    exit /b 1
)


echo.
echo [3/5] Running Python syntax validation...
python -m py_compile migratekit.py
if %ERRORLEVEL% neq 0 (
    echo ERROR: migratekit.py failed syntax validation.
    exit /b 1
)


echo.
echo [4/5] Compiling application using PyInstaller...
for /f "delims=" %%i in ('python -c "import customtkinter, os; print(os.path.dirname(customtkinter.__file__))"') do set "CTK_PATH=%%i"
if "%CTK_PATH%"=="" (
    echo ERROR: Could not locate customtkinter.
    exit /b 1
)

if exist build rmdir /s /q build
if exist dist rmdir /s /q dist
if exist MigrateKit.spec del MigrateKit.spec

pyinstaller --clean --noconfirm --onefile --windowed ^
  --add-data "%CTK_PATH%;customtkinter/" ^
  --hidden-import=darkdetect ^
  --name=MigrateKit ^
  migratekit.py

if %ERRORLEVEL% neq 0 (
    echo ERROR: PyInstaller compilation failed.
    exit /b 1
)


echo.
echo [5/5] Verifying executable...
if not exist "%CD%\dist\MigrateKit.exe" (
    echo ERROR: MigrateKit.exe was not produced.
    exit /b 1
)

for %%A in ("%CD%\dist\MigrateKit.exe") do echo Built: %%~fA && echo Size: %%~zA bytes

echo.
echo Build completed successfully.
exit /b 0
