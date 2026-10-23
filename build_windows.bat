@echo off
setlocal enabledelayedexpansion
chcp 65001 >nul
cd /d "%~dp0"

REM HyperMix — сборка портативного Windows-релиза
REM Требуется: Windows 10/11, Python 3.10+, интернет для pip.
REM Результат: release\HyperMix-<version>-Windows-x86_64.zip

for /f "usebackq delims=" %%v in ("VERSION") do set "VERSION=%%v"
set "NAME=HyperMix-%VERSION%-Windows-x86_64"
set "DIST=release\%NAME%"

echo ============================================================
echo  HyperMix %VERSION% - Windows build
echo ============================================================

python -m pip install --upgrade pip
if errorlevel 1 goto :error
python -m pip install -r requirements-windows.txt pyinstaller
if errorlevel 1 goto :error

REM Python 3.13+ удалил audioop — pydub нужен audioop-lts
python -c "import sys; sys.exit(0 if sys.version_info >= (3,13) else 1)"
if not errorlevel 1 (
  python -m pip install audioop-lts
  if errorlevel 1 goto :error
)

if exist build rmdir /s /q build
if exist dist rmdir /s /q dist
if exist "%DIST%" rmdir /s /q "%DIST%"
if not exist release mkdir release
if not exist "%DIST%" mkdir "%DIST%"

echo.
echo === PyInstaller ===
python -m PyInstaller --noconfirm --clean --onefile --windowed --name "HyperMix" ^
  --icon "assets\hypermix.ico" ^
  --version-file "packaging\version_info.txt" ^
  --add-data "assets;assets" ^
  --distpath "dist" ^
  --workpath "build" ^
  --collect-all sounddevice ^
  --collect-all soundfile ^
  --hidden-import=pynput.keyboard._win32 ^
  --hidden-import=pynput.mouse._win32 ^
  --exclude-module=dbus_next ^
  --exclude-module=keyboard ^
  --exclude-module=fcntl ^
  main.py
if errorlevel 1 goto :error
if not exist "dist\HyperMix.exe" goto :error

echo.
echo === Формирую %DIST% ===
copy /y "dist\HyperMix.exe" "%DIST%\HyperMix.exe" >nul
copy /y "packaging\config.default.json" "%DIST%\config.json" >nul
copy /y "README.md" "%DIST%\README.md" >nul
copy /y "CHANGELOG.md" "%DIST%\CHANGELOG.md" >nul
copy /y "LICENSE" "%DIST%\LICENSE" >nul
copy /y "assets\hypermix.ico" "%DIST%\hypermix.ico" >nul
copy /y "packaging\START_HERE.txt" "%DIST%\START_HERE.txt" >nul

if exist "release\%NAME%.zip" del /q "release\%NAME%.zip"
powershell -NoProfile -ExecutionPolicy Bypass -Command "Compress-Archive -Path '%DIST%\*' -DestinationPath 'release\%NAME%.zip' -Force"
if errorlevel 1 goto :error

echo.
echo Готово:
echo   %DIST%\HyperMix.exe
echo   release\%NAME%.zip
echo.
if not defined CI pause
exit /b 0

:error
echo.
echo ОШИБКА сборки. Смотрите вывод выше.
if not defined CI pause
exit /b 1
