"""
04_funnel.py
SQL funnel analysis on neobank.duckdb
Outputs: 4 CSV files + 3 chart PNGs
"""

import os
import duckdb
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.ticker import FuncFormatter

# ── Paths ─────────────────────────────────────────────────────────────────────

BASE      = "/Users/suparna_deshmukh/projects/neobank-funnel"
DB_PATH   = f"{BASE}/data/neobank.duckdb"
OUT_CSV   = f"{BASE}/outputs"
OUT_FIG   = f"{BASE}/outputs/figures"

os.makedirs(OUT_CSV, exist_ok=True)
os.makedirs(OUT_FIG, exist_ok=True)

con = duckdb.connect(DB_PATH, read_only=True)

print("=" * 62)
print("  Neobank Funnel Analysis")
print("=" * 62)


# ── Shared style ──────────────────────────────────────────────────────────────

BRAND   = "#5B5FEF"          # indigo — primary bars
ACCENT  = "#F05454"          # red    — drop-off annotations
MUTED   = "#B0B4C8"          # grey   — secondary bars
DEVICE_COLORS = {
    "android": "#4CAF50",
    "ios":     "#2196F3",
    "web":     "#FF9800",
}

plt.rcParams.update({
    "font.family":      "DejaVu Sans",
    "axes.spines.top":  False,
    "axes.spines.right":False,
    "axes.spines.left": False,
    "axes.grid":        True,
    "axes.grid.axis":   "x",
    "grid.color":       "#EBEBEB",
    "grid.linewidth":   0.8,
    "figure.dpi":       150,
})


# ─────────────────────────────────────────────────────────────────────────────
# QUERY 1 — Main funnel
# ─────────────────────────────────────────────────────────────────────────────

print("\n[1/4] Main funnel …")

q1 = """
WITH base AS (
    SELECT COUNT(*) AS total FROM users
)
SELECT
    step_name,
    users,
    ROUND(users * 100.0 / FIRST_VALUE(users) OVER (ORDER BY step_order), 1)
        AS pct_of_top,
    ROUND(users * 100.0 / LAG(users) OVER (ORDER BY step_order), 1)
        AS pct_of_prev
FROM (
    VALUES
        (1, 'Signup completed',   (SELECT SUM(signup_completed)  FROM users)),
        (2, 'Email verified',     (SELECT SUM(email_verified)    FROM users)),
        (3, 'KYC started',        (SELECT SUM(kyc_started)       FROM users)),
        (4, 'KYC completed',      (SELECT SUM(kyc_completed)     FROM users)),
        (5, 'First transaction',  (SELECT SUM(first_transaction) FROM users))
) t(step_order, step_name, users)
ORDER BY step_order
"""

df1 = con.execute(q1).df()
df1["dropoff_pct"] = (100 - df1["pct_of_prev"]).round(1)
df1.loc[0, "dropoff_pct"] = None          # no drop-off for the top step

csv1 = f"{OUT_CSV}/main_funnel.csv"
df1.to_csv(csv1, index=False)
print(f"  Saved → {csv1}")
print(df1.to_string(index=False))


# ─────────────────────────────────────────────────────────────────────────────
# QUERY 2 — KYC sub-funnel
# ─────────────────────────────────────────────────────────────────────────────

print("\n[2/4] KYC sub-funnel …")

q2 = """
WITH kyc_counts AS (
    SELECT
        SUM(CASE WHEN event_type = 'kyc_started'           THEN 1 END) AS kyc_started,
        SUM(CASE WHEN event_type = 'kyc_pan_submitted'     THEN 1 END) AS kyc_pan,
        SUM(CASE WHEN event_type = 'kyc_aadhaar_submitted' THEN 1 END) AS kyc_aadhaar,
        SUM(CASE WHEN event_type = 'kyc_selfie_submitted'  THEN 1 END) AS kyc_selfie,
        SUM(CASE WHEN event_type = 'kyc_completed'         THEN 1 END) AS kyc_completed
    FROM (
        SELECT event_type, user_id
        FROM events
        WHERE event_type IN (
            'kyc_started','kyc_pan_submitted','kyc_aadhaar_submitted',
            'kyc_selfie_submitted','kyc_completed'
        )
        GROUP BY event_type, user_id   -- one row per user per step
    )
)
SELECT step_order, step_name, users,
    ROUND(users * 100.0 / FIRST_VALUE(users) OVER (ORDER BY step_order), 1) AS pct_of_top,
    ROUND(users * 100.0 / LAG(users)         OVER (ORDER BY step_order), 1) AS pct_of_prev
FROM (
    SELECT 1 AS step_order, 'KYC started'           AS step_name, kyc_started   AS users FROM kyc_counts UNION ALL
    SELECT 2,               'PAN submitted',                       kyc_pan               FROM kyc_counts UNION ALL
    SELECT 3,               'Aadhaar submitted',                   kyc_aadhaar           FROM kyc_counts UNION ALL
    SELECT 4,               'Selfie submitted',                    kyc_selfie            FROM kyc_counts UNION ALL
    SELECT 5,               'KYC completed',                       kyc_completed         FROM kyc_counts
) t
ORDER BY step_order
"""

df2 = con.execute(q2).df()
df2["dropoff_pct"] = (100 - df2["pct_of_prev"]).round(1)
df2.loc[0, "dropoff_pct"] = None

csv2 = f"{OUT_CSV}/kyc_subfunnel.csv"
df2.to_csv(csv2, index=False)
print(f"  Saved → {csv2}")
print(df2.to_string(index=False))


# ─────────────────────────────────────────────────────────────────────────────
# QUERY 3 — Drop-off segmentation
# ─────────────────────────────────────────────────────────────────────────────

print("\n[3/4] Drop-off segmentation …")

q3 = """
-- For each KYC sub-step, find users who reached it but NOT the next one.
-- Then describe those drop-off users.

WITH kyc_steps AS (
    SELECT user_id, event_type, device, step_duration_seconds
    FROM events
    WHERE event_type IN (
        'kyc_started','kyc_pan_submitted','kyc_aadhaar_submitted',
        'kyc_selfie_submitted','kyc_completed','kyc_doc_rejected'
    )
),

-- Flag which steps each user completed
user_flags AS (
    SELECT
        user_id,
        MAX(CASE WHEN event_type='kyc_started'           THEN 1 ELSE 0 END) AS did_start,
        MAX(CASE WHEN event_type='kyc_pan_submitted'     THEN 1 ELSE 0 END) AS did_pan,
        MAX(CASE WHEN event_type='kyc_aadhaar_submitted' THEN 1 ELSE 0 END) AS did_aadhaar,
        MAX(CASE WHEN event_type='kyc_selfie_submitted'  THEN 1 ELSE 0 END) AS did_selfie,
        MAX(CASE WHEN event_type='kyc_completed'         THEN 1 ELSE 0 END) AS did_complete,
        MAX(CASE WHEN event_type='kyc_doc_rejected'      THEN 1 ELSE 0 END) AS had_rejection
    FROM kyc_steps
    GROUP BY user_id
),

-- Tag each user with where they dropped off
dropoffs AS (
    SELECT user_id, had_rejection,
        CASE
            WHEN did_start=1  AND did_pan=0       THEN 'After KYC started'
            WHEN did_pan=1    AND did_aadhaar=0   THEN 'After PAN submitted'
            WHEN did_aadhaar=1 AND did_selfie=0   THEN 'After Aadhaar submitted'
            WHEN did_selfie=1 AND did_complete=0  THEN 'After Selfie submitted'
            ELSE NULL
        END AS dropped_at
    FROM user_flags
    WHERE did_complete = 0 AND did_start = 1
),

-- Get the device + duration of the last event each dropper performed
last_event AS (
    SELECT k.user_id, k.device, k.step_duration_seconds,
           k.event_type AS last_event_type
    FROM kyc_steps k
    INNER JOIN (
        SELECT user_id, MAX(
            CASE event_type
                WHEN 'kyc_started'           THEN 1
                WHEN 'kyc_pan_submitted'     THEN 2
                WHEN 'kyc_aadhaar_submitted' THEN 3
                WHEN 'kyc_selfie_submitted'  THEN 4
                ELSE 0
            END
        ) AS max_step
        FROM kyc_steps
        WHERE event_type != 'kyc_doc_rejected'
        GROUP BY user_id
    ) m ON k.user_id = m.user_id
       AND CASE k.event_type
               WHEN 'kyc_started'           THEN 1
               WHEN 'kyc_pan_submitted'     THEN 2
               WHEN 'kyc_aadhaar_submitted' THEN 3
               WHEN 'kyc_selfie_submitted'  THEN 4
               ELSE 0
           END = m.max_step
)

SELECT
    d.dropped_at,
    COUNT(*)                                                          AS dropoff_users,
    ROUND(AVG(le.step_duration_seconds), 1)                          AS avg_duration_sec,
    ROUND(SUM(CASE WHEN le.device='android' THEN 1 ELSE 0 END)*100.0/COUNT(*), 1) AS pct_android,
    ROUND(SUM(CASE WHEN le.device='ios'     THEN 1 ELSE 0 END)*100.0/COUNT(*), 1) AS pct_ios,
    ROUND(SUM(CASE WHEN le.device='web'     THEN 1 ELSE 0 END)*100.0/COUNT(*), 1) AS pct_web,
    ROUND(SUM(d.had_rejection)*100.0/COUNT(*), 1)                    AS pct_had_rejection
FROM dropoffs d
LEFT JOIN last_event le ON d.user_id = le.user_id
WHERE d.dropped_at IS NOT NULL
GROUP BY d.dropped_at
ORDER BY
    CASE d.dropped_at
        WHEN 'After KYC started'       THEN 1
        WHEN 'After PAN submitted'     THEN 2
        WHEN 'After Aadhaar submitted' THEN 3
        WHEN 'After Selfie submitted'  THEN 4
    END
"""

df3 = con.execute(q3).df()
csv3 = f"{OUT_CSV}/dropoff_segments.csv"
df3.to_csv(csv3, index=False)
print(f"  Saved → {csv3}")
print(df3.to_string(index=False))


# ─────────────────────────────────────────────────────────────────────────────
# QUERY 4 — Device comparison
# ─────────────────────────────────────────────────────────────────────────────

print("\n[4/4] Device comparison …")

q4 = """
SELECT
    device,
    COUNT(*)                                                 AS users_who_started_kyc,
    SUM(kyc_completed)                                       AS users_completed_kyc,
    ROUND(SUM(kyc_completed)*100.0/COUNT(*), 1)              AS kyc_completion_rate,
    ROUND(AVG(CASE WHEN e.avg_selfie IS NOT NULL
                   THEN e.avg_selfie END), 1)                AS avg_selfie_sec
FROM users u
LEFT JOIN (
    SELECT user_id, AVG(step_duration_seconds) AS avg_selfie
    FROM events
    WHERE event_type = 'kyc_selfie_submitted'
    GROUP BY user_id
) e ON u.user_id = e.user_id
WHERE u.kyc_started = 1
GROUP BY device
ORDER BY kyc_completion_rate DESC
"""

df4 = con.execute(q4).df()
csv4 = f"{OUT_CSV}/device_comparison.csv"
df4.to_csv(csv4, index=False)
print(f"  Saved → {csv4}")
print(df4.to_string(index=False))

con.close()


# ─────────────────────────────────────────────────────────────────────────────
# CHART 1 — Main funnel (horizontal bar)
# ─────────────────────────────────────────────────────────────────────────────

print("\n[Charts] Generating visualizations …")

fig, ax = plt.subplots(figsize=(11, 5.5))
fig.patch.set_facecolor("white")
ax.set_facecolor("white")

steps  = df1["step_name"].tolist()
counts = df1["users"].tolist()
top    = counts[0]

# Taper: each bar is slightly narrower so it reads as a funnel
bar_heights = [0.55 - i * 0.04 for i in range(len(steps))]
y_pos = range(len(steps) - 1, -1, -1)

for i, (y, step, count, bh) in enumerate(
        zip(y_pos, steps, counts, bar_heights)):
    width = count / top
    bar = ax.barh(y, width, height=bh, color=BRAND,
                  alpha=0.85 + i * 0.02, zorder=3)

    # User count inside bar
    ax.text(width / 2, y, f"{count:,}",
            ha="center", va="center",
            fontsize=10, fontweight="bold", color="white", zorder=4)

    # Step label left of bar
    ax.text(-0.01, y, step, ha="right", va="center",
            fontsize=9.5, color="#333333")

    # Drop-off annotation to the right
    if i > 0:
        dp = df1.loc[df1["step_name"] == step, "dropoff_pct"].values[0]
        if pd.notna(dp):
            ax.text(width + 0.01, y,
                    f"▼ {dp:.0f}% drop",
                    ha="left", va="center",
                    fontsize=8.5, color=ACCENT)

ax.set_xlim(-0.35, 1.18)
ax.set_ylim(-0.6, len(steps) - 0.4)
ax.set_xticks([])
ax.set_yticks([])
ax.spines[:].set_visible(False)
ax.grid(False)
ax.set_title("Main Onboarding Funnel", fontsize=14,
             fontweight="bold", pad=14, color="#1A1A2E")

fig.tight_layout()
p1 = f"{OUT_FIG}/01_main_funnel.png"
fig.savefig(p1, bbox_inches="tight", facecolor="white")
plt.close()
print(f"  Saved → {p1}")


# ─────────────────────────────────────────────────────────────────────────────
# CHART 2 — KYC sub-funnel
# ─────────────────────────────────────────────────────────────────────────────

fig, ax = plt.subplots(figsize=(11, 5.5))
fig.patch.set_facecolor("white")
ax.set_facecolor("white")

steps2  = df2["step_name"].tolist()
counts2 = df2["users"].tolist()
top2    = counts2[0]
bar_heights2 = [0.55 - i * 0.04 for i in range(len(steps2))]
y_pos2 = range(len(steps2) - 1, -1, -1)

KYCC = "#7C3AED"   # purple for KYC

for i, (y, step, count, bh) in enumerate(
        zip(y_pos2, steps2, counts2, bar_heights2)):
    width = count / top2
    ax.barh(y, width, height=bh,
            color=KYCC, alpha=0.75 + i * 0.04, zorder=3)

    ax.text(width / 2, y, f"{count:,}",
            ha="center", va="center",
            fontsize=10, fontweight="bold", color="white", zorder=4)

    ax.text(-0.01, y, step, ha="right", va="center",
            fontsize=9.5, color="#333333")

    if i > 0:
        dp = df2.loc[df2["step_name"] == step, "dropoff_pct"].values[0]
        pp = df2.loc[df2["step_name"] == step, "pct_of_prev"].values[0]
        if pd.notna(dp):
            ax.text(width + 0.01, y,
                    f"▼ {dp:.0f}% drop  ({pp:.0f}% pass)",
                    ha="left", va="center",
                    fontsize=8.5, color=ACCENT)

ax.set_xlim(-0.32, 1.30)
ax.set_ylim(-0.6, len(steps2) - 0.4)
ax.set_xticks([])
ax.set_yticks([])
ax.spines[:].set_visible(False)
ax.grid(False)
ax.set_title("KYC Sub-Funnel", fontsize=14,
             fontweight="bold", pad=14, color="#1A1A2E")

fig.tight_layout()
p2 = f"{OUT_FIG}/02_kyc_subfunnel.png"
fig.savefig(p2, bbox_inches="tight", facecolor="white")
plt.close()
print(f"  Saved → {p2}")


# ─────────────────────────────────────────────────────────────────────────────
# CHART 3 — KYC completion rate by device (grouped bars)
# ─────────────────────────────────────────────────────────────────────────────

fig, axes = plt.subplots(1, 2, figsize=(12, 5))
fig.patch.set_facecolor("white")

devices     = df4["device"].tolist()
comp_rates  = df4["kyc_completion_rate"].tolist()
selfie_secs = df4["avg_selfie_sec"].tolist()
colors      = [DEVICE_COLORS.get(d, MUTED) for d in devices]

# Left: KYC completion rate
ax_l = axes[0]
ax_l.set_facecolor("white")
bars = ax_l.bar(devices, comp_rates, color=colors,
                width=0.5, zorder=3, edgecolor="white", linewidth=1.5)
for bar, val in zip(bars, comp_rates):
    ax_l.text(bar.get_x() + bar.get_width() / 2,
              bar.get_height() + 0.5,
              f"{val:.1f}%",
              ha="center", va="bottom",
              fontsize=11, fontweight="bold", color="#333333")

ax_l.set_ylim(0, max(comp_rates) * 1.22)
ax_l.set_ylabel("KYC Completion Rate (%)", fontsize=10)
ax_l.set_title("KYC Completion Rate by Device",
               fontsize=12, fontweight="bold", pad=10, color="#1A1A2E")
ax_l.set_xticks(range(len(devices)))
ax_l.set_xticklabels([d.capitalize() for d in devices], fontsize=11)
ax_l.yaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v:.0f}%"))

# Right: Average selfie duration
ax_r = axes[1]
ax_r.set_facecolor("white")
bars2 = ax_r.bar(devices, selfie_secs, color=colors,
                 width=0.5, zorder=3, edgecolor="white", linewidth=1.5)
for bar, val in zip(bars2, selfie_secs):
    ax_r.text(bar.get_x() + bar.get_width() / 2,
              bar.get_height() + 0.4,
              f"{val:.1f}s",
              ha="center", va="bottom",
              fontsize=11, fontweight="bold", color="#333333")

ax_r.set_ylim(0, max(selfie_secs) * 1.22)
ax_r.set_ylabel("Avg Selfie Duration (seconds)", fontsize=10)
ax_r.set_title("Avg Selfie Step Duration by Device",
               fontsize=12, fontweight="bold", pad=10, color="#1A1A2E")
ax_r.set_xticks(range(len(devices)))
ax_r.set_xticklabels([d.capitalize() for d in devices], fontsize=11)

legend_patches = [
    mpatches.Patch(color=DEVICE_COLORS["android"], label="Android"),
    mpatches.Patch(color=DEVICE_COLORS["ios"],     label="iOS"),
    mpatches.Patch(color=DEVICE_COLORS["web"],     label="Web"),
]
fig.legend(handles=legend_patches, loc="lower center",
           ncol=3, fontsize=10, frameon=False,
           bbox_to_anchor=(0.5, -0.04))

fig.suptitle("Device Performance in KYC Flow",
             fontsize=14, fontweight="bold", color="#1A1A2E", y=1.02)
fig.tight_layout()
p3 = f"{OUT_FIG}/03_device_comparison.png"
fig.savefig(p3, bbox_inches="tight", facecolor="white")
plt.close()
print(f"  Saved → {p3}")


# ─────────────────────────────────────────────────────────────────────────────
# Observations
# ─────────────────────────────────────────────────────────────────────────────

# Pull the numbers we need for dynamic observations
kyc_start_row    = df2[df2["step_name"] == "KYC started"].iloc[0]
pan_row          = df2[df2["step_name"] == "PAN submitted"].iloc[0]
aadhaar_row      = df2[df2["step_name"] == "Aadhaar submitted"].iloc[0]
selfie_row       = df2[df2["step_name"] == "Selfie submitted"].iloc[0]
complete_row     = df2[df2["step_name"] == "KYC completed"].iloc[0]

biggest_drop_row = df2.dropna(subset=["dropoff_pct"]).sort_values(
    "dropoff_pct", ascending=False).iloc[0]

android_row = df4[df4["device"] == "android"].iloc[0]
ios_row     = df4[df4["device"] == "ios"].iloc[0]

rejection_rows = df3[df3["pct_had_rejection"] > 0]

print()
print("=" * 62)
print("  KEY OBSERVATIONS")
print("=" * 62)
print(f"""
  • Biggest KYC drop-off is at "{biggest_drop_row['step_name']}" —
    {biggest_drop_row['dropoff_pct']:.0f}% of users who reached that step did
    not proceed. This is the single highest-friction point in the
    entire KYC flow and the most valuable place to investigate UX
    improvements (clearer instructions, real-time validation, etc.).

  • Android users take {android_row['avg_selfie_sec']:.0f}s on average to complete the
    selfie step vs {ios_row['avg_selfie_sec']:.0f}s on iOS — a {android_row['avg_selfie_sec']/ios_row['avg_selfie_sec']:.1f}× difference. Despite the
    longer capture time, KYC completion rates across devices are
    broadly similar, suggesting the selfie delay alone isn't causing
    abandonment — but it may erode confidence and contribute to
    drop-off when combined with a prior document rejection.

  • PAN document rejections create a measurable ripple effect:
    {df3[df3['dropped_at']=='After PAN submitted']['pct_had_rejection'].values[0]:.0f}% of users who dropped off after PAN submission had
    already received a kyc_doc_rejected event. Introducing an
    inline PAN validator (format check before server-side review)
    could prevent a meaningful share of these rejections and recover
    users who currently give up after a failed first attempt.
""")

print("=" * 62)
print("  Analysis complete. All files saved to outputs/")
print("=" * 62)