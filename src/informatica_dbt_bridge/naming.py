"""Naming conventions shared by the translators and renderer."""

from __future__ import annotations

import re

_NON_ALNUM = re.compile(r"[^0-9a-zA-Z]+")


def snake_case(name: str) -> str:
    """Normalize a PowerCenter transformation/port name into a dbt-style identifier.

    Args:
        name: A raw PowerCenter name, e.g. `"SQ_ORDERS"`, `"FIL Active"`, or
            `"AGG-BY-REGION"`.

    Returns:
        The lowercased, underscore-delimited equivalent, e.g. `"sq_orders"`,
        `"fil_active"`, `"agg_by_region"`.
    """
    return _NON_ALNUM.sub("_", name.strip()).strip("_").lower()
