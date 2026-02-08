from enum import Enum


# Legacy Category enum mapping for database migration.
# New transactions use string-based categories from CategoryRegistry.
LEGACY_CATEGORY_MIGRATION_MAP = {
    "MEAT_FISH": "Meat",
    "ALCOHOL": "Alcohol",
    "DRINKS_SOFT_SODA": "Drinks",
    "DRINKS_WATER": "Drinks",
    "HOUSEHOLD": "Household",
    "SNACKS_SWEETS": "Snacks",
    "FRESH_PRODUCE": "Vegetables",
    "DAIRY_EGGS": "Dairy & Eggs",
    "READY_MEALS": "Ready Meals",
    "BAKERY": "Bakery",
    "PANTRY": "Pantry",
    "PERSONAL_CARE": "Personal Care",
    "FROZEN": "Frozen",
    "BABY_KIDS": "Baby & Kids",
    "PET_SUPPLIES": "Pet Supplies",
    "TOBACCO": "Tobacco",
    "OTHER": "Other",
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
