@echo off
REM Build the MotoTRBO TTS installer on Windows, with all English voices built in.
REM Needs: 64-bit Python 3.10-3.13 from python.org ("Add to PATH" ticked),
REM        Inno Setup 6 (https://jrsoftware.org/isdl.php), about 15 GB free disk.
setlocal
cd /d "%~dp0"

where py >nul 2>nul && (set PY=py -3) || (set PY=python)

echo === Creating build environment ===
%PY% -m venv .build-venv || goto :fail
call .build-venv\Scripts\activate.bat || goto :fail
python -m pip install --upgrade pip || goto :fail
python -m pip install -r requirements.txt pyinstaller || goto :fail

echo === Building app folder ===
pyinstaller --noconfirm --clean --onedir --windowed ^
  --name MotoTRBO-TTS --icon icon.ico --add-data "icon.ico;." ^
  --collect-all piper --collect-binaries onnxruntime ^
  app.py || goto :fail

echo === Downloading English voices (several GB; safe to re-run) ===
python fetch_voices.py --match "^en_" --out voices || goto :fail

echo === Self-test ===
set MOTOTRBO_BUNDLED_VOICES=%CD%\voices
start /wait "" dist\MotoTRBO-TTS\MotoTRBO-TTS.exe --selftest "%CD%\selftest-output"
type selftest-output\selftest.log
findstr /c:"SELFTEST PASSED" selftest-output\selftest.log >nul || goto :fail
set MOTOTRBO_BUNDLED_VOICES=

echo === Building installer ===
set ISCC="%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if not exist %ISCC% (
  echo Inno Setup 6 not found. Install it from https://jrsoftware.org/isdl.php and run build.bat again.
  goto :fail
)
%ISCC% /Q installer.iss || goto :fail

echo.
echo Done. Installer files are in %CD%\installer-output
echo Keep MotoTRBO-TTS-Setup.exe and all MotoTRBO-TTS-Setup-*.bin files together.
exit /b 0

:fail
echo.
echo BUILD FAILED
exit /b 1
