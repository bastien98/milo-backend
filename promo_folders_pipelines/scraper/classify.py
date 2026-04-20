"""Classify promo-folder cover images: is this a food/grocery supermarket flyer?

Single responsibility: given the cover thumbnail + retailer name, answer yes or no.
All additional logic (shortcuts, max_folders caps, fail-open behaviour) lives in
`select_food_folders` so the classifier itself stays trivial and testable.
"""

from __future__ import annotations

import logging
import os
import time
from typing import Iterable

from google import genai
from google.genai import types

from promo_folders_pipelines.scraper.scrape import FolderInfo, download_cover_image

logger = logging.getLogger(__name__)

CLASSIFICATION_MODEL = "gemini-2.0-flash"
RETRY_BACKOFFS = (5, 15, 30)  # seconds; len = number of retries after the first attempt

CLASSIFICATION_PROMPT = """Look at this cover image of a promotional folder from {retailer_name}.

Is this folder primarily about FOOD and GROCERIES — the kind of products a Belgian supermarket shopper buys for eating, drinking, cooking, or basic household care?

Answer YES when the cover advertises any of:
- Fresh or packaged food, beverages, produce, meat, fish, dairy, bakery, pantry staples
- Household essentials sold alongside groceries (cleaning, personal care, baby, pet food)
- A general weekly supermarket flyer covering many categories

Answer NO when the cover is primarily about:
- Electronics, appliances, or technology
- Garden, outdoor, or DIY products
- Fashion, clothing, or toys
- A loyalty / rewards / points brochure with no grocery pricing

Respond with only the single word YES or NO."""


class ClassificationUnavailable(RuntimeError):
    """Raised when the classifier cannot produce a decision (rate-limited, model down, etc.)."""


def is_grocery_folder(cover_image: bytes, retailer_name: str) -> bool:
    """Return True iff Gemini classifies this cover as a food/grocery folder.

    Retries transient errors (429 / 5xx / deadlines) with simple backoff.
    Raises `ClassificationUnavailable` when every attempt fails so the caller
    can pick a fallback strategy.
    """
    api_key = os.environ.get("GEMINI_API_KEY", "")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY not set")

    client = genai.Client(api_key=api_key)
    prompt = CLASSIFICATION_PROMPT.format(retailer_name=retailer_name)

    attempts = 1 + len(RETRY_BACKOFFS)
    last_error: Exception | None = None

    for attempt in range(attempts):
        try:
            response = client.models.generate_content(
                model=CLASSIFICATION_MODEL,
                contents=[
                    types.Content(parts=[
                        types.Part.from_bytes(data=cover_image, mime_type="image/webp"),
                        types.Part.from_text(text=prompt),
                    ])
                ],
                config=types.GenerateContentConfig(temperature=0, max_output_tokens=4),
            )
            answer = (response.text or "").strip().upper()
            decision = answer.startswith("YES")
            logger.info(
                f"Classification for {retailer_name}: {answer or '<empty>'} "
                f"→ {'ACCEPT' if decision else 'REJECT'}"
            )
            return decision

        except Exception as e:  # noqa: BLE001 — network/model errors are opaque
            last_error = e
            is_last = attempt == attempts - 1
            if not _is_transient(e) or is_last:
                break
            wait = RETRY_BACKOFFS[attempt]
            logger.warning(
                f"Classifier transient error for {retailer_name} "
                f"(attempt {attempt + 1}/{attempts}): {e}; retrying in {wait}s"
            )
            time.sleep(wait)

    raise ClassificationUnavailable(
        f"Classifier failed after {attempts} attempts: {last_error}"
    ) from last_error


def _is_transient(exc: Exception) -> bool:
    """Crude but sufficient check: 429, 5xx, deadline-exceeded, and service-unavailable
    errors are worth retrying; authentication/schema errors are not."""
    msg = str(exc).upper()
    return any(
        token in msg
        for token in ("429", "RESOURCE_EXHAUSTED", "500", "503", "504", "DEADLINE", "UNAVAILABLE")
    )


def select_food_folders(
    folders: Iterable[FolderInfo],
    max_folders: int,
    retailer_name: str,
) -> list[FolderInfo]:
    """Return up to `max_folders` folders that look like food/grocery flyers.

    Rules (kept deliberately simple):
      1. Zero folders in → zero folders out.
      2. Exactly one folder → accept without classification (no real choice to make).
      3. Multiple folders → classify each cover:
           • explicit YES → accept.
           • explicit NO  → drop.
           • classifier unavailable (rate limit, service error) → accept as fallback.
             A scheduled cron dropping real folders because of a transient 429 is
             worse than occasionally ingesting a borderline folder. Downstream
             extraction will still run; non-grocery items will just be sparse.
         Stop once `max_folders` accepted.
    """
    folders = list(folders)

    if not folders:
        return []

    if len(folders) == 1:
        logger.info("Single folder — accepting without classification")
        return folders[:max_folders]

    selected: list[FolderInfo] = []
    accepted_reason: list[str] = []

    for folder in folders:
        if len(selected) >= max_folders:
            break

        try:
            cover = download_cover_image(folder)
        except Exception as e:
            logger.warning(f"Cover download failed for {folder.uuid}: {e}; skipping")
            continue

        try:
            if is_grocery_folder(cover, retailer_name):
                selected.append(folder)
                accepted_reason.append("classified YES")
            else:
                logger.info(f"Rejecting {folder.uuid} ({folder.name!r}): classifier said NO")
        except ClassificationUnavailable as e:
            logger.warning(
                f"Classifier unavailable for {folder.uuid} ({folder.name!r}): {e}. "
                "Accepting as fail-open fallback."
            )
            selected.append(folder)
            accepted_reason.append("fail-open")

    breakdown = ", ".join(f"{r}: {accepted_reason.count(r)}" for r in set(accepted_reason)) or "none"
    logger.info(
        f"Selected {len(selected)}/{len(folders)} folder(s) for {retailer_name} "
        f"(max={max_folders}; {breakdown})"
    )
    return selected


# ---- Legacy alias (kept for anything that imports the old name) ----
classify_folder = is_grocery_folder
