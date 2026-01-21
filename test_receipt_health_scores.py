#!/usr/bin/env python3
"""
Integration test script for the Receipt Upload API with Health Scores.

Usage:
    python test_receipt_health_scores.py --token <your-firebase-token>

Or set the FIREBASE_TOKEN environment variable:
    export FIREBASE_TOKEN=<your-firebase-token>
    python test_receipt_health_scores.py
"""

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

try:
    import httpx
except ImportError:
    print("Please install httpx: pip install httpx")
    sys.exit(1)


API_BASE_URL = os.getenv("API_BASE_URL", "http://localhost:8000")


async def test_health():
    """Test the health endpoint."""
    async with httpx.AsyncClient() as client:
        response = await client.get(f"{API_BASE_URL}/health")
        print(f"Health check: {response.status_code}")
        return response.status_code == 200


async def upload_receipt(token: str, file_path: Path):
    """Upload a receipt and return the response."""
    async with httpx.AsyncClient(timeout=120.0) as client:
        with open(file_path, "rb") as f:
            files = {"file": (file_path.name, f, "application/pdf")}
            response = await client.post(
                f"{API_BASE_URL}/api/v1/receipts/upload",
                headers={"Authorization": f"Bearer {token}"},
                files=files,
            )
        return response


def print_receipt_results(response, file_name: str):
    """Print the receipt processing results with health scores."""
    print(f"\n{'='*60}")
    print(f"Receipt: {file_name}")
    print(f"{'='*60}")

    if response.status_code != 200:
        print(f"Error: {response.status_code}")
        print(f"Response: {response.text}")
        return

    data = response.json()

    print(f"Store: {data.get('store_name', 'Unknown')}")
    print(f"Date: {data.get('receipt_date', 'Unknown')}")
    print(f"Total: €{data.get('total_amount', 0):.2f}")
    print(f"Items Count: {data.get('items_count', 0)}")

    if data.get("warnings"):
        print(f"Warnings: {data['warnings']}")

    print(f"\n{'Items with Health Scores':^60}")
    print("-" * 60)
    print(f"{'Item Name':<30} {'Price':>8} {'Health':>8} {'Category':<15}")
    print("-" * 60)

    transactions = data.get("transactions", [])
    health_scores = []

    for item in transactions:
        health_score = item.get("health_score")
        health_display = str(health_score) if health_score is not None else "N/A"
        health_scores.append(health_score) if health_score is not None else None

        # Truncate item name if too long
        item_name = item.get("item_name", "Unknown")[:28]
        category = item.get("category", "Unknown")[:13]
        price = item.get("item_price", 0)

        print(f"{item_name:<30} €{price:>6.2f} {health_display:>8} {category:<15}")

    print("-" * 60)

    # Calculate average health score
    valid_scores = [s for s in health_scores if s is not None]
    if valid_scores:
        avg_health = sum(valid_scores) / len(valid_scores)
        print(f"\nAverage Health Score: {avg_health:.2f}/5")
        print(f"Health Score Distribution:")
        for score in range(6):
            count = valid_scores.count(score)
            if count > 0:
                bar = "█" * count
                print(f"  {score}: {bar} ({count})")
    else:
        print("\nNo health scores available (all items are non-food)")


async def run_tests(token: str, receipt_dir: str = "test-receipts"):
    """Run receipt upload tests."""
    print("=" * 60)
    print("Receipt Upload API Tests - Health Scores")
    print("=" * 60)
    print(f"API URL: {API_BASE_URL}")
    print()

    # Test health endpoint
    print("Testing health endpoint...")
    if not await test_health():
        print("Health check failed! Is the server running?")
        return

    # Find all test receipts
    receipt_path = Path(receipt_dir)
    if not receipt_path.exists():
        print(f"Error: Receipt directory '{receipt_dir}' not found")
        return

    pdf_files = list(receipt_path.rglob("*.pdf"))
    if not pdf_files:
        print(f"No PDF files found in {receipt_dir}")
        return

    print(f"\nFound {len(pdf_files)} test receipts")

    # Process each receipt
    results = []
    for pdf_file in pdf_files:
        print(f"\nProcessing: {pdf_file.name}...")
        response = await upload_receipt(token, pdf_file)
        print_receipt_results(response, pdf_file.name)

        if response.status_code == 200:
            results.append(response.json())

    # Summary
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)

    total_items = sum(r.get("items_count", 0) for r in results)
    all_transactions = []
    for r in results:
        all_transactions.extend(r.get("transactions", []))

    all_health_scores = [
        t.get("health_score")
        for t in all_transactions
        if t.get("health_score") is not None
    ]

    print(f"Total Receipts Processed: {len(results)}")
    print(f"Total Items Extracted: {total_items}")
    print(f"Items with Health Scores: {len(all_health_scores)}")

    if all_health_scores:
        avg = sum(all_health_scores) / len(all_health_scores)
        print(f"Overall Average Health Score: {avg:.2f}/5")

    print("\n" + "=" * 60)
    print("Tests completed!")
    print("=" * 60)


def main():
    parser = argparse.ArgumentParser(
        description="Test the Receipt Upload API with Health Scores"
    )
    parser.add_argument(
        "--token",
        help="Firebase ID token for authentication",
        default=os.getenv("FIREBASE_TOKEN"),
    )
    parser.add_argument(
        "--url",
        help="API base URL",
        default=os.getenv("API_BASE_URL", "http://localhost:8000"),
    )
    parser.add_argument(
        "--receipts",
        help="Path to test receipts directory",
        default="test-receipts",
    )
    args = parser.parse_args()

    if not args.token:
        print("Error: Firebase token is required.")
        print("Provide it via --token argument or FIREBASE_TOKEN environment variable.")
        print()
        print("To get a Firebase token:")
        print("1. Sign in to your app")
        print("2. Call: firebase.auth().currentUser.getIdToken()")
        print("3. Use the returned token")
        sys.exit(1)

    global API_BASE_URL
    API_BASE_URL = args.url

    asyncio.run(run_tests(args.token, args.receipts))


if __name__ == "__main__":
    main()
