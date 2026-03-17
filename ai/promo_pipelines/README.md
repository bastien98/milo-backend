# Promo Folder Ingestion Pipeline

Generic pipeline for extracting promotional items from Belgian supermarket folder PDFs and upserting them into the Pinecone `promos` vector index.

Adding a new store = creating a YAML config file. Zero Python code.

## Prerequisites

- `GEMINI_API_KEY` and `PINECONE_API_KEY` in your `.env` file
- Python dependencies: `pip install -r requirements.txt` (includes PyYAML, PyMuPDF, google-genai, pinecone)

## Quick Start

All commands run from the `milo-backend/` directory.

```bash
# List available stores
.venv/bin/python -m ai.promo_pipelines.ingest --list-stores

# Dry run (extract + parse, no Pinecone upsert) — saves JSON next to PDF
.venv/bin/python -m ai.promo_pipelines.ingest --store colruyt --folder-path ./path/to/folder.pdf --dry-run

# Full ingestion (extract + parse + upsert to Pinecone)
.venv/bin/python -m ai.promo_pipelines.ingest --store colruyt --folder-path ./path/to/folder.pdf

# With source URL metadata
.venv/bin/python -m ai.promo_pipelines.ingest --store delhaize --folder-path ./folder.pdf --url "https://example.com/folder"

# Clear all existing promos for a store before ingesting (requires confirmation)
.venv/bin/python -m ai.promo_pipelines.ingest --store aldi --folder-path ./folder.pdf --clear-index

# Clear all promos for a store WITHOUT ingesting (standalone cleanup)
.venv/bin/python -m ai.promo_pipelines.ingest --clear-index --store colruyt

# Wipe the ENTIRE promos index clean — all stores, all data (requires confirmation)
.venv/bin/python -m ai.promo_pipelines.ingest --nuke-index

# Use --latest to auto-find the most recent folder for a store
.venv/bin/python -m ai.promo_pipelines.ingest --store colruyt --latest --dry-run

# Ingest ALL PDFs in the latest week directory (for stores with multiple folders)
.venv/bin/python -m ai.promo_pipelines.ingest --store lidl --latest --all --dry-run

# Custom output path for extracted JSON
.venv/bin/python -m ai.promo_pipelines.ingest --store lidl --folder-path ./folder.pdf --dry-run --output ./results/lidl.json
```

## CLI Options

| Flag | Description |
|------|-------------|
| `--store` | Store ID (canonical name, e.g. `colruyt`, `delhaize`, `albert_heijn`) |
| `--folder-path` | Path to the promo folder PDF |
| `--url` | Source URL of the promo folder (stored as Pinecone metadata) |
| `--dry-run` | Extract and parse only — no Pinecone upsert |
| `--clear-index` | Delete ALL existing promos for this store (requires confirmation) |
| `--nuke-index` | Delete ALL records from the entire index (requires confirmation) |
| `--latest` | Auto-find the most recent `folder.pdf` in `promo_folders/{store}/` (replaces `--folder-path`) |
| `--all` | With `--latest`: ingest ALL `*.pdf` files in the latest week directory (not just `folder.pdf`) |
| `--output` | Custom path for the extracted JSON output |
| `--list-stores` | Print available store configs and exit |

### Destructive Operations

Both `--clear-index` and `--nuke-index` require you to type `yes` to confirm before any deletion happens.

- **`--clear-index --store X`** (without `--folder-path`): standalone cleanup — deletes all promos for that store and exits
- **`--clear-index --store X --folder-path ...`**: clears the store's promos first, then runs the full ingestion pipeline
- **`--nuke-index`**: wipes the entire Pinecone promos index (all stores, all validity periods) and exits

## Supported Stores

| Store | Config File | Language | Notes |
|-------|------------|----------|-------|
| Colruyt | `colruyt.yaml` | NL/FR | Bilingual, dedup across languages |
| OKay | `okay.yaml` | NL/FR | Colruyt Group shared brands |
| Spar | `spar.yaml` | NL/FR | Colruyt Group operated |
| Delhaize | `delhaize.yaml` | NL/FR | SuperPlus loyalty promos |
| Proxy Delhaize | `proxy_delhaize.yaml` | NL/FR | Same mechanisms as Delhaize |
| Carrefour Hyper | `carrefour_hyper.yaml` | NL/FR | Bonus Card / Prix Choc |
| Carrefour Market | `carrefour_market.yaml` | NL/FR | Market-scope promos |
| Aldi | `aldi.yaml` | NL/FR | Weekly + themed specials |
| Lidl | `lidl.yaml` | NL/FR | Stunt deals, Lidl Plus |
| Albert Heijn | `albert_heijn.yaml` | NL | Bonus week, mandatory prices |
| Intermarché | `intermarche.yaml` | FR | French-primary folders |
| Jumbo | `jumbo.yaml` | NL | Extra's loyalty deals |
| Makro | `makro.yaml` | NL/FR | Bulk/professional pricing |

## Promo Folder Storage

Weekly promo folder PDFs are stored under `ai/promo_pipelines/promo_folders/`, organized by store and week. PDFs are **git-ignored** (too large to track), but the directory structure and `metadata.json` files are tracked.

### Directory Structure

```
ai/promo_pipelines/promo_folders/
├── .gitignore              # Ignores *.pdf
├── colruyt/
│   ├── 2026-W11/
│   │   ├── folder.pdf      # Main promo folder PDF (git-ignored)
│   │   └── metadata.json   # Source URL + validity dates (tracked in git)
│   ├── 2026-W12/
│   │   ├── folder.pdf
│   │   └── metadata.json
│   └── ...
├── lidl/
│   └── 2026-W12/
│       ├── folder.pdf      # Main food folder
│       ├── nonfood.pdf     # Additional non-food folder
│       └── metadata.json
├── delhaize/
├── aldi/
├── albert_heijn/
├── carrefour_hyper/
├── carrefour_market/
├── intermarche/
├── jumbo/
├── makro/
├── okay/
├── proxy_delhaize/
└── spar/
```

### Naming Convention

Each week's folder goes in a directory named: **`{YYYY}-W{WW}`**

- `YYYY-WWW` — ISO week number when the PDF was added (ensures chronological sorting)
- Example: `2026-W12` (added during week 12 of 2026)

The promo validity period is stored in `metadata.json`, not in the directory name.

Tip — get the current week number: `date +%Y-W%V` (e.g. `2026-W11`). Use it directly:
```bash
mkdir -p ai/promo_pipelines/promo_folders/colruyt/$(date +%Y-W%V)
```

### metadata.json

Create a `metadata.json` alongside each PDF:

```json
{
  "promo_folder_url": "https://www.colruyt.be/nl/folders?folder=alle-acties",
  "added_at": "2026-03-14T10:30:00",
  "validity_start": "2026-03-10",
  "validity_end": "2026-03-16"
}
```

### Adding a Weekly Folder

**Single folder** (most stores):

```bash
# 1. Create the week directory
mkdir -p ai/promo_pipelines/promo_folders/colruyt/2026-W12

# 2. Copy the downloaded PDF — name it folder.pdf
cp ~/Downloads/colruyt_folder.pdf ai/promo_pipelines/promo_folders/colruyt/2026-W12/folder.pdf

# 3. Create metadata.json with the source URL and dates
# (manually or copy from a previous week and update)

# 4. Ingest
.venv/bin/python -m ai.promo_pipelines.ingest --store colruyt --latest --dry-run
```

**Multiple folders** (stores like Lidl, Aldi that have separate food/non-food folders):

```bash
# 1. Create the week directory
mkdir -p ai/promo_pipelines/promo_folders/lidl/2026-W12

# 2. Copy all PDFs — name the main one folder.pdf, others descriptively
cp ~/Downloads/lidl_food.pdf ai/promo_pipelines/promo_folders/lidl/2026-W12/folder.pdf
cp ~/Downloads/lidl_nonfood.pdf ai/promo_pipelines/promo_folders/lidl/2026-W12/nonfood.pdf

# 3. Create metadata.json

# 4. Ingest ALL PDFs in the directory with --all
.venv/bin/python -m ai.promo_pipelines.ingest --store lidl --latest --all --dry-run
```

You can also ingest a specific PDF directly with `--folder-path`:

```bash
.venv/bin/python -m ai.promo_pipelines.ingest --store lidl \
  --folder-path ai/promo_pipelines/promo_folders/lidl/2026-W12/nonfood.pdf
```

### Using `--latest` and `--all`

`--latest` automatically finds the most recent week directory for a store (sorted alphabetically — the `YYYY-WWW` prefix ensures chronological order).

| Command | What it ingests |
|---------|----------------|
| `--latest` | Only `folder.pdf` from the latest week directory |
| `--latest --all` | ALL `*.pdf` files from the latest week directory |

```bash
# Just the main folder.pdf
.venv/bin/python -m ai.promo_pipelines.ingest --store colruyt --latest --dry-run

# All PDFs in the latest week (food + non-food, etc.)
.venv/bin/python -m ai.promo_pipelines.ingest --store lidl --latest --all --dry-run
```

- `--latest` and `--folder-path` are mutually exclusive
- `--all` requires `--latest`
- `--clear-index` deletes ALL promos for the store before ingestion starts, then all PDFs are ingested into a clean slate

## How It Works

1. **PDF splitting** — PyMuPDF splits the folder into batches of 2 pages (oversized batches >1.5MB are further split into single pages)
2. **Gemini extraction** — Each batch is sent to Gemini with structured output mode (Pydantic schema), temperature 1.0, thinking level "high"
3. **Parsing & validation** — Structured output is parsed into `PromoItem` objects, categories validated against `app/core/categories.py`
4. **Deduplication** — Items deduplicated by `normalized_name` (handles bilingual folders)
5. **Pinecone upsert** — Items upserted with integrated embedding text:
   ```
   [brand] [product_name] [packaging_type] [pack_size] [content_value] [content_unit] [category]
   ```
   Example: `jupiler pils blik 24 25 cl [Beer Pils]`

### Upsert Behavior (How Duplicates Are Handled)

When you run the pipeline **without `--clear-index`**, it automatically **deletes existing promos for the same store + same validity period** before upserting new ones. This means:

- **Re-ingesting the same folder** replaces the previous extraction cleanly — no duplicates.
- **Ingesting a new week's folder** (different validity period) adds alongside existing weeks — old weeks are preserved.
- **`--clear-index`** is only needed if you want to wipe ALL promos for a store (all validity periods) and start fresh.

#### Multi-PDF stores (e.g., Lidl with food + nonfood folders)

When using `--latest --all`, the auto-delete only runs **before the first PDF**. Subsequent PDFs in the same batch are upserted without deleting, so items from all PDFs coexist in Pinecone.

This means:
- `--latest --all` is safe — all PDFs end up in the index
- If you ingest PDFs **one at a time** with separate `--folder-path` commands for the same store and validity period, each run will wipe the previous one. Use `--latest --all` instead to ingest all PDFs in one go.

#### Edge cases

- **Missing validity dates**: If Gemini fails to extract `validity_start`/`validity_end` (both are `null`), the auto-delete is skipped and items accumulate as duplicates. Use `--clear-index` to clean up before re-ingesting.
- **Re-running a single PDF**: Safe — the auto-delete removes the previous extraction for that store+validity, then upserts the fresh one.

## Adding a New Store

Create a YAML file in `ai/promo_pipelines/stores/`:

```yaml
store_id: "new_store"            # Must match canonical name in app/core/stores.py
display_name: "New Store"
language: "nl_fr"                # "nl" | "fr" | "nl_fr"
bilingual_dedup: true            # Deduplicate across NL/FR sides

validity_format: >
  "Geldig van DD/MM tot DD/MM" or "Valable du DD/MM au DD/MM"

store_brands:
  - name: "house_brand"
    description: "Standard house brand"

promo_mechanisms:
  - label: "1+1 gratis"
    aliases: ["1+1 gratuit"]
    description: "Buy one get one free. promo_price = price of one item"

normalized_name_examples:
  - input: "Jupiler Pils 6x33cl"
    output: "pils"

content_examples:
  - input: "6x33cl"
    pack_size: 6
    content_value: 33
    content_unit: "cl"

price_rules:
  original_price: "nullable"     # "nullable" or "mandatory"
  promo_price: "nullable"

# Optional escape hatches for store-specific prompt sections
normalized_name_guidance: null
price_calculation_table: null
extra_rules: []
validation_checklist: []
```

Then run:
```bash
.venv/bin/python -m ai.promo_pipelines.ingest --store new_store --folder-path ./folder.pdf --dry-run
```

## Extracted Fields

| Field | Description | Example |
|-------|-------------|---------|
| `normalized_name` | Lowercase product name, **excludes brand**, includes variant/flavour | `"pils"`, `"cola zero"`, `"chips paprika"` |
| `normalized_brand` | Lowercase brand name | `"jupiler"`, `"boni"`, `null` |
| `is_premium` | `true` for national brands, `false` for house brands | `true` |
| `packaging_type` | Container format | `"blik"`, `"fles"`, `"pet"`, `"zak"`, `null` |
| `pack_size` | Multi-pack count | `24`, `6`, `1` |
| `content_value` | Size of ONE item | `25` (from 24x25cl), `500` (from 500g) |
| `content_unit` | Unit lowercase | `"cl"`, `"g"`, `"l"`, `"kg"` |
| `granular_category` | From `app/core/categories.py` | `"Beer Pils"` |
| `original_price` | Regular price | `12.99` |
| `promo_price` | Promotional price | `9.99` |
| `promo_mechanism` | Promo label as printed | `"1+1 gratis"`, `"-30%"` |

## File Structure

```
ai/promo_pipelines/
├── README.md              # This file
├── __init__.py
├── ingest.py              # CLI entry point
├── pipeline.py            # Shared pipeline engine (extract, parse, upsert)
├── models.py              # PromoItem dataclass
├── prompt_builder.py      # Builds Gemini prompt from YAML config
├── stores/
│   ├── __init__.py        # load_store_config() + list_stores()
│   ├── colruyt.yaml
│   ├── okay.yaml
│   ├── spar.yaml
│   ├── delhaize.yaml
│   ├── proxy_delhaize.yaml
│   ├── carrefour_hyper.yaml
│   ├── carrefour_market.yaml
│   ├── aldi.yaml
│   ├── lidl.yaml
│   ├── albert_heijn.yaml
│   ├── intermarche.yaml
│   ├── jumbo.yaml
│   └── makro.yaml
└── promo_folders/         # Weekly PDF storage (PDFs git-ignored)
    ├── .gitignore
    ├── colruyt/
    │   └── {YYYY}-W{WW}/
    │       ├── folder.pdf
    │       └── metadata.json
    ├── delhaize/
    ├── aldi/
    └── ... (13 stores)
```

## Typical Workflow

```bash
# 1. Download the store's weekly promo folder PDF

# 2. Add it to the promo_folders structure
mkdir -p ai/promo_pipelines/promo_folders/colruyt/$(date +%Y-W%V)
cp ~/Downloads/colruyt.pdf ai/promo_pipelines/promo_folders/colruyt/$(date +%Y-W%V)/folder.pdf

# 3. Test extraction with dry run (--latest auto-finds the newest folder)
.venv/bin/python -m ai.promo_pipelines.ingest --store colruyt --latest --dry-run

# 4. Review extracted_promos.json — check normalized_name, brands, categories

# 5. Full ingestion (auto-deletes previous promos for same store + validity period)
.venv/bin/python -m ai.promo_pipelines.ingest --store colruyt --latest --url "https://..."

# 6. To re-ingest from scratch (clears ALL promos for the store first, asks for confirmation)
.venv/bin/python -m ai.promo_pipelines.ingest --store colruyt --latest --clear-index

# 7. Nuclear option — wipe the entire index and re-ingest all stores
.venv/bin/python -m ai.promo_pipelines.ingest --nuke-index
# Then re-ingest each store with --latest...
```

### Ingest a Specific Folder

If you have multiple weeks stored and want to ingest a specific one (not the latest), use `--folder-path` directly:

```bash
# Ingest a specific week's folder by path
.venv/bin/python -m ai.promo_pipelines.ingest --store colruyt \
  --folder-path ai/promo_pipelines/promo_folders/colruyt/2026-W11/folder.pdf --dry-run
```
