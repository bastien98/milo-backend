"""
Colruyt Promo Folder Extractor
Extracts product offers from PDF using OpenAI GPT-4o and stores in Pinecone.
"""

import os
import json
import hashlib
import base64
from datetime import datetime
from typing import List, Dict
from pathlib import Path

from openai import OpenAI
from pinecone import Pinecone
import fitz  # PyMuPDF for PDF to image conversion

from categories import CATEGORY_PROMPT_SECTION

# ============================================
# CONFIGURATION
# ============================================

PINECONE_API_KEY = "pcsk_7P1u4N_NUgCS8Y5TaZ9oxKmAyNmK3hVy922MoixfYnK9jCBwYTf7X3HEkVZttTV134y1tz"
PINECONE_INDEX_NAME = "promos"

OPENAI_API_KEY = "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"

# Models
OPENAI_MODEL = "gpt-4o"  # Best current OpenAI model
EMBEDDING_MODEL = "llama-text-embed-v2"  # Pinecone's embedding model

# System prompt for extraction
SYSTEM_PROMPT = """Role: You are an expert data extraction assistant specializing in retail documents and OCR analysis.

Task: Analyze the provided images from a supermarket promotional folder and extract every product offer into a structured JSON format.

Extraction Rules:
1. Identify Each Product: Distinct items often have their own image and price block.
2. Colruyt Specifics:
   - Volume Discounts: Capture "vanaf X verpakkingen" (from X packs) or "vanaf X flessen".
   - XTRA: Set the `is_xtra_exclusive` flag to true if the discount requires the "XTRA" loyalty card.
   - Calculated Prices: If the folder shows a calculation (e.g., "11.98 8.99/2 packs"), extract the final price paid for the bundle.
   - Free Products: Identify "1+1 gratis" or "2+1 gratis".

Output Format:
You must return a single valid JSON object containing a list of offers. Do not include markdown formatting (like ```json), intro text, or outro text. Output ONLY the raw JSON string.

JSON Schema:
The root object must have a key "offers" which is a list of objects. Each object must have the following fields:
- "brand": (String) The brand name. If unknown, use null.
- "description": (String) Full product name and variant.
- "volume_weight": (String) e.g., "1.5L", "500g".
- "category": (String) Product category. Must be exactly one of these values:
""" + CATEGORY_PROMPT_SECTION + """
- "price_standard": (Float) The single unit price before discount. If not visible, use null.
- "promo_type": (String) e.g., "percentage_off", "volume_discount", "bogo" (buy-one-get-one).
- "promo_description": (String) The text describing the deal, e.g., "-25% from 3 bottles".
- "condition_qty": (Integer) The minimum quantity required for the deal (e.g., 2 for "Buy 2"). Default to 1.
- "is_xtra_exclusive": (Boolean) True if XTRA card is required, else False.
- "price_promo_final": (Float) The final price listed for the deal (bundle total or reduced unit price).

Handling Missing Data:
- For missing string fields, use null.
- For missing numeric fields, use null."""


def pdf_to_images(pdf_path: str) -> List[str]:
    """
    Convert PDF pages to base64-encoded images.

    Args:
        pdf_path: Path to the PDF file

    Returns:
        List of base64-encoded PNG images
    """
    print(f"📄 Converting PDF to images...")

    doc = fitz.open(pdf_path)
    images = []

    for page_num in range(len(doc)):
        page = doc[page_num]
        # Render at 2x resolution for better OCR
        mat = fitz.Matrix(2, 2)
        pix = page.get_pixmap(matrix=mat)
        img_bytes = pix.tobytes("png")
        img_base64 = base64.b64encode(img_bytes).decode('utf-8')
        images.append(img_base64)
        print(f"   Page {page_num + 1}/{len(doc)} converted")

    doc.close()
    print(f"   ✅ Converted {len(images)} pages")
    return images


def extract_promos_from_pdf(pdf_path: str, batch_size: int = 4) -> Dict:
    """
    Extract promotional offers from a PDF using OpenAI GPT-4o.
    Processes pages in batches to avoid timeouts.

    Args:
        pdf_path: Path to the Colruyt promo folder PDF
        batch_size: Number of pages to process per API call

    Returns:
        Dictionary containing extracted offers
    """
    print(f"📄 Processing PDF: {pdf_path}")

    # Convert PDF to images
    images = pdf_to_images(pdf_path)

    # Initialize OpenAI client with extended timeout
    client = OpenAI(api_key=OPENAI_API_KEY, timeout=180.0)  # 3 minutes per batch

    print(f"🤖 Extracting offers with {OPENAI_MODEL} in batches of {batch_size} pages...")

    all_offers = []
    total_batches = (len(images) + batch_size - 1) // batch_size

    for batch_num in range(total_batches):
        start_idx = batch_num * batch_size
        end_idx = min(start_idx + batch_size, len(images))
        batch_images = images[start_idx:end_idx]

        print(f"   Processing batch {batch_num + 1}/{total_batches} (pages {start_idx + 1}-{end_idx})...")

        # Build message content with images
        content = [{"type": "text", "text": f"Please analyze these promotional folder pages ({start_idx + 1}-{end_idx}) and extract all product offers:"}]

        for img_base64 in batch_images:
            content.append({
                "type": "image_url",
                "image_url": {
                    "url": f"data:image/png;base64,{img_base64}",
                    "detail": "high"
                }
            })

        # Call OpenAI API
        try:
            response = client.chat.completions.create(
                model=OPENAI_MODEL,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": content}
                ],
                max_tokens=8192,
                temperature=0.1
            )

            # Parse the JSON response
            response_text = response.choices[0].message.content.strip()

            # Remove markdown code blocks if present
            if response_text.startswith("```"):
                lines = response_text.split("\n")
                response_text = "\n".join(lines[1:-1]).strip()

            batch_result = json.loads(response_text)
            batch_offers = batch_result.get("offers", [])
            all_offers.extend(batch_offers)
            print(f"   ✅ Batch {batch_num + 1}: extracted {len(batch_offers)} offers")

        except json.JSONDecodeError as e:
            print(f"   ⚠️ Batch {batch_num + 1}: Failed to parse JSON: {e}")
        except Exception as e:
            print(f"   ⚠️ Batch {batch_num + 1}: Error: {e}")

    print(f"   ✅ Total: extracted {len(all_offers)} offers from {len(images)} pages")
    return {"offers": all_offers}


def create_embedding_text(offer: Dict) -> str:
    """
    Create a text representation of an offer for embedding.
    Only includes searchable terms (brand, product, category).
    All other data is stored as metadata for filtering/display.
    """
    parts = []

    if offer.get("brand"):
        parts.append(offer["brand"])
    if offer.get("description"):
        parts.append(offer["description"])
    if offer.get("category"):
        parts.append(offer["category"])

    return " ".join(parts)


def generate_offer_id(offer: Dict, source: str) -> str:
    """
    Generate a unique ID for an offer based on its content.
    """
    unique_string = f"{source}_{offer.get('brand', '')}_{offer.get('description', '')}_{offer.get('price_promo_final', '')}"
    return hashlib.md5(unique_string.encode()).hexdigest()


def store_in_pinecone(offers: List[Dict], source: str = "colruyt") -> int:
    """
    Store extracted offers in Pinecone vector database using llama-text-embed-v2.

    Args:
        offers: List of offer dictionaries
        source: Source identifier (e.g., "colruyt")

    Returns:
        Number of vectors upserted
    """
    print(f"🗄️ Connecting to Pinecone...")

    # Initialize Pinecone
    pc = Pinecone(api_key=PINECONE_API_KEY)

    # Get the index
    index = pc.Index(PINECONE_INDEX_NAME)
    print(f"   ✅ Connected to index: {PINECONE_INDEX_NAME}")

    print(f"📊 Generating embeddings with {EMBEDDING_MODEL} for {len(offers)} offers...")

    # Prepare texts for batch embedding
    texts_to_embed = []
    offer_data = []

    for offer in offers:
        embedding_text = create_embedding_text(offer)
        texts_to_embed.append(embedding_text)
        offer_data.append({
            "offer": offer,
            "text": embedding_text,
            "id": generate_offer_id(offer, source)
        })

    # Generate embeddings using Pinecone's inference API (llama-text-embed-v2)
    # Batch embeddings - llama-text-embed-v2 has a limit of 96 inputs per request
    print(f"   Generating embeddings...")
    embedding_batch_size = 96
    embeddings_response = []

    for i in range(0, len(texts_to_embed), embedding_batch_size):
        batch_texts = texts_to_embed[i:i + embedding_batch_size]
        print(f"   Embedding batch {i // embedding_batch_size + 1}/{(len(texts_to_embed) + embedding_batch_size - 1) // embedding_batch_size}...")
        batch_embeddings = pc.inference.embed(
            model=EMBEDDING_MODEL,
            inputs=batch_texts,
            parameters={"input_type": "passage"}
        )
        embeddings_response.extend(batch_embeddings)

    # Prepare vectors for upsert
    vectors_to_upsert = []

    for i, (data, embedding) in enumerate(zip(offer_data, embeddings_response)):
        offer = data["offer"]

        # Prepare metadata
        metadata = {
            "source": source,
            "brand": offer.get("brand") or "",
            "description": offer.get("description") or "",
            "volume_weight": offer.get("volume_weight") or "",
            "category": offer.get("category") or "Other",
            "subcategory": offer.get("subcategory") or "",
            "price_standard": float(offer.get("price_standard") or 0),
            "promo_type": offer.get("promo_type") or "",
            "promo_description": offer.get("promo_description") or "",
            "condition_qty": int(offer.get("condition_qty") or 1),
            "is_xtra_exclusive": bool(offer.get("is_xtra_exclusive")),
            "price_promo_final": float(offer.get("price_promo_final") or 0),
            "extracted_at": datetime.now().isoformat(),
            "embedding_text": data["text"],
        }

        vectors_to_upsert.append({
            "id": data["id"],
            "values": embedding["values"],
            "metadata": metadata
        })

        if (i + 1) % 10 == 0:
            print(f"   Processed {i + 1}/{len(offers)} embeddings...")

    # Upsert to Pinecone in batches
    print(f"⬆️ Upserting {len(vectors_to_upsert)} vectors to Pinecone...")

    batch_size = 100
    for i in range(0, len(vectors_to_upsert), batch_size):
        batch = vectors_to_upsert[i:i + batch_size]
        index.upsert(vectors=batch)
        print(f"   Upserted batch {i // batch_size + 1}")

    print(f"   ✅ Successfully stored {len(vectors_to_upsert)} offers in Pinecone")

    return len(vectors_to_upsert)


def search_promos(query: str, top_k: int = 10) -> List[Dict]:
    """
    Search for promotions using semantic search with llama-text-embed-v2.

    Args:
        query: Search query (e.g., "cheap beer", "pasta discount")
        top_k: Number of results to return

    Returns:
        List of matching offers with scores
    """
    print(f"🔍 Searching for: '{query}'")

    # Initialize Pinecone
    pc = Pinecone(api_key=PINECONE_API_KEY)
    index = pc.Index(PINECONE_INDEX_NAME)

    # Generate query embedding using Pinecone inference
    query_embedding = pc.inference.embed(
        model=EMBEDDING_MODEL,
        inputs=[query],
        parameters={"input_type": "query"}
    )

    # Search Pinecone
    results = index.query(
        vector=query_embedding[0]["values"],
        top_k=top_k,
        include_metadata=True
    )

    # Format results
    matches = []
    for match in results.matches:
        matches.append({
            "score": match.score,
            "brand": match.metadata.get("brand"),
            "description": match.metadata.get("description"),
            "promo_description": match.metadata.get("promo_description"),
            "price_promo_final": match.metadata.get("price_promo_final"),
            "source": match.metadata.get("source"),
        })

    return matches


# ============================================
# USER PREFERENCE MATCHING
# ============================================

CATEGORY_EXTRACTION_PROMPT = """You are a product categorization expert for Belgian supermarkets. Given a list of product names (possibly with OCR errors), extract the categories and clean product names.

For each product, determine:
1. The cleaned/corrected product name
2. The category - must be exactly one of these values:
""" + CATEGORY_PROMPT_SECTION + """

Return a JSON object with:
- "products": list of {"original": str, "cleaned": str, "category": str}
- "categories": list of unique categories found

Output ONLY valid JSON, no markdown formatting."""


def extract_categories_from_preferences(preferences: List[str]) -> Dict:
    """
    Use LLM to extract and clean categories from user preferences.

    Args:
        preferences: List of product names from user purchase history

    Returns:
        Dictionary with cleaned products and extracted categories
    """
    client = OpenAI(api_key=OPENAI_API_KEY)

    response = client.chat.completions.create(
        model=OPENAI_MODEL,
        messages=[
            {"role": "system", "content": CATEGORY_EXTRACTION_PROMPT},
            {"role": "user", "content": f"Categorize these products:\n{json.dumps(preferences, ensure_ascii=False)}"}
        ],
        max_tokens=4096,
        temperature=0.1
    )

    response_text = response.choices[0].message.content.strip()

    # Remove markdown if present
    if response_text.startswith("```"):
        lines = response_text.split("\n")
        response_text = "\n".join(lines[1:-1]).strip()

    try:
        return json.loads(response_text)
    except json.JSONDecodeError:
        return {"products": [], "categories": [], "subcategories": []}


def search_promos_for_user(
    preferences: List[str],
    top_k_per_preference: int = 3,
    top_k_total: int = 20
) -> List[Dict]:
    """
    Search for promotions matching a user's preferences using hybrid search.

    Args:
        preferences: List of product names from user purchase history
        top_k_per_preference: Number of results per preference query
        top_k_total: Maximum total results to return

    Returns:
        List of matching offers ranked by relevance
    """
    print(f"🔍 Finding promos for {len(preferences)} user preferences...")

    # Step 1: Extract categories from preferences
    print("   Extracting categories from preferences...")
    category_info = extract_categories_from_preferences(preferences)

    categories = category_info.get("categories", [])
    cleaned_products = category_info.get("products", [])

    print(f"   Found categories: {categories}")

    # Step 2: Initialize Pinecone
    pc = Pinecone(api_key=PINECONE_API_KEY)
    index = pc.Index(PINECONE_INDEX_NAME)

    # Step 3: Search for each cleaned preference with category filter
    all_results = []
    seen_ids = set()

    for product in cleaned_products:
        query_text = product.get("cleaned", product.get("original", ""))
        category = product.get("category")

        if not query_text:
            continue

        # Generate query embedding
        query_embedding = pc.inference.embed(
            model=EMBEDDING_MODEL,
            inputs=[query_text],
            parameters={"input_type": "query"}
        )

        # Build filter - search within the product's category
        filter_dict = None
        if category and category != "Other":
            filter_dict = {"category": {"$eq": category}}

        # Query Pinecone
        results = index.query(
            vector=query_embedding[0]["values"],
            top_k=top_k_per_preference,
            filter=filter_dict,
            include_metadata=True
        )

        # Add results with source preference info
        for match in results.matches:
            if match.id not in seen_ids:
                seen_ids.add(match.id)
                all_results.append({
                    "id": match.id,
                    "score": match.score,
                    "matched_preference": product.get("original"),
                    "brand": match.metadata.get("brand"),
                    "description": match.metadata.get("description"),
                    "category": match.metadata.get("category"),
                    "subcategory": match.metadata.get("subcategory"),
                    "promo_description": match.metadata.get("promo_description"),
                    "price_promo_final": match.metadata.get("price_promo_final"),
                    "price_standard": match.metadata.get("price_standard"),
                    "is_xtra_exclusive": match.metadata.get("is_xtra_exclusive"),
                    "source": match.metadata.get("source"),
                })

    # Step 4: Sort by score and limit results
    all_results.sort(key=lambda x: x["score"], reverse=True)
    final_results = all_results[:top_k_total]

    print(f"   ✅ Found {len(final_results)} matching promotions")

    return final_results


def process_colruyt_folder(pdf_path: str) -> Dict:
    """
    Main function to process a Colruyt promo folder.

    Args:
        pdf_path: Path to the PDF file

    Returns:
        Summary of processing
    """
    print("=" * 50)
    print("🛒 COLRUYT PROMO FOLDER PROCESSOR")
    print(f"   Extraction: {OPENAI_MODEL}")
    print(f"   Embeddings: {EMBEDDING_MODEL}")
    print("=" * 50)

    # Step 1: Extract offers from PDF
    extraction_result = extract_promos_from_pdf(pdf_path)

    if "error" in extraction_result:
        return {
            "success": False,
            "error": extraction_result["error"],
            "offers_extracted": 0,
            "offers_stored": 0
        }

    offers = extraction_result.get("offers", [])

    if not offers:
        print("⚠️ No offers extracted from PDF")
        return {
            "success": False,
            "error": "No offers found in PDF",
            "offers_extracted": 0,
            "offers_stored": 0
        }

    # Step 2: Store in Pinecone
    stored_count = store_in_pinecone(offers, source="colruyt")

    # Save extracted JSON for reference
    output_json_path = pdf_path.replace(".pdf", "_extracted.json")
    with open(output_json_path, "w", encoding="utf-8") as f:
        json.dump(extraction_result, f, indent=2, ensure_ascii=False)
    print(f"💾 Saved extracted data to: {output_json_path}")

    print("\n" + "=" * 50)
    print("✅ PROCESSING COMPLETE")
    print(f"   Offers extracted: {len(offers)}")
    print(f"   Offers stored in Pinecone: {stored_count}")
    print("=" * 50)

    return {
        "success": True,
        "offers_extracted": len(offers),
        "offers_stored": stored_count,
        "output_file": output_json_path
    }


# ============================================
# CLI INTERFACE
# ============================================

if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage:")
        print("  Extract:     python extract_colruyt_promos.py <pdf_path>")
        print("  Search:      python extract_colruyt_promos.py --search 'your query'")
        print("  User prefs:  python extract_colruyt_promos.py --user-prefs 'product1' 'product2' ...")
        print("")
        print("Examples:")
        print("  python extract_colruyt_promos.py colruyt_promo_folder.pdf")
        print("  python extract_colruyt_promos.py --search 'bier korting'")
        print("  python extract_colruyt_promos.py --user-prefs 'Monster Zero Sugar' 'Pringles Hot & Spicy'")
        sys.exit(1)

    if sys.argv[1] == "--search":
        if len(sys.argv) < 3:
            print("Please provide a search query")
            sys.exit(1)

        query = " ".join(sys.argv[2:])
        results = search_promos(query)

        print(f"\n🔍 Search results for '{query}':\n")
        for i, result in enumerate(results, 1):
            print(f"{i}. [{result['score']:.3f}] {result['brand']} - {result['description']}")
            print(f"   Deal: {result['promo_description']}")
            print(f"   Price: €{result['price_promo_final']}")
            print()

    elif sys.argv[1] == "--user-prefs":
        if len(sys.argv) < 3:
            print("Please provide at least one product preference")
            sys.exit(1)

        preferences = sys.argv[2:]
        results = search_promos_for_user(preferences)

        print(f"\n🎯 Personalized promotions based on your preferences:\n")
        for i, result in enumerate(results, 1):
            print(f"{i}. [{result['score']:.3f}] {result['brand']} - {result['description']}")
            print(f"   Category: {result['category']} / {result['subcategory']}")
            print(f"   Deal: {result['promo_description']}")
            print(f"   Price: €{result['price_promo_final']}")
            if result.get('is_xtra_exclusive'):
                print(f"   ⭐ XTRA exclusive")
            print(f"   Matched: '{result['matched_preference']}'")
            print()

    else:
        pdf_path = sys.argv[1]

        if not os.path.exists(pdf_path):
            print(f"❌ File not found: {pdf_path}")
            sys.exit(1)

        result = process_colruyt_folder(pdf_path)

        if not result["success"]:
            print(f"❌ Processing failed: {result.get('error')}")
            sys.exit(1)
