"""Coupon barcode decoder.

Given a promo tile crop (PIL Image) for an item Gemini classified as `is_coupon`,
find and decode the 1D barcode printed on the tile. Returns the decoded digit
string, its format, and a page-normalized bounding box around the barcode.

Safety model
------------
Input pages from the promopromo.be scrape are low-res (~106 DPI). To rule out
misreads we run zxing-cpp at THREE upscales (2×, 3×, 4× LANCZOS) and accept
a (text, format) tuple that decodes identically at AT LEAST TWO of the three
scales. zxing already enforces the EAN-13 checksum on each individual read,
so a misread would have to produce the same wrong checksum-valid digit string
on two independent resamplings — still vanishingly unlikely. Requiring all
three scales agree turned out to be too strict: one scale routinely failed
on borderline tiles that two others got right, leaving valid coupons
unscannable.

We additionally cross-check with pyzbar at 2× when available; if pyzbar is
installed and disagrees with zxing on the chosen text, we reject.

Only 1D retail formats are accepted. QR / DataMatrix / PDF417 / Aztec are not
coupon formats in Belgian retail and are explicitly rejected.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

from PIL import Image

logger = logging.getLogger(__name__)


# 1D retail formats used on Belgian supermarket coupons. Anything 2D is rejected.
ALLOWED_FORMATS = frozenset(
    {"EAN-13", "EAN-8", "UPC-A", "UPC-E", "Code-128", "Code-39", "ITF"}
)

# Scales at which we re-decode. 2/3/4 gives us three independent resamplings;
# a (text, format) tuple is accepted if it survives at least MIN_SCALE_AGREEMENT
# of them.
UPSCALE_FACTORS = (2, 3, 4)
MIN_SCALE_AGREEMENT = 2


@dataclass
class DecodedBarcode:
    """A coupon barcode that survived multi-scale verification."""

    value: str                       # digit string, e.g. "0453697700003"
    barcode_format: str              # zxing format name, e.g. "EAN-13"
    bbox_page_normalized: dict       # {x_min, y_min, x_max, y_max} in 0-1 coords over the page


def decode_coupon_barcode(
    tile_crop: Image.Image,
    tile_bbox_page_normalized: dict,
    page_size: tuple[int, int],
) -> Optional[DecodedBarcode]:
    """Decode the coupon barcode inside a tile crop.

    Parameters
    ----------
    tile_crop : PIL.Image
        The tile region cropped from the page at native resolution.
    tile_bbox_page_normalized : dict
        The tile bbox in 0-1 coords relative to the whole page. Used to map the
        decoded barcode position back to page-normalized coords.
    page_size : (int, int)
        (page_width_px, page_height_px) at the native render resolution, for the
        final page-normalized coordinate computation.

    Returns
    -------
    DecodedBarcode | None
        None if no barcode decodes identically at >= 2 of the 3 scales AND passes
        the format allowlist.
    """
    try:
        import zxingcpp
    except ImportError:
        logger.warning("zxing-cpp not installed — skipping coupon barcode decode")
        return None

    tile_w, tile_h = tile_crop.size

    # per_scale[i] maps (value, format) -> position (list of 4 (x, y) pixel corners
    # at that scale's upscaled image). We keep the 3× position for final mapping
    # because it's the middle-of-the-range scale.
    per_scale: list[dict[tuple[str, str], list[tuple[int, int]]]] = []
    position_at_3x: dict[tuple[str, str], list[tuple[int, int]]] = {}

    for scale in UPSCALE_FACTORS:
        upscaled = tile_crop.resize((tile_w * scale, tile_h * scale), Image.LANCZOS)
        try:
            results = zxingcpp.read_barcodes(
                upscaled,
                try_rotate=True,
                try_invert=True,
                try_downscale=True,
            )
        except Exception as e:  # zxing can throw on malformed images
            logger.warning(f"zxing read_barcodes failed at {scale}x: {e}")
            results = []

        this_scale: dict[tuple[str, str], list[tuple[int, int]]] = {}
        for r in results:
            if not r.valid:
                continue
            fmt = str(r.format)
            if fmt not in ALLOWED_FORMATS:
                continue
            pos = r.position
            corners = [
                (pos.top_left.x, pos.top_left.y),
                (pos.top_right.x, pos.top_right.y),
                (pos.bottom_right.x, pos.bottom_right.y),
                (pos.bottom_left.x, pos.bottom_left.y),
            ]
            key = (r.text, fmt)
            this_scale[key] = corners
            if scale == 3:
                position_at_3x[key] = corners
        per_scale.append(this_scale)

    if not per_scale:
        return None

    # Count how many scales agree on each (text, format). A key survives if it
    # decoded identically at >= MIN_SCALE_AGREEMENT scales. Since zxing's EAN-13
    # checksum is enforced per read, two agreeing scales is strong enough
    # evidence that the value is right.
    agreement_count: dict[tuple[str, str], int] = {}
    for s in per_scale:
        for key in s.keys():
            agreement_count[key] = agreement_count.get(key, 0) + 1
    stable_keys = {k for k, n in agreement_count.items() if n >= MIN_SCALE_AGREEMENT}

    if not stable_keys:
        return None

    # Optional secondary cross-check with pyzbar at 2× — if the library is
    # available and disagrees on the text, reject.
    pyzbar_texts = _pyzbar_texts(tile_crop, scale=2)
    if pyzbar_texts is not None:
        stable_keys = {(t, f) for (t, f) in stable_keys if t in pyzbar_texts}
        if not stable_keys:
            logger.info("Barcode rejected: zxing ↔ pyzbar disagreement")
            return None

    # Pick a (corners, scale) for each stable key. Prefer 3× (middle scale,
    # balances resolution against upscale distortion), falling back to whichever
    # of the other two scales has the key. Under 2-of-3 agreement a key may be
    # absent from 3×, so the fallback is load-bearing, not just defensive.
    def _corners_for(key: tuple[str, str]) -> tuple[list[tuple[int, int]], int]:
        if key in position_at_3x:
            return position_at_3x[key], 3
        for i, s in enumerate(per_scale):
            if key in s:
                return s[key], UPSCALE_FACTORS[i]
        raise KeyError(key)  # unreachable: key came from per_scale

    # If multiple stable barcodes remain on the same tile (rare — e.g. two coupon
    # products in one tile), pick the one with the largest area.
    def _area(corners: list[tuple[int, int]]) -> float:
        xs = [c[0] for c in corners]
        ys = [c[1] for c in corners]
        return (max(xs) - min(xs)) * (max(ys) - min(ys))

    chosen_key = max(stable_keys, key=lambda k: _area(_corners_for(k)[0]))
    if len(stable_keys) > 1:
        logger.info(f"Multiple stable barcodes in tile; picked largest: {chosen_key}")

    value, fmt = chosen_key
    corners, upscale = _corners_for(chosen_key)
    bbox_norm = _corners_to_page_normalized_bbox(
        corners,
        upscale_factor=upscale,
        tile_size=tile_crop.size,
        tile_bbox_page_normalized=tile_bbox_page_normalized,
        page_size=page_size,
    )
    if bbox_norm is None:
        return None

    return DecodedBarcode(
        value=value,
        barcode_format=fmt,
        bbox_page_normalized=bbox_norm,
    )


def _pyzbar_texts(tile_crop: Image.Image, scale: int) -> Optional[set[str]]:
    """Return the set of pyzbar-decoded text strings, or None if pyzbar isn't installed.

    Only used as a cross-check against zxing. If pyzbar can't be imported, we skip
    the check entirely (returns None, not empty set — an absent check is different
    from a check that found nothing).
    """
    try:
        from pyzbar.pyzbar import decode as pyzbar_decode
    except ImportError:
        return None

    w, h = tile_crop.size
    upscaled = tile_crop.resize((w * scale, h * scale), Image.LANCZOS)
    try:
        results = pyzbar_decode(upscaled)
    except Exception as e:
        logger.warning(f"pyzbar decode failed: {e}")
        return None
    return {r.data.decode("utf-8", errors="ignore") for r in results}


def _corners_to_page_normalized_bbox(
    corners: list[tuple[int, int]],
    upscale_factor: int,
    tile_size: tuple[int, int],
    tile_bbox_page_normalized: dict,
    page_size: tuple[int, int],
) -> Optional[dict]:
    """Map zxing's 4 corners (in upscaled-tile pixel coords) to page-normalized 0-1 bbox."""
    tile_w, tile_h = tile_size
    page_w, page_h = page_size

    # 1. Upscaled-tile pixels → native-tile pixels
    xs_tile = [c[0] / upscale_factor for c in corners]
    ys_tile = [c[1] / upscale_factor for c in corners]

    # 2. Native-tile pixels → page pixels (offset by tile's top-left in the page)
    tile_x_px_offset = tile_bbox_page_normalized["x_min"] * page_w
    tile_y_px_offset = tile_bbox_page_normalized["y_min"] * page_h
    xs_page = [tile_x_px_offset + x for x in xs_tile]
    ys_page = [tile_y_px_offset + y for y in ys_tile]

    # 3. Page pixels → page-normalized 0-1
    x_min = max(0.0, min(xs_page) / page_w)
    y_min = max(0.0, min(ys_page) / page_h)
    x_max = min(1.0, max(xs_page) / page_w)
    y_max = min(1.0, max(ys_page) / page_h)

    if x_min >= x_max or y_min >= y_max:
        return None

    return {"x_min": x_min, "y_min": y_min, "x_max": x_max, "y_max": y_max}
