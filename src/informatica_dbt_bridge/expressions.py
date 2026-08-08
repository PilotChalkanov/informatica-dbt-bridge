"""Translates Informatica expression-language strings into SQL.

Recognizes a documented table of common functions (skill file §4) and rewrites
their call sites, recursing into arguments so nested calls translate too.
Anything it doesn't recognize is left verbatim and reported back to the caller
via `ExpressionResult.unrecognized_functions` — never silently guessed.
"""

from __future__ import annotations

from dataclasses import dataclass, field


class _ArgCountError(Exception):
    """Raised by a renderer when it got a number of arguments it can't handle."""


@dataclass(frozen=True)
class ExpressionResult:
    sql: str
    unrecognized_functions: list[str] = field(default_factory=list)


def translate_expression(expr: str) -> ExpressionResult:
    translator = _Translator()
    sql = translator.translate(expr)
    return ExpressionResult(sql=sql, unrecognized_functions=translator.unrecognized)


def _scan_string_literal(s: str, i: int) -> int:
    """`s[i] == \"'\"`; return the index just past the closing quote (handles '' escapes)."""
    j = i + 1
    n = len(s)
    while j < n:
        if s[j] == "'":
            if j + 1 < n and s[j + 1] == "'":
                j += 2
                continue
            return j + 1
        j += 1
    return j  # unterminated literal; treat rest of string as the literal


def _find_matching_paren(s: str, open_idx: int) -> int:
    depth = 0
    i = open_idx
    n = len(s)
    while i < n:
        ch = s[i]
        if ch == "'":
            i = _scan_string_literal(s, i)
            continue
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                return i
        i += 1
    raise ValueError(f"unbalanced parentheses in expression: {s!r}")


def _split_top_level_args(inner: str) -> list[str]:
    if inner.strip() == "":
        return []
    parts = []
    depth = 0
    start = 0
    i = 0
    n = len(inner)
    while i < n:
        ch = inner[i]
        if ch == "'":
            i = _scan_string_literal(inner, i)
            continue
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        elif ch == "," and depth == 0:
            parts.append(inner[start:i])
            start = i + 1
        i += 1
    parts.append(inner[start:])
    return [p.strip() for p in parts]


def _render_iif(args: list[str]) -> str:
    if len(args) != 3:
        raise _ArgCountError
    cond, when_true, when_false = args
    return f"CASE WHEN {cond} THEN {when_true} ELSE {when_false} END"


def _render_nvl(args: list[str]) -> str:
    if len(args) != 2:
        raise _ArgCountError
    return f"COALESCE({args[0]}, {args[1]})"


def _render_nvl2(args: list[str]) -> str:
    if len(args) != 3:
        raise _ArgCountError
    val, when_not_null, when_null = args
    return f"CASE WHEN {val} IS NOT NULL THEN {when_not_null} ELSE {when_null} END"


def _render_isnull(args: list[str]) -> str:
    if len(args) != 1:
        raise _ArgCountError
    return f"{args[0]} IS NULL"


def _render_decode(args: list[str]) -> str:
    if len(args) < 3:
        raise _ArgCountError
    value, *rest = args
    has_default = len(rest) % 2 == 1
    default = rest[-1] if has_default else None
    pairs = rest[:-1] if has_default else rest
    clauses = " ".join(f"WHEN {pairs[i]} THEN {pairs[i + 1]}" for i in range(0, len(pairs), 2))
    sql = f"CASE {value} {clauses}"
    if default is not None:
        sql += f" ELSE {default}"
    return f"{sql} END"


def _render_substr(args: list[str]) -> str:
    if len(args) != 3:
        raise _ArgCountError
    return f"SUBSTRING({', '.join(args)})"


_FUNCTION_RENDERERS = {
    "IIF": _render_iif,
    "NVL": _render_nvl,
    "NVL2": _render_nvl2,
    "ISNULL": _render_isnull,
    "DECODE": _render_decode,
    "SUBSTR": _render_substr,
}

_BARE_IDENTIFIER_REPLACEMENTS = {
    "SYSDATE": "CURRENT_TIMESTAMP",
    "SYSTIMESTAMP": "CURRENT_TIMESTAMP",
}


class _Translator:
    def __init__(self) -> None:
        self.unrecognized: list[str] = []

    def translate(self, expr: str) -> str:
        out: list[str] = []
        i = 0
        n = len(expr)
        while i < n:
            ch = expr[i]
            if ch == "'":
                j = _scan_string_literal(expr, i)
                out.append(expr[i:j])
                i = j
                continue
            if ch.isalpha() or ch == "_":
                j = i
                while j < n and (expr[j].isalnum() or expr[j] == "_"):
                    j += 1
                ident = expr[i:j]
                k = j
                while k < n and expr[k].isspace():
                    k += 1
                if k < n and expr[k] == "(":
                    close = _find_matching_paren(expr, k)
                    raw_args = _split_top_level_args(expr[k + 1 : close])
                    translated_args = [self.translate(a) for a in raw_args]
                    out.append(self._render_call(ident, translated_args))
                    i = close + 1
                    continue
                out.append(_BARE_IDENTIFIER_REPLACEMENTS.get(ident.upper(), ident))
                i = j
                continue
            out.append(ch)
            i += 1
        return "".join(out)

    def _render_call(self, ident: str, args: list[str]) -> str:
        renderer = _FUNCTION_RENDERERS.get(ident.upper())
        if renderer is not None:
            try:
                return renderer(args)
            except _ArgCountError:
                pass
        self.unrecognized.append(ident)
        return f"{ident}({', '.join(args)})"
