@echo off
REM Build MotoTRBO-TTS.exe on Windows.
REM Needs Python 3.10-3.13 (64-bit) from python.org, with "Add to PATH" ticked.
setlocal
cd /d "%~dp0"

where py >nul 2>nul && (set PY=py -3) || (set PY=python)

echo === Creating build environment ===
%PY% -m venv .build-venv || goto :fail
call .build-venv\Scripts\activate.bat || goto :fail
python -m pip install --upgrade pip || goto :fail
python -m pip install -r requirements.txt pyinstaller || goto :fail

echo === Building MotoTRBO-TTS.exe ===
pyinstaller --noconfirm --clean --onefile --windowed ^
  --name MotoTRBO-TTS --icon icon.ico --add-data "icon.ico;." ^
  --collect-all piper --collect-binaries onnxruntime ^
  app.py || goto :fail

echo === Self-test (downloads one small voice) ===
start /wait "" dist\MotoTRBO-TTS.exe --selftest "%CD%\selftest-output"
type selftest-output\selftest.log
findstr /c:"SELFTEST PASSED" selftest-output\selftest.log >nul || goto :fail

echo.
echo Done:  %CD%\dist\MotoTRBO-TTS.exe
exit /b 0

:fail
echo.
echo BUILD FAILED
exit /b 1
