#!/usr/bin/env python3
"""
Create Test User with Synthetic Belgian Consumer Profile

Generates a realistic Belgian shopper profile and ingests it directly into the database.
Supports different shopper personas for testing various promo recommendation scenarios.

Usage:
    SSL_CERT_FILE=$(python -c "import certifi; print(certifi.where())") python testbench/create_test_user_db.py
"""

import asyncio
import random
import uuid
from datetime import date, datetime, timedelta
from pathlib import Path
import sys

import certifi
import os
os.environ["SSL_CERT_FILE"] = certifi.where()
os.environ["REQUESTS_CA_BUNDLE"] = certifi.where()

BACKEND_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_ROOT))

from dotenv import load_dotenv
load_dotenv(BACKEND_ROOT / ".env")

import asyncpg

# Production database (same as promo_recommender.py)
DB_CONFIG = {
    "host": "switchback.proxy.rlwy.net",
    "port": 45896,
    "user": "postgres",
    "password": "hrGaUOZtYDDNPUDPmXlzpnVAReIgxlkx",
    "database": "railway",
}

# ==========================================
# BELGIAN STORE CONFIGURATIONS
# ==========================================
STORES = {
    "colruyt": {"premium": False, "frequency": 0.25},
    "delhaize": {"premium": True, "frequency": 0.15},
    "carrefour": {"premium": False, "frequency": 0.15},
    "aldi": {"premium": False, "frequency": 0.15},
    "lidl": {"premium": False, "frequency": 0.10},
    "albert heijn": {"premium": False, "frequency": 0.10},
    "spar": {"premium": False, "frequency": 0.05},
    "okay": {"premium": False, "frequency": 0.03},
    "bio-planet": {"premium": True, "frequency": 0.02},
}

# ==========================================
# PRODUCT CATALOG WITH GRANULAR CATEGORIES
# ==========================================
# Format: (item_name, normalized_name, brand, unit_price, health_score, granular_category, parent_category)

PRODUCTS = {
    "Beer Pils": [
        ("Jupiler Pils 24x25cl", "pils", "jupiler", 14.99, 1, "Beer Pils", "Alcohol"),
        ("Stella Artois 24x25cl", "pils", "stella artois", 15.49, 1, "Beer Pils", "Alcohol"),
        ("Cara Pils 24x33cl", "pils", "cara", 9.99, 1, "Beer Pils", "Alcohol"),
        ("Maes Pils 24x25cl", "pils", "maes", 13.99, 1, "Beer Pils", "Alcohol"),
    ],
    "Beer Special": [
        ("Duvel 4x33cl", "duvel", "duvel", 6.99, 1, "Beer Special", "Alcohol"),
        ("Leffe Blond 6x33cl", "leffe", "leffe", 7.49, 1, "Beer Special", "Alcohol"),
        ("Chimay Blauw 33cl", "chimay", "chimay", 3.49, 1, "Beer Special", "Alcohol"),
        ("Westmalle Tripel 33cl", "westmalle tripel", "westmalle", 2.99, 1, "Beer Special", "Alcohol"),
    ],
    "Wine": [
        ("Rode Wijn Bordeaux 75cl", "rode wijn", "bordeaux", 6.99, 2, "Wine Red", "Alcohol"),
        ("Witte Wijn Chardonnay 75cl", "witte wijn", "chardonnay", 5.99, 2, "Wine White", "Alcohol"),
        ("Rose Provence 75cl", "rose", "provence", 7.99, 2, "Wine Rose", "Alcohol"),
    ],
    "Chips": [
        ("Lay's Paprika 175g", "chips", "lay's", 1.99, 1, "Chips", "Snacks & Sweets"),
        ("Pringles Original 165g", "chips", "pringles", 2.49, 1, "Chips", "Snacks & Sweets"),
        ("Croky Bolognese 200g", "chips", "croky", 1.79, 1, "Chips", "Snacks & Sweets"),
        ("Lays Oven Baked Naturel 150g", "chips oven baked naturel", "lay's", 2.29, 2, "Chips", "Snacks & Sweets"),
    ],
    "Chocolate": [
        ("Cote d'Or Melk 200g", "chocolade", "cote d'or", 2.99, 1, "Chocolate Bars", "Snacks & Sweets"),
        ("Leonidas Pralines 250g", "pralines", "leonidas", 12.99, 1, "Chocolate Pralines", "Snacks & Sweets"),
        ("Callebaut Chocolade 400g", "chocolade", "callebaut", 5.99, 1, "Chocolate Baking", "Snacks & Sweets"),
    ],
    "Frozen Pizza": [
        ("Dr. Oetker Ristorante Margherita", "pizza", "dr. oetker", 3.49, 2, "Frozen Pizza", "Frozen"),
        ("Wagner Big Pizza Salami", "pizza", "wagner", 3.99, 2, "Frozen Pizza", "Frozen"),
        ("Buitoni Bella Napoli 4 Fromaggi", "pizza", "buitoni", 4.49, 2, "Frozen Pizza", "Frozen"),
    ],
    "Meals Fresh": [
        ("Lasagne Bolognese 400g", "lasagne", "boni", 3.99, 2, "Meals Fresh", "Ready Meals"),
        ("Spaghetti Bolognese 450g", "spaghetti bolognese", "come a casa", 4.49, 2, "Meals Fresh", "Ready Meals"),
        ("Macaroni Ham Kaas 400g", "macaroni", "everyday", 3.29, 2, "Meals Fresh", "Ready Meals"),
    ],
    "Salads Ready": [
        ("Caesar Salade 250g", "caesar salade", "bonduelle", 3.99, 4, "Salads Ready", "Ready Meals"),
        ("Pasta Salade 300g", "pasta salade", "everyday", 3.49, 3, "Salads Ready", "Ready Meals"),
        ("Griekse Salade 200g", "griekse salade", "bonduelle", 3.79, 4, "Salads Ready", "Ready Meals"),
        ("Poké Bowl Zalm 350g", "poké bowl", "boni", 6.99, 4, "Salads Ready", "Ready Meals"),
    ],
    "Soups Fresh": [
        ("Tomatensoep 1L", "tomatensoep", "knorr", 3.49, 3, "Soups Fresh", "Ready Meals"),
        ("Groentensoep 1L", "groentensoep", "liebig", 3.29, 4, "Soups Fresh", "Ready Meals"),
        ("Pompoensoep 1L", "pompoensoep", "knorr", 3.49, 4, "Soups Fresh", "Ready Meals"),
        ("Thai Kokossoep 500ml", "kokossoep", "go tan", 4.29, 3, "Soups Fresh", "Ready Meals"),
    ],
    "Salami & Sausage": [
        ("Salami Ministicks 100g", "salami ministicks", "aoste", 2.49, 2, "Salami & Sausage", "Meat & Fish"),
        ("Hongaarse Salami 100g", "hongaarse salami", "boni", 2.29, 2, "Salami & Sausage", "Meat & Fish"),
        ("Chorizo Pamplona 100g", "chorizo", "navidul", 2.99, 2, "Salami & Sausage", "Meat & Fish"),
    ],
    "Milk Fresh": [
        ("Halfvolle Melk 1L", "halfvolle melk", "campina", 0.99, 4, "Milk Fresh", "Dairy & Eggs"),
        ("Volle Melk 1L", "volle melk", "campina", 1.09, 4, "Milk Fresh", "Dairy & Eggs"),
        ("Magere Melk 1L", "magere melk", "everyday", 0.89, 5, "Milk Fresh", "Dairy & Eggs"),
    ],
    "Eggs": [
        ("Eieren 12 stuks", "eieren", "colruyt", 2.49, 4, "Eggs", "Dairy & Eggs"),
        ("Bio Eieren 6 stuks", "bio eieren", "bio-planet", 3.49, 5, "Eggs Bio", "Dairy & Eggs"),
        ("Vrije Uitloop Eieren 10 stuks", "vrije uitloop eieren", "boni", 3.29, 5, "Eggs Free Range", "Dairy & Eggs"),
    ],
    "Cheese": [
        ("Gouda Jong 500g", "gouda", "milner", 4.99, 3, "Cheese Gouda", "Dairy & Eggs"),
        ("Emmentaler 200g", "emmentaler", "leerdammer", 3.49, 3, "Cheese Emmental", "Dairy & Eggs"),
        ("Brie 200g", "brie", "president", 2.99, 3, "Cheese Brie", "Dairy & Eggs"),
    ],
    "Yogurt": [
        ("Griekse Yoghurt 500g", "griekse yoghurt", "fage", 2.99, 4, "Yogurt Greek", "Dairy & Eggs"),
        ("Fruityoghurt Aardbei 4x125g", "fruityoghurt", "danone", 2.49, 3, "Yogurt Fruit", "Dairy & Eggs"),
        ("Skyr Naturel 450g", "skyr", "arla", 2.79, 5, "Yogurt Skyr", "Dairy & Eggs"),
    ],
    "Bread": [
        ("Baguette Traditioneel", "baguette", "colruyt", 1.19, 3, "Bread Baguette", "Bakery"),
        ("Volkoren Brood 800g", "volkoren brood", "harry's", 2.29, 5, "Bread Whole Grain", "Bakery"),
        ("Pistolets 6 stuks", "pistolets", "everyday", 1.99, 3, "Bread Rolls", "Bakery"),
    ],
    "Croissants": [
        ("Roomboter Croissants 4 stuks", "croissants", "la boulangere", 3.49, 2, "Croissants", "Bakery"),
        ("Chocolade Croissants 4 stuks", "pain au chocolat", "everyday", 2.99, 1, "Croissants", "Bakery"),
    ],
    "Fruit": [
        ("Bananen 1kg", "bananen", None, 1.99, 5, "Fruit Tropical", "Fresh Produce"),
        ("Appels Jonagold 1kg", "appels", "jonagold", 2.49, 5, "Fruit Apples", "Fresh Produce"),
        ("Sinaasappels 2kg", "sinaasappels", None, 3.49, 5, "Fruit Citrus", "Fresh Produce"),
        ("Aardbeien 500g", "aardbeien", None, 3.99, 5, "Fruit Berries", "Fresh Produce"),
    ],
    "Vegetables": [
        ("Tomaten 1kg", "tomaten", None, 2.49, 5, "Vegetables Tomatoes", "Fresh Produce"),
        ("Komkommer", "komkommer", None, 0.89, 5, "Vegetables Cucumber", "Fresh Produce"),
        ("Wortelen 1kg", "wortelen", None, 1.29, 5, "Vegetables Carrots", "Fresh Produce"),
        ("Sla Mix 250g", "sla", None, 1.99, 5, "Vegetables Salad", "Fresh Produce"),
        ("Broccoli 500g", "broccoli", None, 1.79, 5, "Vegetables Broccoli", "Fresh Produce"),
    ],
    "Chicken": [
        ("Kipfilet 500g", "kipfilet", "volys", 5.99, 4, "Chicken Breast", "Meat & Fish"),
        ("Kippenboutjes 1kg", "kippenboutjes", "boni", 4.99, 4, "Chicken Legs", "Meat & Fish"),
        ("Kippenworst 4 stuks", "kippenworst", "herta", 2.99, 3, "Chicken Sausage", "Meat & Fish"),
    ],
    "Beef & Pork": [
        ("Gehakt Half-om-Half 500g", "gehakt", "boni", 4.99, 3, "Meat Minced", "Meat & Fish"),
        ("Biefstuk 200g", "biefstuk", "boni", 6.99, 4, "Beef Steak", "Meat & Fish"),
        ("Varkensfilet 400g", "varkensfilet", "boni", 5.49, 3, "Pork Tenderloin", "Meat & Fish"),
        ("Spek Gerookt 200g", "spek", "aoste", 2.99, 2, "Bacon", "Meat & Fish"),
    ],
    "Fish": [
        ("Zalmfilet 200g", "zalmfilet", "boni", 5.99, 5, "Fish Salmon", "Meat & Fish"),
        ("Kabeljauw Filet 400g", "kabeljauw", "boni", 7.99, 5, "Fish Cod", "Meat & Fish"),
        ("Garnalen 200g", "garnalen", None, 6.99, 5, "Shellfish", "Meat & Fish"),
    ],
    "Pasta & Rice": [
        ("Spaghetti 500g", "spaghetti", "barilla", 1.29, 3, "Pasta Spaghetti", "Pantry"),
        ("Penne 500g", "penne", "de cecco", 1.49, 3, "Pasta Penne", "Pantry"),
        ("Basmati Rijst 1kg", "basmati rijst", "uncle ben's", 2.99, 4, "Rice Basmati", "Pantry"),
    ],
    "Sauces": [
        ("Olijfolie Extra Vierge 500ml", "olijfolie", "carapelli", 6.99, 4, "Oil Olive", "Pantry"),
        ("Tomatensaus 400g", "tomatensaus", "mutti", 1.99, 4, "Sauce Tomato", "Pantry"),
        ("Mayonaise 500ml", "mayonaise", "devos lemmens", 2.99, 1, "Sauce Mayo", "Pantry"),
    ],
    "Soft Drinks": [
        ("Coca Cola 1.5L", "coca cola", "coca cola", 2.19, 0, "Soft Drinks Cola", "Drinks (Soft/Soda)"),
        ("Fanta Orange 1.5L", "fanta", "fanta", 2.19, 0, "Soft Drinks Orange", "Drinks (Soft/Soda)"),
        ("Ice Tea Peach 1.5L", "ice tea", "lipton", 2.49, 1, "Soft Drinks Tea", "Drinks (Soft/Soda)"),
    ],
    "Water": [
        ("Spa Blauw 6x1.5L", "spa blauw", "spa", 4.99, 5, "Water Still", "Drinks (Water)"),
        ("Spa Rood 6x1.5L", "spa rood", "spa", 4.99, 5, "Water Sparkling", "Drinks (Water)"),
        ("Vittel 1.5L", "vittel", "vittel", 1.29, 5, "Water Still", "Drinks (Water)"),
    ],
    "Coffee & Tea": [
        ("Koffie Pads 36 stuks", "koffiepads", "douwe egberts", 4.99, 3, "Coffee Pods", "Pantry"),
        ("Espresso Bonen 500g", "espresso bonen", "lavazza", 7.99, 3, "Coffee Beans", "Pantry"),
        ("Groene Thee 20 zakjes", "groene thee", "lipton", 2.49, 5, "Tea Green", "Pantry"),
    ],
    "Household": [
        ("Toiletpapier 12 rollen", "toiletpapier", "page", 5.99, None, "Toilet Paper", "Household"),
        ("Afwasmiddel 500ml", "afwasmiddel", "dreft", 2.99, None, "Dish Soap", "Household"),
        ("Wasmiddel 2L", "wasmiddel", "persil", 9.99, None, "Laundry Detergent", "Household"),
        ("Vuilniszakken 20 stuks", "vuilniszakken", "everyday", 3.49, None, "Trash Bags", "Household"),
    ],
    # Kid-specific categories
    "Baby Diapers": [
        ("Pampers Baby-Dry Maat 5 72st", "luiers", "pampers", 24.99, None, "Diapers", "Baby & Kids"),
        ("Pampers Premium Protection 4 82st", "luiers", "pampers", 27.99, None, "Diapers", "Baby & Kids"),
        ("Huggies Ultra Comfort 5 42st", "luiers", "huggies", 14.99, None, "Diapers", "Baby & Kids"),
        ("Kruidvat Luiers Maat 5 44st", "luiers", "kruidvat", 8.99, None, "Diapers", "Baby & Kids"),
    ],
    "Baby Wipes": [
        ("Pampers Sensitive Billendoekjes 52st", "billendoekjes", "pampers", 3.49, None, "Baby Wipes", "Baby & Kids"),
        ("Huggies Pure Doekjes 56st", "billendoekjes", "huggies", 2.99, None, "Baby Wipes", "Baby & Kids"),
    ],
    "Baby Food": [
        ("Olvarit Groentehapje 6m 200g", "babyvoeding", "olvarit", 1.89, 4, "Baby Food Jars", "Baby & Kids"),
        ("Hipp Fruithapje 4m 190g", "babyvoeding", "hipp", 1.79, 4, "Baby Food Jars", "Baby & Kids"),
        ("Bledina Petit Pot Legumes 2x200g", "babyvoeding", "bledina", 3.29, 4, "Baby Food Jars", "Baby & Kids"),
        ("Ella's Kitchen Fruit Pouch 120g", "fruitknijper", "ella's kitchen", 1.99, 4, "Baby Food Pouches", "Baby & Kids"),
    ],
    "Toddler Milk": [
        ("Nutrilon Dreumesmelk 2+ 800g", "peutermelk", "nutrilon", 14.99, 4, "Toddler Milk", "Baby & Kids"),
        ("Aptamil Peutermelk 1+ 800g", "peutermelk", "aptamil", 13.99, 4, "Toddler Milk", "Baby & Kids"),
    ],
    "Kids Cereals": [
        ("Kellogg's Choco Pops 375g", "choco pops", "kellogg's", 3.99, 2, "Cereals Kids", "Pantry"),
        ("Nestle Chocapic 375g", "chocapic", "nestle", 3.79, 2, "Cereals Kids", "Pantry"),
        ("Kellogg's Frosties 375g", "frosties", "kellogg's", 3.99, 2, "Cereals Kids", "Pantry"),
        ("Nestle Lion Cereals 400g", "lion cereals", "nestle", 3.99, 1, "Cereals Kids", "Pantry"),
        ("Kellogg's Smacks 375g", "smacks", "kellogg's", 3.79, 1, "Cereals Kids", "Pantry"),
    ],
    "Kids Drinks": [
        ("Fristi Rood Fruit 6x200ml", "fristi", "fristi", 3.49, 2, "Kids Drinks", "Dairy & Eggs"),
        ("Yakult 7x65ml", "yakult", "yakult", 4.99, 3, "Kids Drinks", "Dairy & Eggs"),
        ("Capri Sun Orange 10x200ml", "capri sun", "capri sun", 4.99, 1, "Juice Packs", "Drinks (Soft/Soda)"),
        ("Appelsientje Kids 6x200ml", "appelsap", "appelsientje", 3.99, 3, "Juice Packs", "Drinks (Soft/Soda)"),
    ],
    "Kids Snacks": [
        ("LU Prince Koekjes 300g", "prince koekjes", "lu", 2.49, 1, "Biscuits Kids", "Snacks & Sweets"),
        ("Kinder Bueno 6st", "kinder bueno", "kinder", 3.49, 1, "Chocolate Kids", "Snacks & Sweets"),
        ("Kinder Surprise 3st", "kinder surprise", "kinder", 4.99, 1, "Chocolate Kids", "Snacks & Sweets"),
        ("Liga Milkbreak 6st", "liga", "liga", 2.99, 2, "Biscuits Kids", "Snacks & Sweets"),
        ("BN Koeken Aardbei 295g", "bn koeken", "bn", 2.49, 2, "Biscuits Kids", "Snacks & Sweets"),
        ("Sultana Fruitbiscuit 5x3st", "sultana", "sultana", 2.79, 3, "Biscuits Fruit", "Snacks & Sweets"),
    ],
    "Kids Yogurt": [
        ("Danone Gervais Petit Suisse 6x50g", "petit suisse", "danone", 2.29, 3, "Yogurt Kids", "Dairy & Eggs"),
        ("Fruttis Kinderen 4x100g", "fruttis", "fruttis", 2.49, 3, "Yogurt Kids", "Dairy & Eggs"),
        ("Actimel Kids 6x100g", "actimel", "danone", 3.99, 3, "Yogurt Kids", "Dairy & Eggs"),
    ],
    "Sandwich Spreads": [
        ("Nutella 400g", "nutella", "nutella", 3.99, 1, "Spreads Chocolate", "Pantry"),
        ("Lotus Speculoospasta 400g", "speculoospasta", "lotus", 3.49, 1, "Spreads Sweet", "Pantry"),
        ("Pindakaas Calvé 350g", "pindakaas", "calvé", 2.99, 3, "Spreads Peanut", "Pantry"),
        ("Confituur Aardbei 450g", "confituur", "materne", 2.49, 2, "Jam", "Pantry"),
    ],
    "Lunchbox Items": [
        ("Boterhamworst 150g", "boterhamworst", "zwan", 2.29, 2, "Deli Meats", "Meat & Fish"),
        ("Kip Filet Gerookt 100g", "kipfilet gerookt", "boni", 2.49, 3, "Deli Meats", "Meat & Fish"),
        ("Mini Babybel 6st", "babybel", "babybel", 3.99, 3, "Cheese Snack", "Dairy & Eggs"),
        ("Smeerkaas Driehoekjes 16st", "smeerkaas", "la vache qui rit", 3.29, 2, "Cheese Spread", "Dairy & Eggs"),
    ],
    "Personal Care": [
        ("Tandpasta 75ml", "tandpasta", "colgate", 2.49, None, "Oral Care", "Personal Care"),
        ("Shampoo 250ml", "shampoo", "head & shoulders", 3.49, None, "Hair Care", "Personal Care"),
        ("Douchegel 250ml", "douchegel", "dove", 2.99, None, "Body Wash", "Personal Care"),
    ],
    # Protein & Fitness products
    "Protein Bars": [
        ("Barebells Protein Bar Caramel Cashew 55g", "protein bar", "barebells", 2.99, 4, "Protein Bars", "Sports Nutrition"),
        ("Barebells Protein Bar Cookies & Cream 55g", "protein bar", "barebells", 2.99, 4, "Protein Bars", "Sports Nutrition"),
        ("Quest Bar Chocolate Chip 60g", "protein bar", "quest", 3.29, 4, "Protein Bars", "Sports Nutrition"),
        ("Grenade Carb Killa Bar 60g", "protein bar", "grenade", 3.49, 4, "Protein Bars", "Sports Nutrition"),
        ("PhD Smart Bar Chocolate Brownie 64g", "protein bar", "phd", 2.79, 4, "Protein Bars", "Sports Nutrition"),
        ("Myprotein Layered Bar 60g", "protein bar", "myprotein", 2.49, 4, "Protein Bars", "Sports Nutrition"),
    ],
    "Protein Drinks": [
        ("Barebells Milkshake Chocolate 330ml", "protein shake", "barebells", 2.99, 4, "Protein Drinks", "Sports Nutrition"),
        ("Barebells Milkshake Vanilla 330ml", "protein shake", "barebells", 2.99, 4, "Protein Drinks", "Sports Nutrition"),
        ("Multipower Protein Shake 330ml", "protein shake", "multipower", 2.49, 4, "Protein Drinks", "Sports Nutrition"),
        ("Optimum Nutrition Protein Shake 330ml", "protein shake", "optimum nutrition", 3.49, 4, "Protein Drinks", "Sports Nutrition"),
    ],
    "High Protein Dairy": [
        ("Skyr Naturel 450g", "skyr", "arla", 2.79, 5, "Yogurt Skyr", "Dairy & Eggs"),
        ("Skyr Vanille 450g", "skyr vanille", "arla", 2.99, 4, "Yogurt Skyr", "Dairy & Eggs"),
        ("Danio Vanille 180g", "danio", "danone", 1.79, 4, "Yogurt High Protein", "Dairy & Eggs"),
        ("Hipro Pudding Chocolade 200g", "hipro", "danone", 1.99, 4, "Pudding High Protein", "Dairy & Eggs"),
        ("Cottage Cheese 200g", "cottage cheese", "boni", 1.99, 5, "Cheese Cottage", "Dairy & Eggs"),
    ],
    "Energy Drinks": [
        ("Red Bull 25cl", "red bull", "red bull", 1.99, 1, "Energy Drinks", "Drinks (Soft/Soda)"),
        ("Monster Energy 50cl", "monster", "monster", 1.99, 1, "Energy Drinks", "Drinks (Soft/Soda)"),
        ("Monster Zero Sugar 50cl", "monster zero", "monster", 1.99, 2, "Energy Drinks", "Drinks (Soft/Soda)"),
        ("Red Bull Sugar Free 25cl", "red bull sugar free", "red bull", 1.99, 2, "Energy Drinks", "Drinks (Soft/Soda)"),
    ],
    "Savory Snacks": [
        ("Borrelnootjes 300g", "borrelnootjes", "duyvis", 2.99, 2, "Nuts Snack", "Snacks & Sweets"),
        ("Doritos Nacho Cheese 170g", "doritos", "doritos", 2.49, 1, "Chips Tortilla", "Snacks & Sweets"),
        ("Bifi Original 5st", "bifi", "bifi", 3.49, 3, "Meat Snack", "Snacks & Sweets"),
        ("Lookworst Sticks 100g", "lookworst", "boni", 2.29, 2, "Meat Snack", "Snacks & Sweets"),
        ("Pinda's Gezouten 500g", "pinda's", "duyvis", 3.99, 3, "Nuts Peanuts", "Snacks & Sweets"),
    ],
}

# ==========================================
# SHOPPER PERSONAS
# ==========================================
PERSONAS = {
    "health_conscious": {
        "description": "Health-focused shopper, prefers organic and fresh produce",
        "preferred_stores": ["bio-planet", "delhaize", "albert heijn"],
        "category_weights": {
            "Fruit": 0.20, "Vegetables": 0.20, "Fish": 0.10, "Chicken": 0.10,
            "Yogurt": 0.10, "Milk Fresh": 0.05, "Eggs": 0.05, "Water": 0.05,
            "Bread": 0.05, "Pasta & Rice": 0.05, "Coffee & Tea": 0.05,
        },
        "avg_receipts_per_month": 12,
        "avg_items_per_receipt": (4, 10),
    },
    "budget_shopper": {
        "description": "Price-conscious, shops deals at discount stores",
        "preferred_stores": ["aldi", "lidl", "colruyt"],
        "category_weights": {
            "Pasta & Rice": 0.15, "Milk Fresh": 0.10, "Eggs": 0.10, "Bread": 0.10,
            "Vegetables": 0.10, "Chicken": 0.10, "Beef & Pork": 0.10,
            "Frozen Pizza": 0.08, "Soft Drinks": 0.07, "Household": 0.05, "Chips": 0.05,
        },
        "avg_receipts_per_month": 8,
        "avg_items_per_receipt": (8, 15),
    },
    "indulgent": {
        "description": "Enjoys treats, snacks, and alcohol",
        "preferred_stores": ["delhaize", "carrefour", "colruyt"],
        "category_weights": {
            "Beer Pils": 0.15, "Beer Special": 0.10, "Wine": 0.10, "Chips": 0.15,
            "Chocolate": 0.10, "Frozen Pizza": 0.10, "Soft Drinks": 0.10,
            "Croissants": 0.05, "Salami & Sausage": 0.05, "Cheese": 0.05, "Meals Fresh": 0.05,
        },
        "avg_receipts_per_month": 15,
        "avg_items_per_receipt": (3, 8),
    },
    "family_shopper": {
        "description": "Large household, bulk buying, varied categories",
        "preferred_stores": ["colruyt", "carrefour", "aldi"],
        "category_weights": {
            "Milk Fresh": 0.08, "Eggs": 0.05, "Bread": 0.08, "Fruit": 0.10,
            "Vegetables": 0.08, "Chicken": 0.08, "Beef & Pork": 0.08,
            "Pasta & Rice": 0.08, "Cheese": 0.05, "Yogurt": 0.05,
            "Frozen Pizza": 0.05, "Soft Drinks": 0.05, "Household": 0.08,
            "Personal Care": 0.05, "Water": 0.04,
        },
        "avg_receipts_per_month": 10,
        "avg_items_per_receipt": (10, 20),
    },
    "mixed": {
        "description": "Balanced shopper with varied preferences",
        "preferred_stores": ["colruyt", "delhaize", "carrefour", "aldi"],
        "category_weights": {
            "Milk Fresh": 0.06, "Eggs": 0.05, "Bread": 0.06, "Fruit": 0.08,
            "Vegetables": 0.08, "Chicken": 0.06, "Beef & Pork": 0.05,
            "Fish": 0.04, "Cheese": 0.05, "Yogurt": 0.05, "Pasta & Rice": 0.06,
            "Chips": 0.05, "Beer Pils": 0.06, "Frozen Pizza": 0.05, "Soft Drinks": 0.05,
            "Water": 0.04, "Household": 0.05, "Personal Care": 0.03, "Coffee & Tea": 0.03,
        },
        "avg_receipts_per_month": 12,
        "avg_items_per_receipt": (5, 12),
    },
    "belgian_family_3kids": {
        "description": "Belgian family with 3 kids (ages 2, 8, 12) - diapers, school snacks, family meals",
        "preferred_stores": ["colruyt", "carrefour", "aldi", "delhaize"],
        "category_weights": {
            # Baby/toddler (age 2) - ~15% of spend
            "Baby Diapers": 0.08,
            "Baby Wipes": 0.02,
            "Baby Food": 0.03,
            "Toddler Milk": 0.02,
            # Kids (ages 8, 12) - ~20% of spend
            "Kids Cereals": 0.05,
            "Kids Drinks": 0.04,
            "Kids Snacks": 0.06,
            "Kids Yogurt": 0.03,
            "Lunchbox Items": 0.02,
            # Family staples - ~35% of spend
            "Milk Fresh": 0.06,
            "Bread": 0.05,
            "Eggs": 0.03,
            "Cheese": 0.04,
            "Sandwich Spreads": 0.04,
            "Fruit": 0.06,
            "Vegetables": 0.04,
            "Chicken": 0.05,
            "Beef & Pork": 0.04,
            "Pasta & Rice": 0.04,
            # Convenience/treats - ~15% of spend
            "Frozen Pizza": 0.04,
            "Meals Fresh": 0.03,
            "Chips": 0.02,
            "Chocolate": 0.02,
            "Soft Drinks": 0.03,
            # Household - ~10% of spend
            "Household": 0.05,
            "Water": 0.02,
            "Coffee & Tea": 0.02,
        },
        "avg_receipts_per_month": 16,  # Families shop more frequently
        "avg_items_per_receipt": (12, 25),  # Larger baskets
    },
    "young_couple": {
        "description": "Young couple (25-35), no kids - convenience, wine nights, premium ingredients",
        "preferred_stores": ["delhaize", "albert heijn", "carrefour", "colruyt"],
        "category_weights": {
            # Convenience & ready meals - ~25% (busy lifestyle)
            "Meals Fresh": 0.10,
            "Frozen Pizza": 0.05,
            "Salads Ready": 0.05,
            "Soups Fresh": 0.05,
            # Wine & drinks - ~15% (social life)
            "Wine": 0.08,
            "Beer Special": 0.04,
            "Soft Drinks": 0.03,
            # Cooking ingredients - ~25% (weekend cooking)
            "Chicken": 0.06,
            "Fish": 0.05,
            "Beef & Pork": 0.04,
            "Pasta & Rice": 0.05,
            "Vegetables": 0.05,
            # Breakfast & snacks - ~15%
            "Coffee & Tea": 0.06,
            "Bread": 0.04,
            "Cheese": 0.05,
            # Treats - ~10%
            "Chocolate": 0.04,
            "Chips": 0.03,
            "Croissants": 0.03,
            # Basics - ~10%
            "Eggs": 0.03,
            "Milk Fresh": 0.03,
            "Household": 0.02,
            "Personal Care": 0.02,
        },
        "avg_receipts_per_month": 10,  # Shop less frequently
        "avg_items_per_receipt": (5, 12),  # Smaller baskets
    },
    "belgian_party_fitness": {
        "description": "27yo Belgian guy - weekend drinks, snacks, protein bars, active lifestyle",
        "preferred_stores": ["colruyt", "delhaize", "carrefour", "albert heijn"],
        "category_weights": {
            # Weekend drinking - ~25% (goes out, also drinks at home)
            "Beer Pils": 0.12,
            "Beer Special": 0.08,
            "Wine": 0.03,
            "Energy Drinks": 0.02,
            # Protein & Fitness - ~20% (gym lifestyle)
            "Protein Bars": 0.10,
            "Protein Drinks": 0.05,
            "High Protein Dairy": 0.05,
            # Snacks - ~20% (party snacks, munchies)
            "Chips": 0.08,
            "Savory Snacks": 0.07,
            "Chocolate": 0.03,
            "Salami & Sausage": 0.02,
            # Quick meals - ~15% (bachelor cooking)
            "Frozen Pizza": 0.06,
            "Meals Fresh": 0.05,
            "Chicken": 0.04,
            # Basics - ~15%
            "Eggs": 0.04,
            "Bread": 0.03,
            "Pasta & Rice": 0.03,
            "Soft Drinks": 0.03,
            "Water": 0.02,
            # Occasional
            "Fruit": 0.02,
            "Vegetables": 0.02,
            "Personal Care": 0.01,
        },
        "avg_receipts_per_month": 14,  # Frequent smaller trips
        "avg_items_per_receipt": (4, 10),  # Smaller baskets
    },
}


def generate_shopping_data(
    user_id: str,
    persona_name: str = "mixed",
    start_date: date = None,
    end_date: date = None,
    num_months: int = 3,
) -> tuple[list[dict], list[dict]]:
    """Generate realistic shopping receipts and transactions for a persona."""

    persona = PERSONAS.get(persona_name, PERSONAS["mixed"])

    if end_date is None:
        end_date = date.today()
    if start_date is None:
        start_date = end_date - timedelta(days=num_months * 30)

    receipts = []
    transactions = []

    # Get category list and weights
    categories = list(persona["category_weights"].keys())
    weights = list(persona["category_weights"].values())

    # Normalize weights
    total_weight = sum(weights)
    weights = [w / total_weight for w in weights]

    # Calculate number of receipts
    days_span = (end_date - start_date).days
    months_span = days_span / 30
    num_receipts = int(persona["avg_receipts_per_month"] * months_span)

    # Generate receipt dates (randomly distributed)
    receipt_dates = []
    for _ in range(num_receipts):
        days_offset = random.randint(0, days_span)
        receipt_date = start_date + timedelta(days=days_offset)
        receipt_dates.append(receipt_date)
    receipt_dates.sort()

    # Preferred stores weighted selection
    preferred_stores = persona["preferred_stores"]
    all_stores = list(STORES.keys())

    for receipt_date in receipt_dates:
        receipt_id = str(uuid.uuid4())

        # Pick store (80% preferred, 20% any)
        if random.random() < 0.8 and preferred_stores:
            store = random.choice(preferred_stores)
        else:
            store = random.choice(all_stores)

        # Generate items
        min_items, max_items = persona["avg_items_per_receipt"]
        num_items = random.randint(min_items, max_items)

        # Pick categories for this receipt
        selected_categories = random.choices(categories, weights=weights, k=num_items)

        receipt_total = 0.0
        shop_time = datetime.combine(
            receipt_date,
            datetime.min.time()
        ) + timedelta(hours=random.randint(8, 20), minutes=random.randint(0, 59))

        for category in selected_categories:
            if category not in PRODUCTS or not PRODUCTS[category]:
                continue

            # Pick a product
            product = random.choice(PRODUCTS[category])
            item_name, normalized_name, brand, unit_price, health_score, granular_cat, parent_cat = product

            # Quantity (usually 1, sometimes 2-3)
            quantity = 1
            if random.random() < 0.15:
                quantity = random.randint(2, 3)

            line_total = round(unit_price * quantity, 2)
            receipt_total += line_total

            transactions.append({
                "id": str(uuid.uuid4()),
                "user_id": user_id,
                "receipt_id": receipt_id,
                "store_name": store,
                "item_name": item_name,
                "item_price": line_total,
                "quantity": quantity,
                "unit_price": unit_price,
                "category": parent_cat,
                "date": receipt_date,
                "created_at": shop_time,
                "health_score": health_score,
                "normalized_name": normalized_name,
                "normalized_brand": brand,
                "granular_category": granular_cat,
                "original_description": item_name,
                "is_premium": STORES.get(store, {}).get("premium", False),
                "is_discount": random.random() < 0.1,
                "is_deposit": False,
            })

        upload_time = shop_time + timedelta(minutes=random.randint(10, 120))
        process_time = upload_time + timedelta(seconds=random.randint(30, 300))

        receipts.append({
            "id": receipt_id,
            "user_id": user_id,
            "original_filename": f"receipt_{receipt_date.strftime('%Y%m%d')}_{random.randint(100, 999)}.jpg",
            "file_type": "jpg",
            "file_size_bytes": random.randint(50000, 2000000),
            "status": "COMPLETED",  # PostgreSQL enum (uppercase)
            "source": "receipt_upload",  # PostgreSQL enum (lowercase)
            "error_message": None,
            "store_name": store,
            "receipt_date": receipt_date,
            "total_amount": round(receipt_total, 2),
            "created_at": upload_time,
            "processed_at": process_time,
        })

    return receipts, transactions


async def create_test_user(
    firebase_uid: str = None,
    email: str = None,
    display_name: str = None,
    persona: str = "mixed",
    num_months: int = 3,
) -> dict:
    """Create a test user with synthetic shopping data."""

    if firebase_uid is None:
        firebase_uid = str(uuid.uuid4())

    user_id = str(uuid.uuid4())

    if email is None:
        email = f"testuser_{firebase_uid[:8]}@scandelicious.test"

    if display_name is None:
        display_name = f"Test User ({persona})"

    print(f"Creating test user:")
    print(f"  firebase_uid: {firebase_uid}")
    print(f"  user_id: {user_id}")
    print(f"  email: {email}")
    print(f"  persona: {persona}")
    print(f"  num_months: {num_months}")

    # Generate shopping data
    end_date = date.today()
    start_date = end_date - timedelta(days=num_months * 30)

    receipts, transactions = generate_shopping_data(
        user_id=user_id,
        persona_name=persona,
        start_date=start_date,
        end_date=end_date,
    )

    print(f"\nGenerated:")
    print(f"  Receipts: {len(receipts)}")
    print(f"  Transactions: {len(transactions)}")

    # Insert into database
    conn = await asyncpg.connect(**DB_CONFIG)

    try:
        async with conn.transaction():
            # Create user
            await conn.execute("""
                INSERT INTO users (id, firebase_uid, email, display_name, is_active, created_at)
                VALUES ($1, $2, $3, $4, true, NOW())
            """, user_id, firebase_uid, email, display_name)

            # Create receipts
            for r in receipts:
                await conn.execute("""
                    INSERT INTO receipts (
                        id, user_id, original_filename, file_type, file_size_bytes,
                        status, source, error_message, store_name, receipt_date,
                        total_amount, created_at, processed_at
                    ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13)
                """,
                    r["id"], r["user_id"], r["original_filename"], r["file_type"],
                    r["file_size_bytes"], r["status"], r["source"], r["error_message"],
                    r["store_name"], r["receipt_date"], r["total_amount"],
                    r["created_at"], r["processed_at"]
                )

            # Create transactions
            for t in transactions:
                await conn.execute("""
                    INSERT INTO transactions (
                        id, user_id, receipt_id, store_name, item_name, item_price,
                        quantity, unit_price, category, date, created_at,
                        health_score, normalized_name, normalized_brand,
                        granular_category, original_description,
                        is_premium, is_discount, is_deposit
                    ) VALUES (
                        $1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11,
                        $12, $13, $14, $15, $16, $17, $18, $19
                    )
                """,
                    t["id"], t["user_id"], t["receipt_id"], t["store_name"],
                    t["item_name"], t["item_price"], t["quantity"], t["unit_price"],
                    t["category"], t["date"], t["created_at"], t["health_score"],
                    t["normalized_name"], t["normalized_brand"], t["granular_category"],
                    t["original_description"], t["is_premium"], t["is_discount"],
                    t["is_deposit"]
                )

            print("\nInserted into database successfully!")

    finally:
        await conn.close()

    return {
        "user_id": user_id,
        "firebase_uid": firebase_uid,
        "email": email,
        "persona": persona,
        "receipts_count": len(receipts),
        "transactions_count": len(transactions),
        "date_range": f"{start_date} to {end_date}",
    }


async def rebuild_enriched_profile(user_id: str):
    """Build enriched profile directly using asyncpg.

    This is a simplified version that creates promo_interest_items from
    the user's transaction data without requiring the full SQLAlchemy stack.
    """
    import json
    from collections import defaultdict

    conn = await asyncpg.connect(**DB_CONFIG)

    try:
        # Fetch all transactions for this user
        rows = await conn.fetch("""
            SELECT
                t.normalized_name,
                t.normalized_brand,
                t.granular_category,
                t.category,
                t.item_price,
                t.quantity,
                t.health_score,
                t.date,
                r.store_name
            FROM transactions t
            JOIN receipts r ON t.receipt_id = r.id
            WHERE t.user_id = $1
            ORDER BY t.date DESC
        """, user_id)

        if not rows:
            print(f"No transactions found for user {user_id}")
            return

        # Aggregate by normalized_name
        item_data: dict = defaultdict(lambda: {
            "total_spend": 0.0,
            "count": 0,
            "brands": set(),
            "categories": set(),
            "granular_categories": set(),
            "health_scores": [],
            "stores": set(),
            "dates": set(),
        })

        store_spend: dict = defaultdict(float)
        total_spend = 0.0
        min_date = None
        max_date = None

        for row in rows:
            name = (row["normalized_name"] or "").lower().strip()
            if not name or name in ("leeggoed", "vidange", "statiegeld"):
                continue

            data = item_data[name]
            data["total_spend"] += row["item_price"]
            data["count"] += row["quantity"]
            if row["normalized_brand"]:
                data["brands"].add(row["normalized_brand"])
            if row["category"]:
                data["categories"].add(row["category"])
            if row["granular_category"]:
                data["granular_categories"].add(row["granular_category"])
            if row["health_score"] is not None:
                data["health_scores"].append(row["health_score"])
            if row["store_name"]:
                data["stores"].add(row["store_name"])
                store_spend[row["store_name"]] += row["item_price"]
            data["dates"].add(row["date"])

            total_spend += row["item_price"]
            if min_date is None or row["date"] < min_date:
                min_date = row["date"]
            if max_date is None or row["date"] > max_date:
                max_date = row["date"]

        # Build promo_interest_items (top items by spend)
        sorted_items = sorted(item_data.items(), key=lambda x: x[1]["total_spend"], reverse=True)

        promo_interest_items = []
        for name, data in sorted_items[:25]:
            granular_cat = list(data["granular_categories"])[0] if data["granular_categories"] else None
            avg_health = sum(data["health_scores"]) / len(data["health_scores"]) if data["health_scores"] else None

            promo_interest_items.append({
                "normalized_name": name,
                "brands": list(data["brands"]),
                "granular_category": granular_cat,
                "tags": [],
                "last_purchased": max(data["dates"]).isoformat() if data["dates"] else None,
                "days_since_last_purchase": (date.today() - max(data["dates"])).days if data["dates"] else None,
                "avg_days_between_purchases": None,
                "preferred_days": [],
                "context": f"Bought {data['count']}x, spent €{data['total_spend']:.2f}",
                "interest_category": "top_purchase",
                "interest_reason": f"Top spend item (€{data['total_spend']:.2f})",
            })

        # Build shopping_habits
        sorted_stores = sorted(store_spend.items(), key=lambda x: x[1], reverse=True)
        preferred_stores = [
            {
                "name": store,
                "spend": round(spend, 2),
                "pct": round(spend / total_spend * 100, 1) if total_spend > 0 else 0,
                "visits": 1,  # Placeholder - would need to count unique receipt days
            }
            for store, spend in sorted_stores[:5]
        ]

        shopping_habits = {
            "total_spend": round(total_spend, 2),
            "preferred_stores": preferred_stores,
            "avg_health_score": None,
            "premium_ratio": 0,
            "top_granular_categories": [],
        }

        # Count receipts
        receipt_count = await conn.fetchval(
            "SELECT COUNT(*) FROM receipts WHERE user_id = $1",
            user_id
        )

        # Upsert enriched profile
        await conn.execute("""
            INSERT INTO user_enriched_profiles (
                user_id, shopping_habits, promo_interest_items,
                data_period_start, data_period_end, receipts_analyzed,
                last_rebuilt_at, created_at
            ) VALUES ($1, $2, $3, $4, $5, $6, NOW(), NOW())
            ON CONFLICT (user_id) DO UPDATE SET
                shopping_habits = EXCLUDED.shopping_habits,
                promo_interest_items = EXCLUDED.promo_interest_items,
                data_period_start = EXCLUDED.data_period_start,
                data_period_end = EXCLUDED.data_period_end,
                receipts_analyzed = EXCLUDED.receipts_analyzed,
                last_rebuilt_at = NOW(),
                updated_at = NOW()
        """,
            user_id,
            json.dumps(shopping_habits),
            json.dumps(promo_interest_items),
            min_date,
            max_date,
            receipt_count
        )

        print(f"\nEnriched profile rebuilt!")
        print(f"  Promo interest items: {len(promo_interest_items)}")
        print(f"  Receipts analyzed: {receipt_count}")
        print(f"  Date range: {min_date} to {max_date}")

    finally:
        await conn.close()


def list_personas():
    """Print available personas."""
    print("\nAvailable personas:")
    print("-" * 60)
    for name, config in PERSONAS.items():
        print(f"\n  {name}:")
        print(f"    {config['description']}")
        print(f"    Preferred stores: {', '.join(config['preferred_stores'])}")
        print(f"    Avg receipts/month: {config['avg_receipts_per_month']}")


async def main():
    import argparse

    parser = argparse.ArgumentParser(description="Create test user with synthetic Belgian shopping data")
    parser.add_argument("--persona", "-p", default="mixed", help="Shopper persona (health_conscious, budget_shopper, indulgent, family_shopper, mixed)")
    parser.add_argument("--months", "-m", type=int, default=3, help="Number of months of shopping history")
    parser.add_argument("--email", "-e", help="User email")
    parser.add_argument("--name", "-n", help="Display name")
    parser.add_argument("--firebase-uid", "-f", help="Firebase UID (optional, will generate if not provided)")
    parser.add_argument("--list-personas", "-l", action="store_true", help="List available personas")
    parser.add_argument("--rebuild-profile", "-r", action="store_true", help="Rebuild enriched profile after creating user")

    args = parser.parse_args()

    if args.list_personas:
        list_personas()
        return

    if args.persona not in PERSONAS:
        print(f"Unknown persona: {args.persona}")
        list_personas()
        return

    result = await create_test_user(
        firebase_uid=args.firebase_uid,
        email=args.email,
        display_name=args.name,
        persona=args.persona,
        num_months=args.months,
    )

    print("\n" + "=" * 60)
    print("TEST USER CREATED SUCCESSFULLY")
    print("=" * 60)
    for key, value in result.items():
        print(f"  {key}: {value}")

    if args.rebuild_profile:
        print("\nRebuilding enriched profile...")
        await rebuild_enriched_profile(result["user_id"])
    else:
        print("\nTo rebuild enriched profile, run:")
        print(f"  python testbench/create_test_user_db.py --rebuild-profile")
        print(f"  Or upload a receipt through the app with firebase_uid: {result['firebase_uid']}")


if __name__ == "__main__":
    asyncio.run(main())
