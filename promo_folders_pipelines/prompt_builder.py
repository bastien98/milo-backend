"""
Generic prompt builder for promo folder extraction.

The system prompt is intentionally minimal: Gemini only produces the PERCEPTUAL
signal (visible text, prices, pack tokens, category, mechanism kind, bboxes).
All display strings, savings math, minimum purchase quantities, and cross-store
normalization are derived in Python by `promo_folders_pipelines.mechanism`.
"""

from datetime import date
from typing import Any, Dict


_GEOMETRY_SECTION = """## GEOMETRY
Every item MUST have both `bbox` and `tile_bbox`, integer coords 0-1000 (0=left/top, 1000=right/bottom).

### `bbox` — the product only
Tight around the PHYSICAL PRODUCT (bottle/box/can/package), with a ~2-3% margin. Exclude price labels, badges, and text outside the packaging.

### `tile_bbox` — the WHOLE promo block
WARNING: A `tile_bbox` that ends immediately at the bottom of the product packaging is almost always wrong. You MUST actively scan outward from the product, not just trace its silhouette.

It MUST fully contain every visual element belonging to this offer:
1. The product photo or illustration (and any secondary product photos that are part of the same offer).
2. The product name / variant text.
3. EVERY price label that belongs to the offer — original price, promo price, per-unit price, savings amount. If a price sits below, beside, or above the product photo, the tile_bbox extends to include it.
4. The promo mechanism / badge ("1+1 GRATIS", "-25%", "€2 korting", "Prix Choc", "Bonus", coupon stamps) wherever it sits, including corner badges that stick out past the photo.
5. The brand block, slogan, fine-print and any descriptive text printed inside the tile boundary that belongs to this offer.
6. The tile's own background colour block / coloured frame, if it has one — extend the rectangle out to the visible edge of that coloured block.

### Active spatial checklist (run this for EVERY tile before emitting tile_bbox)
1. ANCHOR: locate the product image.
2. SCAN DOWN: is there a price, per-unit price, or "Bespaar / Économisez" line below the product? Push `y_max` past the bottom of the lowest such line.
3. SCAN UP / SIDES: is a "-25%" badge, "1+1" stamp, or coupon mark floating above or to the side of the product? Push `y_min`, `x_min`, or `x_max` outward to capture it. Corner stickers count.
4. SCAN BACKGROUND: is there a coloured background box / frame enclosing the offer? Snap `tile_bbox` to the OUTER edges of that coloured block, not to the product silhouette.
5. EXPAND: after the four scans, expand the rectangle outward by ~1-2% on every side so nothing skims the edge. Better too generous than clipping a price line or badge.

### Overlap & containment
- Adjacent `tile_bbox`es in a dense grid may touch or lightly overlap — that is acceptable. NEVER shrink a tile inward to avoid touching a neighbour if doing so would clip price text, a badge, or a description line.
- `tile_bbox` must fully contain `bbox`.
- Validation: x_min < x_max, y_min < y_max."""


_EXTRACTION_PROCESS_SECTION = """## YOUR EXTRACTION PROCESS (THINKING PHASE)
Before generating the JSON output, use your reasoning phase to map the page spatially so that ZERO items are skipped.
1. Scan the page systematically in a grid: top row (left → right), middle row (left → right), bottom row (left → right). For multi-column or staggered layouts, scan column-by-column the same way.
2. Count the total number of valid promotional tiles you see (a "valid tile" is defined in the EXCLUSIONS section: it must have its OWN price label or mechanism).
3. Briefly list every valid tile by product name in your thought process to build an internal checklist.
4. Only after this checklist exists, begin generating the JSON `items` array — and emit one entry for every name on your checklist, in order. Do NOT close the array until every checklist item has been emitted."""


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
Produce a clear, **grounded explanation** of THIS specific promotion in Markdown — readable, well-structured, and built **only** from what is printed on the tile. After reading this text, the shopper should immediately understand WHAT the deal is and HOW it works. This field is shown to shoppers as-is in the product / coupon detail screen.

### WHAT TO INCLUDE (consumer-relevant deal info)
- The mechanism / headline as printed (e.g. `1+1 GRATIS`, `-25%`, `€2,49`).
- Product name & variant info printed on the tile.
- Both prices when shown: the current promo price AND any "was" / original price (see strikethrough rule below).
- Unit / per-quantity price if printed on the tile (e.g. `€1,66/L`, `€4,98/kg`, `€0,50 per stuk`, `€0,42 par pièce`). If it's printed, always carry it through — it's important for shoppers comparing value.
- Pack size / volume if printed on the tile (e.g. `1,5 L`, `6 x 25 cl`, `500 g`).
- Explicit savings claim ("Bespaar €3,00", "Économisez €3,00").
- Meaningful purchase conditions / restrictions ("vanaf 2 stuks", "max. 4 per klant", "bij aankoop van 2").
- For COUPONS: the loyalty reward ("X Bonuspunten", "€X korting") AND the trigger condition ("bij aankoop van 1 pot Natù-fruitspread").

### WHAT TO EXCLUDE (not useful for the consumer here)
- Store-wide marketing banners that are decorative and already captured separately (e.g. "Sunday Deal", "Bonus Card", "Mega Deal", "Prix Choc" used as a banner) — those live in `promo_campaign`.
- Generic slogans / filler ("Lekker voordelig!", "De beste prijs van de week", "Nieuw!").
- Legal / redemption fine-print not specific to the offer ("Geldig bij afgifte van deze originele bon", "Bon per aankoop", barcode digits).
- Page numbers, section headers, navigation text, anything bleeding in from neighbouring tiles.
- Sustainability / origin / nutrition labels that are not part of THIS deal ("Bio", "Belgisch", "Nutri-Score") unless they are the headline of the offer itself.
- **Validity periods** ("Geldig t/m zondag", "Valable jusqu'au 12/05", "Geldig van 02/05 t/m 08/05") — these are shown separately in the UI from the folder/coupon validity dates, so omitting them avoids duplicate information. The only exception is a hard, offer-specific time restriction printed on the tile that's tighter than the folder window (e.g. "enkel vandaag", "uniquement le dimanche", "le matin uniquement") — keep those, since they're a real shopping constraint.
- Image descriptions, bounding box info, anything not actually printed on the tile.

### MARKDOWN FORMATTING
1. **Grounded rewrite** — paraphrase, restructure, and add short clarifying explanation so the deal reads naturally on a mobile screen. Use the **same language as the tile** (NL stays NL, FR stays FR — never translate between them, never mix). Every concrete fact (mechanism, prices, sizes, dates, conditions, brand/product names, savings claims) must come straight from the tile.

   You MAY:
   - Spell out cryptic shorthand into plain wording (e.g. `1+1 GRATIS` → also explain "koop er 1, krijg de 2e gratis"; `-25% vanaf 2` → also "korting geldt vanaf 2 stuks"; `2 voor €5` → "betaal €5 voor 2 stuks").
   - Reorder lines, merge or split them, choose where blank lines go, and turn enumerations into bullets, all to make the text easy to scan. Aim for the reading order: headline → product → price line → conditions.
   - Restate a fact in slightly clearer phrasing if the tile's exact wording is awkward.

   You MUST NOT:
   - Invent prices, percentages, dates, savings, validity, conditions, or product details that aren't on the tile.
   - Compute or derive new numbers — no effective unit price after discount, no total savings math, no rounded prices. Only repeat what is printed (Python derives those separately).
   - Translate between Dutch and French, or output English.
   - Add marketing language, opinions, or comparisons ("great deal", "the best price", "compared to last week").

   If you'd write a sentence and can't point to the tile for every concrete detail in it, drop the sentence. Currency-symbol placement is governed by rule 6, not by this rule: prepending `€` to a price token that lacks the symbol on the tile is required, not a violation.
2. **Bold for highlights** — wrap the key data points the shopper's eye should catch: the mechanism / headline (`**1+1 GRATIS**`, `**-25%**`), the promo price (`**€2,49**`), and the savings amount (`**€1,00**`). Use bold sparingly — if everything is bold, nothing stands out. Plain product names, conditions, and explanatory clauses stay un-bolded.
3. **Strikethrough** — if a piece of text is printed on the tile with a visible line struck through it (almost always the original "was" price), wrap it in `~~…~~`. Combine with `**bold**` when both apply (e.g. `~~**€3,49**~~ **€2,49**`). Do NOT add strikethrough to text that is merely faded, greyed, or smaller — only when an actual line is drawn through it.
4. **Bullet lists** — use `- ` for enumerations: multi-brand/variant choices, multi-line conditions, savings + restrictions on separate lines, etc.
5. **Blocks** — separate logical blocks (headline, product, price line, conditions) with a single blank line.
6. **Prices** — always render every price token as `€X,YY`, regardless of how the tile prints it. The euro symbol goes immediately before the digits, with no space. The amount itself stays verbatim: keep the comma as decimal separator, do not round, do not derive a price from another (Python does that). Examples of normalization:
   - tile prints `€ 2,49` → `€2,49`
   - tile prints `2,49 €` → `€2,49`
   - tile prints `2,49` (no symbol, but clearly a price) → `€2,49`
   - tile prints big `2` with superscript `49` → `€2,49`
   - tile prints `0,⁹⁹` or `0,99` → `€0,99`
   - whole-euro price like `€5` or `5 €` → `€5,00` only if both decimals are visible on the tile; otherwise `€5`.
   Apply the same `€X,YY` normalization to per-unit prices: `1,66/L` → `€1,66/L`, `4,98 /kg` → `€4,98/kg`, `0,50 per stuk` → `€0,50 per stuk`. Keep the unit suffix (`/L`, `/kg`, `/stuk`, `per pièce`, etc.) exactly as printed.
   Only apply the `€` prefix to **prices**. Do NOT prepend `€` to volumes (`1,5 L`), weights (`500 g`), pack counts (`6 x 25 cl`), percentages (`-25%`), or loyalty-point values (`50 Bonuspunten`).
7. **No code fences, no surrounding quotes** in the output.
8. Return `null` if, after filtering, there is nothing consumer-relevant left to show (rare).

### EXAMPLE
Tile prints (Dutch): banner "Sunday Deal", headline "1+1 GRATIS", product "Coca-Cola Zero 1,5 L", prices "~~€ 3,49~~ 2,49 per fles" (symbol only on the struck-through price), per-unit "€1,66/L", "Bespaar €1,00", validity "Geldig t/m zondag", footer "Lekker voordelig!".

```
**1+1 GRATIS** op Coca-Cola Zero 1,5 L — koop er 1, krijg de 2e gratis.

Per fles: ~~**€3,49**~~ **€2,49** (€1,66/L). Je bespaart **€1,00**.
```

Trace each fact to the tile: mechanism + product + the explanatory clarifier (same idea, plainer Dutch), both prices verbatim (and `€` added to the un-symbolled price per rule 6), per-unit price verbatim, savings verbatim. The "Sunday Deal" banner (→ `promo_campaign`), "Lekker voordelig!" slogan (→ filler), and the "Geldig t/m zondag" validity (→ shown separately in the UI) are all dropped. No new numbers, no NL→FR translation. A French tile would produce the same shape in French; never mix languages. Do not include the ``` fences in your output — they only delimit the example here."""



_SEARCH_ENRICHMENT_SECTION = """## SEARCH ENRICHMENT (`search_text`, `generic_product_type`)

These two fields power the in-app product search bar. Shoppers search in Dutch, French, OR English — so every item must be findable from all three languages, even when the tile only prints one.

### `search_text`
ONE lowercase, unaccented, space-separated string covering every word a shopper might type to find this item. Include:
- The brand (if any) — `primary_brand` plus each name in `additional_brands`.
- All meaningful words from `product_name` (size/volume tokens are fine but not required).
- The generic product noun in **NL, FR, AND EN** — even if only one language is on the tile. Example: a beer tile gets "bier biere beer" added; a chocolate bar gets "chocolade chocolat chocolate"; a diaper gets "luier couche diaper".
- Obvious flavor/variant words ("vanilla", "blond", "tripel", "salt pepper", "lait entier").
- Common abbreviations or shop-floor synonyms ("coke" for Coca-Cola, "lays" alongside "lay's", "pamper" for Pampers).

Rules:
- Strip apostrophes, accents, punctuation. Keep digits and the letter `x` (so "6 x 33 cl" survives).
- Lowercase everything.
- Single spaces between tokens. No commas, slashes, or hyphens.
- No promo mechanism, no prices, no validity, no marketing slogans, no store names.
- Hard limit: ~120 characters. Pick the most useful tokens; do NOT pad.

Example outputs:

| Tile shows | search_text |
|---|---|
| Stella Artois 6 x 0,33 L (Pilsners & Lagers) | `stella artois pils blond bier biere beer pilsner lager 6 33 cl` |
| Côte d'Or Tablet Lait 200 g (Chocolate & Confectionery) | `cote dor cote d or tablet lait melk milk chocolade chocolat chocolate bar 200 g` |
| Pampers Cruisers Taille 4+ 37 luiers (Baby Care) | `pampers cruisers luier luiers couche diaper taille 4+ 37` |
| Lay's Bugles Cheese 100 g (Salty Snacks & Nuts) | `lays bugles cheese kaas fromage chips snack 100 g` |

### `generic_product_type`
ONE short lowercase English noun phrase (max 32 chars) — what the item IS, ignoring brand. Used for cross-brand grouping ("show me all crisps").

Examples: `"beer"`, `"chocolate bar"`, `"diaper"`, `"shampoo"`, `"laundry detergent"`, `"crisps"`, `"yogurt"`, `"frozen pizza"`, `"olive oil"`, `"toilet paper"`. Never include brand or size. Null only if no clear generic type exists (extremely rare — almost every promo item has one)."""


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

    # --- Reasoning-phase scaffolding (force a spatial pre-scan before JSON emission) ---
    sections.append(_EXTRACTION_PROCESS_SECTION)

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

    # --- Search enrichment (search_text + generic_product_type) ---
    sections.append(_SEARCH_ENRICHMENT_SECTION)

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

    # --- Geometry rules (kept right before the validation checklist) ---
    sections.append(_GEOMETRY_SECTION)

    # --- Validation checklist (LAST on purpose: recency bias — this is the model's
    # final mental pass before it begins streaming the JSON `items` array) ---
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

### EXCLUSIONS (WHAT NOT TO EXTRACT)
Do NOT extract lifestyle images, decorative background products, or broad thematic hero banners (e.g. a large picture of a BBQ scene with no specific price, a "Greek week" banner with stylised feta photos, a "Bonus Card" cover panel). To be a valid item, a product MUST be physically adjacent to its OWN specific, actionable price tag or promotional mechanism (e.g. "1+1 Gratis", "-25%", "€4,99"). If a product is just a generic illustration that belongs to a page-wide banner — not its own tile with its own price/mechanism — ignore it entirely. When a banner-illustrated product also appears further down the page as a real priced tile, only the priced tile is an item.

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
- `is_coupon` is TRUE only when the tile has a loyalty-badge + 1D barcode + redemption fine-print together. Product-packaging EANs and QR codes don't qualify.
- `search_text` includes the generic product noun in NL, FR, AND EN (e.g. "bier biere beer" on every beer item) — never assume the shopper types in the same language as the tile.
- `generic_product_type` is a short English noun phrase, no brand, no size."""
