# Promo Candidate Pipeline

Offline scripts for building B2C promo candidate pools.

These scripts are **not** part of the live `/api/v2/promos` request path.
The API assembles reports at serve time from pre-computed candidates — no database queries at request time.

## Architecture

```
Batch (offline):
  1. Ingest promo folders into promo_items table (see promo_folders_pipelines/)
  2. Rebuild enriched profiles with category_profiles (from latest receipts)
  3. Generate promo candidates (promo-first reverse matching → promo_candidates table)

Serve Time (GET /api/v2/promos):
  Fetch candidates → Filter by user's current preferred_stores → Deterministic assembly → Response
```

The recommendation engine uses **promo-first reverse matching**: each promo item in `promo_items` is scored against users' `category_profiles` (purchase frequency, brand loyalty, restock urgency, discount depth). Results are bucketed into 4 UX sections per store:

1. **Your Everyday Staples** (5 items) — loyal + high frequency
2. **Stock Up & Save** (4 items) — deep discounts in brand-agnostic categories
3. **Ending Soon** (3 items) — expiring within 2 days
4. **Discover for You** (3 items) — complementary items via category affinities

Each user has **one** candidates row that gets overwritten on each generation run.

When a user changes their preferred stores, the next `GET /api/v2/promos` request (e.g. pull-to-refresh) returns a correctly filtered report — no regeneration needed.

## What Lives Here

- `generate_promo_candidates.py` — Generates and stores promo candidate pools for all users with enriched profiles.
- `promo_candidate_generation.py` — Core matching engine (scoring, bucketing).
- `promo_candidate_generator.py` — Orchestrator (fetches profiles, calls engine, stores results).

The enriched profile rebuild script lives at `scripts/rebuild_profiles.py` (outside this folder).

## Runbook

Run in this order:

1. **Ingest new promo folders into PostgreSQL** (see `promo_folders_pipelines/README.md`)
2. **Rebuild enriched profiles**
3. **Generate promo candidates**

## Commands

### 1. Rebuild Enriched Profiles

```bash
make rebuild-profiles ENV=production
```

This is idempotent — it rebuilds profiles from the latest 120 days of transaction data. Safe to re-run at any time.

### 2. Generate Promo Candidates

```bash
make generate-promos ENV=production
```

This always overwrites the existing candidates for each user. Safe to re-run at any time.

## What The API Returns

- `report_status=ready` — The user has candidates.
- `report_status=no_enriched_profile` — The user needs more receipt history before candidates can be built.
- `report_status=no_report_available` — The user has an enriched profile, but candidates were not generated yet.

The API does not generate missing candidates on demand.

## Suggested Railway Cron

Two separate jobs:

- **Profile rebuild** (daily, 3 AM UTC):
  `python -m scripts.rebuild_profiles`
- **Candidate generation** (after profile rebuild):
  `python -m scripts.promo_reports.generate_promo_candidates`

## Troubleshooting

### Candidates Missing For Users

Check:

- whether the user has an enriched profile row in `user_enriched_profiles`
- whether a row exists in `promo_candidates` for that user

### Candidates Generated But Empty

Check:

- whether the user has `category_profiles` in their enriched profile
- whether active promos exist in the `promo_items` table for the current date
- whether promos matched any of the user's purchased categories

### Store Preferences Not Reflected

The serve-time assembly (`app/services/promo_report_service.py`) filters candidates by the user's **current** `preferred_stores` on every request. If a user changed stores but still sees old results:

- verify `preferred_stores` was updated in the `user_profiles` table
- verify the user pulled to refresh (the app does not auto-refresh after store changes)
