"""
Granular category definitions for semantic categorization.

Maps ~200 granular categories to the 15 parent categories.
Used by GeminiVisionService for detailed product classification.

Category names are kept flat (no parentheses) to optimize for semantic search
and embedding similarity matching.
"""

# Mapping of granular categories to parent categories (string-based)
GRANULAR_CATEGORIES: dict[str, str] = {
    # ===================
    # ALCOHOL
    # ===================
    "Beer Pils": "Alcohol",
    "Beer Abbey Trappist": "Alcohol",
    "Beer Special": "Alcohol",
    "Beer White Fruit": "Alcohol",
    "Beer Non-Alcoholic": "Drinks (Soft/Soda)",  # Non-alcoholic
    "Cider": "Alcohol",
    "Wine Red": "Alcohol",
    "Wine White": "Alcohol",
    "Wine Rosé": "Alcohol",
    "Wine Sparkling": "Alcohol",
    "Spirits Whisky": "Alcohol",
    "Spirits Gin": "Alcohol",
    "Spirits Vodka": "Alcohol",
    "Spirits Rum": "Alcohol",
    "Spirits Liqueur": "Alcohol",
    "Aperitif": "Alcohol",

    # ===================
    # DRINKS (SOFT/SODA)
    # ===================
    "Cola": "Drinks (Soft/Soda)",
    "Lemonade & Soda": "Drinks (Soft/Soda)",
    "Energy Drinks": "Drinks (Soft/Soda)",
    "Ice Tea": "Drinks (Soft/Soda)",
    "Fruit Juice": "Drinks (Soft/Soda)",
    "Vegetable Juice": "Drinks (Soft/Soda)",
    "Smoothies": "Drinks (Soft/Soda)",
    "Syrup": "Drinks (Soft/Soda)",

    # ===================
    # DRINKS (WATER)
    # ===================
    "Water Still": "Drinks (Water)",
    "Water Sparkling": "Drinks (Water)",
    "Water Flavored": "Drinks (Water)",

    # ===================
    # HOT BEVERAGES (mapped to PANTRY)
    # ===================
    "Coffee Beans Ground": "Pantry",
    "Coffee Capsules": "Pantry",
    "Coffee Instant": "Pantry",
    "Tea": "Pantry",
    "Hot Chocolate": "Pantry",

    # ===================
    # DAIRY & EGGS
    # ===================
    "Plant Milk": "Dairy & Eggs",
    "Milk Fresh": "Dairy & Eggs",
    "Milk Long Life": "Dairy & Eggs",
    "Cream": "Dairy & Eggs",
    "Yoghurt Natural": "Dairy & Eggs",
    "Yoghurt Fruit": "Dairy & Eggs",
    "Yoghurt Drinks": "Dairy & Eggs",
    "Skyr & Quark": "Dairy & Eggs",
    "Pudding & Desserts": "Dairy & Eggs",
    "Butter": "Dairy & Eggs",
    "Margarine": "Dairy & Eggs",
    "Cooking Fat": "Dairy & Eggs",
    "Cheese Hard": "Dairy & Eggs",
    "Cheese Soft": "Dairy & Eggs",
    "Cheese Blue": "Dairy & Eggs",
    "Cheese Fresh": "Dairy & Eggs",
    "Cheese Spread": "Dairy & Eggs",
    "Cheese Sliced": "Dairy & Eggs",
    "Cheese Grated": "Dairy & Eggs",
    "Cheese Belgian": "Dairy & Eggs",
    "Eggs": "Dairy & Eggs",

    # ===================
    # MEAT & FISH
    # ===================
    "Beef": "Meat & Fish",
    "Pork": "Meat & Fish",
    "Chicken": "Meat & Fish",
    "Turkey": "Meat & Fish",
    "Lamb": "Meat & Fish",
    "Minced Meat": "Meat & Fish",
    "Meat Preparations": "Meat & Fish",
    "Offal": "Meat & Fish",
    "Ham Cooked": "Meat & Fish",
    "Ham Dry": "Meat & Fish",
    "Salami & Sausage": "Meat & Fish",
    "Pâté & Terrine": "Meat & Fish",
    "Bacon & Lardons": "Meat & Fish",
    "Chicken Turkey Deli": "Meat & Fish",
    "Vegetarian Deli": "Meat & Fish",
    "Fish Fresh": "Meat & Fish",
    "Fish Smoked": "Meat & Fish",
    "Fish Frozen": "Meat & Fish",
    "Shellfish": "Meat & Fish",
    "Canned Fish": "Meat & Fish",
    "Surimi": "Meat & Fish",

    # ===================
    # FRESH PRODUCE
    # ===================
    "Fruit Apples Pears": "Fresh Produce",
    "Fruit Citrus": "Fresh Produce",
    "Fruit Bananas": "Fresh Produce",
    "Fruit Berries": "Fresh Produce",
    "Fruit Stone": "Fresh Produce",
    "Fruit Grapes": "Fresh Produce",
    "Fruit Melons": "Fresh Produce",
    "Fruit Tropical": "Fresh Produce",
    "Fruit Dried": "Fresh Produce",
    "Nuts": "Fresh Produce",
    "Tomatoes": "Fresh Produce",
    "Salad & Leafy Greens": "Fresh Produce",
    "Cucumber & Peppers": "Fresh Produce",
    "Onions & Garlic": "Fresh Produce",
    "Carrots & Root Veg": "Fresh Produce",
    "Potatoes": "Fresh Produce",
    "Cabbage & Broccoli": "Fresh Produce",
    "Beans & Peas": "Fresh Produce",
    "Mushrooms": "Fresh Produce",
    "Zucchini & Eggplant": "Fresh Produce",
    "Corn": "Fresh Produce",
    "Fresh Herbs": "Fresh Produce",
    "Prepared Vegetables": "Fresh Produce",

    # ===================
    # BAKERY
    # ===================
    "Bread Fresh": "Bakery",
    "Bread Sliced": "Bakery",
    "Bread Specialty": "Bakery",
    "Wraps & Pita": "Bakery",
    "Croissants & Pastries": "Bakery",
    "Cakes & Tarts": "Bakery",
    "Cookies & Biscuits": "Snacks & Sweets",  # Cookies are sweets
    "Waffles": "Bakery",
    "Crackers": "Bakery",

    # ===================
    # PANTRY
    # ===================
    "Pasta Dry": "Pantry",
    "Pasta Fresh": "Pantry",
    "Rice": "Pantry",
    "Noodles Asian": "Pantry",
    "Couscous & Bulgur": "Pantry",
    "Grains & Legumes": "Pantry",
    "Canned Tomatoes": "Pantry",
    "Canned Vegetables": "Pantry",
    "Canned Beans": "Pantry",
    "Canned Fruits": "Pantry",
    "Pickles & Olives": "Pantry",
    "Jarred Antipasti": "Pantry",
    "Pasta Sauce": "Pantry",
    "Tomato Sauce & Ketchup": "Pantry",
    "Mayonnaise": "Pantry",
    "Mustard": "Pantry",
    "Soy & Asian Sauce": "Pantry",
    "BBQ Sauce": "Pantry",
    "Salad Dressing": "Pantry",
    "Vinegar": "Pantry",
    "Olive Oil": "Pantry",
    "Cooking Oil": "Pantry",
    "Salt Pepper & Spices": "Pantry",
    "Stock & Bouillon": "Pantry",
    "Dried Herbs": "Pantry",
    "Cereals": "Pantry",
    "Oatmeal": "Pantry",
    "Spreads Chocolate": "Pantry",
    "Spreads Jam": "Pantry",
    "Spreads Honey": "Pantry",
    "Spreads Peanut Nut": "Pantry",
    "Spreads Savory": "Pantry",
    "Soup Canned": "Pantry",
    "Soup Carton Fresh": "Pantry",
    "Soup Instant": "Pantry",
    "Flour": "Pantry",
    "Sugar": "Pantry",
    "Baking Ingredients": "Pantry",
    "Baking Decorations": "Pantry",

    # ===================
    # SNACKS & SWEETS
    # ===================
    "Chips": "Snacks & Sweets",
    "Nuts Snack": "Snacks & Sweets",
    "Crackers Snack": "Snacks & Sweets",
    "Popcorn": "Snacks & Sweets",
    "Dried Meat Snack": "Snacks & Sweets",
    "Chocolate Bars": "Snacks & Sweets",
    "Chocolate Pralines": "Snacks & Sweets",
    "Chocolate Baking": "Pantry",  # Baking ingredient
    "Candy": "Snacks & Sweets",
    "Licorice": "Snacks & Sweets",
    "Gum & Mints": "Snacks & Sweets",
    "Marshmallows": "Snacks & Sweets",

    # ===================
    # SPORTS NUTRITION
    # ===================
    "Protein Bars": "Snacks & Sweets",
    "Protein Shakes": "Dairy & Eggs",
    "Protein Desserts": "Dairy & Eggs",

    # ===================
    # FROZEN
    # ===================
    "Frozen Fries": "Frozen",
    "Frozen Pizza": "Frozen",
    "Frozen Meals": "Frozen",
    "Frozen Vegetables": "Frozen",
    "Frozen Fish": "Frozen",
    "Frozen Meat": "Frozen",
    "Frozen Snacks": "Frozen",
    "Frozen Bread": "Frozen",
    "Ice Cream": "Frozen",
    "Frozen Desserts": "Frozen",
    "Frozen Fruits": "Frozen",

    # ===================
    # READY MEALS
    # ===================
    "Meals Fresh": "Ready Meals",
    "Meals Salads": "Ready Meals",
    "Pizza Fresh": "Ready Meals",
    "Sandwiches": "Ready Meals",
    "Sushi": "Ready Meals",
    "Hummus & Dips": "Ready Meals",
    "Meat Substitute": "Ready Meals",
    "Vegetarian Meals": "Ready Meals",
    "Vegan Cheese Dairy": "Ready Meals",
    "Asian Food": "Ready Meals",
    "Mexican Food": "Ready Meals",
    "Italian Specialty": "Ready Meals",
    "Middle Eastern": "Ready Meals",

    # ===================
    # BABY & KIDS
    # ===================
    "Baby Milk": "Baby & Kids",
    "Baby Food": "Baby & Kids",
    "Baby Snacks": "Baby & Kids",
    "Diapers": "Baby & Kids",
    "Baby Care": "Baby & Kids",

    # ===================
    # HOUSEHOLD
    # ===================
    "Cleaning All-Purpose": "Household",
    "Cleaning Kitchen": "Household",
    "Cleaning Bathroom": "Household",
    "Cleaning Floor": "Household",
    "Cleaning Glass": "Household",
    "Cleaning WC": "Household",
    "Cleaning Tools": "Household",
    "Trash Bags": "Household",
    "Laundry Detergent": "Household",
    "Laundry Softener": "Household",
    "Laundry Stain Remover": "Household",
    "Laundry Ironing": "Household",
    "Toilet Paper": "Household",
    "Kitchen Paper": "Household",
    "Tissues": "Household",
    "Napkins": "Household",
    "Batteries": "Household",
    "Lightbulbs": "Household",
    "Kitchen Accessories": "Household",
    "Party Supplies": "Household",
    "Flowers & Plants": "Household",

    # ===================
    # PERSONAL CARE
    # ===================
    "Shower Gel": "Personal Care",
    "Soap": "Personal Care",
    "Deodorant": "Personal Care",
    "Body Lotion": "Personal Care",
    "Sunscreen": "Personal Care",
    "Shampoo": "Personal Care",
    "Conditioner": "Personal Care",
    "Hair Styling": "Personal Care",
    "Hair Color": "Personal Care",
    "Face Care": "Personal Care",
    "Toothpaste": "Personal Care",
    "Toothbrush": "Personal Care",
    "Mouthwash": "Personal Care",
    "Shaving": "Personal Care",
    "Feminine Hygiene": "Personal Care",
    "Contraception": "Personal Care",
    "First Aid": "Personal Care",
    "Vitamins & Supplements": "Personal Care",
    "Pain Relief": "Personal Care",

    # ===================
    # PET SUPPLIES
    # ===================
    "Pet Food Dog": "Pet Supplies",
    "Pet Food Cat": "Pet Supplies",
    "Pet Treats": "Pet Supplies",
    "Pet Litter": "Pet Supplies",
    "Pet Care": "Pet Supplies",

    # ===================
    # TOBACCO
    # ===================
    "Tobacco": "Tobacco",

    # ===================
    # DISCOUNTS
    # ===================
    "Discounts": "Other",

    # ===================
    # OTHER
    # ===================
    "Other": "Other",
}


def get_parent_category(granular: str) -> str:
    """Get parent category for a granular category, defaulting to Other."""
    return GRANULAR_CATEGORIES.get(granular, "Other")


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
