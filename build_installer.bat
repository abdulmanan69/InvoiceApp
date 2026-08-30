@echo off
setlocal
cd /d "%~dp0"
echo === InvoiceApp installer build ===
if not exist "InvoiceApp.exe" (
  echo InvoiceApp.exe not found. Run build.bat first.
  exit /b 1
)
set "ISCC="
if exist "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" set "ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if exist "%ProgramFiles%\Inno Setup 6\ISCC.exe" set "ISCC=%ProgramFiles%\Inno Setup 6\ISCC.exe"
if exist "%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe" set "ISCC=%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe"
if not defined ISCC (
  for /f "delims=" %%I in ('where iscc 2^>nul') do set "ISCC=%%I"
)
if not defined ISCC (
  echo Inno Setup 6 was not found.
  echo Install it once with:  winget install JRSoftware.InnoSetup
  echo Then run this script again.
  exit /b 1
)
echo Using: %ISCC%
"%ISCC%" installer.iss || (echo Installer build failed & exit /b 1)
echo.
echo Done: %~dp0dist\InvoiceApp-Setup.exe
echo Share that single file - double-clicking it installs InvoiceApp on any Windows 10/11 PC.
endlocal
