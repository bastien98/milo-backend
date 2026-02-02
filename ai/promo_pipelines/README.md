# Promo Pipelines

Extract promotional offers from supermarket folders and store them in Pinecone for semantic search.

## Setup

```bash
cd ai/promo_pipelines

# Install dependencies
pip install -r requirements.txt
```

## Usage

### Extract offers from a PDF

```bash
python extract_colruyt_promos.py colruyt_promo_folder.pdf
```

This will:
1. Convert PDF pages to images
2. Send to GPT-4o for extraction
3. Generate embeddings with llama-text-embed-v2
4. Store in Pinecone vector database
5. Save extracted JSON to `colruyt_promo_folder_extracted.json`

### Search for promotions

```bash
python extract_colruyt_promos.py --search "bier korting"
python extract_colruyt_promos.py --search "goedkope pasta"
python extract_colruyt_promos.py --search "1+1 gratis"
```

## Output Format

Each offer is stored with the following metadata:

```json
{
  "brand": "Jupiler",
  "description": "Pils bak 24x25cl",
  "volume_weight": "24x25cl",
  "price_standard": 14.99,
  "promo_type": "volume_discount",
  "promo_description": "-25% vanaf 2 bakken",
  "condition_qty": 2,
  "is_xtra_exclusive": false,
  "price_promo_final": 11.24,
  "source": "colruyt",
  "extracted_at": "2026-02-01T19:00:00"
}
```

## Configuration

- **Pinecone Index**: `promos`
- **Embedding Model**: `llama-text-embed-v2` (Pinecone Inference)
- **Extraction Model**: `gpt-4o` (OpenAI)

## API Keys

Both API keys are configured in the script:
- **OpenAI**: GPT-4o for PDF extraction
- **Pinecone**: Vector storage and llama-text-embed-v2 embeddings
