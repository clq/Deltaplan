# Deltaplan Shift Monitor

A web dashboard that monitors shift schedules from [Deltaplan](https://deltaplan.dk) and alerts when new vacant shifts become available.

## Features

- **Your shifts** — see your upcoming schedule at a glance
- **Colleagues' shifts** — who's working FP 1, FP 2, and E 3 each day
- **Vacant shift alerts** — audio chime + visual alert when new shifts open up
- **Configurable polling** — adjust how often it checks (1–120 minutes)

## Quick Start

1. Copy `config.example.json` to `config.json` and fill in your credentials:
   ```bash
   cp config.example.json config.json
   # Edit config.json with your username and password
   ```

2. Run:
   ```bash
   ./start.sh
   ```
   This sets up a Python virtual environment, installs dependencies, and opens the dashboard in your browser.

## Requirements

- Python 3.9+ (macOS: `brew install python3` or download from [python.org](https://www.python.org/downloads/))

## CLI Usage

If you prefer the command line:

```bash
source .venv/bin/activate
python main.py login          # Test login
python main.py shifts         # Show your shifts
python main.py vacant         # Show available shifts
python main.py shifttypes     # List all shift types
python main.py monitor        # Poll & send desktop notifications
```
