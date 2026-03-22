# Promo Candidate Pipeline

Offline scripts for building the weekly B2C promo candidate pools.

These scripts are **not** part of the live `/api/v2/promos` request path.
The API assembles reports at serve time from pre-computed candidates — no Pinecone or Gemini calls at request time.

## Architecture

```
Weekly Batch (offline):
  1. Rebuild enriched profiles (from latest receipts)
  2. Generate promo candidates (Pinecone search → Gemini annotations → DB)

Serve Time (GET /api/v2/promos):
  Fetch candidates → Filter by user's current preferred_stores → Deterministic assembly → Response
```

When a user changes their preferred stores, the next `GET /api/v2/promos` request (e.g. pull-to-refresh) returns a correctly filtered report — no regeneration needed.

## What Lives Here

- `generate_weekly_promo_candidates.py` — Generates and stores weekly promo candidate pools for all users with enriched profiles.

The enriched profile rebuild script lives at `scripts/rebuild_profiles.py` (outside this folder).

## Weekly Runbook

Run in this order:

1. **Ingest new promo folders into Pinecone** (see `promo_folders_pipelines/README.md`)
2. **Rebuild enriched profiles**
3. **Generate weekly promo candidates**

## Commands

### 1. Rebuild Enriched Profiles

From the backend repo root:

```bash
python -m scripts.rebuild_profiles
```

This is idempotent — it rebuilds profiles from the latest 120 days of transaction data. Safe to re-run at any time.

### 2. Generate Weekly Promo Candidates

Generate for the current Brussels week (all users):

```bash
python -m scripts.promo_reports.generate_weekly_promo_candidates
```

Generate for a specific ISO week:

```bash
python -m scripts.promo_reports.generate_weekly_promo_candidates --week 2026-W12
```

Replace candidates that already exist for that week:

```bash
python -m scripts.promo_reports.generate_weekly_promo_candidates --week 2026-W12 --replace-existing
```

## What The API Returns

- `report_status=ready` — The user has candidates for the current week.
- `report_status=no_enriched_profile` — The user needs more receipt history before candidates can be built.
- `report_status=no_report_available` — The user has an enriched profile, but this week's candidates were not generated yet.

The API does not generate missing candidates on demand.

## When To Use `--replace-existing`

Use it only if one of these changed after the first run:

- the weekly promo folder ingestion
- enriched profile data
- promo display rules
- the Gemini annotation prompt or candidate building logic

Do not use it for routine re-runs if the stored week is already correct.

## Suggested Railway Cron

Two separate jobs:

- **Profile rebuild** (daily, 3 AM UTC):
  `python -m scripts.rebuild_profiles`
- **Candidate generation** (weekly, after profile rebuild):
  `python -m scripts.promo_reports.generate_weekly_promo_candidates`

## Troubleshooting

### Candidates Missing For Users

Check:

- whether the user has an enriched profile row in `user_enriched_profiles`
- whether a row exists in `promo_weekly_candidates` for the expected ISO week
- whether the week used was the expected Brussels ISO week

### Candidates Generated But Empty

Check:

- whether the user had `promo_interest_items` in their enriched profile
- whether active promos existed in Pinecone for this week
- whether promos were rejected by display-eligibility rules

### Store Preferences Not Reflected

The serve-time assembly (`app/services/promo_report_service.py`) filters candidates by the user's **current** `preferred_stores` on every request. If a user changed stores but still sees old results:

- verify `preferred_stores` was updated in the `user_profiles` table
- verify the user pulled to refresh (the app does not auto-refresh after store changes)
