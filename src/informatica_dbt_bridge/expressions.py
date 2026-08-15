"""Translates Informatica expression-language strings into SQL.

Recognizes a documented table of common functions (skill file §4) and rewrites
their call sites, recursing into arguments so nested calls translate too.
Anything it doesn't recognize is left verbatim and reported back to the caller
via `ExpressionResult.unrecognized_functions` — never silently guessed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field


class _ArgCountError(Exception):
    """Raised by a renderer when it got a number of arguments it can't handle."""


@dataclass(frozen=True)
class ExpressionResult:
    """The SQL translation of an expression, plus any functions it couldn't translate."""

    sql: str
    unrecognized_functions: list[str] = field(default_factory=list)


def translate_expression(expr: str) -> ExpressionResult:
    """Translate a single Informatica expression-language string into SQL.

    Args:
        expr: A raw expression-language string, e.g.
            `"IIF(AMOUNT > 1000, 'Y', 'N')"`.

    Returns:
        An ExpressionResult with the translated SQL and the name of any
        function this translator didn't recognize (empty if everything was
        translated).
    """
    translator = _Translator()
    sql = translator.translate(expr)
    return ExpressionResult(sql=sql, unrecognized_functions=translator.unrecognized)


def _scan_string_literal(s: str, i: int) -> int:
    """Skip past a single-quoted string literal, handling `''`-escaped quotes.

    Args:
        s: The expression text.
        i: Index of the opening `'` (i.e. `s[i] == "'"`).

    Returns:
        The index just past the literal's closing quote.
    """
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
    """Find the `)` that closes the `(` at `open_idx`, skipping string literals.

    Args:
        s: The expression text.
        open_idx: Index of the opening `(`.

    Returns:
        The index of the matching closing `)`.

    Raises:
        ValueError: `s` has no matching closing paren for `open_idx`.
    """
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
    """Split a function call's argument list on top-level commas.

    Commas inside nested `(...)` or `'...'` don't count as separators.

    Args:
        inner: The text between a function call's outer parentheses.

    Returns:
        Each argument's text, stripped of surrounding whitespace. Empty list
        if `inner` is blank (a zero-argument call).
    """
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
    """`IIF(cond, a, b)` -> `CASE WHEN cond THEN a ELSE b END`.

    Args:
        args: The call's already-translated arguments; must have length 3.

    Returns:
        The equivalent `CASE WHEN` SQL expression.

    Raises:
        _ArgCountError: `args` doesn't have exactly 3 elements.
    """
    if len(args) != 3:
        raise _ArgCountError
    cond, when_true, when_false = args
    return f"CASE WHEN {cond} THEN {when_true} ELSE {when_false} END"


def _render_nvl(args: list[str]) -> str:
    """`NVL(val, default)` -> `COALESCE(val, default)`.

    Args:
        args: The call's already-translated arguments; must have length 2.

    Returns:
        The equivalent `COALESCE` SQL expression.

    Raises:
        _ArgCountError: `args` doesn't have exactly 2 elements.
    """
    if len(args) != 2:
        raise _ArgCountError
    return f"COALESCE({args[0]}, {args[1]})"


def _render_nvl2(args: list[str]) -> str:
    """`NVL2(val, a, b)` -> `CASE WHEN val IS NOT NULL THEN a ELSE b END`.

    Args:
        args: The call's already-translated arguments; must have length 3.

    Returns:
        The equivalent `CASE WHEN` SQL expression.

    Raises:
        _ArgCountError: `args` doesn't have exactly 3 elements.
    """
    if len(args) != 3:
        raise _ArgCountError
    val, when_not_null, when_null = args
    return f"CASE WHEN {val} IS NOT NULL THEN {when_not_null} ELSE {when_null} END"


def _render_isnull(args: list[str]) -> str:
    """`ISNULL(val)` -> `val IS NULL`.

    Args:
        args: The call's already-translated arguments; must have length 1.

    Returns:
        The equivalent `IS NULL` SQL expression.

    Raises:
        _ArgCountError: `args` doesn't have exactly 1 element.
    """
    if len(args) != 1:
        raise _ArgCountError
    return f"{args[0]} IS NULL"


def _render_decode(args: list[str]) -> str:
    """`DECODE(val, s1, r1, ..., [dflt])` -> `CASE val WHEN s1 THEN r1 ... [ELSE dflt] END`.

    Args:
        args: The call's already-translated arguments; must have at least 3
            elements (`val` plus at least one `search, result` pair), with an
            odd remainder after `val` meaning the last argument is a default.

    Returns:
        The equivalent `CASE` SQL expression.

    Raises:
        _ArgCountError: `args` has fewer than 3 elements.
    """
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
    """`SUBSTR(str, start, len)` -> `SUBSTRING(str, start, len)`.

    Args:
        args: The call's already-translated arguments; must have length 3.

    Returns:
        The equivalent `SUBSTRING` SQL expression.

    Raises:
        _ArgCountError: `args` doesn't have exactly 3 elements.
    """
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

# Aggregate functions that are already valid SQL as written - per skill file
# §4 ("same, only valid inside Aggregator/Rank context") - so only their
# arguments need recursive translation, not the call itself. Recognized (no
# TranslationNote), unlike a genuinely unsupported function. Deliberately
# excludes FIRST/LAST, which need a FIRST_VALUE()/LAST_VALUE() OVER (...)
# rewrite this translator doesn't attempt yet - those stay unrecognized.
_PASSTHROUGH_FUNCTIONS = {"SUM", "COUNT", "AVG", "MIN", "MAX"}

# All PowerCenter Aggregator-function names, per the Transformation Language
# Reference's aggregate-functions category - a superset of
# `_PASSTHROUGH_FUNCTIONS`. Used to recognize a call as *some* aggregate
# (even one this translator can't render, like MEDIAN/FIRST/LAST) so callers
# like the Aggregator translator can distinguish "untranslatable aggregate"
# from "not an aggregate at all".
AGGREGATE_FUNCTION_NAMES = {
    "AVG",
    "COUNT",
    "FIRST",
    "LAST",
    "MAX",
    "MEDIAN",
    "MIN",
    "PERCENTILE",
    "STDDEV",
    "SUM",
    "VARIANCE",
}


def _render_aggregate_passthrough(ident: str, args: list[str]) -> str:
    """`NAME(value)` -> unchanged; `NAME(value, cond)` -> `NAME(CASE WHEN cond THEN value END)`.

    Implements PowerCenter's Aggregator conditional-clause argument (docs:
    transformation-guide/aggregator-transformation/aggregate-expressions/
    conditional-clauses.html): a second boolean argument on SUM/COUNT/AVG/
    MIN/MAX restricts which rows get aggregated, e.g.
    `SUM(AMOUNT, STATUS = 'ACTIVE')` sums `AMOUNT` only over rows where
    `STATUS = 'ACTIVE'`.

    Args:
        ident: The function name as written at the call site (preserves
            original casing, unlike the other renderers which hardcode SQL
            keywords).
        args: The call's already-translated arguments; must have length 1 or
            2.

    Returns:
        The equivalent SQL aggregate call.

    Raises:
        _ArgCountError: `args` doesn't have exactly 1 or 2 elements.
    """
    if len(args) == 1:
        return f"{ident}({args[0]})"
    if len(args) == 2:
        value, condition = args
        return f"{ident}(CASE WHEN {condition} THEN {value} END)"
    raise _ArgCountError


def is_aggregate_function_call(expr: str) -> bool:
    """Whether `expr` is a single top-level call to a PowerCenter Aggregator function.

    "Aggregator function" here means any name in `AGGREGATE_FUNCTION_NAMES`
    (SUM, AVG, COUNT, MAX, MIN, MEDIAN, FIRST, LAST, PERCENTILE, STDDEV,
    VARIANCE - the PowerCenter Transformation Language Reference's
    aggregate-functions category), regardless of whether this translator can
    actually render it as SQL. Used by the Aggregator translator to tell a
    genuine (if perhaps untranslatable) aggregate expression apart from a
    plain non-aggregate one - PowerCenter resolves the latter to a last-row
    value with no safe `GROUP BY` equivalent (see the Aggregator
    transformation guide's "non-aggregate expressions" note).

    Args:
        expr: A raw Informatica expression-language string.

    Returns:
        True if `expr`, stripped of surrounding whitespace, is exactly one
        call `FUNC(...)` where `FUNC` is a known aggregate function name and
        the parens span the whole expression; False otherwise (including for
        expressions that merely contain an aggregate call, e.g. `SUM(A) + 1`
        or `IIF(x, SUM(A), 0)`, which this translator doesn't attempt to
        recognize as GROUP BY-safe today).
    """
    stripped = expr.strip()
    match = re.match(r"^([A-Za-z_]\w*)\s*\(", stripped)
    if match is None or match.group(1).upper() not in AGGREGATE_FUNCTION_NAMES:
        return False
    try:
        close_idx = _find_matching_paren(stripped, match.end() - 1)
    except ValueError:
        return False
    return close_idx == len(stripped) - 1


_BARE_IDENTIFIER_REPLACEMENTS = {
    "SYSDATE": "CURRENT_TIMESTAMP",
    "SYSTIMESTAMP": "CURRENT_TIMESTAMP",
}


class _Translator:
    """Recursive-descent translator: walks an expression once, tracking any
    function names it couldn't translate along the way."""

    def __init__(self) -> None:
        self.unrecognized: list[str] = []

    def translate(self, expr: str) -> str:
        """Translate `expr`, recursing into every function call's arguments.

        Args:
            expr: The expression-language text to translate.

        Returns:
            The translated SQL text. Any unrecognized function calls
            encountered are recorded on `self.unrecognized` as a side effect.
        """
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
        """Render one already-translated function call.

        Args:
            ident: The function name as written in the source expression.
            args: The call's arguments, already translated recursively.

        Returns:
            The SQL translation if `ident` is a known function called with a
            valid argument count; `ident` re-assembled verbatim with its
            (translated) arguments if it's a recognized passthrough function
            (e.g. `SUM`); otherwise the same verbatim reassembly, but with
            `ident` appended to `self.unrecognized`.
        """
        renderer = _FUNCTION_RENDERERS.get(ident.upper())
        if renderer is not None:
            try:
                return renderer(args)
            except _ArgCountError:
                pass
        if ident.upper() in _PASSTHROUGH_FUNCTIONS:
            try:
                return _render_aggregate_passthrough(ident, args)
            except _ArgCountError:
                pass
        self.unrecognized.append(ident)
        return f"{ident}({', '.join(args)})"
