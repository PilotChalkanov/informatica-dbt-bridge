"""Aggregator -> `GROUP BY` + aggregate output columns.

`Group By Ports` (comma-or-newline-separated) supplies the GROUP BY columns;
non-grouped output ports with an EXPRESSION become the aggregate columns,
via the same expression translator Expression uses. An output port whose
expression is neither a Group By Ports column nor a recognized aggregate
function call is flagged rather than mistranslated - see
`_flag_non_aggregate_column`.
"""

from __future__ import annotations

import re

from informatica_dbt_bridge.cte import Cte, TranslationNote
from informatica_dbt_bridge.expressions import is_aggregate_function_call, translate_expression
from informatica_dbt_bridge.models import Port, TransformationNode
from informatica_dbt_bridge.naming import snake_case

_OUTPUT_PORT_TYPES = {"OUTPUT", "INPUT/OUTPUT"}
_GROUP_BY_PORTS_SPLIT = re.compile(r"[,\n]+")


def translate_aggregator(node: TransformationNode, *, upstream_cte: str) -> Cte:
    """Translate an Aggregator into `select <group>, <agg> from <upstream>` [+ `group by`].

    A missing (or blank) `Group By Ports` attribute is a legitimate global
    aggregate - no GROUP BY clause, and (unlike Filter's blank-condition
    case) not unusual enough to warrant a TranslationNote on its own.

    Args:
        node: The Aggregator `TransformationNode`.
        upstream_cte: The (already snake_cased) name of the CTE this
            aggregator reads from.

    Returns:
        The translated Cte. Includes a TranslationNote for every aggregate
        expression function that couldn't be translated (see
        `translate_expression`), and for every output port whose expression
        is neither a Group By Ports column nor a recognized aggregate call
        (see `_flag_non_aggregate_column`).
    """
    group_by_columns = _parse_group_by_ports(node.attribute("Group By Ports"))
    group_by_set = set(group_by_columns)

    notes: list[TranslationNote] = []
    aggregate_columns: list[str] = []
    for port in node.ports:
        if port.port_type not in _OUTPUT_PORT_TYPES or not port.expression:
            continue
        if port.name in group_by_set:
            # Already represented via the raw group-by column reference.
            continue
        if not is_aggregate_function_call(port.expression):
            aggregate_columns.append(_flag_non_aggregate_column(port))
            notes.append(_non_aggregate_column_note(node.name, port))
            continue
        result = translate_expression(port.expression)
        aggregate_columns.append(f"{result.sql} as {snake_case(port.name)}")
        for func in result.unrecognized_functions:
            notes.append(
                TranslationNote(
                    transformation=node.name,
                    message=(
                        f"unrecognized expression function {func!r} in port "
                        f"{port.name!r}; left verbatim, needs manual review"
                    ),
                )
            )

    columns = ", ".join([*group_by_columns, *aggregate_columns])
    sql = f"select {columns}\nfrom {upstream_cte}"
    if group_by_columns:
        sql += f"\ngroup by {', '.join(group_by_columns)}"

    return Cte(name=snake_case(node.name), sql=sql, notes=notes)


def _flag_non_aggregate_column(port: Port) -> str:
    """Render a TODO-flagged column for a non-aggregate, non-group-by output port.

    PowerCenter permits an Aggregator output port whose expression is neither
    a Group By Ports column nor wrapped in an aggregate function; at runtime
    it resolves to that column's value from the last (or first) physical row
    received per group - semantics with no safe, deterministic ANSI SQL
    `GROUP BY` equivalent (docs: transformation-guide/aggregator-transformation/
    group-by-ports/non-aggregate-expressions.html). Rather than silently
    guessing an aggregate wrapper (which would change behavior from what
    PowerCenter actually does), the raw expression is left verbatim with an
    inline block comment - a `/* ... */` block comment, not `-- `, so it stays
    safe to embed mid-select-list without swallowing the rest of the line.

    Args:
        port: The flagged output port.

    Returns:
        The column text: a TODO block comment, the raw (untranslated)
        expression, and the port's alias.
    """
    alias = snake_case(port.name)
    todo = (
        f"/* TODO(pc-migration): {port.name} is a non-aggregate, non-group-by "
        "expression - PowerCenter resolves this to a last-row value per group, "
        "which has no safe GROUP BY equivalent; manual review needed */"
    )
    return f"{todo} {port.expression} as {alias}"


def _non_aggregate_column_note(transformation: str, port: Port) -> TranslationNote:
    """Build the TranslationNote for a flagged non-aggregate, non-group-by output port.

    Args:
        transformation: The Aggregator's instance name.
        port: The flagged output port.

    Returns:
        The TranslationNote explaining the last-row semantics gap.
    """
    return TranslationNote(
        transformation=transformation,
        message=(
            f"port {port.name!r} has a non-aggregate expression {port.expression!r} "
            "that isn't listed in Group By Ports; PowerCenter resolves this to the "
            "last row received per group, which has no safe ANSI SQL GROUP BY "
            "equivalent - left as a TODO, needs manual review."
        ),
    )


def _parse_group_by_ports(value: str | None) -> list[str]:
    """Split a `Group By Ports` attribute value into its column names.

    Args:
        value: The raw `Group By Ports` TABLEATTRIBUTE value - a
            comma-or-newline-separated list of port names - or None if the
            attribute is absent.

    Returns:
        The column names, in order, stripped of surrounding whitespace.
        Empty if `value` is None or blank (a global aggregate).
    """
    if not value:
        return []
    return [part.strip() for part in _GROUP_BY_PORTS_SPLIT.split(value) if part.strip()]
