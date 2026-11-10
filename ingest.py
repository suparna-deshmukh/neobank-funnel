"""
ingest.py
Fetches all events from the local Flask API and loads them into DuckDB.

Usage:
    python3 ingest.py          (API must be running on localhost:5000)
"""

import math
import time

import duckdb
import requests

# ── Config ────────────────────────────────────────────────────────────────────

API_BASE   = "http://localhost:5000"
PAGE_SIZE  = 1000
DB_PATH    = "/Users/suparna_deshmukh/projects/neobank-funnel/data/neobank.duckdb"

RETRY_ATTEMPTS = 3
RETRY_WAIT     = 2   # seconds between retries


# ── Helpers ───────────────────────────────────────────────────────────────────

def fetch_with_retry(url: str, params: dict = None) -> dict:
    """
    GET the given URL and return the parsed JSON.
    On failure, waits RETRY_WAIT seconds and retries up to RETRY_ATTEMPTS times.
    Raises RuntimeError if all attempts fail.
    """
    for attempt in range(1, RETRY_ATTEMPTS + 1):
        try:
            response = requests.get(url, params=params, timeout=10)
            response.raise_for_status()          # raises on 4xx / 5xx
            return response.json()
        except requests.RequestException as err:
            if attempt < RETRY_ATTEMPTS:
                print(f"  ⚠ Request failed (attempt {attempt}/{RETRY_ATTEMPTS}): {err}")
                print(f"    Retrying in {RETRY_WAIT}s …")
                time.sleep(RETRY_WAIT)
        else:
            raise RuntimeError(
                f"All {RETRY_ATTEMPTS} attempts failed for {url}. "
                "Is the API server running on localhost:5000?"
            )


# ── Step 1 — Health check ─────────────────────────────────────────────────────

print("=" * 60)
print("  Neobank Funnel — Data Ingest")
print("=" * 60)
print()
print("Step 1 / 4 — Checking API health …")

health      = fetch_with_retry(f"{API_BASE}/health")
total_events = health["total_events"]
total_pages  = math.ceil(total_events / PAGE_SIZE)

print(f"  ✓ API is up. {total_events:,} events across {total_pages:,} pages "
      f"(page size = {PAGE_SIZE:,})")


# ── Step 2 — Fetch all pages ──────────────────────────────────────────────────

print()
print(f"Step 2 / 4 — Fetching {total_pages:,} pages from the API …")

all_events: list[dict] = []

for page in range(1, total_pages + 1):
    data = fetch_with_retry(
        f"{API_BASE}/events",
        params={"page": page, "page_size": PAGE_SIZE},
    )
    all_events.extend(data["events"])

    if page % 10 == 0 or page == total_pages:
        print(f"  Fetched page {page:>{len(str(total_pages))}}/{total_pages} "
              f"— {len(all_events):,} events so far")

print(f"  ✓ All pages fetched. {len(all_events):,} events collected.")


# ── Step 3 — Load into DuckDB ─────────────────────────────────────────────────

print()
print(f"Step 3 / 4 — Loading into DuckDB at:")
print(f"  {DB_PATH}")

con = duckdb.connect(DB_PATH)

# ── Table: events ─────────────────────────────────────────────────────────────
# Drop and recreate so the script is safely re-runnable
con.execute("DROP TABLE IF EXISTS events")
con.execute("""
    CREATE TABLE events (
        event_id              VARCHAR,
        user_id               VARCHAR,
        timestamp             TIMESTAMPTZ,
        event_type            VARCHAR,
        device                VARCHAR,
        session_id            VARCHAR,
        step_duration_seconds INTEGER
    )
""")

# DuckDB can ingest a Python list of dicts directly via a VALUES approach,
# but the fastest method for large lists is to register it as a relation.
import pandas as pd   # DuckDB bundles its own pandas bridge

df_events = pd.DataFrame(all_events)
# Cast timestamp column (stored as ISO string) to proper datetime
df_events["timestamp"] = pd.to_datetime(df_events["timestamp"], utc=True)

con.execute("""
    INSERT INTO events
    SELECT
        event_id,
        user_id,
        timestamp,
        event_type,
        device,
        session_id,
        step_duration_seconds
    FROM df_events
""")

print(f"  ✓ 'events' table created and loaded.")

# ── Table: users ──────────────────────────────────────────────────────────────
con.execute("DROP TABLE IF EXISTS users")
con.execute("""
    CREATE TABLE users AS
    SELECT
        user_id,

        -- first event timestamp for this user
        MIN(timestamp)                                              AS first_seen_at,

        -- device: pick the one seen on the user's very first event
        FIRST(device ORDER BY timestamp)                           AS device,

        -- milestone flags (1 if the user ever produced that event, else 0)
        MAX(CASE WHEN event_type = 'signup_completed'   THEN 1 ELSE 0 END)  AS signup_completed,
        MAX(CASE WHEN event_type = 'email_verified'     THEN 1 ELSE 0 END)  AS email_verified,
        MAX(CASE WHEN event_type = 'kyc_started'        THEN 1 ELSE 0 END)  AS kyc_started,
        MAX(CASE WHEN event_type = 'kyc_completed'      THEN 1 ELSE 0 END)  AS kyc_completed,
        MAX(CASE WHEN event_type = 'first_transaction'  THEN 1 ELSE 0 END)  AS first_transaction

    FROM events
    GROUP BY user_id
""")

print(f"  ✓ 'users' table created.")


# ── Step 4 — Sanity checks ────────────────────────────────────────────────────

print()
print("Step 4 / 4 — Running sanity checks …")
print()

# 4a. Total event count
total_in_db = con.execute("SELECT COUNT(*) FROM events").fetchone()[0]
print(f"  Total events in DB        : {total_in_db:,}")

# 4b. Total unique users
unique_users = con.execute("SELECT COUNT(*) FROM users").fetchone()[0]
print(f"  Unique users in DB        : {unique_users:,}")

# 4c. Most recent event timestamp
latest_ts = con.execute(
    "SELECT MAX(timestamp) FROM events"
).fetchone()[0]
print(f"  Most recent event         : {latest_ts}")

# Bonus — quick funnel summary from users table
print()
print("  ── Funnel summary (from users table) ───────────────────")
funnel = con.execute("""
    SELECT
        SUM(signup_completed)   AS signups,
        SUM(email_verified)     AS emails,
        SUM(kyc_started)        AS kyc_start,
        SUM(kyc_completed)      AS kyc_done,
        SUM(first_transaction)  AS transacted,
        COUNT(*)                AS total_users
    FROM users
""").fetchone()

labels = ["Signup", "Email verified", "KYC started", "KYC completed", "First transaction"]
values = funnel[:5]
total  = funnel[5]

for label, val in zip(labels, values):
    pct = val / total * 100
    print(f"  {label:<20}: {val:>7,}  ({pct:.1f}% of all users)")

con.close()

print()
print("=" * 60)
print("  ✓ Ingest complete. Database is ready.")
print(f"  Location: {DB_PATH}")
print("=" * 60)