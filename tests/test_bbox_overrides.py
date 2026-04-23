"""Tests for the pure override-apply step in promo_folders_pipelines.pipeline."""

from promo_folders_pipelines.models import PromoItem
from promo_folders_pipelines.pipeline import (
    _apply_overrides_to_items,
    _normalize_override_name,
)


def _item(name: str, page: int, tile: tuple, bbox: tuple) -> PromoItem:
    return PromoItem(
        display_name=name,
        page_number=page,
        tile_bbox={"x_min": tile[0], "y_min": tile[1], "x_max": tile[2], "y_max": tile[3]},
        bbox={"x_min": bbox[0], "y_min": bbox[1], "x_max": bbox[2], "y_max": bbox[3]},
    )


def test_normalize_override_name():
    assert _normalize_override_name("Rode Paprika") == "rode paprika"
    assert _normalize_override_name("  Coca-Cola 1,5 L  ") == "coca-cola 1,5 l"
    assert _normalize_override_name("") == ""


def test_no_overrides_leaves_items_untouched():
    items = [_item("A", 1, (0.0, 0.0, 0.1, 0.1), (0.01, 0.01, 0.09, 0.09))]
    before_tile = dict(items[0].tile_bbox)
    before_bbox = dict(items[0].bbox)

    count = _apply_overrides_to_items(items, overrides={})

    assert count == 0
    assert items[0].tile_bbox == before_tile
    assert items[0].bbox == before_bbox


def test_single_match_is_applied_and_others_untouched():
    items = [
        _item("Rode paprika", 7, (0.10, 0.10, 0.20, 0.20), (0.11, 0.11, 0.19, 0.19)),
        _item("Nutella 400g", 7, (0.30, 0.30, 0.40, 0.40), (0.31, 0.31, 0.39, 0.39)),
        _item("Lay's Salt", 8, (0.10, 0.10, 0.20, 0.20), (0.11, 0.11, 0.19, 0.19)),
    ]
    overrides = {
        (7, "rode paprika"): {
            "tile_bbox": {"x_min": 0.50, "y_min": 0.50, "x_max": 0.80, "y_max": 0.80},
            "bbox": {"x_min": 0.52, "y_min": 0.52, "x_max": 0.78, "y_max": 0.78},
        }
    }

    count = _apply_overrides_to_items(items, overrides)

    assert count == 1
    assert items[0].tile_bbox == {"x_min": 0.50, "y_min": 0.50, "x_max": 0.80, "y_max": 0.80}
    assert items[0].bbox == {"x_min": 0.52, "y_min": 0.52, "x_max": 0.78, "y_max": 0.78}
    # Other items must be byte-identical.
    assert items[1].tile_bbox == {"x_min": 0.30, "y_min": 0.30, "x_max": 0.40, "y_max": 0.40}
    assert items[1].bbox == {"x_min": 0.31, "y_min": 0.31, "x_max": 0.39, "y_max": 0.39}
    assert items[2].tile_bbox == {"x_min": 0.10, "y_min": 0.10, "x_max": 0.20, "y_max": 0.20}


def test_name_matching_is_case_and_whitespace_insensitive():
    items = [_item("  RODE Paprika  ", 7, (0.1, 0.1, 0.2, 0.2), (0.11, 0.11, 0.19, 0.19))]
    overrides = {
        (7, "rode paprika"): {
            "tile_bbox": {"x_min": 0.5, "y_min": 0.5, "x_max": 0.8, "y_max": 0.8},
            "bbox": {"x_min": 0.5, "y_min": 0.5, "x_max": 0.8, "y_max": 0.8},
        }
    }
    count = _apply_overrides_to_items(items, overrides)
    assert count == 1


def test_page_mismatch_is_not_applied():
    items = [_item("Rode paprika", 8, (0.1, 0.1, 0.2, 0.2), (0.11, 0.11, 0.19, 0.19))]
    overrides = {
        (7, "rode paprika"): {
            "tile_bbox": {"x_min": 0.5, "y_min": 0.5, "x_max": 0.8, "y_max": 0.8},
            "bbox": {"x_min": 0.5, "y_min": 0.5, "x_max": 0.8, "y_max": 0.8},
        }
    }
    count = _apply_overrides_to_items(items, overrides)
    assert count == 0
    assert items[0].tile_bbox == {"x_min": 0.1, "y_min": 0.1, "x_max": 0.2, "y_max": 0.2}


def test_item_with_null_page_is_skipped():
    item = PromoItem(display_name="Ghost", page_number=None, tile_bbox=None, bbox=None)
    overrides = {
        (1, "ghost"): {
            "tile_bbox": {"x_min": 0.5, "y_min": 0.5, "x_max": 0.8, "y_max": 0.8},
            "bbox": {"x_min": 0.5, "y_min": 0.5, "x_max": 0.8, "y_max": 0.8},
        }
    }
    count = _apply_overrides_to_items([item], overrides)
    assert count == 0


def test_applied_bboxes_are_deep_copies():
    items = [_item("A", 1, (0.1, 0.1, 0.2, 0.2), (0.11, 0.11, 0.19, 0.19))]
    override_tile = {"x_min": 0.5, "y_min": 0.5, "x_max": 0.8, "y_max": 0.8}
    overrides = {
        (1, "a"): {"tile_bbox": override_tile, "bbox": override_tile},
    }
    _apply_overrides_to_items(items, overrides)
    # Mutating the item's bbox must not leak back into the overrides dict.
    items[0].tile_bbox["x_min"] = 0.99
    assert override_tile["x_min"] == 0.5
