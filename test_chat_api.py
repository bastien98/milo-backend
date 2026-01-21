#!/usr/bin/env python3
"""
Integration test script for the Dobby AI Chat API.

Usage:
    python test_chat_api.py --token <your-firebase-token>

Or set the FIREBASE_TOKEN environment variable:
    export FIREBASE_TOKEN=<your-firebase-token>
    python test_chat_api.py

To get a Firebase token, you can use the Firebase Admin SDK or get it from your frontend app.
"""

import argparse
import asyncio
import json
import os
import sys

try:
    import httpx
except ImportError:
    print("Please install httpx: pip install httpx")
    sys.exit(1)


API_BASE_URL = os.getenv("API_BASE_URL", "https://scandalicious-api-production.up.railway.app")


async def test_health():
    """Test the health endpoint."""
    async with httpx.AsyncClient() as client:
        response = await client.get(f"{API_BASE_URL}/health")
        print(f"Health check: {response.status_code}")
        print(f"Response: {response.json()}")
        return response.status_code == 200


async def test_chat(token: str, message: str):
    """Test the non-streaming chat endpoint."""
    async with httpx.AsyncClient(timeout=60.0) as client:
        response = await client.post(
            f"{API_BASE_URL}/api/v1/chat/",
            headers={"Authorization": f"Bearer {token}"},
            json={"message": message}
        )
        print(f"\n--- Chat Response (Non-streaming) ---")
        print(f"Status: {response.status_code}")
        if response.status_code == 200:
            data = response.json()
            print(f"Response: {data['response']}")
            return True
        else:
            print(f"Error: {response.text}")
            return False


async def test_chat_stream(token: str, message: str):
    """Test the streaming chat endpoint."""
    print(f"\n--- Chat Response (Streaming) ---")
    async with httpx.AsyncClient(timeout=60.0) as client:
        async with client.stream(
            "POST",
            f"{API_BASE_URL}/api/v1/chat/stream",
            headers={"Authorization": f"Bearer {token}"},
            json={"message": message}
        ) as response:
            print(f"Status: {response.status_code}")
            if response.status_code == 200:
                print("Response: ", end="", flush=True)
                async for line in response.aiter_lines():
                    if line.startswith("data: "):
                        try:
                            data = json.loads(line[6:])
                            if data["type"] == "text":
                                print(data["content"], end="", flush=True)
                            elif data["type"] == "done":
                                print("\n[Stream completed]")
                            elif data["type"] == "error":
                                print(f"\n[Error: {data['error']}]")
                        except json.JSONDecodeError:
                            pass
                return True
            else:
                body = await response.aread()
                print(f"Error: {body.decode()}")
                return False


async def run_tests(token: str):
    """Run all tests."""
    print("=" * 60)
    print("Dobby AI Chat API Integration Tests")
    print("=" * 60)
    print(f"API URL: {API_BASE_URL}")
    print()

    # Test 1: Health check
    print("Test 1: Health Check")
    if not await test_health():
        print("Health check failed!")
        return

    # Test 2: Total spending query (non-streaming)
    print("\nTest 2: Query Total Spending (Non-streaming)")
    await test_chat(token, "What is my total spending?")

    # Test 3: Category breakdown (non-streaming)
    print("\nTest 3: Query Category Breakdown (Non-streaming)")
    await test_chat(token, "What are my top 3 spending categories?")

    # Test 4: Store comparison (streaming)
    print("\nTest 4: Query Store Comparison (Streaming)")
    await test_chat_stream(token, "Compare my spending at different stores")

    # Test 5: Specific item query (streaming)
    print("\nTest 5: Query Specific Items (Streaming)")
    await test_chat_stream(token, "What dairy products have I bought?")

    # Test 6: Time-based query (streaming)
    print("\nTest 6: Query Recent Spending (Streaming)")
    await test_chat_stream(token, "How much did I spend in the last week?")

    print("\n" + "=" * 60)
    print("Tests completed!")
    print("=" * 60)


def main():
    parser = argparse.ArgumentParser(description="Test the Dobby AI Chat API")
    parser.add_argument(
        "--token",
        help="Firebase ID token for authentication",
        default=os.getenv("FIREBASE_TOKEN")
    )
    parser.add_argument(
        "--url",
        help="API base URL",
        default=os.getenv("API_BASE_URL", "https://scandalicious-api-production.up.railway.app")
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

    asyncio.run(run_tests(args.token))


if __name__ == "__main__":
    main()
