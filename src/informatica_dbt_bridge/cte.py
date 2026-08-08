"""The intermediate representation translators emit: one CTE per transformation."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class TranslationNote:
    """A manual-review flag raised by a translator, surfaced in the migration report."""

    transformation: str
    message: str


@dataclass(frozen=True)
class Cte:
    """One translated transformation: a named SQL body plus any TranslationNotes it raised."""

    name: str
    sql: str  # full "select ...\nfrom ..." body, no leading/trailing "with"/"as (...)"
    notes: list[TranslationNote] = field(default_factory=list)
