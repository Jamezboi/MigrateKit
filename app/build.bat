@echo off
setlocal EnableExtensions
cd /d "%~dp0"

echo ===================================================
echo   MigrateKit 1.2.2 Onedir Build Utility
echo ===================================================
python -m pip install -r requirements.txt || exit /b 1
python -m pip install pyinstaller || exit /b 1
if not exist migratekit_pro.py exit /b 1
if not exist github_upload.py exit /b 1
if not exist patch_github_upload.py exit /b 1

REM Apply source fixes and GitHub backup upload support before compilation.
python patch_github_upload.py
if %ERRORLEVEL% neq 0 exit /b 1

python -m py_compile migratekit_pro.py github_upload.py || exit /b 1
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist
if exist MigrateKit.spec del MigrateKit.spec

echo Building onedir runtime...
pyinstaller --clean --noconfirm --onedir --windowed --name=MigrateKit migratekit_pro.py
if %ERRORLEVEL% neq 0 exit /b 1
if not exist "%CD%\dist\MigrateKit\MigrateKit.exe" exit /b 1
if not exist "%CD%\dist\MigrateKit\_internal" exit /b 1

for /f %%A in ('powershell -NoProfile -Command "(Get-ChildItem -Recurse -File 'dist\\MigrateKit').Count"') do echo Runtime files: %%A
for %%A in ("%CD%\dist\MigrateKit\MigrateKit.exe") do echo Launcher: %%~zA bytes

if exist MigrateKit-1.2.2-Windows.zip del MigrateKit-1.2.2-Windows.zip
powershell -NoProfile -Command "Compress-Archive -Path 'dist\\MigrateKit\\*' -DestinationPath 'MigrateKit-1.2.2-Windows.zip' -CompressionLevel Optimal"
if %ERRORLEVEL% neq 0 exit /b 1
if not exist MigrateKit-1.2.2-Windows.zip exit /b 1

echo Build completed successfully.
exit /b 0
