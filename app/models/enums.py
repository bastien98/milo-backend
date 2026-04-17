from enum import Enum


# Legacy Category enum mapping for database migration.
# New transactions use string-based categories from app.core.categories.
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


class Language(str, Enum):
    ENGLISH = "en"
    DUTCH = "nl"
    FRENCH = "fr"


class CashbackStatus(str, Enum):
    PENDING = "pending"
    CONFIRMED = "confirmed"
    PAID_OUT = "paid_out"


class ReferralStatus(str, Enum):
    PENDING = "pending"
    COMPLETED = "completed"


class WithdrawalStatus(str, Enum):
    PENDING_REVIEW = "pending_review"
    AUTO_APPROVED = "auto_approved"
    APPROVED = "approved"
    REJECTED = "rejected"
    PAID_OUT = "paid_out"


class CharityDonationStatus(str, Enum):
    PENDING_REVIEW = "pending_review"
    PENDING = "pending"
    TRANSFERRED = "transferred"
    REJECTED = "rejected"


class StreakRewardStatus(str, Enum):
    CLAIMABLE = "claimable"
    CLAIMED = "claimed"


class StreakRewardType(str, Enum):
    SPINS = "spins"
    CASH = "cash"
    POINTS = "points"


class TierLevel(str, Enum):
    BRONZE = "bronze"   # < 4 tickets/month
    SILVER = "silver"   # 4–9 tickets/month
    GOLD = "gold"       # 10+ tickets/month


class SpinType(str, Enum):
    STANDARD = "standard"   # EV ~100 pts
    PREMIUM = "premium"     # EV ~200 pts


class LotteryDrawingStatus(str, Enum):
    PENDING = "pending"
    PARTICIPANTS_LOCKED = "participants_locked"
    DRAWN = "drawn"
    PUBLISHED = "published"


class LoyaltyStatus(str, Enum):
    STRICTLY_LOYAL = "strictly_loyal"   # top brand >= 80% AND events >= 3
    SOFT_LOYAL = "soft_loyal"           # top brand 60-80%
    BRAND_AGNOSTIC = "brand_agnostic"   # top brand < 60% OR >= 3 brands
    NEW = "new"                         # events < 3


class PromoInteractionEventType(str, Enum):
    """Telemetry for the folder → hotspot → detail → similar-carousel flow.

    Decoupled from any report/candidates table. Event rows may be anonymous
    (user_id NULL) for public folder browsing.
    """
    DEAL_OPENED = "deal_opened"
    SIMILAR_PROMO_CLICKED = "similar_promo_clicked"
