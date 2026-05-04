"""Pydantic-level validation for AdminLineItemCreate.

Covers the store-conditional product_codes requirement (Colruyt/Delhaize must
have codes; other stores may have none) and the digits-only / length / dedupe
rules.
"""

import pytest
from pydantic import ValidationError

from app.schemas.brand_cashback import AdminLineItemCreate


def _base(**overrides):
    """Default-valid payload with codes empty (Carrefour-style)."""
    payload = {
        "store_name": "Carrefour Express",
        "exact_line_item": "MONST.GR.ZERO 50CL",
        "alt_line_items": [],
        "product_codes": [],
        "notes": None,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Store-conditional requirement
# ---------------------------------------------------------------------------

def test_colruyt_without_codes_raises():
    with pytest.raises(ValidationError) as exc:
        AdminLineItemCreate(**_base(store_name="Colruyt"))
    assert "product_codes is required" in str(exc.value)


def test_delhaize_without_codes_raises():
    with pytest.raises(ValidationError) as exc:
        AdminLineItemCreate(**_base(store_name="Delhaize"))
    assert "product_codes is required" in str(exc.value)


def test_colruyt_with_codes_ok():
    m = AdminLineItemCreate(**_base(store_name="Colruyt", product_codes=["123456"]))
    assert m.product_codes == ["123456"]


def test_delhaize_with_codes_ok():
    m = AdminLineItemCreate(
        **_base(store_name="Delhaize", product_codes=["5410123456789"])
    )
    assert m.product_codes == ["5410123456789"]


def test_carrefour_without_codes_ok():
    m = AdminLineItemCreate(**_base(store_name="Carrefour Express"))
    assert m.product_codes == []


def test_albert_heijn_without_codes_ok():
    m = AdminLineItemCreate(**_base(store_name="Albert Heijn"))
    assert m.product_codes == []


def test_aldi_without_codes_ok():
    m = AdminLineItemCreate(**_base(store_name="Aldi"))
    assert m.product_codes == []


def test_lidl_without_codes_ok():
    m = AdminLineItemCreate(**_base(store_name="Lidl"))
    assert m.product_codes == []


def test_store_match_is_case_insensitive():
    """COLRUYT, colruyt, Colruyt all hit the requirement."""
    for variant in ("colruyt", "COLRUYT", "Colruyt"):
        with pytest.raises(ValidationError):
            AdminLineItemCreate(**_base(store_name=variant))


# ---------------------------------------------------------------------------
# Code-format validation
# ---------------------------------------------------------------------------

def test_non_digit_code_raises():
    with pytest.raises(ValidationError) as exc:
        AdminLineItemCreate(
            **_base(store_name="Delhaize", product_codes=["abc123"])
        )
    assert "digits only" in str(exc.value)


def test_code_too_short_raises():
    with pytest.raises(ValidationError) as exc:
        AdminLineItemCreate(**_base(store_name="Delhaize", product_codes=["123"]))
    assert "must be" in str(exc.value)


def test_code_too_long_raises():
    with pytest.raises(ValidationError) as exc:
        AdminLineItemCreate(
            **_base(store_name="Delhaize", product_codes=["123456789012345"])
        )
    assert "must be" in str(exc.value)


def test_code_with_spaces_raises():
    with pytest.raises(ValidationError):
        AdminLineItemCreate(
            **_base(store_name="Delhaize", product_codes=["5410 123 456 789"])
        )


def test_duplicate_codes_dedupe():
    m = AdminLineItemCreate(
        **_base(
            store_name="Delhaize",
            product_codes=["5410123456789", "5410123456789", "1234"],
        )
    )
    assert m.product_codes == ["5410123456789", "1234"]


def test_empty_string_codes_dropped():
    """Whitespace-only entries are filtered out (parsed from textarea)."""
    m = AdminLineItemCreate(
        **_base(
            store_name="Delhaize",
            product_codes=["", "  ", "5410123456789"],
        )
    )
    assert m.product_codes == ["5410123456789"]


def test_code_strip_whitespace():
    m = AdminLineItemCreate(
        **_base(store_name="Delhaize", product_codes=["  5410123456789  "])
    )
    assert m.product_codes == ["5410123456789"]


def test_leading_zeros_preserved():
    """Colruyt artikel numbers can be left-padded — must not be coerced to int."""
    m = AdminLineItemCreate(
        **_base(store_name="Colruyt", product_codes=["004515"])
    )
    assert m.product_codes == ["004515"]
