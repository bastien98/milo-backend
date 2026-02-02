# AI / Scraping Tools

This folder contains AI and web scraping utilities for Scandelicious.

## Scripts

### `scrape_carrefour.py`
Scrapes current promotions from Carrefour Belgium website.

**Output:** `carrefour_promotions.csv` with columns:
- `title` - Product name with brand
- `offer_details` - Promotion text (e.g., "2+1 GRATIS")
- `valid_until` - Expiration date (YYYY-MM-DD)
- `product_url` - Link to product page
- `image_url` - Product image URL
- `scraped_at` - Timestamp of scrape

## Setup

```bash
# Navigate to ai folder
cd ai

# Create virtual environment (optional but recommended)
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Install Playwright browsers (required first time only)
playwright install chromium
```

## Usage

```bash
# Run the scraper
python scrape_carrefour.py
```

The script will:
1. Open Carrefour promotions page
2. Scroll to load all products (infinite scroll)
3. Extract promotion details
4. Save to `carrefour_promotions.csv`

## Notes

- Set `headless=False` in the script to watch the browser while scraping
- The scraper may take 1-2 minutes depending on how many promotions are available
- Respects website structure - if Carrefour changes their HTML, selectors may need updating