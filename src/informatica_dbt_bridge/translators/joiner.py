"""Joiner (connected) -> two-upstream `JOIN` between a master and detail pipeline.

Unlike every other translator built so far, a Joiner reads from *two*
distinct upstream CTEs - not an external source like Lookup, but two other
transformations already in this same mapping's DAG - and fully redeclares
its own output row shape from its own ports (no upstream is passed through
via `*`; every selected column is one of the Joiner's own OUTPUT-bearing
ports, already deduplicated/renamed by PowerCenter itself, since a
transformation's port names must be unique within that transformation - see
`translators/aggregator.py`'s explicit-column-list precedent, not
`translators/lookup.py`'s/`translators/expression.py`'s additive `*` one,
since a Joiner reshapes into a brand-new row rather than adding onto an
existing one).

Which upstream is "master" vs "detail" is carried by the Joiner's own ports:
a master-side port's PORTTYPE has a `MASTER` token appended (e.g.
`"INPUT/OUTPUT/MASTER"`); a detail-side port's PORTTYPE has no such token
(e.g. `"INPUT/OUTPUT"`, `"INPUT"`, `"OUTPUT"`). `converter.py` uses
`is_master_port_type` (exported from this module) to resolve, of a Joiner's
two upstream predecessors, which one feeds the master ports and which feeds
the detail ports.
"""

from __future__ import annotations

import re

from informatica_dbt_bridge.cte import Cte, TranslationNote
from informatica_dbt_bridge.models import TransformationNode
from informatica_dbt_bridge.naming import snake_case

_IDENTIFIER_OR_STRING_LITERAL = re.compile(r"'[^']*'|[A-Za-z_]\w*")

_JOIN_TYPE_KEYWORDS = {
    "Normal Join": "inner join",
    "Master Outer Join": "right join",
    "Detail Outer Join": "left join",
    "Full Outer Join": "full join",
}

_BLANK_CONDITION_TODO = (
    "/* TODO(pc-migration): Join Condition is empty; manual review needed */ 1=1"
)


def is_master_port_type(port_type: str) -> bool:
    """Whether a Joiner port's PORTTYPE marks it as master-side.

    PowerCenter appends a `MASTER` token to a Joiner port's PORTTYPE for its
    master-side ports (e.g. `"INPUT/OUTPUT/MASTER"`); detail-side ports carry
    no such token (e.g. `"INPUT/OUTPUT"`). Checked as a `/`-delimited token,
    not a raw substring match, so it can't be fooled by some future PORTTYPE
    value that merely contains "MASTER" as a substring.

    Args:
        port_type: A `Port.port_type` value.

    Returns:
        True if `port_type` carries the `MASTER` token.
    """
    return "MASTER" in port_type.split("/")


def translate_joiner(node: TransformationNode, *, master_cte: str, detail_cte: str) -> Cte:
    """Translate a connected Joiner into a `JOIN` between its master and detail CTEs.

    Args:
        node: The Joiner `TransformationNode`.
        master_cte: The (already snake_cased) name of the master-side CTE.
        detail_cte: The (already snake_cased) name of the detail-side CTE.

    Returns:
        The translated Cte. Includes a TranslationNote if `Join Condition` is
        blank (a genuine authoring mistake - a JOIN can't be generated
        without one, mirroring Filter's blank-condition case) or if
        `Join Type` is missing/unrecognized (defaults to an `inner join`,
        flagged rather than silently assumed correct).
    """
    notes: list[TranslationNote] = []

    master_port_names = {p.name for p in node.ports if is_master_port_type(p.port_type)}
    detail_port_names = {p.name for p in node.ports if not is_master_port_type(p.port_type)}

    columns: list[str] = []
    for port in node.ports:
        if "OUTPUT" not in port.port_type.split("/"):
            continue
        alias = master_cte if port.name in master_port_names else detail_cte
        columns.append(f"{alias}.{port.name} as {snake_case(port.name)}")

    condition = node.attribute("Join Condition")
    if condition:
        on_clause = _qualify_condition(
            condition,
            master_port_names=master_port_names,
            detail_port_names=detail_port_names,
            master_cte=master_cte,
            detail_cte=detail_cte,
        )
    else:
        on_clause = _BLANK_CONDITION_TODO
        notes.append(
            TranslationNote(
                transformation=node.name,
                message=(
                    "Join Condition is empty; a JOIN needs a join condition - left as a "
                    "TODO placeholder, needs manual review."
                ),
            )
        )

    join_type = node.attribute("Join Type")
    join_keyword = _JOIN_TYPE_KEYWORDS.get(join_type) if join_type else None
    if join_keyword is None:
        join_keyword = (
            "/* TODO(pc-migration): unrecognized or missing Join Type "
            f"{join_type!r}; defaulted to INNER JOIN, needs manual review */ inner join"
        )
        notes.append(
            TranslationNote(
                transformation=node.name,
                message=(
                    f"Join Type {join_type!r} is missing or unrecognized; defaulted to an "
                    "INNER JOIN, needs manual review."
                ),
            )
        )

    columns_block = ",\n    ".join(columns)
    sql = (
        f"select\n    {columns_block}\n"
        f"from {master_cte}\n"
        f"{join_keyword} {detail_cte}\n"
        f"    on {on_clause}"
    )

    return Cte(name=snake_case(node.name), sql=sql, notes=notes)


def _qualify_condition(
    condition: str,
    *,
    master_port_names: set[str],
    detail_port_names: set[str],
    master_cte: str,
    detail_cte: str,
) -> str:
    """Qualify a `Join Condition` string's port-name tokens with table aliases.

    Deterministic, based only on this Joiner's own declared ports - no
    CONNECTOR-graph traversal (the same simplification `translators/lookup.py`
    makes for `Lookup condition`). A token matching one of this Joiner's own
    master-side port names is qualified with the master alias; a token
    matching a detail-side port name is qualified with the detail alias.
    Anything else (operators, literals, unrecognized identifiers) is left
    untouched.

    Args:
        condition: The raw `Join Condition` value, e.g. `"SKU1 = SKU"`.
        master_port_names: This Joiner's own master-side port names.
        detail_port_names: This Joiner's own detail-side port names.
        master_cte: The (already snake_cased) master CTE name.
        detail_cte: The (already snake_cased) detail CTE name.

    Returns:
        `condition` with recognized port-name tokens qualified.
    """
    master_upper = {n.upper() for n in master_port_names}
    detail_upper = {n.upper() for n in detail_port_names}

    def _replace(match: re.Match[str]) -> str:
        token = match.group(0)
        if token.startswith("'"):
            return token
        upper = token.upper()
        if upper in master_upper:
            return f"{master_cte}.{token}"
        if upper in detail_upper:
            return f"{detail_cte}.{token}"
        return token

    return _IDENTIFIER_OR_STRING_LITERAL.sub(_replace, condition)
