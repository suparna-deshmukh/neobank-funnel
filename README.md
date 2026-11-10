# Neobank Funnel — Onboarding Funnel Analytics + A/B Test Design

Full-funnel analytics for a neobank onboarding flow: **30,000 synthetic users**, their events served through a **Flask REST API**, ingested into **DuckDB**, analysed with SQL (main funnel, KYC subfunnel, device comparison, drop-off segments), and closed out with **two simulated A/B experiments** with two-proportion z-tests.

**Author:** Suparna Deshmukh
**Stack:** Python · Flask · DuckDB (SQL) · NumPy / SciPy · matplotlib
**Full report:** [neobank_funnel_report-2.pdf](neobank_funnel_report-2.pdf) · [A/B hypotheses doc](ab_hypotheses.md)

## The question

~40 % of users who start KYC never finish it. This project pinpoints *where* they drop — down to individual KYC sub-steps and device — then designs and statistically validates two experiments to fix the two worst leak points.

The event data is **synthetic** (seeded generator with realistic step-by-step completion rates), so the whole pipeline is reproducible end to end.

## Pipeline

| # | Script | What it does |
|---|--------|--------------|
| 0 | `generate_events.py` | Simulates 30,000 users through the funnel (signup → email verify → KYC → first transaction) with per-step completion rates, including KYC sub-steps (PAN → Aadhaar → selfie) and device (Android/iOS) behaviour. Writes `data/raw_events.json`. |
| 1 | `api/server.py` | A small Flask REST API serving the events with pagination and a simulated 50 ms latency — a realistic "fetch from prod" layer. |
| 2 | `ingest.py` | Pulls every page from the API with retries and loads everything into `data/neobank.duckdb`. |
| 3 | `04_funnel.py` | SQL on DuckDB: main funnel, KYC subfunnel, Android vs iOS comparison, drop-off segments. Writes 4 CSVs + 3 charts to `outputs/`. |
| 4 | `05_ab_test.py` | Writes the two experiment designs to Markdown, simulates both experiments on the population, runs two-proportion z-tests with 95 % CIs, and draws a forest plot. |

## Results (from committed `outputs/`)

**Main funnel** (`outputs/main_funnel.csv`) — 28,477 signups:

| Step | Users | % of signups | Drop-off |
|------|------:|-------------:|---------:|
| Signup completed | 28,477 | 100 % | — |
| Email verified | 24,233 | 85.1 % | 14.9 % |
| KYC started | 16,817 | 59.1 % | 30.6 % |
| KYC completed | 8,434 | 29.6 % | 49.8 % |
| First transaction | 7,153 | 25.1 % | 15.2 % |

**KYC subfunnel** (`outputs/kyc_subfunnel.csv`): PAN submitted 92.8 % → Aadhaar 75.8 % → selfie 79.6 % → completed 89.5 %. The Aadhaar step is the single biggest sub-funnel leak.

**A/B results** (`outputs/ab_results.csv`), both experiments simulated and statistically significant:

| Experiment | Population | Control | Treatment | Lift | z | Significant |
|------------|-----------|--------:|----------:|-----:|---:|:-----------:|
| 1 — Real-time field validation | All KYC starters (n≈16.8K) | 50.43 % | 58.91 % | **+8.47 pp** | 11.04 | ✅ |
| 2 — Android selfie progress bar | Android KYC starters (n≈8.5K) | 49.96 % | 60.59 % | **+10.63 pp** | 9.84 | ✅ |

Hypotheses, primary/secondary metrics and expected effects are documented in `ab_hypotheses.md` (also regenerated to `outputs/ab_hypotheses.md`).

## Data

| File | What it is |
|------|------------|
| `data/raw_events.json` | 30K users' simulated funnel events (regenerable via `generate_events.py`, seed 42) |
| `data/neobank.duckdb` | DuckDB database with all events loaded (output of `ingest.py`) |

## How to run

```bash
# Dependencies (Python 3.9+)
pip install flask duckdb requests pandas numpy scipy matplotlib

python generate_events.py      # regenerate data/raw_events.json (seeded)
python api/server.py           # terminal 1: Flask API on :5000
python ingest.py               # terminal 2: API → DuckDB
python 04_funnel.py
python 05_ab_test.py
```

> **Note:** `04_funnel.py` / `05_ab_test.py` carry absolute paths in a `BASE` variable at the top — point it at your copy of the folder before running.

## Repository layout

```
neobank-funnel/
├── generate_events.py        # seeded synthetic event generator
├── api/server.py             # Flask REST API over the events
├── ingest.py                 # API → DuckDB with retries
├── 04_funnel.py              # SQL funnel / subfunnel / device analysis
├── 05_ab_test.py             # A/B design + simulation + z-tests + forest plot
├── ab_hypotheses.md          # the two experiment designs
├── data/                     # raw_events.json + neobank.duckdb
├── outputs/                  # CSVs, figures, regenerated hypotheses
└── neobank_funnel_report-2.pdf
```
