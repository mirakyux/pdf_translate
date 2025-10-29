#!/usr/bin/env sh

# Thin wrapper to delegate to Python serve.py
# Usage:
#   ./serve.sh [--host HOST] [--port PORT] [--frontend-dir DIR] [--out-dir DIR] [--api-base-url URL]
#
# Behavior:
# - If front/package.json exists and pnpm is available, runs a frontend build in ./front
# - Build failures do NOT stop backend startup; a warning is printed and the script continues
# - Starts the Python backend by invoking serve.py with all passed arguments

# Resolve the directory of this script (portable, handles symlinks)
SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd -P)"

# Frontend build step (conditional)
if [ -f "$SCRIPT_DIR/front/package.json" ]; then
  if command -v pnpm >/dev/null 2>&1; then
    echo "Running 'pnpm build' in '$SCRIPT_DIR/front'..."
    if (cd "$SCRIPT_DIR/front" && pnpm build); then
      echo "Frontend build completed successfully."
    else
      echo "WARNING: 'pnpm build' failed in front directory. Continuing to start backend server."
    fi
  else
    echo "WARNING: pnpm not found on PATH, skipping frontend build."
  fi
else
  echo "INFO: front/package.json not found, skipping frontend build."
fi

# Start backend (prefer 'uv run serve.py', then fall back to python3/python/py)
if command -v uv >/dev/null 2>&1; then
  uv run "$SCRIPT_DIR/serve.py" "$@"
  exit $?
fi

PYTHON_CMD=""
for cmd in python3 python py; do
  if command -v "$cmd" >/dev/null 2 >&1; then
    PYTHON_CMD="$cmd"
    break
  fi
done

if [ -n "$PYTHON_CMD" ]; then
  "$PYTHON_CMD" "$SCRIPT_DIR/serve.py" "$@"
  exit $?
fi

echo "ERROR: Python or uv not found, or failed to start. Please install uv or Python 3 and ensure it's on PATH."
exit 1