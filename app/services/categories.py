"""
Granular category definitions for semantic categorization.

Maps ~200 granular categories to the 15 parent categories.
Used by GeminiVisionService for detailed product classification.

Category names are kept flat (no parentheses) to optimize for semantic search
and embedding similarity matching.
"""

from app.models.enums import Category

# Mapping of granular categories to parent categories
GRANULAR_CATEGORIES: dict[str, Category] = {
    # ===================
    # ALCOHOL
    # ===================
    "Beer Pils": Category.ALCOHOL,
    "Beer Abbey Trappist": Category.ALCOHOL,
    "Beer Special": Category.ALCOHOL,
    "Beer White Fruit": Category.ALCOHOL,
    "Beer Non-Alcoholic": Category.DRINKS_SOFT_SODA,  # Non-alcoholic
    "Cider": Category.ALCOHOL,
    "Wine Red": Category.ALCOHOL,
    "Wine White": Category.ALCOHOL,
    "Wine Rosé": Category.ALCOHOL,
    "Wine Sparkling": Category.ALCOHOL,
    "Spirits Whisky": Category.ALCOHOL,
    "Spirits Gin": Category.ALCOHOL,
    "Spirits Vodka": Category.ALCOHOL,
    "Spirits Rum": Category.ALCOHOL,
    "Spirits Liqueur": Category.ALCOHOL,
    "Aperitif": Category.ALCOHOL,

    # ===================
    # DRINKS (SOFT/SODA)
    # ===================
    "Cola": Category.DRINKS_SOFT_SODA,
    "Lemonade & Soda": Category.DRINKS_SOFT_SODA,
    "Energy Drinks": Category.DRINKS_SOFT_SODA,
    "Ice Tea": Category.DRINKS_SOFT_SODA,
    "Fruit Juice": Category.DRINKS_SOFT_SODA,
    "Vegetable Juice": Category.DRINKS_SOFT_SODA,
    "Smoothies": Category.DRINKS_SOFT_SODA,
    "Syrup": Category.DRINKS_SOFT_SODA,

    # ===================
    # DRINKS (WATER)
    # ===================
    "Water Still": Category.DRINKS_WATER,
    "Water Sparkling": Category.DRINKS_WATER,
    "Water Flavored": Category.DRINKS_WATER,

    # ===================
    # HOT BEVERAGES (mapped to PANTRY)
    # ===================
    "Coffee Beans Ground": Category.PANTRY,
    "Coffee Capsules": Category.PANTRY,
    "Coffee Instant": Category.PANTRY,
    "Tea": Category.PANTRY,
    "Hot Chocolate": Category.PANTRY,

    # ===================
    # DAIRY & EGGS
    # ===================
    "Plant Milk": Category.DAIRY_EGGS,
    "Milk Fresh": Category.DAIRY_EGGS,
    "Milk Long Life": Category.DAIRY_EGGS,
    "Cream": Category.DAIRY_EGGS,
    "Yoghurt Natural": Category.DAIRY_EGGS,
    "Yoghurt Fruit": Category.DAIRY_EGGS,
    "Yoghurt Drinks": Category.DAIRY_EGGS,
    "Skyr & Quark": Category.DAIRY_EGGS,
    "Pudding & Desserts": Category.DAIRY_EGGS,
    "Butter": Category.DAIRY_EGGS,
    "Margarine": Category.DAIRY_EGGS,
    "Cooking Fat": Category.DAIRY_EGGS,
    "Cheese Hard": Category.DAIRY_EGGS,
    "Cheese Soft": Category.DAIRY_EGGS,
    "Cheese Blue": Category.DAIRY_EGGS,
    "Cheese Fresh": Category.DAIRY_EGGS,
    "Cheese Spread": Category.DAIRY_EGGS,
    "Cheese Sliced": Category.DAIRY_EGGS,
    "Cheese Grated": Category.DAIRY_EGGS,
    "Cheese Belgian": Category.DAIRY_EGGS,
    "Eggs": Category.DAIRY_EGGS,

    # ===================
    # MEAT & FISH
    # ===================
    "Beef": Category.MEAT_FISH,
    "Pork": Category.MEAT_FISH,
    "Chicken": Category.MEAT_FISH,
    "Turkey": Category.MEAT_FISH,
    "Lamb": Category.MEAT_FISH,
    "Minced Meat": Category.MEAT_FISH,
    "Meat Preparations": Category.MEAT_FISH,
    "Offal": Category.MEAT_FISH,
    "Ham Cooked": Category.MEAT_FISH,
    "Ham Dry": Category.MEAT_FISH,
    "Salami & Sausage": Category.MEAT_FISH,
    "Pâté & Terrine": Category.MEAT_FISH,
    "Bacon & Lardons": Category.MEAT_FISH,
    "Chicken Turkey Deli": Category.MEAT_FISH,
    "Vegetarian Deli": Category.MEAT_FISH,
    "Fish Fresh": Category.MEAT_FISH,
    "Fish Smoked": Category.MEAT_FISH,
    "Fish Frozen": Category.MEAT_FISH,
    "Shellfish": Category.MEAT_FISH,
    "Canned Fish": Category.MEAT_FISH,
    "Surimi": Category.MEAT_FISH,

    # ===================
    # FRESH PRODUCE
    # ===================
    "Fruit Apples Pears": Category.FRESH_PRODUCE,
    "Fruit Citrus": Category.FRESH_PRODUCE,
    "Fruit Bananas": Category.FRESH_PRODUCE,
    "Fruit Berries": Category.FRESH_PRODUCE,
    "Fruit Stone": Category.FRESH_PRODUCE,
    "Fruit Grapes": Category.FRESH_PRODUCE,
    "Fruit Melons": Category.FRESH_PRODUCE,
    "Fruit Tropical": Category.FRESH_PRODUCE,
    "Fruit Dried": Category.FRESH_PRODUCE,
    "Nuts": Category.FRESH_PRODUCE,
    "Tomatoes": Category.FRESH_PRODUCE,
    "Salad & Leafy Greens": Category.FRESH_PRODUCE,
    "Cucumber & Peppers": Category.FRESH_PRODUCE,
    "Onions & Garlic": Category.FRESH_PRODUCE,
    "Carrots & Root Veg": Category.FRESH_PRODUCE,
    "Potatoes": Category.FRESH_PRODUCE,
    "Cabbage & Broccoli": Category.FRESH_PRODUCE,
    "Beans & Peas": Category.FRESH_PRODUCE,
    "Mushrooms": Category.FRESH_PRODUCE,
    "Zucchini & Eggplant": Category.FRESH_PRODUCE,
    "Corn": Category.FRESH_PRODUCE,
    "Fresh Herbs": Category.FRESH_PRODUCE,
    "Prepared Vegetables": Category.FRESH_PRODUCE,

    # ===================
    # BAKERY
    # ===================
    "Bread Fresh": Category.BAKERY,
    "Bread Sliced": Category.BAKERY,
    "Bread Specialty": Category.BAKERY,
    "Wraps & Pita": Category.BAKERY,
    "Croissants & Pastries": Category.BAKERY,
    "Cakes & Tarts": Category.BAKERY,
    "Cookies & Biscuits": Category.SNACKS_SWEETS,  # Cookies are sweets
    "Waffles": Category.BAKERY,
    "Crackers": Category.BAKERY,

    # ===================
    # PANTRY
    # ===================
    "Pasta Dry": Category.PANTRY,
    "Pasta Fresh": Category.PANTRY,
    "Rice": Category.PANTRY,
    "Noodles Asian": Category.PANTRY,
    "Couscous & Bulgur": Category.PANTRY,
    "Grains & Legumes": Category.PANTRY,
    "Canned Tomatoes": Category.PANTRY,
    "Canned Vegetables": Category.PANTRY,
    "Canned Beans": Category.PANTRY,
    "Canned Fruits": Category.PANTRY,
    "Pickles & Olives": Category.PANTRY,
    "Jarred Antipasti": Category.PANTRY,
    "Pasta Sauce": Category.PANTRY,
    "Tomato Sauce & Ketchup": Category.PANTRY,
    "Mayonnaise": Category.PANTRY,
    "Mustard": Category.PANTRY,
    "Soy & Asian Sauce": Category.PANTRY,
    "BBQ Sauce": Category.PANTRY,
    "Salad Dressing": Category.PANTRY,
    "Vinegar": Category.PANTRY,
    "Olive Oil": Category.PANTRY,
    "Cooking Oil": Category.PANTRY,
    "Salt Pepper & Spices": Category.PANTRY,
    "Stock & Bouillon": Category.PANTRY,
    "Dried Herbs": Category.PANTRY,
    "Cereals": Category.PANTRY,
    "Oatmeal": Category.PANTRY,
    "Spreads Chocolate": Category.PANTRY,
    "Spreads Jam": Category.PANTRY,
    "Spreads Honey": Category.PANTRY,
    "Spreads Peanut Nut": Category.PANTRY,
    "Spreads Savory": Category.PANTRY,
    "Soup Canned": Category.PANTRY,
    "Soup Carton Fresh": Category.PANTRY,
    "Soup Instant": Category.PANTRY,
    "Flour": Category.PANTRY,
    "Sugar": Category.PANTRY,
    "Baking Ingredients": Category.PANTRY,
    "Baking Decorations": Category.PANTRY,

    # ===================
    # SNACKS & SWEETS
    # ===================
    "Chips": Category.SNACKS_SWEETS,
    "Nuts Snack": Category.SNACKS_SWEETS,
    "Crackers Snack": Category.SNACKS_SWEETS,
    "Popcorn": Category.SNACKS_SWEETS,
    "Dried Meat Snack": Category.SNACKS_SWEETS,
    "Chocolate Bars": Category.SNACKS_SWEETS,
    "Chocolate Pralines": Category.SNACKS_SWEETS,
    "Chocolate Baking": Category.PANTRY,  # Baking ingredient
    "Candy": Category.SNACKS_SWEETS,
    "Licorice": Category.SNACKS_SWEETS,
    "Gum & Mints": Category.SNACKS_SWEETS,
    "Marshmallows": Category.SNACKS_SWEETS,

    # ===================
    # SPORTS NUTRITION
    # ===================
    "Protein Bars": Category.SNACKS_SWEETS,
    "Protein Shakes": Category.DAIRY_EGGS,
    "Protein Desserts": Category.DAIRY_EGGS,

    # ===================
    # FROZEN
    # ===================
    "Frozen Fries": Category.FROZEN,
    "Frozen Pizza": Category.FROZEN,
    "Frozen Meals": Category.FROZEN,
    "Frozen Vegetables": Category.FROZEN,
    "Frozen Fish": Category.FROZEN,
    "Frozen Meat": Category.FROZEN,
    "Frozen Snacks": Category.FROZEN,
    "Frozen Bread": Category.FROZEN,
    "Ice Cream": Category.FROZEN,
    "Frozen Desserts": Category.FROZEN,
    "Frozen Fruits": Category.FROZEN,

    # ===================
    # READY MEALS
    # ===================
    "Meals Fresh": Category.READY_MEALS,
    "Meals Salads": Category.READY_MEALS,
    "Pizza Fresh": Category.READY_MEALS,
    "Sandwiches": Category.READY_MEALS,
    "Sushi": Category.READY_MEALS,
    "Hummus & Dips": Category.READY_MEALS,
    "Meat Substitute": Category.READY_MEALS,
    "Vegetarian Meals": Category.READY_MEALS,
    "Vegan Cheese Dairy": Category.READY_MEALS,
    "Asian Food": Category.READY_MEALS,
    "Mexican Food": Category.READY_MEALS,
    "Italian Specialty": Category.READY_MEALS,
    "Middle Eastern": Category.READY_MEALS,

    # ===================
    # BABY & KIDS
    # ===================
    "Baby Milk": Category.BABY_KIDS,
    "Baby Food": Category.BABY_KIDS,
    "Baby Snacks": Category.BABY_KIDS,
    "Diapers": Category.BABY_KIDS,
    "Baby Care": Category.BABY_KIDS,

    # ===================
    # HOUSEHOLD
    # ===================
    "Cleaning All-Purpose": Category.HOUSEHOLD,
    "Cleaning Kitchen": Category.HOUSEHOLD,
    "Cleaning Bathroom": Category.HOUSEHOLD,
    "Cleaning Floor": Category.HOUSEHOLD,
    "Cleaning Glass": Category.HOUSEHOLD,
    "Cleaning WC": Category.HOUSEHOLD,
    "Cleaning Tools": Category.HOUSEHOLD,
    "Trash Bags": Category.HOUSEHOLD,
    "Laundry Detergent": Category.HOUSEHOLD,
    "Laundry Softener": Category.HOUSEHOLD,
    "Laundry Stain Remover": Category.HOUSEHOLD,
    "Laundry Ironing": Category.HOUSEHOLD,
    "Toilet Paper": Category.HOUSEHOLD,
    "Kitchen Paper": Category.HOUSEHOLD,
    "Tissues": Category.HOUSEHOLD,
    "Napkins": Category.HOUSEHOLD,
    "Batteries": Category.HOUSEHOLD,
    "Lightbulbs": Category.HOUSEHOLD,
    "Kitchen Accessories": Category.HOUSEHOLD,
    "Party Supplies": Category.HOUSEHOLD,
    "Flowers & Plants": Category.HOUSEHOLD,

    # ===================
    # PERSONAL CARE
    # ===================
    "Shower Gel": Category.PERSONAL_CARE,
    "Soap": Category.PERSONAL_CARE,
    "Deodorant": Category.PERSONAL_CARE,
    "Body Lotion": Category.PERSONAL_CARE,
    "Sunscreen": Category.PERSONAL_CARE,
    "Shampoo": Category.PERSONAL_CARE,
    "Conditioner": Category.PERSONAL_CARE,
    "Hair Styling": Category.PERSONAL_CARE,
    "Hair Color": Category.PERSONAL_CARE,
    "Face Care": Category.PERSONAL_CARE,
    "Toothpaste": Category.PERSONAL_CARE,
    "Toothbrush": Category.PERSONAL_CARE,
    "Mouthwash": Category.PERSONAL_CARE,
    "Shaving": Category.PERSONAL_CARE,
    "Feminine Hygiene": Category.PERSONAL_CARE,
    "Contraception": Category.PERSONAL_CARE,
    "First Aid": Category.PERSONAL_CARE,
    "Vitamins & Supplements": Category.PERSONAL_CARE,
    "Pain Relief": Category.PERSONAL_CARE,

    # ===================
    # PET SUPPLIES
    # ===================
    "Pet Food Dog": Category.PET_SUPPLIES,
    "Pet Food Cat": Category.PET_SUPPLIES,
    "Pet Treats": Category.PET_SUPPLIES,
    "Pet Litter": Category.PET_SUPPLIES,
    "Pet Care": Category.PET_SUPPLIES,

    # ===================
    # TOBACCO
    # ===================
    "Tobacco": Category.TOBACCO,

    # ===================
    # DISCOUNTS
    # ===================
    "Discounts": Category.OTHER,

    # ===================
    # OTHER
    # ===================
    "Other": Category.OTHER,
}


def get_parent_category(granular: str) -> Category:
    """Get parent category for a granular category, defaulting to OTHER."""
    return GRANULAR_CATEGORIES.get(granular, Category.OTHER)


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
