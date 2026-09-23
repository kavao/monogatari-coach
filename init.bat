@echo off
REM Initialize local Python workspace via uv + howto_init.py

setlocal

cd /d "%~dp0"

where uv >nul 2>&1
if errorlevel 1 (
  echo uv was not found. Install it first:
  echo   https://docs.astral.sh/uv/
  echo   powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
  goto :END
)

echo Running uv sync...
uv sync
if errorlevel 1 (
  echo uv sync failed.
  goto :END
)

echo Running howto_init.py...
uv run python howto_init.py
if errorlevel 1 (
  echo howto_init.py failed.
  goto :END
)

echo.
echo Use uv run python to execute tools after this.

:END
endlocal
pause
