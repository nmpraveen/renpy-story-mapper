@echo off
setlocal

cd /d "%~dp0"
set "RSM_LAUNCHER=%CD%\.venv\Scripts\renpy-story-mapper-web.exe"

if not exist "%RSM_LAUNCHER%" (
    echo Ren'Py Story Mapper is not installed in this checkout yet.
    echo.
    echo Run this command from PowerShell first:
    echo   py -3.12 -m venv .venv
    echo   .\.venv\Scripts\python.exe -m pip install -e ".[dev]"
    echo.
    pause
    exit /b 1
)

"%RSM_LAUNCHER%" %*
set "RSM_EXIT_CODE=%ERRORLEVEL%"

if not "%RSM_EXIT_CODE%"=="0" (
    echo.
    echo Ren'Py Story Mapper stopped with exit code %RSM_EXIT_CODE%.
    pause
)

exit /b %RSM_EXIT_CODE%
