"""Gemini Vision classifier for promo folder cover images.

Uses gemini-2.0-flash to determine if a folder cover image
represents a food/grocery promotional folder.
"""

import logging
import os

from google import genai
from google.genai import types

logger = logging.getLogger(__name__)

CLASSIFICATION_MODEL = "gemini-2.0-flash"

CLASSIFICATION_PROMPT = """You are classifying supermarket promotional folders (flyers).

Given this cover image of a promotional folder from {retailer_name},
determine if this is a FOOD/GROCERY promotional folder.

Answer YES if:
- It shows food products, beverages, household groceries
- It's a general weekly supermarket promo folder
- It shows fresh produce, meat, dairy, bakery, cleaning products

Answer NO if:
- It's focused on electronics, appliances, or technology
- It's a garden/outdoor/DIY folder
- It's a loyalty/points program brochure
- It's a clothing/fashion folder
- It's a toy/baby specialty folder

Respond with only: YES or NO"""


def classify_folder(cover_image: bytes, retailer_name: str) -> bool:
    """Classify a folder cover image as food/grocery or not.

    Args:
        cover_image: Raw image bytes (WebP/JPEG/PNG)
        retailer_name: Display name of the retailer (e.g., "Carrefour")

    Returns:
        True if the folder is classified as food/grocery.
    """
    api_key = os.environ.get("GEMINI_API_KEY", "")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY not set")

    client = genai.Client(api_key=api_key)

    prompt = CLASSIFICATION_PROMPT.format(retailer_name=retailer_name)

    response = client.models.generate_content(
        model=CLASSIFICATION_MODEL,
        contents=[
            types.Content(
                parts=[
                    types.Part.from_bytes(data=cover_image, mime_type="image/webp"),
                    types.Part.from_text(text=prompt),
                ],
            ),
        ],
        config=types.GenerateContentConfig(
            temperature=0,
            max_output_tokens=10,
        ),
    )

    answer = response.text.strip().upper()
    is_food = answer.startswith("YES")

    logger.info(f"Classification for {retailer_name}: {answer} → {'ACCEPT' if is_food else 'REJECT'}")
    return is_food
