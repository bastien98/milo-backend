#!/usr/bin/env python3
"""
Ingest PDF receipts for a specific Firebase UID.

This script:
1. Uses Firebase Admin SDK to create a custom token for the UID
2. Exchanges it for an ID token via Firebase Auth REST API
3. Uploads all PDFs from a directory to the backend
"""

import os
import sys
import argparse
import requests
import json
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

import firebase_admin
from firebase_admin import credentials, auth

# Firebase Web API Key (from GoogleService-Info.plist)
FIREBASE_WEB_API_KEY = "AIzaSyBX431ZHYa4HSzf_gAUSu5dPWY6dfEz1Fc"

# API endpoints
API_URLS = {
    "prod": "https://scandalicious-api-production.up.railway.app",
    "non-prod": "https://scandalicious-api-non-prod.up.railway.app",
    "local": "http://localhost:8000",
}


def init_firebase_admin():
    """Initialize Firebase Admin SDK."""
    if firebase_admin._apps:
        return  # Already initialized

    # Try environment variable first
    service_account_json = os.environ.get("FIREBASE_SERVICE_ACCOUNT")
    if service_account_json:
        cred_dict = json.loads(service_account_json)
        cred = credentials.Certificate(cred_dict)
        firebase_admin.initialize_app(cred)
        return

    # Try credentials file
    cred_file = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
    if cred_file and os.path.exists(cred_file):
        cred = credentials.Certificate(cred_file)
        firebase_admin.initialize_app(cred)
        return

    # Try default location
    default_path = Path(__file__).parent.parent / "firebase-service-account.json"
    if default_path.exists():
        cred = credentials.Certificate(str(default_path))
        firebase_admin.initialize_app(cred)
        return

    raise RuntimeError(
        "Firebase Admin SDK credentials not found. Set FIREBASE_SERVICE_ACCOUNT "
        "or GOOGLE_APPLICATION_CREDENTIALS environment variable."
    )


def get_id_token_for_uid(uid: str) -> str:
    """
    Generate an ID token for a given Firebase UID.

    1. Create a custom token using Firebase Admin SDK
    2. Exchange it for an ID token using Firebase Auth REST API
    """
    # Create custom token
    custom_token = auth.create_custom_token(uid)

    # Exchange for ID token via REST API
    url = f"https://identitytoolkit.googleapis.com/v1/accounts:signInWithCustomToken?key={FIREBASE_WEB_API_KEY}"

    response = requests.post(
        url,
        json={
            "token": custom_token.decode() if isinstance(custom_token, bytes) else custom_token,
            "returnSecureToken": True,
        },
        timeout=30,
    )

    if response.status_code != 200:
        raise RuntimeError(f"Failed to exchange custom token: {response.text}")

    data = response.json()
    return data["idToken"]


def find_pdf_files(directory: str) -> list[Path]:
    """Find all PDF files in the given directory."""
    path = Path(directory)
    if not path.exists():
        raise ValueError(f"Directory does not exist: {directory}")
    if not path.is_dir():
        raise ValueError(f"Not a directory: {directory}")

    pdf_files = list(path.glob("*.pdf")) + list(path.glob("*.PDF"))
    return sorted(pdf_files)


def upload_receipt(api_url: str, token: str, file_path: Path) -> dict:
    """Upload a single receipt PDF to the API."""
    upload_url = f"{api_url}/api/v2/receipts/upload"

    headers = {"Authorization": f"Bearer {token}"}

    with open(file_path, "rb") as f:
        files = {"file": (file_path.name, f, "application/pdf")}
        response = requests.post(
            upload_url,
            headers=headers,
            files=files,
            timeout=120,
        )

    return {
        "status_code": response.status_code,
        "response": response.json() if response.headers.get("content-type", "").startswith("application/json") else response.text,
    }


def main():
    parser = argparse.ArgumentParser(
        description="Ingest PDF receipts for a Firebase UID",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    parser.add_argument("uid", help="Firebase UID of the user")
    parser.add_argument("directory", help="Directory containing PDF receipt files")
    parser.add_argument(
        "--env",
        choices=["prod", "non-prod", "local"],
        default="non-prod",
        help="Target environment (default: non-prod)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="List files without uploading",
    )

    args = parser.parse_args()

    api_url = API_URLS[args.env]

    print(f"\n{'='*60}")
    print("PDF Receipt Ingestion (with Firebase UID)")
    print(f"{'='*60}")
    print(f"Firebase UID: {args.uid}")
    print(f"Target API:   {api_url}")
    print(f"Directory:    {args.directory}")
    print()

    # Find PDFs
    try:
        pdf_files = find_pdf_files(args.directory)
    except ValueError as e:
        print(f"Error: {e}")
        sys.exit(1)

    if not pdf_files:
        print("No PDF files found.")
        sys.exit(0)

    print(f"Found {len(pdf_files)} PDF file(s)")

    if args.dry_run:
        print("\nDry run - files that would be uploaded:")
        for f in pdf_files:
            print(f"  - {f.name}")
        sys.exit(0)

    # Initialize Firebase and get ID token
    print("\nInitializing Firebase Admin SDK...")
    try:
        init_firebase_admin()
    except RuntimeError as e:
        print(f"Error: {e}")
        sys.exit(1)

    print(f"Generating ID token for UID: {args.uid}...")
    try:
        id_token = get_id_token_for_uid(args.uid)
        print(f"ID token obtained (length: {len(id_token)} chars)")
    except Exception as e:
        print(f"Error getting ID token: {e}")
        sys.exit(1)

    # Upload files
    print(f"\n{'='*60}")
    print("Starting uploads...")
    print(f"{'='*60}\n")

    results = {"success": [], "failed": [], "duplicates": []}

    for i, pdf_file in enumerate(pdf_files, 1):
        print(f"[{i}/{len(pdf_files)}] {pdf_file.name}")

        try:
            result = upload_receipt(api_url, id_token, pdf_file)
            status_code = result["status_code"]
            response = result["response"]

            if status_code == 200:
                if isinstance(response, dict) and response.get("is_duplicate"):
                    print(f"  -> Duplicate (skipped)")
                    results["duplicates"].append(pdf_file.name)
                else:
                    store = response.get("store_name", "?") if isinstance(response, dict) else "?"
                    items = response.get("items_count", 0) if isinstance(response, dict) else 0
                    total = response.get("total_amount", 0) if isinstance(response, dict) else 0
                    print(f"  -> OK: {store}, {items} items, EUR {total:.2f}")
                    results["success"].append(pdf_file.name)
            elif status_code == 401:
                print(f"  -> Auth failed")
                results["failed"].append(pdf_file.name)
            elif status_code == 429:
                print(f"  -> Rate limited")
                results["failed"].append(pdf_file.name)
                break  # Stop on rate limit
            else:
                error = response.get("detail", str(response)[:100]) if isinstance(response, dict) else str(response)[:100]
                print(f"  -> Failed ({status_code}): {error}")
                results["failed"].append(pdf_file.name)

        except Exception as e:
            print(f"  -> Error: {e}")
            results["failed"].append(pdf_file.name)

    # Summary
    print(f"\n{'='*60}")
    print("Summary")
    print(f"{'='*60}")
    print(f"  Successful: {len(results['success'])}")
    print(f"  Duplicates: {len(results['duplicates'])}")
    print(f"  Failed:     {len(results['failed'])}")

    if results["failed"]:
        print(f"\nFailed files:")
        for f in results["failed"]:
            print(f"  - {f}")


if __name__ == "__main__":
    main()