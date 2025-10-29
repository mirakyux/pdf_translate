@echo off
setlocal

REM Thin wrapper to delegate to Python serve.py (supports --build-frontend and other arguments)
REM Usage:
REM   serve.bat [--build-frontend] [--host HOST] [--port PORT] [--frontend-dir DIR] [--out-dir DIR] [--api-base-url URL]

set "SCRIPT_DIR=%~dp0"

REM Build frontend with pnpm in the 'front' directory (if pnpm and package.json are available)
if exist "%SCRIPT_DIR%front\package.json" (
  where pnpm >nul 2>&1
  if %ERRORLEVEL% EQU 0 (
    echo Running 'pnpm -C "%SCRIPT_DIR%front" build'...
    call pnpm -C "%SCRIPT_DIR%front" build
    if %ERRORLEVEL% NEQ 0 (
      echo WARNING: 'pnpm build' failed in front directory. Continuing to start backend server.
    ) else (
      echo Frontend build completed successfully.
    )
  ) else (
    echo WARNING: pnpm not found on PATH, skipping frontend build.
  )
) else (
  echo INFO: front/package.json not found, skipping frontend build.
)

REM Try python directly first
REM Prefer uv run if available
where uv >nul 2>&1
if %ERRORLEVEL% EQU 0 (
  echo Starting server with 'uv run'...
  call uv run "%SCRIPT_DIR%serve.py" %*
  if %ERRORLEVEL% EQU 0 (
    goto :eof
  ) else (
    echo WARNING: 'uv run' exited with code %ERRORLEVEL%, falling back to python.
  )
) else (
  echo INFO: uv not found on PATH, trying python.
)

REM Try python directly first
python "%SCRIPT_DIR%serve.py" %*
if %ERRORLEVEL% EQU 0 (
  goto :eof
)

REM Fallback to py launcher if python failed or not found
py "%SCRIPT_DIR%serve.py" %*
if %ERRORLEVEL% EQU 0 (
  goto :eof
)

echo ERROR: uv and Python not found or failed to start. Please install uv or Python 3 and ensure it's on PATH.
exit /b 1