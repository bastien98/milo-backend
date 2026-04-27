"""
Generic prompt builder for promo folder extraction.

The system prompt is intentionally minimal: Gemini only produces the PERCEPTUAL
signal (visible text, prices, pack tokens, category, mechanism kind, bboxes).
All display strings, savings math, minimum purchase quantities, and cross-store
normalization are derived in Python by `promo_folders_pipelines.mechanism`.
"""

from datetime import date
from typing import Any, Dict


_CANONICAL_MECHANISM_TABLE = """## PROMO MECHANISMS
Classify every promo into ONE canonical `mechanism_kind` and fill `mechanism_x` / `mechanism_y` with the printed numbers. DO NOT output localized labels — Python builds those.

| mechanism_kind         | Typical printed labels (any store, NL/FR)                        | mechanism_x         | mechanism_y         |
|------------------------|------------------------------------------------------------------|---------------------|---------------------|
| buy_x_get_y_free       | "X+Y gratis", "X+Y gratuit", "1+1 gratis"                        | X (int)             | Y (int)             |
| second_half_price      | "2e aan halve prijs", "2e halve prijs", "2ème à moitié prix"     | null                | null                |
| second_percent_off     | "2e aan -X%", "2e tegen -X%", "2e voor -X%"                      | X (percent)         | null                |
| percent_off            | "-X%", "X% korting", bare "-30%"                                  | X (percent)         | null                |
| percent_off_from_n     | "-X% vanaf Y verpakkingen", "-X% bij aankoop van Y", "-X% à partir de Y" | X (percent)  | Y (min qty)         |
| euro_off               | "€X.XX korting", "-€X korting", "€X.XX réduction"                | X (euro amount)     | null                |
| n_for_euro             | "X voor €Y", "X pour €Y"                                          | X (qty)             | Y (total euro)      |
| price_reduction        | plain lowered price, "Prix Choc", "Mega Deal" (no other label)   | null                | null                |

Put the store's marketing banner (e.g. "Bonus", "Prix Choc", "Mega Deal", "Sunday Deal", "Bonus Card") verbatim in `promo_campaign`. It is ORTHOGONAL to `mechanism_kind` — still pick the underlying mechanism kind from the table above."""


_COUPON_DETECTION_SECTION = """## COUPON DETECTION
A **coupon** is a tile with a scannable barcode the shopper presents at the till to redeem loyalty points, cash back, a free product, or a percentage discount. A non-coupon promo tile is a normal discounted product. Coupons look distinctly different — they always combine these three signals:

1. A **loyalty-program badge** visible on the tile: "Bonuspunten", "Bonus Card", "SuperPlus", "Plus Points", "Xtra", "Fidelity", "Fidélité".
2. A **1D barcode** (stripes) printed within the tile's own boundary, with human-readable digits underneath (typically EAN-13 or Code-128).
3. **Redemption fine print** like "Geldig bij afgifte van deze originele bon", "Bon per aankoop", "Valable sur présentation de ce bon", or a coupon-specific "Geldig tot DD/MM/YYYY" date independent of the folder's validity.

For each item, emit:

- `is_coupon: bool` — TRUE only if ALL THREE signals are present. A barcode printed on product PACKAGING (visible in the product photo) is NOT a coupon — that's just the product's own EAN. A QR code is NOT a coupon — coupons are 1D barcodes only.
- `coupon_type: str | null` — if `is_coupon` is TRUE, classify into ONE of:
  - `"loyalty_points"` — the reward is loyalty-card points ("X Bonuspunten", "X Plus-punten", "X pts")
  - `"cashback"` — the reward is a direct euro discount ("€X korting", "-€X", "€X réduction")
  - `"free_product"` — one product free with a qualifying purchase ("1 gratis product", "produit gratuit")
  - `"percent_off_coupon"` — the reward is a percentage off ("-X% op", "-X% sur")
  - `"other"` — clearly a coupon but none of the above fit
- `coupon_value: float | null` — the numeric reward: points count for `loyalty_points`, euro amount for `cashback`, percent for `percent_off_coupon`, null for `free_product` and `other`.
- `coupon_min_purchase: str | null` — the verbatim trigger condition ("1 pot Natù-fruitspread", "€20 aan Nivea-gezichtsverzorging", "2 producten van Prince").
- `coupon_validity_end: str | null` — YYYY-MM-DD parsed from the coupon's own "Geldig tot" / "Valable jusqu'au" date, if printed on the tile. null if only the folder's global validity applies.

Non-coupon items: emit `is_coupon: false` and leave all other coupon_* fields null.

When a coupon tile is present: still fill `product_name`, brands, `promo_text_markdown`, category, `bbox`, `tile_bbox` for the underlying product the coupon applies to. Coupons don't have `original_price` / `promo_price` (unless the tile also prints one) — leave pricing fields null for pure loyalty-points / free-product coupons."""


_PROMO_TEXT_MARKDOWN_SECTION = """## CONSUMER-FACING PROMO TEXT (`promo_text_markdown`)
Produce a clean, Markdown-formatted summary of the printed text that is **relevant to the consumer about THIS specific promotion**. This field is shown to shoppers as-is in the product / coupon detail screen, so it must be faithful, focused, and readable.

### WHAT TO INCLUDE (consumer-relevant deal info)
- The mechanism / headline as printed (e.g. `1+1 GRATIS`, `-25%`, `€2,49`).
- Product name & variant info printed on the tile.
- Both prices when shown: the current promo price AND any "was" / original price (see strikethrough rule below).
- Pack size / volume if printed on the tile (e.g. `1,5 L`, `6 x 25 cl`, `500 g`).
- Explicit savings claim ("Bespaar €3,00", "Économisez €3,00").
- Validity date if explicitly printed on this tile (e.g. "Geldig t/m zondag", "Valable jusqu'au 12/05").
- Meaningful purchase conditions / restrictions ("vanaf 2 stuks", "max. 4 per klant", "bij aankoop van 2").
- For COUPONS: the loyalty reward ("X Bonuspunten", "€X korting") AND the trigger condition ("bij aankoop van 1 pot Natù-fruitspread").

### WHAT TO EXCLUDE (not useful for the consumer here)
- Store-wide marketing banners that are decorative and already captured separately (e.g. "Sunday Deal", "Bonus Card", "Mega Deal", "Prix Choc" used as a banner) — those live in `promo_campaign`.
- Generic slogans / filler ("Lekker voordelig!", "De beste prijs van de week", "Nieuw!").
- Legal / redemption fine-print not specific to the offer ("Geldig bij afgifte van deze originele bon", "Bon per aankoop", barcode digits).
- Page numbers, section headers, navigation text, anything bleeding in from neighbouring tiles.
- Sustainability / origin / nutrition labels that are not part of THIS deal ("Bio", "Belgisch", "Nutri-Score") unless they are the headline of the offer itself.
- Image descriptions, bounding box info, anything not actually printed on the tile.

### MARKDOWN FORMATTING
1. **Verbatim wording** — keep the original Dutch or French exactly as printed for the text you DO include. Do not translate, paraphrase, summarize, or invent text. You may, however, freely **restructure the layout** — add or remove line breaks, regroup lines, choose where blank lines go, and turn enumerations into bullet lists — purely so the output reads cleanly in a mobile detail screen. Aim for this reading order: headline → product → price line → conditions / validity.
2. **Bold** — wrap the mechanism/headline and standalone prices in `**…**` (e.g. `**1+1 GRATIS**`, `**-25%**`, `**€2,49**`).
3. **Strikethrough** — if a piece of text is printed on the tile with a visible line struck through it (almost always the original "was" price), wrap it in `~~…~~`. Combine with `**bold**` when both apply (e.g. `~~**€3,49**~~ **€2,49**`). Do NOT add strikethrough to text that is merely faded, greyed, or smaller — only when an actual line is drawn through it.
4. **Bullet lists** — use `- ` for enumerations: multi-brand/variant choices, multi-line conditions, validity + savings on separate lines, etc.
5. **Blocks** — separate logical blocks (headline, product, price line, conditions) with a single blank line.
6. **Prices** — write exactly as on the tile: euro sign + comma decimal (`€2,49`, `€0,99`). Do not round or reformat.
7. **No code fences, no surrounding quotes** in the output.
8. Return `null` if, after filtering, there is nothing consumer-relevant left to show (rare).

### EXAMPLE
Tile prints (Dutch): banner "Sunday Deal", headline "1+1 GRATIS", product "Coca-Cola Zero 1,5 L", prices "~~€3,49~~ €2,49 per fles", "Bespaar €1,00", validity "Geldig t/m zondag", footer "Lekker voordelig!".

```
**1+1 GRATIS**

Coca-Cola Zero 1,5 L

~~**€3,49**~~ **€2,49** per fles

- Bespaar €1,00
- Geldig t/m zondag
```

Note the "Sunday Deal" banner and "Lekker voordelig!" slogan are dropped (banner → `promo_campaign`, slogan → filler). Do not include the ``` fences in your output — they only delimit the example here."""



def build_system_prompt(config: Dict[str, Any], categories_list: str) -> str:
    """Build a complete Gemini system prompt from a store config and the granular category list."""
    display_name = config["display_name"]
    language = config.get("language", "nl_fr")
    bilingual_dedup = config.get("bilingual_dedup", False)

    sections: list[str] = []

    # --- Intro ---
    sections.append(
        f"You are a specialist in extracting promotional offers from "
        f"{display_name} supermarket folders (Belgium)."
    )

    # --- Folder format & language ---
    sections.append(_build_language_section(display_name, language, bilingual_dedup))

    # --- Validity dates ---
    validity_fmt = config.get("validity_format")
    if validity_fmt:
        sections.append(
            "## VALIDITY DATES\n"
            f"The validity period is typically: {validity_fmt}\n"
            f"Convert to YYYY-MM-DD (today is {date.today().isoformat()}, use year {date.today().year} if not shown).\n"
            "Apply the same validity to all items unless an item shows its own range. Use null when no dates are visible."
        )

    # --- Canonical mechanism table (shared across all stores) ---
    sections.append(_CANONICAL_MECHANISM_TABLE)

    # --- Coupon detection (bonus points, cashback, free product, % off coupons) ---
    sections.append(_COUPON_DETECTION_SECTION)

    # --- Verbatim promo text → Markdown ---
    sections.append(_PROMO_TEXT_MARKDOWN_SECTION)

    # --- Store brands (helps Gemini recognize house brands) ---
    store_brands = config.get("store_brands", [])
    if store_brands:
        sections.append(_build_store_brands_section(display_name, store_brands))

    # --- Extraction rules ---
    sections.append(_build_extraction_rules(categories_list))

    # --- Extra rules (escape hatch from store YAML) ---
    extra_rules = config.get("extra_rules", [])
    if extra_rules:
        sections.append("## ADDITIONAL RULES\n" + "\n".join(f"- {r}" for r in extra_rules))

    # --- Validation checklist ---
    sections.append(_build_validation_checklist())

    return "\n\n".join(sections)


def _build_language_section(display_name: str, language: str, bilingual_dedup: bool) -> str:
    lines = [f"## {display_name.upper()} FOLDER FORMAT"]
    if language == "nl_fr":
        lines.append(f"- {display_name} folders are typically bilingual: Dutch on one side, French on the other.")
        if bilingual_dedup:
            lines.append("  Extract from EITHER language — do not duplicate items that appear in both languages.")
    elif language == "nl":
        lines.append(f"- {display_name} folders are in Dutch.")
    elif language == "fr":
        lines.append(f"- {display_name} folders are primarily in French.")
    return "\n".join(lines)


def _build_store_brands_section(display_name: str, store_brands: list) -> str:
    lines = [
        f"## {display_name.upper()} STORE BRANDS\n"
        f"These are {display_name}'s house brands — include the brand name in `primary_brand`:"
    ]
    for b in store_brands:
        lines.append(f'- **{b["name"].title()}**: {b.get("description", "")}')
    lines.append("\nAll other recognized brands are national / premium brands.")
    return "\n".join(lines)


def _build_extraction_rules(categories_list: str) -> str:
    return f"""## EXTRACTION RULES

### COVERAGE GOAL
Extract EVERY product that has ANY promotional offer, deal, or reduced price. A single promo tile = ONE item, regardless of how many products are shown inside it.

### MULTI-PRODUCT TILES (IMPORTANT)
When a single tile advertises multiple brands or variants together (e.g. "Coca-Cola, Fanta of Sprite", "Lay's, Doritos of Bugles"):
- Return ONE item, not several.
- `primary_brand` = the most prominent brand on the tile.
- `additional_brands` = the other brands listed on the tile (e.g. ["Fanta", "Sprite"]).
- `product_name` describes the shared product category + size (e.g. "Frisdrank 1,5 L" or keep the prominent brand's name if it dominates).
- Shared pricing, pack size, mechanism, and bbox apply to the item as a whole.

### For each promotional item extract:

1. **product_name** — clean Title Case label for the consumer app.
   - Omit the brand when the product is identifiable without it (brand lives in `primary_brand`).
   - Keep the brand INSIDE `product_name` only when essential for identity ("Coca-Cola Zero", "Jupiler Pils").
   - For drinks always include volume ("33 cl", "6 x 25 cl", "1,5 L").
   - No promo text, no pricing.

2. **primary_brand / additional_brands** — Title Case brand names as printed. null for truly unbranded tiles.

3. **Pricing (visible only — NEVER compute):**
   - `original_price`: the struck-through or "was" price, only if visible.
   - `promo_price`: the shelf price actually printed on the tile.
   - `stated_savings`: only when the tile explicitly prints a savings amount ("Bespaar €3.00"). Otherwise null.
   - Do NOT derive one price from another. Do NOT "compute" promo_price from a percentage. Python does that.

4. **Pack size (observable tokens — NEVER convert):**
   - `pack_size_value`, `pack_size_unit`, `pack_count` transcribed exactly as printed.
   - "500 g" → value=500, unit="g", count=1.
   - "1,5 L" → value=1.5, unit="l", count=1.
   - "6 x 25 cl" → value=25, unit="cl", count=6.
   - "24 blikjes 33 cl" → value=33, unit="cl", count=24.
   - "4-pack toiletpapier 6 rollen" → value=6, unit="rol", count=4.
   - Countables without an explicit unit → unit="stuk".
   - Approximate/per-weight items ("± 500 g", "ongeveer 1,2 kg"): value=1, unit="kg", count=1 — the printed price is then the €/kg shelf price.
   - Size ranges ("80 g - 175 g", "200/300 g"): pick the LOWER value (worst-case €/kg).
   - Nothing visible → leave all three null.

5. **Mechanism:** classify via `mechanism_kind` + `mechanism_x` / `mechanism_y` per the table above. Put any store marketing banner in `promo_campaign` verbatim.

6. **granular_category:** assign ONE category from the list below (used for similarity ranking — precision matters, e.g. a Pilsner goes in "Pilsners & Lagers", never in "Specialty & Abbey Beers"). Use "Other" only if nothing fits.
{categories_list}"""


def _build_validation_checklist() -> str:
    return """## VALIDATION CHECKLIST
Before outputting each item, verify:
- `product_name` is Title Case, includes size/volume when visible, no promo text, no pricing.
- `mechanism_kind` matches the table; `mechanism_x` / `mechanism_y` are the PRINTED numbers (not derived).
- Prices are copied verbatim (rounded to 2 decimals if needed). You did NOT compute one from another.
- Pack size tokens are transcribed verbatim — no unit conversion.
- A multi-brand tile is ONE item with brands split into primary_brand + additional_brands.
- `granular_category` is chosen precisely (wine → wine sub-category, beer → beer sub-category; never cross over).
- Every item has both `bbox` (physical product) and `tile_bbox` (whole tile, contains bbox).
- `is_coupon` is TRUE only when the tile has a loyalty-badge + 1D barcode + redemption fine-print together. Product-packaging EANs and QR codes don't qualify."""
