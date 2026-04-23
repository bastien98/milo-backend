"""Post-ingest anomaly detection for promo item bboxes.

Pure functions over `list[PromoItem]` — no Gemini calls, no DB. Surfaces pages/items
that are likely to have wrong bounding boxes so a human can spot-check them instead
of eyeballing every page. Built to run at the tail of every folder ingest.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from statistics import median
from typing import Iterable

from promo_folders_pipelines.models import PromoItem


# Thresholds chosen to catch the pathological cases without drowning the report.
OVERLAP_IOU_THRESHOLD = 0.25      # two tiles that overlap this much almost always mean a misplaced box
AREA_OUTLIER_RATIO = 3.0          # flag tiles >3x or <1/3 of the page's median tile area
EDGE_EPSILON = 0.002              # coord within 0.002 of 0 or 1 counts as edge-hugging
FALLBACK_BBOX_EPSILON = 1e-6      # bbox == tile_bbox exactly ⇒ pass-2 fell back to tile


FLAG_FELL_BACK_TO_TILE = "fell_back_to_tile"
FLAG_TILE_OVERLAP_HIGH = "tile_overlap_high"
FLAG_AREA_OUTLIER = "area_outlier"
FLAG_EDGE_HUGGER = "edge_hugger"
FLAG_IOU_REJECTION = "iou_rejection"


@dataclass
class Anomaly:
    page_number: int
    display_name: str
    flags: list[str] = field(default_factory=list)


def _iou(a: dict, b: dict) -> float:
    ix_min = max(a["x_min"], b["x_min"])
    iy_min = max(a["y_min"], b["y_min"])
    ix_max = min(a["x_max"], b["x_max"])
    iy_max = min(a["y_max"], b["y_max"])
    if ix_max <= ix_min or iy_max <= iy_min:
        return 0.0
    inter = (ix_max - ix_min) * (iy_max - iy_min)
    area_a = (a["x_max"] - a["x_min"]) * (a["y_max"] - a["y_min"])
    area_b = (b["x_max"] - b["x_min"]) * (b["y_max"] - b["y_min"])
    union = area_a + area_b - inter
    return inter / union if union > 0 else 0.0


def _area(bbox: dict) -> float:
    return max(0.0, bbox["x_max"] - bbox["x_min"]) * max(0.0, bbox["y_max"] - bbox["y_min"])


def _approx_equal(a: dict, b: dict, eps: float = FALLBACK_BBOX_EPSILON) -> bool:
    return all(
        abs(a[k] - b[k]) < eps for k in ("x_min", "y_min", "x_max", "y_max")
    )


def _touches_edge(bbox: dict, eps: float = EDGE_EPSILON) -> bool:
    return (
        bbox["x_min"] <= eps
        or bbox["y_min"] <= eps
        or bbox["x_max"] >= 1.0 - eps
        or bbox["y_max"] >= 1.0 - eps
    )


def detect_anomalies(
    items: Iterable[PromoItem],
    iou_rejections: set[tuple[int, str]] | None = None,
) -> list[Anomaly]:
    """Scan items, return one Anomaly per flagged item.

    Args:
        items: The final PromoItem list for a single folder (after validation + overrides).
        iou_rejections: Optional {(page, display_name)} pairs whose pass-2 correction
            was rejected on the IoU gate. Wired in from pipeline if available;
            empty set when the pass-2 path isn't running.

    Any item that trips at least one flag is included. An item may have multiple flags.
    """
    rejections = iou_rejections or set()
    items = [i for i in items if i.page_number is not None]

    # Group by page for the overlap + area-outlier checks.
    by_page: dict[int, list[PromoItem]] = defaultdict(list)
    for item in items:
        by_page[item.page_number].append(item)

    anomalies: dict[tuple[int, str], Anomaly] = {}

    def _add_flag(page: int, name: str, flag: str) -> None:
        key = (page, name)
        existing = anomalies.get(key)
        if existing is None:
            anomalies[key] = Anomaly(page_number=page, display_name=name, flags=[flag])
        elif flag not in existing.flags:
            existing.flags.append(flag)

    for page, page_items in by_page.items():
        tiles = [(it, it.tile_bbox) for it in page_items if it.tile_bbox]

        # Area outlier: median tile area on this page; flag items 3x above or 1/3 below.
        if len(tiles) >= 3:
            areas = [_area(tile) for _, tile in tiles]
            med = median(areas)
            if med > 0:
                upper = med * AREA_OUTLIER_RATIO
                lower = med / AREA_OUTLIER_RATIO
                for item, tile in tiles:
                    a = _area(tile)
                    if a > upper or a < lower:
                        _add_flag(page, item.display_name, FLAG_AREA_OUTLIER)

        # Pairwise overlap: O(n^2) per page, fine at ~50 items/page max.
        for i, (item_i, tile_i) in enumerate(tiles):
            for item_j, tile_j in tiles[i + 1:]:
                if _iou(tile_i, tile_j) > OVERLAP_IOU_THRESHOLD:
                    _add_flag(page, item_i.display_name, FLAG_TILE_OVERLAP_HIGH)
                    _add_flag(page, item_j.display_name, FLAG_TILE_OVERLAP_HIGH)

        # Per-item flags: edge-hugging tiles and fallback-to-tile bboxes.
        for item in page_items:
            if item.tile_bbox and _touches_edge(item.tile_bbox):
                _add_flag(page, item.display_name, FLAG_EDGE_HUGGER)
            if (
                item.tile_bbox
                and item.bbox
                and _approx_equal(item.tile_bbox, item.bbox)
            ):
                _add_flag(page, item.display_name, FLAG_FELL_BACK_TO_TILE)

    # Pass-2 IoU rejections (may be empty on the CLI path where pass-2 isn't wired).
    for page, name in rejections:
        _add_flag(page, name, FLAG_IOU_REJECTION)

    # Stable sort: page first, then display_name.
    return sorted(anomalies.values(), key=lambda a: (a.page_number, a.display_name))


def format_report(
    anomalies: list[Anomaly],
    folder_label: str,
    total_items: int,
) -> str:
    """Render the anomaly list as a compact multi-line string for console output."""
    if not anomalies:
        return f"[QA] {folder_label} — 0 items flagged of {total_items}. ✓"

    lines = [f"[QA] {folder_label} — {len(anomalies)} items flagged of {total_items}:"]
    max_name_len = min(40, max(len(a.display_name) for a in anomalies))
    for a in anomalies:
        name = a.display_name
        if len(name) > max_name_len:
            name = name[: max_name_len - 1] + "…"
        flags = ", ".join(a.flags)
        lines.append(f'  p{a.page_number:<3} "{name:<{max_name_len}}"  {flags}')
    return "\n".join(lines)


def anomalies_to_json(anomalies: list[Anomaly]) -> list[dict]:
    """Machine-readable dump for writing alongside --dry-run output."""
    return [
        {
            "page_number": a.page_number,
            "display_name": a.display_name,
            "flags": list(a.flags),
        }
        for a in anomalies
    ]
