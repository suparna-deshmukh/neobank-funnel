"""
generate_events.py
Generates synthetic onboarding funnel data for 30,000 neobank users.
Output: data/raw_events.json
"""

import json
import random
import uuid
from datetime import datetime, timedelta, timezone
import os

# ── Reproducibility ───────────────────────────────────────────────────────────
random.seed(42)

# ── Config ────────────────────────────────────────────────────────────────────
TOTAL_USERS          = 30_000
OUTPUT_PATH          = os.path.join(os.path.dirname(__file__), "data", "raw_events.json")

# Funnel completion rates (each relative to the previous step)
RATE_SIGNUP          = 0.95
RATE_EMAIL_VERIFIED  = 0.85
RATE_KYC_STARTED     = 0.70
RATE_KYC_COMPLETED   = 0.50   # of KYC-started users
RATE_FIRST_TXN       = 0.85

# KYC sub-step completion rates (each relative to previous KYC sub-step)
KYC_RATE_PAN         = 0.95
KYC_RATE_AADHAAR     = 0.75
KYC_RATE_SELFIE      = 0.80
KYC_RATE_COMPLETED   = 0.90

# PAN rejection
PAN_REJECTION_RATE   = 0.08   # 8% of PAN submitters get rejected first
PAN_RETRY_RATE       = 0.70   # 70% of rejected PAN users retry and succeed

# Device distribution
DEVICES              = ["android", "ios", "web"]
DEVICE_WEIGHTS       = [0.50,     0.30,  0.20]

# Step duration ranges (seconds) — (mean, std)
DURATION = {
    "signup_completed":       (120,  40),
    "email_verified":         (180,  60),
    "kyc_started":            (20,   5),
    "kyc_pan_submitted":      (90,   30),
    "kyc_pan_rejected":       (30,   10),
    "kyc_aadhaar_submitted":  (100,  35),
    "kyc_selfie_submitted":   None,        # handled separately per device
    "kyc_completed":          (60,   20),
    "first_transaction":      (150,  50),
    "kyc_doc_rejected":       (30,   10),
}
SELFIE_DURATION = {
    "ios":     (30,  8),
    "android": (65, 15),
    "web":     (45, 12),
}

# Time window: last 6 months from script run date
REFERENCE_DATE = datetime(2025, 5, 1, tzinfo=timezone.utc)  # fixed for reproducibility
WINDOW_START   = REFERENCE_DATE - timedelta(days=182)

# Each user's first event is scattered across the 6-month window
# Subsequent events within a user session are spaced 1–14 days apart
MAX_INTER_EVENT_DAYS = 14


# ── Helpers ───────────────────────────────────────────────────────────────────

def new_uuid() -> str:
    return str(uuid.UUID(int=random.getrandbits(128)))

def sample_duration(event_type: str, device: str) -> int:
    """Return a realistic step_duration_seconds for the given event."""
    if event_type == "kyc_selfie_submitted":
        mean, std = SELFIE_DURATION[device]
    else:
        params = DURATION.get(event_type, (60, 20))
        mean, std = params
    val = int(random.gauss(mean, std))
    return max(5, val)   # floor at 5 seconds

def rand_timestamp(base: datetime, min_offset_hours: float = 0.5) -> datetime:
    """Return a timestamp between min_offset_hours and MAX_INTER_EVENT_DAYS after base."""
    offset_seconds = random.uniform(
        min_offset_hours * 3600,
        MAX_INTER_EVENT_DAYS * 86400
    )
    return base + timedelta(seconds=offset_seconds)

def make_event(user_id: str, event_type: str, device: str,
               session_id: str, ts: datetime) -> dict:
    return {
        "event_id":              new_uuid(),
        "user_id":               user_id,
        "timestamp":             ts.isoformat(),
        "event_type":            event_type,
        "device":                device,
        "session_id":            session_id,
        "step_duration_seconds": sample_duration(event_type, device),
    }

def roll(rate: float) -> bool:
    return random.random() < rate


# ── Event generation ──────────────────────────────────────────────────────────

def generate_user_events(user_idx: int) -> list[dict]:
    """Generate all events for a single user. Returns a list of event dicts."""
    events       = []
    user_id      = f"usr_{user_idx:06d}"
    device       = random.choices(DEVICES, weights=DEVICE_WEIGHTS, k=1)[0]

    # Each user starts at a random point in the 6-month window
    first_ts = WINDOW_START + timedelta(
        seconds=random.uniform(0, 182 * 86400)
    )
    ts         = first_ts
    session_id = new_uuid()   # one session per major step (refresh for KYC)

    # ── 1. Signup ─────────────────────────────────────────────────────────────
    if not roll(RATE_SIGNUP):
        return events   # user never signed up

    events.append(make_event(user_id, "signup_completed", device, session_id, ts))
    ts = rand_timestamp(ts)

    # ── 2. Email verified ─────────────────────────────────────────────────────
    if not roll(RATE_EMAIL_VERIFIED):
        return events

    events.append(make_event(user_id, "email_verified", device, session_id, ts))
    ts = rand_timestamp(ts)

    # ── 3. KYC started ────────────────────────────────────────────────────────
    if not roll(RATE_KYC_STARTED):
        return events

    session_id = new_uuid()   # new session for KYC flow
    events.append(make_event(user_id, "kyc_started", device, session_id, ts))
    ts = rand_timestamp(ts, min_offset_hours=0.1)

    # ── 3a. PAN submitted (with optional rejection + retry) ───────────────────
    if not roll(KYC_RATE_PAN):
        return events   # dropped out before PAN

    # Check if this user gets a PAN rejection first
    if roll(PAN_REJECTION_RATE):
        # Generate rejection event
        events.append(make_event(user_id, "kyc_doc_rejected", device, session_id, ts))
        ts = rand_timestamp(ts, min_offset_hours=0.1)

        if not roll(PAN_RETRY_RATE):
            return events   # gave up after rejection

        # Retry succeeds
        events.append(make_event(user_id, "kyc_pan_submitted", device, session_id, ts))
    else:
        events.append(make_event(user_id, "kyc_pan_submitted", device, session_id, ts))

    ts = rand_timestamp(ts, min_offset_hours=0.1)

    # ── 3b. Aadhaar submitted ─────────────────────────────────────────────────
    if not roll(KYC_RATE_AADHAAR):
        return events

    events.append(make_event(user_id, "kyc_aadhaar_submitted", device, session_id, ts))
    ts = rand_timestamp(ts, min_offset_hours=0.1)

    # ── 3c. Selfie submitted ──────────────────────────────────────────────────
    if not roll(KYC_RATE_SELFIE):
        return events

    events.append(make_event(user_id, "kyc_selfie_submitted", device, session_id, ts))
    ts = rand_timestamp(ts, min_offset_hours=0.1)

    # ── 3d. KYC completed (overall rate gate: 50% of kyc_started) ─────────────
    # We've already applied individual sub-step rates above.
    # The final kyc_completed rate is applied here to ensure the ~50% target
    # is met for users who made it through all sub-steps.
    if not roll(KYC_RATE_COMPLETED):
        return events

    # ── Gate: enforce the 50%-of-kyc_started ceiling across the whole funnel.
    # Because sub-steps already filter ~0.95*0.75*0.80*0.90 ≈ 51%, the
    # KYC_RATE_COMPLETED roll above takes us to ~46%, which is within the
    # 40–50% target. No additional gate needed.

    events.append(make_event(user_id, "kyc_completed", device, session_id, ts))
    ts = rand_timestamp(ts)

    # ── 4. First transaction ──────────────────────────────────────────────────
    if not roll(RATE_FIRST_TXN):
        return events

    session_id = new_uuid()
    events.append(make_event(user_id, "first_transaction", device, session_id, ts))

    return events


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    print("=" * 60)
    print("  Neobank Onboarding Event Generator")
    print("=" * 60)
    print(f"  Generating events for {TOTAL_USERS:,} users …")

    all_events = []
    for i in range(1, TOTAL_USERS + 1):
        all_events.extend(generate_user_events(i))
        if i % 5000 == 0:
            print(f"  … processed {i:,} / {TOTAL_USERS:,} users")

    # ── Save ──────────────────────────────────────────────────────────────────
    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    with open(OUTPUT_PATH, "w") as f:
        json.dump(all_events, f, indent=2)

    # ── Stats ─────────────────────────────────────────────────────────────────
    from collections import defaultdict

    # Per-user: track which steps each user reached
    user_steps: dict[str, set] = defaultdict(set)
    for e in all_events:
        user_steps[e["user_id"]].add(e["event_type"])

    total_users        = TOTAL_USERS
    signed_up          = sum(1 for s in user_steps.values() if "signup_completed"       in s)
    email_verified     = sum(1 for s in user_steps.values() if "email_verified"         in s)
    kyc_started        = sum(1 for s in user_steps.values() if "kyc_started"            in s)
    kyc_completed      = sum(1 for s in user_steps.values() if "kyc_completed"          in s)
    first_txn          = sum(1 for s in user_steps.values() if "first_transaction"      in s)

    kyc_dropoff_pct    = (1 - kyc_completed / kyc_started) * 100 if kyc_started else 0

    # Selfie duration stats by device
    selfie_events      = [e for e in all_events if e["event_type"] == "kyc_selfie_submitted"]
    selfie_by_device: dict[str, list] = defaultdict(list)
    for e in selfie_events:
        selfie_by_device[e["device"]].append(e["step_duration_seconds"])
    selfie_avg = {
        d: (sum(v) / len(v) if v else 0)
        for d, v in selfie_by_device.items()
    }

    # PAN rejection count
    pan_rejections     = sum(1 for e in all_events if e["event_type"] == "kyc_doc_rejected")

    print()
    print("=" * 60)
    print("  RESULTS")
    print("=" * 60)
    print(f"  Total events generated       : {len(all_events):>10,}")
    print(f"  Output file                  : {OUTPUT_PATH}")
    print()
    print("  ── Funnel (% of all 30,000 users) ──────────────────────")
    print(f"  Signup completed             : {signed_up:>7,}  ({signed_up/total_users*100:5.1f}%)")
    print(f"  Email verified               : {email_verified:>7,}  ({email_verified/total_users*100:5.1f}%)")
    print(f"  KYC started                  : {kyc_started:>7,}  ({kyc_started/total_users*100:5.1f}%)")
    print(f"  KYC completed                : {kyc_completed:>7,}  ({kyc_completed/total_users*100:5.1f}%)")
    print(f"  First transaction            : {first_txn:>7,}  ({first_txn/total_users*100:5.1f}%)")
    print()
    print("  ── KYC drop-off ─────────────────────────────────────────")
    print(f"  Users who started KYC        : {kyc_started:,}")
    print(f"  Users who completed KYC      : {kyc_completed:,}")
    print(f"  Drop-off (started → complete): {kyc_dropoff_pct:.1f}%  (target: ~40–50%)")
    print()
    print("  ── Selfie avg duration (seconds) ────────────────────────")
    for device in ["ios", "android", "web"]:
        avg = selfie_avg.get(device, 0)
        print(f"  {device:<8}                      : {avg:>6.1f}s")
    print()
    print("  ── PAN rejection events ─────────────────────────────────")
    print(f"  kyc_doc_rejected events      : {pan_rejections:,}")
    print("=" * 60)


if __name__ == "__main__":
    main()