#!/usr/bin/env bash
# Deltaplan Shift Monitor — one-command launcher
# Works on macOS and Linux. Sets up venv, installs deps, starts the dashboard.

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

VENV_DIR="$SCRIPT_DIR/.venv"
PORT="${DELTAPLAN_PORT:-5055}"

# ── Ensure Python 3 is available ──
if ! command -v python3 &>/dev/null; then
    echo "❌ Python 3 is required but not found."
    echo "   macOS: Install from https://www.python.org/downloads/ or run: brew install python3"
    echo "   Linux: sudo apt install python3 python3-venv"
    exit 1
fi

# ── Create venv if needed ──
if [ ! -d "$VENV_DIR" ]; then
    echo "📦 Creating virtual environment…"
    python3 -m venv "$VENV_DIR"
fi

# ── Activate venv ──
source "$VENV_DIR/bin/activate"

# ── Install/update dependencies ──
echo "📦 Installing dependencies…"
pip install -q -r requirements.txt

# ── Check config ──
if [ ! -f config.json ]; then
    echo "❌ config.json not found!"
    echo "   Copy config.example.json to config.json and fill in your credentials."
    exit 1
fi

if grep -q "YOUR_USERNAME_HERE" config.json 2>/dev/null; then
    echo "❌ Please edit config.json with your Deltaplan username and password first."
    exit 1
fi

# ── Start ──
echo ""
echo "🚀 Starting Deltaplan Shift Monitor on http://localhost:$PORT"
echo "   Press Ctrl+C to stop."
echo ""

# Open browser automatically (works on macOS and Linux)
(sleep 2 && {
    if command -v open &>/dev/null; then
        open "http://localhost:$PORT"
    elif command -v xdg-open &>/dev/null; then
        xdg-open "http://localhost:$PORT"
    fi
}) &

DELTAPLAN_PORT="$PORT" python3 web.py
