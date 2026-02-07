#!/usr/bin/env python3
"""
Promo Recommender Quality Report

Generates a quality report for investors showing:
1. Match rate - % of interest items that find relevant promos
2. Relevance scores - how well promos match user interests
3. Savings potential - estimated € savings per user
4. Coverage - categories and stores covered
5. Personalization quality - brand/preference alignment

Usage:
    SSL_CERT_FILE=$(python -c "import certifi; print(certifi.where())") python testbench/promo_quality_report.py
"""

import asyncio
import json
import os
import sys
from datetime import date, datetime
from pathlib import Path

import certifi
os.environ["SSL_CERT_FILE"] = certifi.where()
os.environ["REQUESTS_CA_BUNDLE"] = certifi.where()

BACKEND_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_ROOT))

from dotenv import load_dotenv
load_dotenv(BACKEND_ROOT / ".env")

import asyncpg
from pinecone import Pinecone

# Import from promo_recommender
from promo_recommender import (
    DB_CONFIG, PINECONE_API_KEY, PINECONE_INDEX_HOST,
    fetch_enriched_profile, search_promos_for_item
)

# Test user IDs (add more for broader testing)
TEST_USER_IDS = [
    "c9b6bc31-d05a-4ab4-97fc-f40ff5fe6f67",
    # Add more user IDs here for broader testing
]


def calculate_savings(promos: list[dict]) -> float:
    """Calculate potential savings from a list of promos."""
    total_savings = 0.0
    for p in promos:
        try:
            original = float(p.get("original_price", 0) or 0)
            promo = float(p.get("promo_price", 0) or 0)
            if original > 0 and promo > 0:
                total_savings += original - promo
        except (ValueError, TypeError):
            pass
    return total_savings


def analyze_brand_alignment(profile: dict, promo_results: dict) -> dict:
    """Check if recommended promos align with user's brand preferences."""
    user_brands = set()
    for item in profile.get("promo_interest_items", []):
        for brand in item.get("brands", []):
            user_brands.add(brand.lower())

    aligned_promos = 0
    total_promos = 0

    for item_name, promos in promo_results.items():
        for p in promos:
            total_promos += 1
            promo_brand = (p.get("brand") or "").lower()
            if promo_brand and promo_brand in user_brands:
                aligned_promos += 1

    return {
        "user_brands": list(user_brands),
        "total_promos": total_promos,
        "brand_aligned_promos": aligned_promos,
        "brand_alignment_rate": aligned_promos / total_promos if total_promos > 0 else 0,
    }


def analyze_store_alignment(profile: dict, promo_results: dict) -> dict:
    """Check if promos are from stores the user actually visits."""
    user_stores = set()
    for store in profile.get("shopping_habits", {}).get("preferred_stores", []):
        user_stores.add(store.get("name", "").lower())

    store_match = 0
    total_promos = 0

    for item_name, promos in promo_results.items():
        for p in promos:
            total_promos += 1
            retailer = (p.get("source_retailer") or "").lower()
            if any(s in retailer or retailer in s for s in user_stores):
                store_match += 1

    return {
        "user_stores": list(user_stores),
        "total_promos": total_promos,
        "store_aligned_promos": store_match,
        "store_alignment_rate": store_match / total_promos if total_promos > 0 else 0,
    }


async def generate_user_report(user_id: str, pc: Pinecone, index) -> dict:
    """Generate a quality report for a single user."""
    # Fetch profile
    profile = await fetch_enriched_profile(user_id)
    interest_items = profile.get("promo_interest_items", [])

    if not interest_items:
        return {"user_id": user_id, "error": "No interest items"}

    # Search for promos
    promo_results = {}
    all_scores = []

    for item in interest_items:
        name = item["normalized_name"]
        promos = search_promos_for_item(pc, index, item)
        promo_results[name] = promos
        all_scores.extend([p["relevance_score"] for p in promos])

    # Calculate metrics
    items_with_matches = sum(1 for promos in promo_results.values() if promos)
    total_promos = sum(len(promos) for promos in promo_results.values())
    total_savings = sum(calculate_savings(promos) for promos in promo_results.values())

    brand_analysis = analyze_brand_alignment(profile, promo_results)
    store_analysis = analyze_store_alignment(profile, promo_results)

    return {
        "user_id": user_id,
        "profile_summary": {
            "receipts_analyzed": profile.get("receipts_analyzed"),
            "data_period": f"{profile.get('data_period_start')} to {profile.get('data_period_end')}",
            "total_spend": profile.get("shopping_habits", {}).get("total_spend"),
            "preferred_stores": [s.get("name") for s in profile.get("shopping_habits", {}).get("preferred_stores", [])[:3]],
        },
        "interest_items": {
            "total": len(interest_items),
            "specific_items": sum(1 for i in interest_items if i.get("interest_category") != "category_fallback"),
            "category_fallbacks": sum(1 for i in interest_items if i.get("interest_category") == "category_fallback"),
        },
        "match_quality": {
            "items_with_matches": items_with_matches,
            "match_rate": items_with_matches / len(interest_items) if interest_items else 0,
            "total_promos_found": total_promos,
            "avg_promos_per_item": total_promos / len(interest_items) if interest_items else 0,
        },
        "relevance_scores": {
            "avg_score": sum(all_scores) / len(all_scores) if all_scores else 0,
            "max_score": max(all_scores) if all_scores else 0,
            "min_score": min(all_scores) if all_scores else 0,
            "scores_above_0.7": sum(1 for s in all_scores if s >= 0.7),
        },
        "savings_potential": {
            "total_savings_eur": round(total_savings, 2),
            "avg_savings_per_promo": round(total_savings / total_promos, 2) if total_promos > 0 else 0,
        },
        "personalization": {
            "brand_alignment_rate": round(brand_analysis["brand_alignment_rate"], 2),
            "store_alignment_rate": round(store_analysis["store_alignment_rate"], 2),
        },
        "promo_breakdown": {
            name: {
                "count": len(promos),
                "scores": [p["relevance_score"] for p in promos],
                "retailers": list(set(p.get("source_retailer", "?") for p in promos)),
            }
            for name, promos in promo_results.items()
        },
    }


def print_report(report: dict):
    """Print a formatted quality report."""
    print("\n" + "=" * 70)
    print(f"QUALITY REPORT: User {report['user_id'][:8]}...")
    print("=" * 70)

    ps = report["profile_summary"]
    print(f"\n📊 PROFILE SUMMARY")
    print(f"   Receipts: {ps['receipts_analyzed']} | Period: {ps['data_period']}")
    print(f"   Total Spend: €{ps['total_spend']}")
    print(f"   Top Stores: {', '.join(ps['preferred_stores'])}")

    ii = report["interest_items"]
    print(f"\n🎯 INTEREST ITEMS")
    print(f"   Total: {ii['total']} ({ii['specific_items']} specific + {ii['category_fallbacks']} category fallbacks)")

    mq = report["match_quality"]
    print(f"\n✅ MATCH QUALITY")
    print(f"   Match Rate: {mq['match_rate']:.0%} ({mq['items_with_matches']}/{ii['total']} items)")
    print(f"   Total Promos: {mq['total_promos_found']} (avg {mq['avg_promos_per_item']:.1f}/item)")

    rs = report["relevance_scores"]
    print(f"\n📈 RELEVANCE SCORES")
    print(f"   Average: {rs['avg_score']:.2f} | Range: {rs['min_score']:.2f} - {rs['max_score']:.2f}")
    print(f"   High Quality (>0.7): {rs['scores_above_0.7']} promos")

    sp = report["savings_potential"]
    print(f"\n💰 SAVINGS POTENTIAL")
    print(f"   Total: €{sp['total_savings_eur']} | Avg per promo: €{sp['avg_savings_per_promo']}")

    pers = report["personalization"]
    print(f"\n🎨 PERSONALIZATION")
    print(f"   Brand Alignment: {pers['brand_alignment_rate']:.0%}")
    print(f"   Store Alignment: {pers['store_alignment_rate']:.0%}")

    print(f"\n📦 PROMO BREAKDOWN BY ITEM")
    for name, data in report["promo_breakdown"].items():
        status = "✓" if data["count"] > 0 else "✗"
        scores_str = ", ".join(f"{s:.2f}" for s in data["scores"][:3])
        print(f"   {status} {name}: {data['count']} promos [{scores_str}]")


def print_aggregate_report(reports: list[dict]):
    """Print aggregate metrics across all users."""
    valid_reports = [r for r in reports if "error" not in r]

    if not valid_reports:
        print("No valid reports to aggregate")
        return

    print("\n" + "=" * 70)
    print("AGGREGATE QUALITY METRICS")
    print("=" * 70)

    # Aggregate metrics
    total_users = len(valid_reports)
    avg_match_rate = sum(r["match_quality"]["match_rate"] for r in valid_reports) / total_users
    avg_relevance = sum(r["relevance_scores"]["avg_score"] for r in valid_reports) / total_users
    total_savings = sum(r["savings_potential"]["total_savings_eur"] for r in valid_reports)
    avg_brand_align = sum(r["personalization"]["brand_alignment_rate"] for r in valid_reports) / total_users
    avg_store_align = sum(r["personalization"]["store_alignment_rate"] for r in valid_reports) / total_users

    print(f"\n📊 SUMMARY ({total_users} users)")
    print(f"   ├─ Match Rate:        {avg_match_rate:.0%}")
    print(f"   ├─ Avg Relevance:     {avg_relevance:.2f}")
    print(f"   ├─ Total Savings:     €{total_savings:.2f}")
    print(f"   ├─ Brand Alignment:   {avg_brand_align:.0%}")
    print(f"   └─ Store Alignment:   {avg_store_align:.0%}")

    # Quality thresholds for investors
    print(f"\n🎯 INVESTOR METRICS")
    print(f"   ├─ Match Rate > 60%:     {'✅ PASS' if avg_match_rate > 0.6 else '❌ NEEDS WORK'}")
    print(f"   ├─ Relevance > 0.65:     {'✅ PASS' if avg_relevance > 0.65 else '❌ NEEDS WORK'}")
    print(f"   ├─ Savings > €5/user:    {'✅ PASS' if total_savings/total_users > 5 else '❌ NEEDS WORK'}")
    print(f"   └─ Personalization > 30%: {'✅ PASS' if (avg_brand_align + avg_store_align)/2 > 0.3 else '❌ NEEDS WORK'}")


async def main():
    print("=" * 70)
    print("PROMO RECOMMENDER QUALITY REPORT")
    print(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 70)

    if not PINECONE_API_KEY:
        print("ERROR: PINECONE_API_KEY not set")
        sys.exit(1)

    pc = Pinecone(api_key=PINECONE_API_KEY)
    index = pc.Index(host=PINECONE_INDEX_HOST)

    reports = []
    for user_id in TEST_USER_IDS:
        print(f"\nProcessing user {user_id[:8]}...")
        report = await generate_user_report(user_id, pc, index)
        reports.append(report)
        print_report(report)

    print_aggregate_report(reports)

    # Export JSON for further analysis
    output_path = BACKEND_ROOT / "testbench/quality_report.json"
    with open(output_path, "w") as f:
        json.dump(reports, f, indent=2, default=str)
    print(f"\n📄 Full report exported to: {output_path}")


if __name__ == "__main__":
    asyncio.run(main())
