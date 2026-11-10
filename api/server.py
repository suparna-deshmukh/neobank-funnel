"""
server.py
REST API for the neobank onboarding funnel event data.
Usage: python3 server.py
"""

import json
import math
import os
import time
from collections import defaultdict

from flask import Flask, jsonify, request

# ── Config ────────────────────────────────────────────────────────────────────

# Path to the raw events file — one level up from this script, inside data/
BASE_DIR        = os.path.dirname(os.path.abspath(__file__))
DATA_FILE       = os.path.join(BASE_DIR, "..", "data", "raw_events.json")
SIMULATED_DELAY = 0.05   # 50 ms

# ── Load data once at startup ─────────────────────────────────────────────────

print("Loading events from disk …")

with open(DATA_FILE, "r") as f:
    ALL_EVENTS: list[dict] = json.load(f)

# Pre-build a user → events index so /events/user/<id> is O(1)
USER_INDEX: dict[str, list[dict]] = defaultdict(list)
for event in ALL_EVENTS:
    USER_INDEX[event["user_id"]].append(event)

TOTAL_EVENTS = len(ALL_EVENTS)

print(f"API server ready. {TOTAL_EVENTS:,} events loaded. Running on http://localhost:5000")

# ── App ───────────────────────────────────────────────────────────────────────

app = Flask(__name__)


# ── Middleware: simulated latency ─────────────────────────────────────────────

@app.before_request
def add_latency():
    """Sleep 50 ms before every request to simulate network latency."""
    time.sleep(SIMULATED_DELAY)


# ── Endpoints ─────────────────────────────────────────────────────────────────

@app.route("/health", methods=["GET"])
def health():
    """
    GET /health
    Returns server status and total event count.
    """
    return jsonify({
        "status":        "ok",
        "total_events":  TOTAL_EVENTS,
    })


@app.route("/events", methods=["GET"])
def get_events():
    """
    GET /events?page=1&page_size=1000
    Returns a paginated slice of all events.

    Query params:
        page      (int, default 1)     — 1-indexed page number
        page_size (int, default 1000)  — events per page
    """
    # ── Parse & validate query params ─────────────────────────────────────────
    try:
        page      = int(request.args.get("page",      1))
        page_size = int(request.args.get("page_size", 1000))
    except ValueError:
        return jsonify({"error": "page and page_size must be integers"}), 400

    if page < 1 or page_size < 1:
        return jsonify({"error": "page and page_size must be positive integers"}), 400

    total_pages = math.ceil(TOTAL_EVENTS / page_size)

    if page > total_pages:
        return jsonify({"error": "page not found"}), 404

    # ── Slice the event list ───────────────────────────────────────────────────
    start  = (page - 1) * page_size
    end    = start + page_size
    chunk  = ALL_EVENTS[start:end]

    return jsonify({
        "page":          page,
        "page_size":     page_size,
        "total_pages":   total_pages,
        "total_events":  TOTAL_EVENTS,
        "events":        chunk,
    })


@app.route("/events/user/<user_id>", methods=["GET"])
def get_user_events(user_id: str):
    """
    GET /events/user/<user_id>
    Returns all events for the given user_id, in the order they were stored.
    """
    events = USER_INDEX.get(user_id)

    if events is None:
        return jsonify({"error": f"user '{user_id}' not found"}), 404

    return jsonify({
        "user_id":      user_id,
        "total_events": len(events),
        "events":       events,
    })


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    # debug=False keeps output clean; use_reloader=False avoids loading the
    # JSON file twice (Flask's reloader spawns a child process).
    app.run(host="0.0.0.0", port=5000, debug=False, use_reloader=False)