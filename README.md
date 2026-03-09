# Deltaplan Shift Monitor

A web dashboard that monitors shift schedules from [Deltaplan](https://deltaplan.dk) and alerts when new vacant shifts become available.

## Features

- **Your shifts** — see your upcoming schedule at a glance
- **Colleagues' shifts** — who's working FP 1, FP 2, E 3, and FP KVELD each day
- **Vacant shift alerts** — audio chime + visual alert when new shifts open up
- **Filter chips** — toggle shift types on/off (defaults to FP 1, FP 2, E 3, FP KVELD)
- **Configurable polling** — adjust how often it checks (1–120 minutes)
- **Two deployment options** — run locally, or host on GitHub Pages + Cloudflare Worker

---

## Option A: Run Locally

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

### Requirements

- Python 3.9+ (macOS: `brew install python3` or download from [python.org](https://www.python.org/downloads/))

### CLI Usage

```bash
source .venv/bin/activate
python main.py login          # Test login
python main.py shifts         # Show your shifts
python main.py vacant         # Show available shifts
python main.py shifttypes     # List all shift types
python main.py monitor        # Poll & send desktop notifications
```

---

## Option B: GitHub Pages + Cloudflare Worker

Host the dashboard online so you can access it from your phone with a bookmarked URL.

### 1. Deploy the Cloudflare Worker (API proxy)

The Worker proxies API calls to Deltaplan (needed because Deltaplan doesn't allow cross-origin browser requests).

1. Create a free [Cloudflare account](https://dash.cloudflare.com/sign-up)
2. Install Wrangler:
   ```bash
   npm install -g wrangler
   wrangler login
   ```
3. Deploy the worker:
   ```bash
   cd worker
   wrangler deploy
   ```
4. Note the URL it prints, e.g. `https://deltaplan-proxy.yourname.workers.dev`

### 2. Deploy to GitHub Pages

1. Push this repo to GitHub
2. Go to **Settings → Pages** and set source to "Deploy from branch", branch `master`, folder `/docs`
3. Your dashboard is live at `https://yourusername.github.io/Deltaplan/`

### 3. Create a bookmark

Open the dashboard with credentials in the URL:

```
https://yourusername.github.io/Deltaplan/?w=https://deltaplan-proxy.yourname.workers.dev&u=YOUR_USERNAME&p=YOUR_PASSWORD
```

Bookmark this URL on your phone for one-tap access. Credentials are sent only to your Cloudflare Worker (which forwards them to Deltaplan) — nothing is stored on any server.

**Tip:** You can hardcode the worker URL in `docs/index.html` (set `HARDCODED_WORKER_URL`) to shorten the bookmark URL to just `?u=USERNAME&p=PASSWORD`.
