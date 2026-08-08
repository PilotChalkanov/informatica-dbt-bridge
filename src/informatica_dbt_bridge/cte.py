"""The intermediate representation translators emit: one CTE per transformation."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class TranslationNote:
    transformation: str
    message: str


@dataclass(frozen=True)
class Cte:
    name: str
    sql: str  # full "select ...\nfrom ..." body, no leading/trailing "with"/"as (...)"
    notes: list[TranslationNote] = field(default_factory=list)
