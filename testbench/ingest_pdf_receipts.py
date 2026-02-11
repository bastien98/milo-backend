#!/usr/bin/env python3
"""
PDF Receipt Ingestion Script
Uploads PDF receipt files to the Scandelicious backend API.
Profile enrichment happens automatically after each successful upload.
"""

import os
import sys
import argparse
import requests
from pathlib import Path
from typing import Optional


# Default API endpoints
API_URLS = {
    "prod": "https://scandalicious-api-production.up.railway.app",
    "non-prod": "https://scandalicious-api-non-prod.up.railway.app",
    "local": "http://localhost:8000",
}


def get_firebase_token() -> str:
    """
    Prompt for Firebase ID token or read from environment.

    To get your Firebase token:
    1. Open the iOS app and log in
    2. In Xcode debugger or app logs, look for the Firebase ID token
    3. Or use Firebase Auth REST API to get a token
    """
    token = os.environ.get("FIREBASE_ID_TOKEN")
    if token:
        print("Using Firebase token from FIREBASE_ID_TOKEN environment variable")
        return token

    print("\n--- Firebase Authentication ---")
    print("To get your Firebase ID token:")
    print("  1. Log into the iOS app")
    print("  2. Find the token in Xcode console/debugger")
    print("  3. Or use: firebase auth:export --format=json")
    print()

    token = input("Enter your Firebase ID token: ").strip()
    if not token:
        raise ValueError("Firebase token is required")
    return token


def find_pdf_files(directory: str) -> list[Path]:
    """Find all PDF files in the given directory."""
    path = Path(directory)
    if not path.exists():
        raise ValueError(f"Directory does not exist: {directory}")
    if not path.is_dir():
        raise ValueError(f"Not a directory: {directory}")

    pdf_files = list(path.glob("*.pdf")) + list(path.glob("*.PDF"))
    return sorted(pdf_files)


def upload_receipt(
    api_url: str,
    token: str,
    file_path: Path,
    receipt_date: Optional[str] = None,
) -> dict:
    """
    Upload a single receipt PDF to the API.

    Args:
        api_url: Base API URL
        token: Firebase ID token
        file_path: Path to the PDF file
        receipt_date: Optional date override (YYYY-MM-DD format)

    Returns:
        API response as dict
    """
    upload_url = f"{api_url}/api/v2/receipts/upload"

    headers = {
        "Authorization": f"Bearer {token}",
    }

    # Prepare the file
    with open(file_path, "rb") as f:
        files = {
            "file": (file_path.name, f, "application/pdf"),
        }

        # Add optional receipt_date parameter
        data = {}
        if receipt_date:
            data["receipt_date"] = receipt_date

        response = requests.post(
            upload_url,
            headers=headers,
            files=files,
            data=data if data else None,
            timeout=120,  # 2 minute timeout for processing
        )

    return {
        "status_code": response.status_code,
        "response": response.json() if response.headers.get("content-type", "").startswith("application/json") else response.text,
    }


def main():
    parser = argparse.ArgumentParser(
        description="Upload PDF receipt files to Scandelicious backend",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Upload all PDFs from a directory to production
  python ingest_pdf_receipts.py /path/to/receipts --env prod

  # Upload to non-prod environment
  python ingest_pdf_receipts.py /path/to/receipts --env non-prod

  # Upload to local development server
  python ingest_pdf_receipts.py /path/to/receipts --env local

  # Upload with a specific date override
  python ingest_pdf_receipts.py /path/to/receipts --date 2025-01-15

  # Use custom API URL
  python ingest_pdf_receipts.py /path/to/receipts --api-url https://custom-api.example.com

Environment Variables:
  FIREBASE_ID_TOKEN - Set this to skip the token prompt
        """,
    )

    parser.add_argument(
        "directory",
        help="Directory containing PDF receipt files",
    )
    parser.add_argument(
        "--env",
        choices=["prod", "non-prod", "local"],
        default="non-prod",
        help="Target environment (default: non-prod)",
    )
    parser.add_argument(
        "--api-url",
        help="Custom API URL (overrides --env)",
    )
    parser.add_argument(
        "--date",
        help="Override receipt date for all uploads (YYYY-MM-DD format)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="List files that would be uploaded without actually uploading",
    )
    parser.add_argument(
        "--continue-on-error",
        action="store_true",
        help="Continue uploading remaining files if one fails",
    )

    args = parser.parse_args()

    # Determine API URL
    api_url = args.api_url if args.api_url else API_URLS[args.env]

    print(f"\n{'='*60}")
    print("PDF Receipt Ingestion Script")
    print(f"{'='*60}")
    print(f"Target API: {api_url}")
    print(f"Directory:  {args.directory}")
    if args.date:
        print(f"Date override: {args.date}")
    print()

    # Find PDF files
    try:
        pdf_files = find_pdf_files(args.directory)
    except ValueError as e:
        print(f"Error: {e}")
        sys.exit(1)

    if not pdf_files:
        print("No PDF files found in the specified directory.")
        sys.exit(0)

    print(f"Found {len(pdf_files)} PDF file(s):")
    for f in pdf_files:
        size_kb = f.stat().st_size / 1024
        print(f"  - {f.name} ({size_kb:.1f} KB)")
    print()

    if args.dry_run:
        print("Dry run mode - no files will be uploaded.")
        sys.exit(0)

    # Get Firebase token
    try:
        token = get_firebase_token()
    except ValueError as e:
        print(f"Error: {e}")
        sys.exit(1)

    # Upload each file
    print(f"\n{'='*60}")
    print("Starting uploads...")
    print(f"{'='*60}\n")

    results = {
        "success": [],
        "failed": [],
        "duplicates": [],
    }

    for i, pdf_file in enumerate(pdf_files, 1):
        print(f"[{i}/{len(pdf_files)}] Uploading: {pdf_file.name}")

        try:
            result = upload_receipt(api_url, token, pdf_file, args.date)
            status_code = result["status_code"]
            response = result["response"]

            if status_code == 200:
                if isinstance(response, dict) and response.get("is_duplicate"):
                    print(f"  ⚠ Duplicate receipt detected (skipped)")
                    results["duplicates"].append(pdf_file.name)
                else:
                    receipt_id = response.get("receipt_id", "N/A") if isinstance(response, dict) else "N/A"
                    store = response.get("store_name", "Unknown") if isinstance(response, dict) else "Unknown"
                    items = response.get("items_count", 0) if isinstance(response, dict) else 0
                    total = response.get("total_amount", 0) if isinstance(response, dict) else 0
                    print(f"  ✓ Success!")
                    print(f"    Receipt ID: {receipt_id}")
                    print(f"    Store: {store}")
                    print(f"    Items: {items}, Total: €{total:.2f}")
                    results["success"].append({
                        "file": pdf_file.name,
                        "receipt_id": receipt_id,
                        "store": store,
                        "items": items,
                        "total": total,
                    })
            elif status_code == 401:
                print(f"  ✗ Authentication failed - check your Firebase token")
                results["failed"].append({"file": pdf_file.name, "error": "Authentication failed"})
                if not args.continue_on_error:
                    print("\nStopping due to authentication error.")
                    break
            elif status_code == 429:
                print(f"  ✗ Rate limit exceeded")
                if isinstance(response, dict):
                    print(f"    Used: {response.get('receipts_used')}/{response.get('receipts_limit')}")
                results["failed"].append({"file": pdf_file.name, "error": "Rate limit exceeded"})
                if not args.continue_on_error:
                    print("\nStopping due to rate limit.")
                    break
            else:
                error_msg = response.get("detail", str(response)) if isinstance(response, dict) else str(response)
                print(f"  ✗ Failed (HTTP {status_code}): {error_msg}")
                results["failed"].append({"file": pdf_file.name, "error": error_msg})
                if not args.continue_on_error:
                    break

        except requests.exceptions.Timeout:
            print(f"  ✗ Request timed out")
            results["failed"].append({"file": pdf_file.name, "error": "Timeout"})
            if not args.continue_on_error:
                break
        except requests.exceptions.RequestException as e:
            print(f"  ✗ Request error: {e}")
            results["failed"].append({"file": pdf_file.name, "error": str(e)})
            if not args.continue_on_error:
                break
        except Exception as e:
            print(f"  ✗ Unexpected error: {e}")
            results["failed"].append({"file": pdf_file.name, "error": str(e)})
            if not args.continue_on_error:
                break

        print()

    # Print summary
    print(f"\n{'='*60}")
    print("Summary")
    print(f"{'='*60}")
    print(f"  Successful uploads: {len(results['success'])}")
    print(f"  Duplicates skipped: {len(results['duplicates'])}")
    print(f"  Failed uploads:     {len(results['failed'])}")

    if results["success"]:
        total_items = sum(r["items"] for r in results["success"])
        total_amount = sum(r["total"] for r in results["success"])
        print(f"\n  Total items processed: {total_items}")
        print(f"  Total amount: €{total_amount:.2f}")

    print("\nProfile enrichment runs automatically after each successful upload.")
    print("Your user profile has been updated with the new receipt data.")


if __name__ == "__main__":
    main()
