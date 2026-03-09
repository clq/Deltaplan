#!/usr/bin/env python3
"""Deltaplan web dashboard — Flask app with SSE for real-time shift updates."""

import json
import os
import threading
import time
from datetime import datetime, timedelta

from flask import Flask, Response, jsonify, render_template, request

from deltaplan import DeltaplanClient, load_config

app = Flask(__name__)

# ── Shared state ────────────────────────────────────────────────────

state_lock = threading.Lock()
state = {
    "own_shifts": [],
    "colleagues_shifts": {},   # date → [shift, …]
    "vacant_shifts": {},       # date → [shift, …]
    "default_types": [],       # configured default filter (from config.json)
    "available_types": [],     # all shift types seen in colleague data
    "last_check": None,
    "poll_interval": 300,
    "error": None,
    "new_vacant_ids": [],
}

sse_subscribers = []
# Threading event to wake the poller immediately
poll_now = threading.Event()


# ── SSE helpers ─────────────────────────────────────────────────────

def push_event(event_type, data):
    msg = f"event: {event_type}\ndata: {json.dumps(data, ensure_ascii=False, default=str)}\n\n"
    dead = []
    for q in sse_subscribers:
        try:
            q.append(msg)
        except Exception:
            dead.append(q)
    for q in dead:
        sse_subscribers.remove(q)


# ── Background poller ──────────────────────────────────────────────

def strip_html(shifts):
    """Remove bulky html field from shift dicts before sending to frontend."""
    if isinstance(shifts, list):
        return [{k: v for k, v in s.items() if k != "html"} for s in shifts]
    if isinstance(shifts, dict):
        return {
            date: [{k: v for k, v in s.items() if k != "html"} for s in slist]
            for date, slist in shifts.items()
        }
    return shifts


def poller_loop():
    config = load_config()
    client = DeltaplanClient(config)
    target_types = config.get("shift_types", [])

    with state_lock:
        state["poll_interval"] = config.get("poll_interval_minutes", 5) * 60
        state["default_types"] = list(target_types)

    prev_vacant_ids = set()

    while True:
        try:
            client.login()

            today = datetime.now().strftime("%Y-%m-%d")
            end = (datetime.now() + timedelta(days=90)).strftime("%Y-%m-%d")
            schedule = client.get_enriched_schedule(today, end, target_types)

            own = strip_html(schedule.get("own_shifts", []))
            # Filter out "anti-shifts" (department_id=1 / department_short="-")
            # which are availability markers, not real assigned shifts
            own = [s for s in own if s.get("department_id") != "1"]
            colleagues = schedule.get("colleagues_shifts", {})
            vacant = strip_html(schedule.get("vacant_shifts", {}))

            # Detect new vacant shifts
            current_ids = set()
            for shifts in (vacant.values() if isinstance(vacant, dict) else [vacant]):
                for s in shifts:
                    current_ids.add(s.get("vagt_id", s.get("id", "")))
            new_ids = list(current_ids - prev_vacant_ids) if prev_vacant_ids else []
            prev_vacant_ids = current_ids

            now = datetime.now().isoformat()
            available_types = schedule.get("available_shift_types", [])

            with state_lock:
                state["own_shifts"] = own
                state["colleagues_shifts"] = colleagues
                state["vacant_shifts"] = vacant
                state["available_types"] = available_types
                state["last_check"] = now
                state["error"] = None
                state["new_vacant_ids"] = new_ids

            push_event("update", {
                "own_shifts": own,
                "colleagues_shifts": colleagues,
                "vacant_shifts": vacant,
                "available_types": available_types,
                "last_check": now,
                "new_vacant_ids": new_ids,
            })

        except Exception as e:
            with state_lock:
                state["error"] = str(e)
                state["last_check"] = datetime.now().isoformat()
            push_event("error", {"error": str(e)})

        with state_lock:
            interval = state["poll_interval"]
        poll_now.wait(timeout=interval)
        poll_now.clear()


# ── Routes ──────────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/state")
def api_state():
    with state_lock:
        return jsonify(state)


@app.route("/api/poll-interval", methods=["POST"])
def set_poll_interval():
    data = request.get_json()
    minutes = max(1, min(120, int(data.get("minutes", 5))))
    with state_lock:
        state["poll_interval"] = minutes * 60
    push_event("config", {"poll_interval_minutes": minutes})
    return jsonify({"ok": True, "poll_interval_minutes": minutes})


@app.route("/api/refresh", methods=["POST"])
def force_refresh():
    poll_now.set()
    return jsonify({"ok": True})


@app.route("/sse")
def sse():
    q = []
    sse_subscribers.append(q)

    def stream():
        with state_lock:
            initial = json.dumps({
                "own_shifts": state["own_shifts"],
                "colleagues_shifts": state["colleagues_shifts"],
                "vacant_shifts": state["vacant_shifts"],
                "available_types": state["available_types"],
                "last_check": state["last_check"],
                "new_vacant_ids": state["new_vacant_ids"],
            }, ensure_ascii=False, default=str)
        yield f"event: update\ndata: {initial}\n\n"

        try:
            while True:
                while q:
                    yield q.pop(0)
                time.sleep(1)
        except GeneratorExit:
            if q in sse_subscribers:
                sse_subscribers.remove(q)

    return Response(stream(), content_type="text/event-stream")


# ── Startup ─────────────────────────────────────────────────────────

def start():
    port = int(os.environ.get("DELTAPLAN_PORT", 5055))
    t = threading.Thread(target=poller_loop, daemon=True)
    t.start()
    app.run(host="0.0.0.0", port=port, debug=False)


if __name__ == "__main__":
    start()
