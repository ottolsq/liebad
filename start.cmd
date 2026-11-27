@echo off
setlocal EnableExtensions DisableDelayedExpansion
pushd "%~dp0" || exit /b 1

if not exist ".venv\pyvenv.cfg" (
    >&2 echo Liebad could not find .venv\pyvenv.cfg. Set up the project environment first.
    popd
    exit /b 1
)

set "LIEBAD_BASE_PYTHON_DIR="
for /f "usebackq tokens=1,2,*" %%A in (".venv\pyvenv.cfg") do (
    if "%%A"=="home" if "%%B"=="=" set "LIEBAD_BASE_PYTHON_DIR=%%C"
)
if not defined LIEBAD_BASE_PYTHON_DIR (
    >&2 echo Liebad could not read the Python home from .venv\pyvenv.cfg.
    popd
    exit /b 1
)
if not exist "%LIEBAD_BASE_PYTHON_DIR%\python.exe" (
    >&2 echo Liebad could not find "%LIEBAD_BASE_PYTHON_DIR%\python.exe".
    popd
    exit /b 1
)

rem Use the base interpreter to avoid a low-integrity .venv launcher.
set "PYTHONPATH=%CD%\src;%CD%\.venv\Lib\site-packages"
rem Keep cmd's Ctrl+C confirmation off the console while preserving Python output.
call :launch 3>&1 4>&2 <nul >nul 2>&1
set "LIEBAD_EXIT_CODE=%ERRORLEVEL%"
popd
exit /b %LIEBAD_EXIT_CODE%

:launch
"%LIEBAD_BASE_PYTHON_DIR%\python.exe" -s -m liebad 1>&3 2>&4
exit /b %ERRORLEVEL%
