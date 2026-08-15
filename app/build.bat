@echo off
setlocal EnableExtensions
cd /d "%~dp0"

echo ===================================================
echo   MigrateKit 1.2.1 Onedir Build Utility
 echo ===================================================
python -m pip install -r requirements.txt || exit /b 1
python -m pip install pyinstaller || exit /b 1
if not exist migratekit_pro.py exit /b 1

REM Fix duplicate CTkButton height kwargs in the source before compilation.
python -c "from pathlib import Path; p=Path('migratekit_pro.py'); s=p.read_text(encoding='utf-8'); old='return ctk.CTkButton(p, text=text, command=command, fg_color=kw.pop(\"fg\", BLUE), hover_color=kw.pop(\"hover\", BLUE_H), corner_radius=9, height=42, font=ctk.CTkFont(size=13, weight=\"bold\"), **kw)'; new='height=kw.pop(\"height\", 42); return ctk.CTkButton(p, text=text, command=command, fg_color=kw.pop(\"fg\", BLUE), hover_color=kw.pop(\"hover\", BLUE_H), corner_radius=9, height=height, font=ctk.CTkFont(size=13, weight=\"bold\"), **kw)'; assert old in s, 'CTkButton helper not found'; p.write_text(s.replace(old,new,1),encoding='utf-8')"
if %ERRORLEVEL% neq 0 exit /b 1

python -m py_compile migratekit_pro.py || exit /b 1
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

if exist MigrateKit-1.2.1-Windows.zip del MigrateKit-1.2.1-Windows.zip
powershell -NoProfile -Command "Compress-Archive -Path 'dist\\MigrateKit\\*' -DestinationPath 'MigrateKit-1.2.1-Windows.zip' -CompressionLevel Optimal"
if %ERRORLEVEL% neq 0 exit /b 1
if not exist MigrateKit-1.2.1-Windows.zip exit /b 1

echo Build completed successfully.
exit /b 0
