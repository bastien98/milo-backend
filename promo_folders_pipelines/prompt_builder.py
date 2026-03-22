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
        f"These are {display_name}'s house brands — always set is_premium=false for these:"
    ]
    for b in store_brands:
        lines.append(f'- **{b["name"].title()}**: {b.get("description", "")}')
    lines.append(
        "\nAll other recognized brands are national/premium brands (is_premium=true).\n"
        "Unbranded items (loose fruit, vegetables, bakery): normalized_brand=null, is_premium=false."
    )
    return "\n".join(lines)


def _build_extraction_rules(config: Dict[str, Any], categories_list: str) -> str:
    display_name = config["display_name"]

    # normalized_name examples
    nn_examples = config.get("normalized_name_examples", [])
    nn_example_lines = ""
    if nn_examples:
        nn_example_lines = "\n   Examples:\n" + "\n".join(
            f'     - "{ex["input"]}" → "{ex["output"]}"' for ex in nn_examples
        )

    # content examples
    content_examples = config.get("content_examples", [])
    content_example_lines = ""
    if content_examples:
        content_example_lines = "\n   Examples:\n" + "\n".join(
            f'     - "{ex["input"]}" → pack_size={ex["pack_size"]}, content_value={ex["content_value"]}, content_unit="{ex["content_unit"]}"'
            for ex in content_examples
        )

    # normalized_name guidance (escape hatch)
    nn_guidance = config.get("normalized_name_guidance") or ""
    if nn_guidance:
        nn_guidance = f"\n   {nn_guidance}"

    # price rules
    price_rules = config.get("price_rules", {})
    orig_price_rule = price_rules.get("original_price", "nullable")
    promo_price_rule = price_rules.get("promo_price", "nullable")

    orig_note = "null if not shown." if orig_price_rule == "nullable" else "MANDATORY — must always be extracted."
    promo_note = "null if only a percentage/mechanism is shown." if promo_price_rule == "nullable" else "MANDATORY — must always be extracted."

    # Price calculation table (escape hatch)
    price_table = config.get("price_calculation_table") or ""
    if price_table:
        price_table = f"\n{price_table}"

    return f"""## EXTRACTION RULES

### For Each Promotional Item Extract:

1. **original_description**: Full product text as shown in the folder.
   Include brand, product name, variant, size/weight exactly as printed.

2. **normalized_name**: Clean, generic, lowercase product name:
   - REMOVE the brand name
   - REMOVE quantities (450ml, 1L, 500g, 6x33cl, 24x25cl, etc.)
   - REMOVE packaging words (PET, Blik, Fles, Doos, Brik, etc.)
   - KEEP the product type in its original language (Dutch or French)
   - KEEP variant, flavour, sub-type: "zero", "light", "paprika", "aardbei", "bruin", "pils"
   - WRONG: including the brand → "jupiler pils" — CORRECT: "pils"
   - WRONG: removing the variant → "chips" — CORRECT: "chips paprika"
   - WRONG: including the quantity → "pils 24x25cl" — CORRECT: "pils"{nn_guidance}{nn_example_lines}

3. **normalized_brand**: Brand/manufacturer in **lowercase**.
   - null for unbranded items (loose fruit, vegetables, bakery without brand)
   - Store/house brands: use the brand name (e.g., "boni", "365", "ah basic")

4. **is_premium**: true for national/premium brands, false for house/store brands and unbranded items.

5. **packaging_type**: Container/packaging format, lowercase single word.
   - Drinks: "blik" (can), "fles" (glass bottle), "pet" (plastic bottle), "brik" (tetra pak)
   - Food: "pot" (jar), "zak" (bag), "doos" (box), "pak" (carton), "kuip" (tub), "bakje" (tray/punnet)
   - Household: "fles" (bottle), "spray", "tube", "rol" (roll)
   - null for loose/unpackaged items (fruit, vegetables, bakery)

6. **pack_size**: Multi-pack count.
   - "6x33cl" → 6, "24x25cl" → 24, single item → 1{content_example_lines}

7. **content_value**: Numeric size of ONE item.
   - "6x33cl" → 33, "500g" → 500, "1,5L" → 1.5

8. **content_unit**: Unit as printed, lowercase.
   - "cl", "ml", "l", "g", "kg"

9. **unit_info**: Raw unit string as printed in the folder.
   - "6x33cl", "500g", "1L", "per kg", "24x25cl"
   - null if not specified

10. **granular_category**: Assign ONE from this list. Use "Other" if nothing fits.
{categories_list}

11. **original_price**: Regular price before promo (float, comma→dot). {orig_note}{price_table}

12. **promo_price**: Promotional price the customer pays (float, comma→dot).
    - For "1+1 gratis": price of one item
    - For multi-buy "X voor €Y": per-unit price (€Y / X)
    - {promo_note}

13. **promo_mechanism**: Promotional label as shown in the folder. ALWAYS provide a value.
    - Examples: "1+1 gratis", "2e aan halve prijs", "-30%"
    - For simple price reductions with no explicit label: use "Prijsverlaging" (NL) or "Réduction de prix" (FR)

14. **page_number**: Page number within the current batch (1-indexed).

15. **display_name**: A clean, human-readable product label for the consumer app.
    - Title Case (capitalize first letter of each significant word)
    - Format: "[Brand] [Product Type] [Variant/Flavour] [Size Info]"
    - ALWAYS include the brand name (even for house brands like Boni, Everyday)
    - Include variant/flavour if applicable
    - Include size/unit info if available
    - Do NOT include promo text, pricing, or mechanism info
    - Examples:
      - "Oîkos Yoghurt Appel-Kaneel 4 x 115 g"
      - "Croky Chips Explosions Salt & Pepper 150 g"
      - "Coca-Cola Regular 1,5 L"
      - "Boni Selection Serranoham Reserva 200 g"
      - "Parodontax Tandpasta" (when no size info available)

16. **display_mechanism**: A clean, standardized promo label.
    - Use the mechanism as printed in the folder
    - Consistent capitalization (title case for words, keep numbers/symbols)
    - Examples: "1+1 Gratis", "-25%", "2e aan Halve Prijs", "2+1 Gratis",
      "-20% vanaf 2 Verpakkingen", "Prijsverlaging", "3+3 Gratis"

17. **display_description**: A short plain-language explanation of the deal (~80 chars max).
    - Written in the folder's language (Dutch or French)
    - Explains what the user gets in simple terms
    - Examples:
      - "Koop 2 pakken Danone yoghurt en krijg het 3e gratis"
      - "Alle Croky chips met 25% korting"
      - "Passendale kaas nu met 20% korting vanaf 1 verpakking"
      - "Coca-Cola flessen: koop 12, krijg 6 gratis"

18. **display_unit_price**: Human-readable price-per-unit string.
    - Compute from promo_price and content_value/content_unit if possible
    - Format: "€X.XX/unit" (e.g., "€0.84/L", "€12.50/kg", "€0.55/stuk")
    - null if not enough info to compute

19. **display_savings_label**: Pre-formatted savings text.
    - When exact euro savings are known: "Bespaar €X.XX"
    - When only mechanism is known: "1 Gratis Item", "2e aan Halve Prijs", "Tot -25% Korting"
    - null only if no meaningful savings description is possible

### IMPORTANT RULES
- Extract EVERY product, including small secondary items and non-food (household, personal care, pet)
- Each unique product appears ONCE — deduplicate across languages if bilingual
- Skip decorative elements, recipe suggestions, and store information
- **Multi-brand promos**: When a promo groups multiple brands together (e.g., "Sprite en Fanta", "Coca-Cola, Fanta of Sprite"), create a SEPARATE item for EACH brand. Each item gets its own normalized_brand and normalized_name. They share the same promo_mechanism and prices."""


def _build_validation_checklist(config: Dict[str, Any]) -> str:
    checklist = config.get("validation_checklist", [])

    lines = [
        "## VALIDATION CHECKLIST",
        "Before outputting each item, verify:",
        "- normalized_name does NOT contain the brand name",
        "- normalized_name DOES contain variant/flavour/sub-type if applicable",
        "- normalized_name does NOT contain quantities or packaging words",
        "- normalized_brand is lowercase (or null for unbranded)",
        "- is_premium is false for store/house brands and unbranded items",
        "- packaging_type is a single lowercase word describing the container (or null for loose items)",
        "- pack_size, content_value, content_unit are consistent (e.g., 6x33cl → 6, 33, cl)",
        "- granular_category is from the provided list",
        "- Prices use dot decimal (not comma)",
        "- normalized_brand is a SINGLE brand — if multiple brands share a promo, split into separate items",
        "- display_name is Title Case, includes brand + product + variant + size (no promo text or pricing)",
        "- display_mechanism matches the promo as printed in the folder, with consistent capitalization",
        "- display_description is a plain-language deal explanation, max ~80 characters",
        "- display_unit_price format is \"€X.XX/unit\" (or null if not computable)",
        "- display_savings_label summarizes the saving in user-friendly text (or null)",
    ]
    for item in checklist:
        lines.append(f"- {item}")
    return "\n".join(lines)
