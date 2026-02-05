"""
Category Registry - loads category hierarchy from CSV and provides lookups.

The category system has 3 levels:
- Group (top): e.g., "Fresh Food", "Snacks & Beverages"
- Category (mid): e.g., "Fruits & Vegetables", "Snacks"
- Sub-Category (leaf): e.g., "Fresh Produce (Fruit & Veg)", "Snacks & Candy"

Transactions store the sub-category display name as a string.
"""
import csv
import os
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from functools import lru_cache
from difflib import SequenceMatcher


@dataclass
class SubCategoryInfo:
    """Full info for a sub-category."""
    sub_category: str
    category: str
    group: str


@dataclass
class CategoryNode:
    """Mid-level category containing sub-categories."""
    name: str
    sub_categories: List[str] = field(default_factory=list)


@dataclass
class GroupNode:
    """Top-level group containing categories."""
    name: str
    categories: Dict[str, CategoryNode] = field(default_factory=dict)


# Group-level colors (hex) for pie chart visualization
GROUP_COLORS: Dict[str, str] = {
    "Fresh Food": "#2ECC71",               # Emerald Green
    "Pantry & Frozen": "#E67E22",          # Warm Orange
    "Snacks & Beverages": "#E74C3C",       # Coral Red
    "Household & Care": "#8E44AD",         # Royal Purple
    "Other": "#95A5A6",                    # Slate Gray
}

# Group-level SF Symbol icons (sent to iOS)
GROUP_ICONS: Dict[str, str] = {
    "Fresh Food": "leaf.fill",
    "Pantry & Frozen": "cabinet.fill",
    "Snacks & Beverages": "cup.and.saucer.fill",
    "Household & Care": "house.fill",
    "Other": "square.grid.2x2.fill",
}


class CategoryRegistry:
    """Singleton registry that loads categories from CSV."""

    _instance: Optional["CategoryRegistry"] = None

    def __init__(self):
        # sub_category display name → SubCategoryInfo
        self._lookup: Dict[str, SubCategoryInfo] = {}
        # Lowercase sub_category → original sub_category (for case-insensitive matching)
        self._lower_lookup: Dict[str, str] = {}
        # group name → GroupNode
        self._groups: Dict[str, GroupNode] = {}
        # All sub-category names
        self._all_sub_categories: List[str] = []

    @classmethod
    def get_instance(cls) -> "CategoryRegistry":
        if cls._instance is None:
            cls._instance = cls()
            cls._instance.load()
        return cls._instance

    @classmethod
    def reset(cls):
        """Reset singleton (for testing)."""
        cls._instance = None

    def load(self, csv_path: Optional[str] = None):
        """Load categories from CSV file."""
        if csv_path is None:
            # Default: categories.csv in project root (2 levels up from app/)
            base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            csv_path = os.path.join(base_dir, "categories.csv")

        if not os.path.exists(csv_path):
            raise FileNotFoundError(f"Categories CSV not found: {csv_path}")

        self._lookup.clear()
        self._lower_lookup.clear()
        self._groups.clear()
        self._all_sub_categories.clear()

        with open(csv_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                group_name = row["Group"].strip()
                category_name = row["Category"].strip()
                sub_category_name = row["Sub-Category"].strip()

                # Build lookup
                info = SubCategoryInfo(
                    sub_category=sub_category_name,
                    category=category_name,
                    group=group_name,
                )
                self._lookup[sub_category_name] = info
                self._lower_lookup[sub_category_name.lower()] = sub_category_name
                self._all_sub_categories.append(sub_category_name)

                # Build tree
                if group_name not in self._groups:
                    self._groups[group_name] = GroupNode(name=group_name)
                group_node = self._groups[group_name]

                if category_name not in group_node.categories:
                    group_node.categories[category_name] = CategoryNode(name=category_name)
                group_node.categories[category_name].sub_categories.append(sub_category_name)

    def get_group(self, sub_category: str) -> Optional[str]:
        """Get the group name for a sub-category."""
        info = self._lookup.get(sub_category)
        if info:
            return info.group
        # Try case-insensitive
        canonical = self._lower_lookup.get(sub_category.lower())
        if canonical:
            return self._lookup[canonical].group
        return None

    def get_category(self, sub_category: str) -> Optional[str]:
        """Get the mid-level category for a sub-category."""
        info = self._lookup.get(sub_category)
        if info:
            return info.category
        canonical = self._lower_lookup.get(sub_category.lower())
        if canonical:
            return self._lookup[canonical].category
        return None

    def get_info(self, sub_category: str) -> Optional[SubCategoryInfo]:
        """Get full info for a sub-category."""
        info = self._lookup.get(sub_category)
        if info:
            return info
        canonical = self._lower_lookup.get(sub_category.lower())
        if canonical:
            return self._lookup[canonical]
        return None

    def get_group_color(self, sub_category: str) -> str:
        """Get the hex color for a sub-category based on its group."""
        group = self.get_group(sub_category)
        if group:
            return GROUP_COLORS.get(group, "#BDC3C7")
        return "#BDC3C7"

    def get_group_icon(self, sub_category: str) -> str:
        """Get the SF Symbol icon for a sub-category based on its group."""
        group = self.get_group(sub_category)
        if group:
            return GROUP_ICONS.get(group, "square.grid.2x2.fill")
        return "square.grid.2x2.fill"

    def is_valid(self, sub_category: str) -> bool:
        """Check if a sub-category is valid."""
        if sub_category in self._lookup:
            return True
        return sub_category.lower() in self._lower_lookup

    def get_all_sub_categories(self) -> List[str]:
        """Get all sub-category names."""
        return self._all_sub_categories.copy()

    def get_sub_categories_for_group(self, group: str) -> List[str]:
        """Get all sub-categories in a group."""
        group_node = self._groups.get(group)
        if not group_node:
            return []
        result = []
        for cat_node in group_node.categories.values():
            result.extend(cat_node.sub_categories)
        return result

    def get_all_groups(self) -> List[str]:
        """Get all group names."""
        return list(self._groups.keys())

    def find_closest_match(self, name: str, threshold: float = 0.6) -> Optional[str]:
        """Find the closest matching sub-category using fuzzy matching."""
        if self.is_valid(name):
            # Normalize case
            canonical = self._lower_lookup.get(name.lower())
            return canonical if canonical else name

        best_match = None
        best_score = 0.0
        name_lower = name.lower()

        for sub_cat in self._all_sub_categories:
            score = SequenceMatcher(None, name_lower, sub_cat.lower()).ratio()
            if score > best_score and score >= threshold:
                best_score = score
                best_match = sub_cat

        return best_match

    def get_hierarchy(self) -> dict:
        """Get the full hierarchy as a dict for API responses."""
        groups = []
        for group_name, group_node in self._groups.items():
            categories = []
            for cat_name, cat_node in group_node.categories.items():
                categories.append({
                    "name": cat_name,
                    "sub_categories": cat_node.sub_categories,
                })
            groups.append({
                "name": group_name,
                "icon": GROUP_ICONS.get(group_name, "square.grid.2x2.fill"),
                "color_hex": GROUP_COLORS.get(group_name, "#BDC3C7"),
                "categories": categories,
            })
        return {"groups": groups}

    def get_category_id(self, sub_category: str) -> str:
        """Generate a stable category_id string from a sub-category name.

        Converts display name to an uppercase snake_case ID.
        e.g., "Fresh Produce (Fruit & Veg)" -> "FRESH_PRODUCE_FRUIT_VEG"
        """
        s = sub_category.upper()
        # Remove parentheses content markers but keep the text
        s = s.replace("(", "").replace(")", "")
        # Replace special chars with underscores
        for ch in "&/-,.":
            s = s.replace(ch, "_")
        # Collapse multiple spaces/underscores
        import re
        s = re.sub(r"[\s_]+", "_", s)
        # Strip leading/trailing underscores
        s = s.strip("_")
        return s


@lru_cache()
def get_category_registry() -> CategoryRegistry:
    """Get the singleton category registry instance."""
    return CategoryRegistry.get_instance()
