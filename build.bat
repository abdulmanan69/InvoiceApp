@echo off
setlocal
cd /d "%~dp0"
echo === InvoiceApp build ===
where python >nul 2>nul || (echo Python 3.11+ is required on PATH. & exit /b 1)
echo Installing dependencies...
python -m pip install --quiet --upgrade -r requirements.txt || (echo pip install failed & exit /b 1)
echo Running tests...
python -m unittest tests.test_flow || (echo Tests failed - build aborted & exit /b 1)
echo Building InvoiceApp.exe ...
python -m PyInstaller --noconfirm --clean --onefile --windowed --name InvoiceApp ^
  --icon appicon.ico ^
  --version-file version_info.txt ^
  --add-data "appicon.ico;." ^
  --collect-data ttkbootstrap ^
  --hidden-import PIL._tkinter_finder ^
  --exclude-module numpy --exclude-module pandas --exclude-module matplotlib --exclude-module scipy ^
  --exclude-module IPython --exclude-module jupyter --exclude-module pytest --exclude-module unittest ^
  --exclude-module test --exclude-module setuptools --exclude-module pip ^
  main.py || (echo PyInstaller failed & exit /b 1)
copy /y dist\InvoiceApp.exe InvoiceApp.exe >nul
echo.
echo Done: %~dp0InvoiceApp.exe
echo The app stores its data in a "data" folder next to the exe (or in %%LOCALAPPDATA%%\InvoiceApp when installed).
echo To also build the Windows installer, run build_installer.bat next.
endlocal
