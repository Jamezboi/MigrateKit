@echo off
echo ===================================================
echo   MigrateKit PyInstaller Executable Build Utility
echo ===================================================
echo.

echo [1/4] Installing dependencies...
pip install -r requirements.txt
if %ERRORLEVEL% neq 0 (
    echo.
    echo ERROR: Failed to install python dependencies. Ensure Python and pip are installed and added to PATH.
    pause
    exit /b 1
)

echo.
echo [2/4] Finding customtkinter package folder dynamically...
for /f "delims=" %%i in ('python -c "import customtkinter, os; print(os.path.dirname(customtkinter.__file__))"') do set CTK_PATH=%%i

if "%CTK_PATH%"=="" (
    echo.
    echo ERROR: Could not locate customtkinter path. Try running 'pip install customtkinter' manually.
    pause
    exit /b 1
)

echo Located CustomTkinter: %CTK_PATH%

echo.
echo [3/4] Compiling application using PyInstaller...
pyinstaller --clean --noconfirm --onefile --windowed ^
  --add-data "%CTK_PATH%;customtkinter/" ^
  --hidden-import=darkdetect ^
  --name=MigrateKit ^
  migratekit.py

if %ERRORLEVEL% neq 0 (
    echo.
    echo ERROR: PyInstaller compilation failed. Check logs above.
    pause
    exit /b 1
)

echo.
echo [4/4] Compilation finished!
echo Executable is located at: %cd%\dist\MigrateKit.exe
echo.
pause
