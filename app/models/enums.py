from enum import Enum


# Legacy Category enum mapping for database migration.
# New transactions use string-based categories from CategoryRegistry.
LEGACY_CATEGORY_MIGRATION_MAP = {
    "MEAT_FISH": "Meat Poultry & Seafood",
    "ALCOHOL": "Beer & Wine (Retail)",
    "DRINKS_SOFT_SODA": "Beverages (Non-Alcoholic)",
    "DRINKS_WATER": "Beverages (Non-Alcoholic)",
    "HOUSEHOLD": "Household Consumables (Paper/Cleaning)",
    "SNACKS_SWEETS": "Snacks & Candy",
    "FRESH_PRODUCE": "Fresh Produce (Fruit & Veg)",
    "DAIRY_EGGS": "Dairy Cheese & Eggs",
    "READY_MEALS": "Ready Meals & Prepared Food",
    "BAKERY": "Bakery & Bread",
    "PANTRY": "Pantry Staples (Pasta/Rice/Oil)",
    "PERSONAL_CARE": "Personal Hygiene (Soap/Shampoo)",
    "FROZEN": "Frozen Foods",
    "BABY_KIDS": "Baby Food & Formula",
    "PET_SUPPLIES": "Pet Food & Supplies",
    "TOBACCO": "Tobacco Products",
    "OTHER": "Unknown Transaction",
}


class ReceiptStatus(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class ReceiptSource(str, Enum):
    RECEIPT_UPLOAD = "receipt_upload"
    BANK_IMPORT = "bank_import"


class Gender(str, Enum):
    MALE = "male"
    FEMALE = "female"
    PREFER_NOT_TO_SAY = "prefer_not_to_say"
