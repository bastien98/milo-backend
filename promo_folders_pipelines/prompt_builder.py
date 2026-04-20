"""
Generic prompt builder for promo folder extraction.

Assembles a Gemini system prompt from a store's YAML config
and the shared category list.
"""

from datetime import date
from typing import Any, Dict


def build_system_prompt(config: Dict[str, Any], categories_list: str) -> str:
    """Build a complete Gemini system prompt from a store config and categories."""
    store_id = config["store_id"]
    display_name = config["display_name"]
    language = config.get("language", "nl_fr")
    bilingual_dedup = config.get("bilingual_dedup", False)

    sections = []

    # --- Intro ---
    sections.append(
        f"You are a specialist in extracting promotional offers from "
        f"{display_name} supermarket folders (Belgium).\n"
        f"You have deep knowledge of {display_name}'s folder layout, pricing labels, "
        f"and promotional mechanics."
    )

    # --- Folder format & language ---
    sections.append(_build_language_section(display_name, language, bilingual_dedup))

    # --- Validity format ---
    validity_fmt = config.get("validity_format")
    if validity_fmt:
        sections.append(
            f"## VALIDITY DATES\n"
            f"The validity period is typically: {validity_fmt}\n"
            f"Convert to YYYY-MM-DD (today is {date.today().isoformat()}, use year {date.today().year} if not shown).\n"
            f"Apply the SAME validity dates to all items unless an item shows its own date range.\n"
            f"If no dates are visible on these pages, use null."
        )

    # --- Promo mechanisms ---
    mechanisms = config.get("promo_mechanisms", [])
    if mechanisms:
        sections.append(_build_mechanisms_section(mechanisms))

    # --- Store brands ---
    store_brands = config.get("store_brands", [])
    if store_brands:
        sections.append(_build_store_brands_section(display_name, store_brands))

    # --- Extraction rules ---
    sections.append(_build_extraction_rules(config, categories_list))

    # --- Extra rules (escape hatch) ---
    extra_rules = config.get("extra_rules", [])
    if extra_rules:
        sections.append("## ADDITIONAL RULES\n" + "\n".join(f"- {r}" for r in extra_rules))

    # --- Validation checklist ---
    sections.append(_build_validation_checklist(config))

    return "\n\n".join(sections)


def _build_language_section(display_name: str, language: str, bilingual_dedup: bool) -> str:
    lines = [f"## {display_name.upper()} FOLDER FORMAT"]
    if language == "nl_fr":
        lines.append(
            f"- {display_name} folders are typically bilingual: Dutch on one side, French on the other."
        )
        if bilingual_dedup:
            lines.append(
                "  Extract from EITHER language — do not duplicate items that appear in both languages."
            )
    elif language == "nl":
        lines.append(f"- {display_name} folders are in Dutch.")
    elif language == "fr":
        lines.append(f"- {display_name} folders are primarily in French.")
    return "\n".join(lines)


def _build_mechanisms_section(mechanisms: list) -> str:
    lines = ["## PROMO MECHANISMS\nRecognize and extract these promotional labels correctly:"]
    for m in mechanisms:
        label = m["label"]
        aliases = m.get("aliases", [])
        desc = m.get("description", "")
        alias_str = " / ".join(f'**"{a}"**' for a in aliases) if aliases else ""
        if alias_str:
            lines.append(f'- **"{label}"** / {alias_str}: {desc}')
        else:
            lines.append(f'- **"{label}"**: {desc}')
    lines.append('- Simple price reductions with no explicit label: use "Prijsverlaging" (NL) or "Réduction de prix" (FR)')
    return "\n".join(lines)


def _build_store_brands_section(display_name: str, store_brands: list) -> str:
    lines = [
        f"## {display_name.upper()} STORE BRANDS\n"
        f"These are {display_name}'s house brands — include the brand name in display_name:"
    ]
    for b in store_brands:
        lines.append(f'- **{b["name"].title()}**: {b.get("description", "")}')
    lines.append(
        "\nAll other recognized brands are national/premium brands."
    )
    return "\n".join(lines)


def _build_extraction_rules(config: Dict[str, Any], categories_list: str) -> str:
    # Price calculation table (escape hatch)
    price_table = config.get("price_calculation_table") or ""
    if price_table:
        price_table = f"\n{price_table}"

    return f"""## EXTRACTION RULES

### COVERAGE GOAL — READ THIS FIRST
Extract EVERY product that has ANY promotional offer, deal, or reduced price on the page.
- Coverage is the top priority: extract ALL promo items on the page.
- If only one price is visible (no original_price), set original_price = promo_price.
- If the promo mechanism is unclear, use "Promo" as display_mechanism.
- DO extract fresh produce, butcher/deli items, and store-brand items — these are promos too.
- ONLY skip purely decorative elements, recipes, or store information that are clearly NOT product offers.

### For Each Promotional Item Extract:

1. **display_name**: Clean, human-readable product label for the consumer app.
   - Title Case (capitalize first letter of each significant word)
   - Format: "[Product Type] [Variant/Flavour] [Size Info]"
   - The brand is extracted separately in the display_brand field, so OMIT the brand from
     display_name when the product is still clearly identifiable without it.
   - However, KEEP the brand in display_name when it is essential to identify the product
     (e.g., "Coca-Cola Zero" makes no sense as just "Zero", "Jupiler Pils" is too generic as just "Pils").
   - ALWAYS include size/quantity info when visible (e.g., "4 x 125 g" not just "125 g")
   - For drinks (beer, soda, wine, water, juice): volume is CRITICAL — always include it
     (e.g., "33 cl", "50 cl", "1,5 L", "6 x 25 cl"). If a can/bottle ("blik"/"fles") is shown
     but no explicit volume, infer from the unit price or context on the page.
   - Include variant/flavour if applicable
   - Do NOT include promo text, pricing, or mechanism info
   - Examples (brand omitted — shown separately):
     - "Yoghurt Appel-Kaneel 4 x 115 g" (brand "Oikos" shown separately)
     - "Chips Explosions Salt & Pepper 150 g" (brand "Croky" shown separately)
     - "Serranoham Reserva 200 g" (brand "Boni Selection" shown separately)
   - Examples (brand kept — essential for identity):
     - "Coca-Cola Zero 1,5 L" (just "Zero 1,5 L" is meaningless)
     - "Jupiler Pils 24 x 25 cl" (just "Pils 24 x 25 cl" is too generic)

2. **original_price**: Regular price before promo (float, comma→dot).
   If not visible, set equal to promo_price. Round to 2 decimal places.{price_table}

3. **promo_price**: Price of ONE item/pack as shown on the shelf (float, comma→dot). REQUIRED.
   - For simple discounts (-25%, -30%): original_price × (1 − discount percentage)
   - For ANY "X+Y gratis" deal (1+1, 2+1, 3+1, 3+3, 4+1, 8+4, 12+6, etc.): promo_price = original_price. NEVER divide or average — the deal's value goes in savings_amount, not here.
   - For "2e aan halve prijs": price of one item at full price (same as original_price)
   - For "X voor €Y": €Y ÷ X
   - Round to 2 decimal places
   - The deal's value is communicated via savings_amount and display_savings_label, NOT by manipulating promo_price.

4. **savings_amount**: Total euro savings when completing the deal. REQUIRED.
   - "1+1 gratis" @ €3.00: savings = 3.00 (one free item worth €3)
   - "2+1 gratis" @ €3.00: savings = 3.00 (one free item worth €3)
   - "2e aan halve prijs" @ €3.00: savings = 1.50 (half off second item)
   - "-25%" on a single item @ €4.00: savings = 1.00 (€4 × 0.25)
   - "-25% vanaf 2 verpakkingen" @ €4.00: savings = 2.00 (€4 × 0.25 × 2 items)
   - "-20% vanaf 3 verpakkingen" @ €2.00: savings = 1.20 (€2 × 0.20 × 3 items)
   - "12+6 gratis" @ €2.33: savings = 13.98 (6 free items × €2.33)
   - "€0.50 korting": savings = 0.50
   - Round to 2 decimal places

5. **display_mechanism**: Standardized promo label. REQUIRED.
   - Title case for words, keep numbers/symbols as-is
   - If no explicit promo label is shown, use "Prijsverlaging"
   - **CRITICAL**: For percentage discounts that require buying multiple items, ALWAYS include
     the condition: "-25% Vanaf 2 Verpakkingen", NOT just "-25%". Use the correct unit
     (Verpakkingen, Flessen, Blikken, Bokalen, Bakken, Producten) and quantity.
     Only use a bare "-25%" if the discount applies to a SINGLE item with no minimum purchase.
   - Examples: "1+1 Gratis", "-25%", "2e aan Halve Prijs", "2+1 Gratis",
     "-25% Vanaf 2 Verpakkingen", "-20% Vanaf 3 Flessen", "-30% Vanaf 12 Blikken",
     "Prijsverlaging", "3+3 Gratis", "12+6 Gratis"

6. **display_description**: Plain-language Dutch explanation of the deal (~80 chars max). REQUIRED.
   - Explain what the shopper needs to DO and what they GET
   - Must be understandable without seeing the folder
   - Examples:
     - "Koop 2 en krijg de 3e gratis"
     - "Nu €0.80 goedkoper per stuk"
     - "Alle Croky chips met 25% korting"
     - "Coca-Cola flessen: koop 12, krijg 6 gratis"

7. **display_savings_label**: Human-friendly savings text. REQUIRED.
   - When exact euro savings are known: "Bespaar €X.XX"
   - For multi-buy free items: "1 Gratis Item", "6 Gratis Items"
   - For percentage discounts: "Tot -25% Korting"
   - For second-item deals: "2e aan Halve Prijs"
   - Examples: "Bespaar €3.00", "1 Gratis Item", "Tot -25% Korting", "2e aan Halve Prijs"

8. **Pack size extraction** (pack_size_value, pack_size_unit, pack_count): REQUIRED when any size info is visible.
   Read the size tokens EXACTLY as printed on the page. Do NOT compute, divide, or convert units —
   Python computes the POST-PROMO effective €/unit from these fields + pricing + min_purchase_qty + savings_amount.
   - "500 g"               → value=500,  unit="g",       count=1
   - "1,5 L"               → value=1.5,  unit="l",       count=1
   - "33 cl"               → value=33,   unit="cl",      count=1
   - "6 x 25 cl"           → value=25,   unit="cl",      count=6
   - "24 blikjes 33 cl"    → value=33,   unit="cl",      count=24
   - "Box 12 capsules"     → value=12,   unit="capsule", count=1
   - "10 zakjes thee"      → value=10,   unit="zakje",   count=1
   - "40 tabs"             → value=40,   unit="tab",     count=1
   - "80 doekjes"          → value=80,   unit="doekje",  count=1
   - "Pot 250 g"           → value=250,  unit="g",       count=1
   - "12 rollen"           → value=12,   unit="rol",     count=1
   - "4-pack toiletpapier 6 rollen" → value=6, unit="rol", count=4
   - "3-pack ijsjes"       → value=3,    unit="stuk",    count=1
   - If ONLY a count is visible with no explicit unit (e.g., "3-pack"): use unit="stuk".
   - If NOTHING visible: leave all three null/default. Do NOT guess 75cl (wine) or 33cl (beer blik) —
     Python applies those canonical fallbacks when appropriate.
   - **SPECIAL CASE — APPROXIMATE WEIGHT ('±', 'ongeveer', 'ca.')**:
     Items sold BY WEIGHT have approximate pack labels — butcher cuts, whole chickens, deli meats, fresh fish.
     The `promo_price` is the per-kg shelf price, NOT the price for a single pack. Return:
       pack_size_value=1, pack_size_unit="kg", pack_count=1
     Examples:
       - "Gemarineerde Varkensribbetjes ± 500 g"     → value=1, unit="kg", count=1
       - "Hele Gebraden Kip Van Weleer ± 1,2 kg"     → value=1, unit="kg", count=1
       - "Toulouserworst ± 500 g"                    → value=1, unit="kg", count=1
       - "Zalm Ongeveer 300 g"                       → value=1, unit="kg", count=1
   - Fill pack_size_reasoning with a one-line trace of which visible tokens you used.

9. **granular_category**: Assign ONE from this list. Use "Other" if nothing fits.
{categories_list}

10. **normalized_brand**: Lowercase brand/manufacturer name for matching against user purchase history.
   - Output the brand name ONLY, lowercase, no product type or variant
   - Use the EXACT same conventions as receipt brand extraction:
     - Hyphenated brands: "coca-cola" (not "coca cola"), "lay's" (keep apostrophes)
     - Multi-word store brands: "boni selection" (not just "boni" when it's Boni Selection)
     - Single-word brands: "jupiler", "danone", "heinz", "nestlé"
   - For store/house brands, use their ACTUAL brand name — NEVER use "in-house" or generic labels:
     - Colruyt house brands: "boni", "boni selection", "boni bio", "everyday", "cru", "boni plan't"
     - Delhaize house brands: "365", "delhaize", "p'tits lions"
     - Carrefour house brands: "simpl", "carrefour bio", "carrefour classic"
     - Lidl house brands: "milbona", "pikok", "chef select", "deluxe", "freeway", "vemondo", "solevita", "alesto", "snack day", "combino", "trattoria alfredo", "fin carré"
     - Aldi house brands: "milsani", "moser roth", "gourmet", "cucina", "lyttos", "barissimo", "river", "sun snacks", "bon gelati", "choceur"
   - null ONLY for truly unbranded generic assortment promos (very rare in promo folders)
   - Examples:
     - "Jupiler Pils 24 x 25 cl" → normalized_brand: "jupiler"
     - "Coca-Cola Zero 1,5 L" → normalized_brand: "coca-cola"
     - "Boni Selection Serranoham Reserva 200 g" → normalized_brand: "boni selection"
     - "Milbona Volle Melk 1 L" → normalized_brand: "milbona"
     - "Croky Chips Explosions 150 g" → normalized_brand: "croky"
     - "Everyday Afwasmiddel 1 L" → normalized_brand: "everyday"

11. **display_brand**: Brand name in clean Title Case for display in the consumer app.
   - Same brand as normalized_brand, but properly capitalized
   - Examples: "Jupiler", "Coca-Cola", "Boni Selection", "Milbona", "Lay's", "365"
   - null when normalized_brand is null

### IMPORTANT RULES
- Each unique product appears ONCE — deduplicate across languages if bilingual
- **Multi-brand promos**: When a promo groups multiple brands together (e.g., "Sprite en Fanta", "Coca-Cola, Fanta of Sprite"), create a SEPARATE item for EACH brand. Each item gets its own display_name but MUST inherit shared attributes from the page: size/volume, pricing, and mechanism. Do NOT drop size info just because it appears once for the group rather than per brand."""


def _build_validation_checklist(config: Dict[str, Any]) -> str:
    checklist = config.get("validation_checklist", [])

    lines = [
        "## VALIDATION CHECKLIST",
        "Before outputting each item, verify:",
        "- display_name is Title Case, includes product + variant + size (no promo text or pricing)",
        "- Include size/volume for drinks and packaged foods when visible (e.g., '33 cl', '6 x 25 cl', '1,5 L')",
        "- At least promo_price is present and positive",
        "- All prices rounded to 2 decimal places (no 3+ decimals)",
        "- display_mechanism is clean and standardized (not raw OCR text)",
        "- display_mechanism includes 'Vanaf X ...' when the discount requires buying multiple items",
        "- pack_size_value/pack_size_unit/pack_count extracted verbatim from visible size tokens (no conversion)",
        "- granular_category is from the provided list",
        "- If multiple brands share a promo, split into separate items",
        "- normalized_brand is lowercase, matches the brand visible on the page (NEVER 'in-house')",
        "- display_brand is Title Case version of normalized_brand",
    ]
    for item in checklist:
        lines.append(f"- {item}")
    return "\n".join(lines)
