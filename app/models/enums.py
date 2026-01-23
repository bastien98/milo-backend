from enum import Enum


class Category(str, Enum):
    MEAT_FISH = "Meat & Fish"
    ALCOHOL = "Alcohol"
    DRINKS_SOFT_SODA = "Drinks (Soft/Soda)"
    DRINKS_WATER = "Drinks (Water)"
    HOUSEHOLD = "Household"
    SNACKS_SWEETS = "Snacks & Sweets"
    FRESH_PRODUCE = "Fresh Produce"
    DAIRY_EGGS = "Dairy & Eggs"
    READY_MEALS = "Ready Meals"
    BAKERY = "Bakery"
    PANTRY = "Pantry"
    PERSONAL_CARE = "Personal Care"
    FROZEN = "Frozen"
    BABY_KIDS = "Baby & Kids"
    PET_SUPPLIES = "Pet Supplies"
    OTHER = "Other"


class ReceiptStatus(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class Gender(str, Enum):
    MALE = "male"
    FEMALE = "female"
    PREFER_NOT_TO_SAY = "prefer_not_to_say"
