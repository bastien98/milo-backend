"""Tests for promo_folders_pipelines.qa_report."""

import pytest

from promo_folders_pipelines.models import PromoItem
from promo_folders_pipelines.qa_report import (
    FLAG_AREA_OUTLIER,
    FLAG_EDGE_HUGGER,
    FLAG_FELL_BACK_TO_TILE,
    FLAG_IOU_REJECTION,
    FLAG_TILE_OVERLAP_HIGH,
    detect_anomalies,
    format_report,
)


def _item(
    name: str,
    page: int,
    tile: tuple[float, float, float, float],
    bbox: tuple[float, float, float, float] | None = None,
) -> PromoItem:
    bbox_dict = None
    if bbox is not None:
        bbox_dict = {"x_min": bbox[0], "y_min": bbox[1], "x_max": bbox[2], "y_max": bbox[3]}
    return PromoItem(
        display_name=name,
        page_number=page,
        tile_bbox={"x_min": tile[0], "y_min": tile[1], "x_max": tile[2], "y_max": tile[3]},
        bbox=bbox_dict,
    )


def test_clean_page_has_no_anomalies():
    # Five normally-sized non-overlapping tiles on one page with real product bboxes.
    items = [
        _item("A", 1, (0.05, 0.05, 0.25, 0.25), (0.07, 0.07, 0.23, 0.23)),
        _item("B", 1, (0.30, 0.05, 0.50, 0.25), (0.32, 0.07, 0.48, 0.23)),
        _item("C", 1, (0.55, 0.05, 0.75, 0.25), (0.57, 0.07, 0.73, 0.23)),
        _item("D", 1, (0.05, 0.30, 0.25, 0.50), (0.07, 0.32, 0.23, 0.48)),
        _item("E", 1, (0.30, 0.30, 0.50, 0.50), (0.32, 0.32, 0.48, 0.48)),
    ]
    assert detect_anomalies(items) == []


def test_fell_back_to_tile_flag():
    # bbox == tile_bbox ⇒ pass-2 fell back.
    items = [
        _item("A", 1, (0.10, 0.10, 0.30, 0.30), (0.12, 0.12, 0.28, 0.28)),
        _item("B", 1, (0.35, 0.10, 0.55, 0.30), (0.35, 0.10, 0.55, 0.30)),
        _item("C", 1, (0.60, 0.10, 0.80, 0.30), (0.62, 0.12, 0.78, 0.28)),
    ]
    anomalies = detect_anomalies(items)
    names = [a.display_name for a in anomalies]
    assert "B" in names
    b = next(a for a in anomalies if a.display_name == "B")
    assert FLAG_FELL_BACK_TO_TILE in b.flags
    assert "A" not in names
    assert "C" not in names


def test_tile_overlap_high_flag():
    # A and B overlap heavily (same region); C sits clear.
    items = [
        _item("A", 2, (0.10, 0.10, 0.40, 0.40), (0.12, 0.12, 0.38, 0.38)),
        _item("B", 2, (0.15, 0.15, 0.45, 0.45), (0.17, 0.17, 0.43, 0.43)),
        _item("C", 2, (0.60, 0.10, 0.80, 0.40), (0.62, 0.12, 0.78, 0.38)),
    ]
    anomalies = detect_anomalies(items)
    flagged = {a.display_name for a in anomalies}
    assert "A" in flagged and "B" in flagged
    assert "C" not in flagged
    a = next(x for x in anomalies if x.display_name == "A")
    assert FLAG_TILE_OVERLAP_HIGH in a.flags


def test_area_outlier_flag():
    # Four normal tiles ~0.04 area each, one huge ~0.5 area.
    items = [
        _item("A", 3, (0.05, 0.05, 0.25, 0.25), (0.07, 0.07, 0.23, 0.23)),
        _item("B", 3, (0.30, 0.05, 0.50, 0.25), (0.32, 0.07, 0.48, 0.23)),
        _item("C", 3, (0.55, 0.05, 0.75, 0.25), (0.57, 0.07, 0.73, 0.23)),
        _item("D", 3, (0.05, 0.30, 0.25, 0.50), (0.07, 0.32, 0.23, 0.48)),
        _item("BIG", 3, (0.30, 0.30, 0.95, 0.95), (0.32, 0.32, 0.93, 0.93)),
    ]
    anomalies = detect_anomalies(items)
    flagged = {a.display_name for a in anomalies}
    assert "BIG" in flagged
    big = next(x for x in anomalies if x.display_name == "BIG")
    assert FLAG_AREA_OUTLIER in big.flags


def test_edge_hugger_flag():
    # Tile touching the left edge.
    items = [
        _item("A", 4, (0.001, 0.10, 0.25, 0.30), (0.002, 0.12, 0.23, 0.28)),
        _item("B", 4, (0.30, 0.10, 0.50, 0.30), (0.32, 0.12, 0.48, 0.28)),
        _item("C", 4, (0.55, 0.10, 0.75, 0.30), (0.57, 0.12, 0.73, 0.28)),
    ]
    anomalies = detect_anomalies(items)
    a = next(x for x in anomalies if x.display_name == "A")
    assert FLAG_EDGE_HUGGER in a.flags


def test_iou_rejection_flag_feeds_through():
    items = [
        _item("A", 5, (0.10, 0.10, 0.30, 0.30), (0.12, 0.12, 0.28, 0.28)),
    ]
    anomalies = detect_anomalies(items, iou_rejections={(5, "A")})
    assert len(anomalies) == 1
    assert FLAG_IOU_REJECTION in anomalies[0].flags


def test_multiple_flags_on_same_item():
    # Tile A: hugs the edge AND overlaps B heavily.
    items = [
        _item("A", 6, (0.0, 0.10, 0.40, 0.40), (0.01, 0.12, 0.38, 0.38)),
        _item("B", 6, (0.05, 0.15, 0.45, 0.45), (0.07, 0.17, 0.43, 0.43)),
        _item("C", 6, (0.60, 0.10, 0.80, 0.40), (0.62, 0.12, 0.78, 0.38)),
    ]
    anomalies = detect_anomalies(items)
    a = next(x for x in anomalies if x.display_name == "A")
    assert FLAG_EDGE_HUGGER in a.flags
    assert FLAG_TILE_OVERLAP_HIGH in a.flags


def test_items_without_page_are_ignored():
    items = [
        PromoItem(display_name="NoPage", page_number=None, tile_bbox=None, bbox=None),
        _item("A", 1, (0.10, 0.10, 0.30, 0.30), (0.12, 0.12, 0.28, 0.28)),
    ]
    anomalies = detect_anomalies(items)
    assert all(a.display_name != "NoPage" for a in anomalies)


def test_format_report_ok():
    out = format_report([], "carrefour/2026-W17", total_items=42)
    assert "0 items flagged of 42" in out


def test_format_report_lists_flags():
    items = [
        _item("Nutella", 7, (0.10, 0.10, 0.30, 0.30), (0.10, 0.10, 0.30, 0.30)),
    ]
    anomalies = detect_anomalies(items)
    out = format_report(anomalies, "carrefour/2026-W17", total_items=1)
    assert "p7" in out
    assert "Nutella" in out
    assert FLAG_FELL_BACK_TO_TILE in out
