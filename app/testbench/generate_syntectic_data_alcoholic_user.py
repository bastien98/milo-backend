import pandas as pd
import numpy as np
import uuid
import random
from datetime import datetime, timedelta

# User and Configuration
USER_ID = "66dd1d99-4282-434c-8228-ee5b99623aae"
START_DATE = datetime(2025, 1, 1)
END_DATE = datetime(2026, 1, 24)
# Stores are already lowercase here, but the code now enforces it during generation
STORES = ["colruyt", "delhaize", "carrefour", "aldi", "lidl", "spar"]

# Product Catalog
PRODUCTS = {
    "ALCOHOL": [
        ("JUPILER BAK 24X25CL", 14.99, 0), ("STELLA ARTOIS 24X25CL", 15.49, 0),
        ("CARA PILS 24X33CL", 9.99, 0), ("DUVEL 4X33CL", 6.99, 0),
        ("LEFFE BLOND 6X33CL", 7.49, 0), ("VODKA SMIRNOFF 70CL", 18.99, 0),
        ("WHISKY JACK DANIELS 70CL", 24.99, 0), ("GORDON'S GIN 70CL", 19.99, 0),
        ("RODE WIJN BORDEAUX", 6.99, 1), ("WITTE WIJN CHARDONNAY", 5.99, 1)
    ],
    "TOBACCO": [
        ("MARLBORO RED", 8.50, 0), ("CAMEL BLUE", 8.20, 0),
        ("L&M RED", 7.90, 0), ("ROLLING TOBACCO DRUM 50G", 12.50, 0)
    ],
    "SNACKS_SWEETS": [
        ("CHIPS LAYS PAPRIKA", 1.99, 1), ("PRINGLES ORIGINAL", 2.49, 1),
        ("CHOCOLATE COTE D'OR", 2.99, 1), ("HARIBO GOLDBEARS", 1.89, 1),
        ("BEN & JERRYS COOKIE DOUGH", 5.99, 1)
    ],
    "READY_MEALS": [
        ("LASAGNE BOLOGNESE 400G", 3.99, 2), ("PIZZA MARGHERITA", 2.99, 2),
        ("SOEP TOMATEN", 2.49, 3), ("FRIKANDEL 4ST", 2.19, 1)
    ],
    "DRINKS_SOFT_SODA": [
        ("COCA COLA 1.5L", 2.19, 1), ("FANTA ORANGE 1.5L", 2.19, 1),
        ("RED BULL 25CL", 1.49, 0)
    ],
    "DRINKS_WATER": [
        ("WATER SPA BLAUW 6X1.5L", 4.99, 5), ("WATER SPA ROOD 6X1.5L", 4.99, 5)
    ],
    "MEAT_FISH": [
        ("GEHAKT 500G", 4.99, 3), ("KIPFILET 1KG", 9.99, 4),
        ("BURGER 2ST", 3.49, 2), ("ZALMFILET 200G", 5.99, 5)
    ],
    "DAIRY_EGGS": [
        ("MELK HALFVOL 1L", 0.99, 4), ("EIEREN 12ST", 2.49, 4),
        ("KAAS GOUDA", 4.99, 3), ("YOGHURT DANONE", 2.99, 3)
    ],
    "FRESH_PRODUCE": [
        ("BANANEN 1KG", 1.99, 5), ("APPELS JONAGOLD", 2.49, 5),
        ("TOMATEN", 1.99, 5), ("KOMKOMMER", 0.89, 5),
        ("WORTELEN 1KG", 1.29, 5), ("SLA MIX", 1.99, 5)
    ],
    "HOUSEHOLD": [
        ("TOILETPAPIER 12ROL", 5.99, 0), ("AFWASMIDDEL DREFT", 2.99, 0),
        ("VUILNISZAKKEN", 3.49, 0)
    ],
    "BAKERY": [
        ("BAGUETTE", 1.19, 3), ("CROISSANTS 4ST", 3.49, 2)
    ],
    "PANTRY": [
        ("PASTA SPAGHETTI 500G", 1.29, 3), ("OLIJFOLIE 50CL", 6.99, 4),
        ("RIJST 1KG", 2.49, 4)
    ],
    "PERSONAL_CARE": [("TANDPASTA", 2.49, 0), ("SHAMPOO", 3.49, 0)],
    "FROZEN": [("ERWTJES DIEPVRIES", 1.99, 4)],
    "BABY_KIDS": [],
    "PET_SUPPLIES": [],
    "OTHER": []
}

def generate_user_data():
    receipts_list = []
    transactions_list = []
    current_date = START_DATE
    total_days = (END_DATE - START_DATE).days

    food_cats = [
        "SNACKS_SWEETS", "READY_MEALS", "DRINKS_SOFT_SODA", "DRINKS_WATER",
        "MEAT_FISH", "DAIRY_EGGS", "FRESH_PRODUCE", "HOUSEHOLD",
        "BAKERY", "PANTRY", "PERSONAL_CARE", "FROZEN"
    ]

    w_start = np.array([0.25, 0.20, 0.15, 0.02, 0.05, 0.05, 0.05, 0.05, 0.08, 0.05, 0.03, 0.02])
    w_end = np.array([0.05, 0.05, 0.05, 0.10, 0.15, 0.15, 0.25, 0.05, 0.05, 0.05, 0.03, 0.02])

    while current_date <= END_DATE:
        days_passed = (current_date - START_DATE).days
        progress = days_passed / total_days if total_days > 0 else 0

        if random.random() < 0.4:
            receipt_id = str(uuid.uuid4())
            # Enforce lowercase on store selection
            store = random.choice(STORES).lower()

            basket_items = []
            unhealthy_prob = 0.9 - (0.6 * progress)

            if random.random() < unhealthy_prob:
                for _ in range(random.randint(1, 3)):
                    basket_items.append(("ALCOHOL", random.choice(PRODUCTS["ALCOHOL"])))

            if random.random() < unhealthy_prob * 0.8:
                for _ in range(random.randint(1, 2)):
                    basket_items.append(("TOBACCO", random.choice(PRODUCTS["TOBACCO"])))

            current_weights = (1 - progress) * w_start + progress * w_end
            current_weights /= current_weights.sum()

            num_items = random.randint(3, 12)
            chosen_cats = np.random.choice(food_cats, size=num_items, p=current_weights)

            for cat in chosen_cats:
                if PRODUCTS[cat]:
                    basket_items.append((cat, random.choice(PRODUCTS[cat])))

            shop_time = current_date + timedelta(hours=random.randint(8, 20), minutes=random.randint(0, 59))
            upload_time = shop_time + timedelta(minutes=random.randint(10, 120))
            process_time = upload_time + timedelta(seconds=random.randint(30, 300))

            receipt_total = 0.0

            for category, (name, price, base_health) in basket_items:
                quantity = 2 if category == "ALCOHOL" and random.random() < 0.2 else 1
                line_total = price * quantity
                receipt_total += line_total

                transactions_list.append({
                    "id": str(uuid.uuid4()),
                    "user_id": USER_ID,
                    "receipt_id": receipt_id,
                    "store_name": store, # Lowercase enforced
                    "item_name": name,
                    "item_price": round(line_total, 2),
                    "quantity": quantity,
                    "unit_price": price,
                    "category": category,
                    "date": current_date.strftime("%Y-%m-%d"),
                    "created_at": shop_time.strftime("%Y-%m-%d %H:%M:%S.%f") + " +00:00",
                    "health_score": int(base_health)
                })

            receipts_list.append({
                "id": receipt_id,
                "user_id": USER_ID,
                "original_filename": f"receipt_{current_date.strftime('%Y%m%d')}_{random.randint(100,999)}.jpg",
                "file_type": "jpg",
                "file_size_bytes": random.randint(50000, 2000000),
                "status": "COMPLETED",
                "error_message": None,
                "store_name": store, # Lowercase enforced
                "receipt_date": current_date.strftime("%Y-%m-%d"),
                "total_amount": round(receipt_total, 2),
                "created_at": upload_time.strftime("%Y-%m-%d %H:%M:%S.%f") + " +00:00",
                "processed_at": process_time.strftime("%Y-%m-%d %H:%M:%S.%f") + " +00:00"
            })

        current_date += timedelta(days=1)

    return pd.DataFrame(receipts_list), pd.DataFrame(transactions_list)

# Generate and Save
df_receipts, df_transactions = generate_user_data()
df_receipts.to_csv('receipts.csv', index=False)
df_transactions.to_csv('transactions.csv', index=False)

print("Sample of generated store names:")
print(df_receipts['store_name'].unique())