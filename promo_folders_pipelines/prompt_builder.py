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


_PROMO_TEXT_MARKDOWN_SECTION = """## VERBATIM PROMO TEXT (`promo_text_markdown`)
Transcribe every piece of text that is actually printed on the promo tile, then reformat it as clean Markdown for display to the end user. This field is shown to shoppers as-is, so it must be faithful and readable.

RULES:
1. **Verbatim wording** — keep the original Dutch or French exactly as printed. Do not translate, paraphrase, or summarize. Do not invent text that is not on the tile.
2. **Markdown formatting**:
   - Use `**bold**` for the mechanism/headline line (e.g. `**1+1 GRATIS**`, `**-25%**`, `**€2,49**`).
   - Regular lines for the product name and descriptive copy.
   - Use `- ` bulleted lists for enumerations (multi-brand choices, variant lists, bullet points printed on the tile).
   - Separate logical blocks with a single blank line.
3. **Prices** — write them exactly as on the tile: euro sign + comma decimal (e.g. `€2,49`, `€0,99`). Do not round or reformat.
4. **Do NOT include** image descriptions, bounding box info, or anything not actually printed on the tile.
5. **Do NOT wrap** the output in a code fence or surrounding quotes.
6. Return `null` only if the tile literally has no visible text (extremely rare — e.g. purely visual teaser).

EXAMPLE for a Coca-Cola 1+1 tile showing "1+1 GRATIS / Coca-Cola Zero 1,5 L / €2,49 per fles / Geldig t/m zondag":
```
**1+1 GRATIS**

Coca-Cola Zero 1,5 L

- €2,49 per fles
- Geldig t/m zondag
```
(Do not include the ``` fences in your output — they are only shown here to delimit the example.)"""



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
- Every item has both `bbox` (physical product) and `tile_bbox` (whole tile, contains bbox)."""
