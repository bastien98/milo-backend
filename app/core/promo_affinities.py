"""
Category affinity dictionary for "Discover for You" promo recommendations.

Maps granular_category → list of complementary granular categories.
When a user frequently buys items in a category, promos in its complementary
categories become candidates for the "Discover" bucket.

All category names MUST match granular categories in app/core/categories.py (_TREE).
Curated for the Belgian grocery market. Update as the taxonomy evolves.
"""

CATEGORY_AFFINITIES: dict[str, list[str]] = {
    # --- Fresh Bakery ---
    "Daily Bread": ["Cheese Sliced & Grated", "Charcuterie", "Butter & Margarine", "Sweet Spreads & Honey"],
    "Viennoiserie & Patisserie": ["Coffee Beans & Ground", "Coffee Pods & Capsules", "Fresh Milk"],

    # --- Meat & Poultry ---
    "Beef Veal Pork": ["Root Vegetables & Potatoes", "Condiments & Sauces", "Mushrooms & Other Vegetables", "Fresh Herbs"],
    "Poultry & Game": ["Staples Pasta Rice", "Fresh Herbs", "Oils & Vinegars", "Condiments & Sauces"],

    # --- Seafood ---
    "Fresh Fish": ["Fresh Herbs", "Oils & Vinegars", "Root Vegetables & Potatoes", "White Wine"],
    "Shellfish & Crustaceans": ["White Wine", "Daily Bread", "Cream"],

    # --- Deli & Convenience ---
    "Charcuterie": ["Red Wine", "Cheese Sliced & Grated", "Condiments & Sauces"],
    "Chilled Ready Meals": ["Colas", "Fruit Sodas & Lemonades", "Salty Snacks & Nuts"],
    "Fresh Tapas & Salads": ["Aperitifs & Ready-to-Drink", "Salty Snacks & Nuts", "White Wine"],
    "Plant-Based Meat Alternatives": ["Mushrooms & Other Vegetables", "Salad & Leafy Greens", "Condiments & Sauces", "Fresh Herbs"],

    # --- Dairy & Eggs ---
    "Fresh Milk": ["Breakfast & Cereals", "Coffee Beans & Ground", "Biscuits & Pastries"],
    "Long Life Milk": ["Coffee Beans & Ground", "Breakfast & Cereals", "Biscuits & Pastries"],
    "Cream": ["Staples Pasta Rice", "Mushrooms & Other Vegetables", "Coffee Beans & Ground"],
    "Cheese Hard": ["Red Wine", "Specialty & Abbey Beers", "Salty Snacks & Nuts"],
    "Cheese Soft & Blue": ["Red Wine", "White Wine", "Champagne & Sparkling Wine"],
    "Cheese Fresh & Spread": ["Daily Bread", "Salad & Leafy Greens", "Tomatoes & Peppers"],
    "Cheese Sliced & Grated": ["Daily Bread", "Charcuterie", "Staples Pasta Rice"],
    "Yoghurt Plain": ["Berries", "Sweet Spreads & Honey", "Breakfast & Cereals"],
    "Yoghurt Fruit & Drinks": ["Breakfast & Cereals", "Bananas"],
    "Butter & Margarine": ["Daily Bread", "Desserts & Home Baking", "Eggs"],
    "Eggs": ["Charcuterie", "Daily Bread", "Butter & Margarine", "Tomatoes & Peppers", "Mushrooms & Other Vegetables"],

    # --- Fruit & Vegetables ---
    "Tomatoes & Peppers": ["Salad & Leafy Greens", "Oils & Vinegars", "Fresh Herbs"],
    "Salad & Leafy Greens": ["Condiments & Sauces", "Tomatoes & Peppers", "Oils & Vinegars"],
    "Root Vegetables & Potatoes": ["Beef Veal Pork", "Poultry & Game", "Butter & Margarine"],
    "Cabbage & Broccoli": ["Beef Veal Pork", "Condiments & Sauces"],
    "Mushrooms & Other Vegetables": ["Cream", "Staples Pasta Rice", "Fresh Herbs"],
    "Fresh Herbs": ["Poultry & Game", "Fresh Fish", "Oils & Vinegars"],
    "Bananas": ["Breakfast & Cereals", "Yoghurt Plain"],
    "Berries": ["Yoghurt Plain", "Sweet Spreads & Honey", "Cream"],
    "Apples & Pears": ["Yoghurt Plain", "Sweet Spreads & Honey"],
    "Citrus Fruit": ["Still Water", "Tea Bags & Loose Tea"],
    "Stone & Tropical Fruit": ["Yoghurt Fruit & Drinks", "Cream"],

    # --- Pantry & Staples ---
    "Staples Pasta Rice": ["Condiments & Sauces", "Cheese Sliced & Grated", "Fresh Herbs", "Canned & Jarred Goods"],
    "Canned & Jarred Goods": ["Staples Pasta Rice", "Condiments & Sauces"],
    "Condiments & Sauces": ["Staples Pasta Rice", "Beef Veal Pork", "Frozen Potato Products"],
    "Soups & Bouillons": ["Daily Bread", "Cream"],
    "Oils & Vinegars": ["Salad & Leafy Greens", "Fresh Fish", "Fresh Herbs"],

    # --- Breakfast ---
    "Breakfast & Cereals": ["Fresh Milk", "Yoghurt Fruit & Drinks", "Bananas"],
    "Sweet Spreads & Honey": ["Daily Bread", "Viennoiserie & Patisserie"],

    # --- Sweets & Snacks ---
    "Biscuits & Pastries": ["Coffee Beans & Ground", "Tea Bags & Loose Tea", "Long Life Milk"],
    "Chocolate & Confectionery": ["Coffee Beans & Ground", "Long Life Milk"],
    "Salty Snacks & Nuts": ["Pilsners & Lagers", "Colas", "Fruit Sodas & Lemonades"],
    "Desserts & Home Baking": ["Butter & Margarine", "Eggs", "Cream"],

    # --- Frozen ---
    "Frozen Potato Products": ["Condiments & Sauces", "Beef Veal Pork"],
    "Frozen Ready Meals & Pizzas": ["Colas", "Salty Snacks & Nuts", "Iced Teas"],
    "Frozen Vegetables & Herbs": ["Staples Pasta Rice", "Poultry & Game"],
    "Ice Cream": ["Chocolate & Confectionery", "Berries", "Biscuits & Pastries", "Salty Snacks & Nuts"],

    # --- Coffee & Tea ---
    "Coffee Beans & Ground": ["Biscuits & Pastries", "Long Life Milk", "Cream"],
    "Coffee Pods & Capsules": ["Biscuits & Pastries", "Long Life Milk"],
    "Tea Bags & Loose Tea": ["Biscuits & Pastries", "Sweet Spreads & Honey"],

    # --- Sodas & Energy ---
    "Colas": ["Salty Snacks & Nuts", "Frozen Ready Meals & Pizzas"],
    "Fruit Sodas & Lemonades": ["Salty Snacks & Nuts", "Frozen Ready Meals & Pizzas"],
    "Energy Drinks": ["Sports Drinks", "Salty Snacks & Nuts"],
    "Iced Teas": ["Salty Snacks & Nuts", "Frozen Ready Meals & Pizzas"],

    # --- Alcohol ---
    "Pilsners & Lagers": ["Salty Snacks & Nuts", "Charcuterie"],
    "Specialty & Abbey Beers": ["Cheese Hard", "Salty Snacks & Nuts"],
    "Red Wine": ["Cheese Hard", "Cheese Soft & Blue", "Chocolate & Confectionery"],
    "White Wine": ["Fresh Fish", "Shellfish & Crustaceans", "Cheese Soft & Blue"],
    "Champagne & Sparkling Wine": ["Chocolate & Confectionery", "Berries"],

    # --- Household (cross-sell into personal care, avoid circular loops) ---
    "Laundry Care": ["Surface Care", "Shower & Bath"],
    "Dishwashing": ["Paper Products & Waste Bags", "Surface Care"],
    "Paper Products & Waste Bags": ["Dishwashing", "Surface Care"],
    "Surface Care": ["Laundry Care", "Shower & Bath"],

    # --- Personal Care ---
    "Shampoo & Conditioner": ["Shower & Bath", "Deodorant"],
    "Shower & Bath": ["Shampoo & Conditioner", "Deodorant"],
    "Toothpaste & Toothbrush": ["Mouthwash", "Shower & Bath"],

    # --- Pet Care (cross-sell into household, not into each other) ---
    "Dog Care": ["Paper Products & Waste Bags", "Surface Care"],
    "Cat Care": ["Paper Products & Waste Bags", "Surface Care", "Fresh Fish"],
}
