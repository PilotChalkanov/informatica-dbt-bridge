"""Naming conventions shared by the translators and renderer."""

from __future__ import annotations

import re

_NON_ALNUM = re.compile(r"[^0-9a-zA-Z]+")


def snake_case(name: str) -> str:
    """Normalize a PowerCenter transformation/port name into a dbt-style identifier."""
    return _NON_ALNUM.sub("_", name.strip()).strip("_").lower()
