from __future__ import annotations

import pytest


def test_normalize_intervals_accepts_comma_string_and_dedupes():
    from app.validation import normalize_intervals

    assert normalize_intervals("15, 60, 1D, 60") == ["15", "60", "D"]


def test_normalize_intervals_rejects_empty_and_invalid():
    from app.validation import normalize_intervals

    with pytest.raises(ValueError):
        normalize_intervals([])
    with pytest.raises(ValueError):
        normalize_intervals("15,bad")
