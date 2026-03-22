# Promo Folder Ingestion Pipeline

Extracts promotional items from Belgian supermarket folder PDFs (stored on Cloudflare R2) and upserts them into the Pinecone `promos` vector index.

Adding a new store = creating a YAML config file. Zero Python code.

## Prerequisites

- `GEMINI_API_KEY`, `PINECONE_API_KEY`, `R2_ACCOUNT_ID`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY` in `.env`

### Python environment setup

```bash
cd milo-backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Activate the venv (`source .venv/bin/activate`) before running any commands below.

## R2 Storage

Promo folder PDFs and metadata are stored in Cloudflare R2:

```
Bucket: milo
promo_folders/{store_id}/{YYYY-W{WW}}/{name}.pdf
promo_folders/{store_id}/{YYYY-W{WW}}/metadata.json
```

### metadata.json

One file per week directory, keyed by PDF filename. Every PDF **must** have an entry or ingestion will abort.

```json
{
  "food.pdf": {
    "promo_folder_url": "https://www.colruyt.be/nl/folders",
    "added_at": "2026-03-20T18:28:00",
    "validity_start": "2026-03-18",
    "validity_end": "2026-03-24"
  },
  "nonfood.pdf": {
    "promo_folder_url": "https://www.lidl.be/aanbiedingen",
    "added_at": "2026-03-20T18:30:00",
    "validity_start": "2026-03-20",
    "validity_end": "2026-03-27"
  }
}
```

### Week directory naming

Use ISO week format: `YYYY-W{WW}`. Get the current week:

```bash
date +%G-W%V    # e.g. 2026-W12
```

## CLI Usage

All commands run from `milo-backend/`.

```bash
# Ingest ALL promo folders for a store (all weeks, all PDFs)
python3 -m promo_folders_pipelines.ingest --store colruyt

# Ingest a specific week (all PDFs in that week)
python3 -m promo_folders_pipelines.ingest --store colruyt --week 2026-W12

# Dry-run (extract only, no Pinecone upsert — writes extracted_promos.json locally)
python3 -m promo_folders_pipelines.ingest --store colruyt --dry-run

# Delete all promos for a store (requires confirmation)
python3 -m promo_folders_pipelines.ingest --clear-index --store colruyt

# Wipe the entire promos index (requires confirmation)
python3 -m promo_folders_pipelines.ingest --nuke-index

# List available stores
python3 -m promo_folders_pipelines.ingest --list-stores
```

| Flag | Description |
|------|-------------|
| `--store` | Store ID (e.g. `colruyt`, `delhaize`, `lidl`) |
| `--week` | Specific week to ingest (e.g. `2026-W12`). Requires `--store`. |
| `--dry-run` | Extract and parse only — no Pinecone upsert |
| `--clear-index` | Delete ALL promos for a store (requires confirmation) |
| `--nuke-index` | Delete ALL records from the entire index (requires confirmation) |
| `--output` | Custom path for extracted JSON output |
| `--list-stores` | Print available stores and exit |

## How It Works

1. **Download** — PDFs are fetched from R2
2. **Split** — PyMuPDF splits into 2-page batches (oversized batches split further)
3. **Extract** — Each batch sent to Gemini with structured output (Pydantic schema)
4. **Parse** — Output validated into `PromoItem` objects, categories checked against `app/core/categories.py`
5. **Dedup** — Items deduplicated by `normalized_name` (handles bilingual folders)
6. **Upsert** — Auto-deletes existing promos for same store+validity, then upserts new records

## Adding a New Store

Create a YAML file in `promo_folders_pipelines/stores/` (see existing configs for examples). The `store_id` must match a canonical name in `app/core/stores.py`.

## File Structure

```
promo_folders_pipelines/
├── ingest.py              # CLI entry point
├── pipeline.py            # Pipeline engine (extract, parse, upsert)
├── r2_storage.py          # Cloudflare R2 client
├── models.py              # PromoItem dataclass
├── prompt_builder.py      # Builds Gemini prompt from YAML config
└── stores/                # One YAML config per store
    ├── __init__.py
    ├── colruyt.yaml
    ├── delhaize.yaml
    └── ... (13 stores)
```
