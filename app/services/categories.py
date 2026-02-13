"""
Granular category definitions for semantic categorization.

Maps ~200 granular categories to the parent categories defined in categories.csv.
Used by GeminiVisionService for detailed product classification.

Category names are kept flat (no parentheses) to optimize for semantic search
and embedding similarity matching.
"""

# Parent category name constants (must match categories.csv exactly)
_FRUITS = "Fruits"
_VEGETABLES = "Vegetables"
_MEAT_RAW = "Meat & Poultry (Raw)"
_CHARCUTERIE = "Charcuterie & Salads (Preparé/Deli)"
_FISH = "Fish & Seafood"
_DAIRY = "Dairy, Eggs & Cheese"
_BAKERY = "Bakery (Bread, Pistolets)"
_PASTRIES = "Pastries & Koffiekoeken"
_GRAINS = "Grains, Pasta & Potatoes"
_CANNED = "Canned & Jarred Goods"
_SAUCES = "Sauces, Mayo & Condiments"
_BREAKFAST = "Breakfast & Cereal (Choco/Jam)"
_BAKING = "Baking & Flour"
_FROZEN_INGR = "Frozen Ingredients (Veg/Fruit)"
_FRIES = "Fries & Snacks (Frituur at home)"
_READY_MEALS = "Ready Meals & Pizza"
_WATER = "Water (Bottled)"
_SODA = "Soda & Juices"
_COFFEE = "Coffee & Tea"
_ALCOHOL = "Alcohol (Beer, Cider, Wine, Whisky, Vodka, Gin, Cava, Champagne)"
_CHIPS = "Chips, Nuts & Aperitif"
_CHOCOLATE = "Chocolate & Sweets (Biscuits)"
_WASTE_BAGS = "Official Waste Bags (PMD/Rest)"
_CLEANING = "Cleaning & Paper Goods"
_PHARMACY = "Pharmacy & Hygiene"
_BABY = "Baby & Kids"
_PET = "Pet Supplies"
_TOBACCO = "Tobacco"
_LOTTERY = "Lottery & Scratch Cards"
_DEPOSITS = "Deposits (Statiegeld/Vidange)"
_OTHER = "Other"


# Mapping of granular categories to parent categories (string-based)
GRANULAR_CATEGORIES: dict[str, str] = {
    # ===================
    # ALCOHOL
    # ===================
    "Beer Pils": _ALCOHOL,
    "Beer Abbey Trappist": _ALCOHOL,
    "Beer Special": _ALCOHOL,
    "Beer White Fruit": _ALCOHOL,
    "Beer Non-Alcoholic": _SODA,  # Non-alcoholic
    "Cider": _ALCOHOL,
    "Wine Red": _ALCOHOL,
    "Wine White": _ALCOHOL,
    "Wine Rosé": _ALCOHOL,
    "Wine Sparkling": _ALCOHOL,
    "Spirits Whisky": _ALCOHOL,
    "Spirits Gin": _ALCOHOL,
    "Spirits Vodka": _ALCOHOL,
    "Spirits Rum": _ALCOHOL,
    "Spirits Liqueur": _ALCOHOL,
    "Aperitif": _ALCOHOL,

    # ===================
    # DRINKS
    # ===================
    "Cola": _SODA,
    "Lemonade & Soda": _SODA,
    "Energy Drinks": _SODA,
    "Ice Tea": _SODA,
    "Fruit Juice": _SODA,
    "Vegetable Juice": _SODA,
    "Smoothies": _SODA,
    "Syrup": _SODA,
    "Water Still": _WATER,
    "Water Sparkling": _WATER,
    "Water Flavored": _WATER,

    # ===================
    # HOT BEVERAGES
    # ===================
    "Coffee Beans Ground": _COFFEE,
    "Coffee Capsules": _COFFEE,
    "Coffee Instant": _COFFEE,
    "Tea": _COFFEE,
    "Hot Chocolate": _COFFEE,

    # ===================
    # DAIRY, EGGS & CHEESE
    # ===================
    "Plant Milk": _DAIRY,
    "Milk Fresh": _DAIRY,
    "Milk Long Life": _DAIRY,
    "Cream": _DAIRY,
    "Yoghurt Natural": _DAIRY,
    "Yoghurt Fruit": _DAIRY,
    "Yoghurt Drinks": _DAIRY,
    "Skyr & Quark": _DAIRY,
    "Pudding & Desserts": _DAIRY,
    "Butter": _DAIRY,
    "Margarine": _DAIRY,
    "Cooking Fat": _DAIRY,
    "Cheese Hard": _DAIRY,
    "Cheese Soft": _DAIRY,
    "Cheese Blue": _DAIRY,
    "Cheese Fresh": _DAIRY,
    "Cheese Spread": _DAIRY,
    "Cheese Sliced": _DAIRY,
    "Cheese Grated": _DAIRY,
    "Cheese Belgian": _DAIRY,
    "Eggs": _DAIRY,

    # ===================
    # MEAT & POULTRY (RAW)
    # ===================
    "Beef": _MEAT_RAW,
    "Pork": _MEAT_RAW,
    "Chicken": _MEAT_RAW,
    "Turkey": _MEAT_RAW,
    "Lamb": _MEAT_RAW,
    "Minced Meat": _MEAT_RAW,
    "Meat Preparations": _MEAT_RAW,
    "Offal": _MEAT_RAW,

    # ===================
    # CHARCUTERIE & SALADS (PREPARÉ/DELI)
    # ===================
    "Ham Cooked": _CHARCUTERIE,
    "Ham Dry": _CHARCUTERIE,
    "Salami & Sausage": _CHARCUTERIE,
    "Pâté & Terrine": _CHARCUTERIE,
    "Bacon & Lardons": _CHARCUTERIE,
    "Chicken Turkey Deli": _CHARCUTERIE,
    "Vegetarian Deli": _CHARCUTERIE,
    "Meals Salads": _CHARCUTERIE,
    "Sandwiches": _CHARCUTERIE,
    "Sushi": _CHARCUTERIE,
    "Hummus & Dips": _CHARCUTERIE,

    # ===================
    # FISH & SEAFOOD
    # ===================
    "Fish Fresh": _FISH,
    "Fish Smoked": _FISH,
    "Fish Frozen": _FISH,
    "Shellfish": _FISH,
    "Canned Fish": _FISH,
    "Surimi": _FISH,

    # ===================
    # FRUITS
    # ===================
    "Fruit Apples Pears": _FRUITS,
    "Fruit Citrus": _FRUITS,
    "Fruit Bananas": _FRUITS,
    "Fruit Berries": _FRUITS,
    "Fruit Stone": _FRUITS,
    "Fruit Grapes": _FRUITS,
    "Fruit Melons": _FRUITS,
    "Fruit Tropical": _FRUITS,
    "Fruit Dried": _FRUITS,
    "Nuts": _FRUITS,

    # ===================
    # VEGETABLES
    # ===================
    "Tomatoes": _VEGETABLES,
    "Salad & Leafy Greens": _VEGETABLES,
    "Cucumber & Peppers": _VEGETABLES,
    "Onions & Garlic": _VEGETABLES,
    "Carrots & Root Veg": _VEGETABLES,
    "Potatoes": _VEGETABLES,
    "Cabbage & Broccoli": _VEGETABLES,
    "Beans & Peas": _VEGETABLES,
    "Mushrooms": _VEGETABLES,
    "Zucchini & Eggplant": _VEGETABLES,
    "Corn": _VEGETABLES,
    "Fresh Herbs": _VEGETABLES,
    "Prepared Vegetables": _VEGETABLES,

    # ===================
    # BAKERY (BREAD, PISTOLETS)
    # ===================
    "Bread Fresh": _BAKERY,
    "Bread Sliced": _BAKERY,
    "Bread Specialty": _BAKERY,
    "Wraps & Pita": _BAKERY,
    "Crackers": _BAKERY,

    # ===================
    # PASTRIES & KOFFIEKOEKEN
    # ===================
    "Croissants & Pastries": _PASTRIES,
    "Cakes & Tarts": _PASTRIES,
    "Waffles": _PASTRIES,

    # ===================
    # GRAINS, PASTA & POTATOES
    # ===================
    "Pasta Dry": _GRAINS,
    "Pasta Fresh": _GRAINS,
    "Rice": _GRAINS,
    "Noodles Asian": _GRAINS,
    "Couscous & Bulgur": _GRAINS,
    "Grains & Legumes": _GRAINS,

    # ===================
    # CANNED & JARRED GOODS
    # ===================
    "Canned Tomatoes": _CANNED,
    "Canned Vegetables": _CANNED,
    "Canned Beans": _CANNED,
    "Canned Fruits": _CANNED,
    "Pickles & Olives": _CANNED,
    "Jarred Antipasti": _CANNED,
    "Soup Canned": _CANNED,
    "Soup Carton Fresh": _CANNED,
    "Soup Instant": _CANNED,

    # ===================
    # SAUCES, MAYO & CONDIMENTS
    # ===================
    "Pasta Sauce": _SAUCES,
    "Tomato Sauce & Ketchup": _SAUCES,
    "Mayonnaise": _SAUCES,
    "Mustard": _SAUCES,
    "Soy & Asian Sauce": _SAUCES,
    "BBQ Sauce": _SAUCES,
    "Salad Dressing": _SAUCES,
    "Vinegar": _SAUCES,
    "Olive Oil": _SAUCES,
    "Cooking Oil": _SAUCES,
    "Salt Pepper & Spices": _SAUCES,
    "Stock & Bouillon": _SAUCES,
    "Dried Herbs": _SAUCES,

    # ===================
    # BREAKFAST & CEREAL (CHOCO/JAM)
    # ===================
    "Cereals": _BREAKFAST,
    "Oatmeal": _BREAKFAST,
    "Spreads Chocolate": _BREAKFAST,
    "Spreads Jam": _BREAKFAST,
    "Spreads Honey": _BREAKFAST,
    "Spreads Peanut Nut": _BREAKFAST,
    "Spreads Savory": _BREAKFAST,

    # ===================
    # BAKING & FLOUR
    # ===================
    "Flour": _BAKING,
    "Sugar": _BAKING,
    "Baking Ingredients": _BAKING,
    "Baking Decorations": _BAKING,
    "Chocolate Baking": _BAKING,

    # ===================
    # CHIPS, NUTS & APERITIF (SNACKS)
    # ===================
    "Chips": _CHIPS,
    "Nuts Snack": _CHIPS,
    "Crackers Snack": _CHIPS,
    "Popcorn": _CHIPS,
    "Dried Meat Snack": _CHIPS,
    "Cookies & Biscuits": _CHIPS,
    "Protein Bars": _CHIPS,

    # ===================
    # CHOCOLATE & SWEETS (BISCUITS)
    # ===================
    "Chocolate Bars": _CHOCOLATE,
    "Chocolate Pralines": _CHOCOLATE,
    "Candy": _CHOCOLATE,
    "Licorice": _CHOCOLATE,
    "Gum & Mints": _CHOCOLATE,
    "Marshmallows": _CHOCOLATE,

    # ===================
    # FROZEN INGREDIENTS (VEG/FRUIT)
    # ===================
    "Frozen Vegetables": _FROZEN_INGR,
    "Frozen Fish": _FROZEN_INGR,
    "Frozen Meat": _FROZEN_INGR,
    "Frozen Bread": _FROZEN_INGR,
    "Frozen Fruits": _FROZEN_INGR,

    # ===================
    # FRIES & SNACKS (FRITUUR AT HOME)
    # ===================
    "Frozen Fries": _FRIES,
    "Frozen Snacks": _FRIES,
    "Ice Cream": _FRIES,
    "Frozen Desserts": _FRIES,

    # ===================
    # READY MEALS & PIZZA
    # ===================
    "Frozen Pizza": _READY_MEALS,
    "Frozen Meals": _READY_MEALS,
    "Meals Fresh": _READY_MEALS,
    "Pizza Fresh": _READY_MEALS,
    "Meat Substitute": _READY_MEALS,
    "Vegetarian Meals": _READY_MEALS,
    "Vegan Cheese Dairy": _READY_MEALS,
    "Asian Food": _READY_MEALS,
    "Mexican Food": _READY_MEALS,
    "Italian Specialty": _READY_MEALS,
    "Middle Eastern": _READY_MEALS,

    # ===================
    # SPORTS NUTRITION
    # ===================
    "Protein Shakes": _DAIRY,
    "Protein Desserts": _DAIRY,

    # ===================
    # BABY & KIDS
    # ===================
    "Baby Milk": _BABY,
    "Baby Food": _BABY,
    "Baby Snacks": _BABY,
    "Diapers": _BABY,
    "Baby Care": _BABY,

    # ===================
    # HOUSEHOLD - WASTE BAGS
    # ===================
    "Trash Bags": _WASTE_BAGS,

    # ===================
    # HOUSEHOLD - CLEANING & PAPER
    # ===================
    "Cleaning All-Purpose": _CLEANING,
    "Cleaning Kitchen": _CLEANING,
    "Cleaning Bathroom": _CLEANING,
    "Cleaning Floor": _CLEANING,
    "Cleaning Glass": _CLEANING,
    "Cleaning WC": _CLEANING,
    "Cleaning Tools": _CLEANING,
    "Laundry Detergent": _CLEANING,
    "Laundry Softener": _CLEANING,
    "Laundry Stain Remover": _CLEANING,
    "Laundry Ironing": _CLEANING,
    "Toilet Paper": _CLEANING,
    "Kitchen Paper": _CLEANING,
    "Tissues": _CLEANING,
    "Napkins": _CLEANING,
    "Batteries": _CLEANING,
    "Lightbulbs": _CLEANING,
    "Kitchen Accessories": _CLEANING,
    "Party Supplies": _CLEANING,
    "Flowers & Plants": _CLEANING,

    # ===================
    # PERSONAL CARE / PHARMACY & HYGIENE
    # ===================
    "Shower Gel": _PHARMACY,
    "Soap": _PHARMACY,
    "Deodorant": _PHARMACY,
    "Body Lotion": _PHARMACY,
    "Sunscreen": _PHARMACY,
    "Shampoo": _PHARMACY,
    "Conditioner": _PHARMACY,
    "Hair Styling": _PHARMACY,
    "Hair Color": _PHARMACY,
    "Face Care": _PHARMACY,
    "Toothpaste": _PHARMACY,
    "Toothbrush": _PHARMACY,
    "Mouthwash": _PHARMACY,
    "Shaving": _PHARMACY,
    "Feminine Hygiene": _PHARMACY,
    "Contraception": _PHARMACY,
    "First Aid": _PHARMACY,
    "Vitamins & Supplements": _PHARMACY,
    "Pain Relief": _PHARMACY,

    # ===================
    # PET SUPPLIES
    # ===================
    "Pet Food Dog": _PET,
    "Pet Food Cat": _PET,
    "Pet Treats": _PET,
    "Pet Litter": _PET,
    "Pet Care": _PET,

    # ===================
    # TOBACCO
    # ===================
    "Tobacco": _TOBACCO,

    # ===================
    # DEPOSITS & DISCOUNTS
    # ===================
    "Discounts": _DEPOSITS,

    # ===================
    # OTHER
    # ===================
    "Other": _OTHER,
}


def get_parent_category(granular: str) -> str:
    """Get parent category for a granular category, defaulting to Other."""
    return GRANULAR_CATEGORIES.get(granular, _OTHER)


def get_all_granular_categories() -> list[str]:
    """Get list of all valid granular categories for Gemini prompt."""
    return list(GRANULAR_CATEGORIES.keys())


# Pre-formatted category list for LLM prompts.
# Both receipt extraction and promo extraction prompts should use this
# so category names always match between pipelines.
CATEGORIES_PROMPT_LIST: str = "\n".join(
    f"- {cat}" for cat in GRANULAR_CATEGORIES.keys()
)


def validate_granular_category(granular: str) -> bool:
    """Check if a granular category is valid."""
    return granular in GRANULAR_CATEGORIES
