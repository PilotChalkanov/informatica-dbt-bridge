"""Lookup Procedure (connected) -> `LEFT JOIN <lookup_table> ON <Lookup condition>`.

Only the *connected* Lookup is handled here - an unconnected Lookup (called
via `:LKP.name(args)` inside an Expression) is a different translation shape
(skill file §3) and out of scope for this translator.

Unlike Filter/Expression/Aggregator, which only ever read one upstream CTE,
a Lookup reads the upstream (driving) CTE *and* joins a second, unrelated
source, then appends the lookup's OUTPUT ports as new columns onto the
upstream row - additive, like Expression, not a reshape like Aggregator. So
the select list follows Expression's "keep everything, add columns"
precedent, but qualified (`<upstream>.*` instead of bare `*`) since there
are now two tables in scope and an unqualified `*`/column name could be
ambiguous (a lookup table's join key column commonly shares its name with
the upstream column it's joined against).
"""

from __future__ import annotations

import re

from informatica_dbt_bridge.cte import Cte, TranslationNote
from informatica_dbt_bridge.models import Port, TransformationNode
from informatica_dbt_bridge.naming import snake_case

_INPUT_PORT_TYPES = {"INPUT", "INPUT/OUTPUT"}
_OUTPUT_PORT_TYPES = {"OUTPUT", "INPUT/OUTPUT"}
_IDENTIFIER_OR_STRING_LITERAL = re.compile(r"'[^']*'|[A-Za-z_]\w*")

_BLANK_CONDITION_TODO = (
    "/* TODO(pc-migration): Lookup condition is empty; manual review needed */ 1=1"
)


def translate_lookup(
    node: TransformationNode,
    *,
    upstream_cte: str,
    lookup_source_system: str,
    lookup_table: str,
) -> Cte:
    """Translate a connected Lookup into a `LEFT JOIN` against its lookup table.

    A `Sql Override`, if present, replaces the lookup table reference
    verbatim (as a derived table), mirroring Source Qualifier's `Sql Query`
    override.

    Args:
        node: The Lookup `TransformationNode`.
        upstream_cte: The (already snake_cased) name of the CTE this lookup
            reads from (the driving/left side of the join).
        lookup_source_system: The dbt `source()` name the lookup table is
            read from, e.g. `"erp"` - analogous to Source Qualifier's
            `source_system` parameter. Unused if `Sql Override` is set.
        lookup_table: The dbt `source()` table name for the lookup table,
            e.g. `"customer"` - analogous to Source Qualifier's
            `source_table` parameter. There's no confirmed, universal
            TABLEATTRIBUTE for this in the parsed model (see module notes in
            the project report), so - like Source Qualifier's source table -
            it's an explicit argument rather than something this function
            infers on its own. Unused if `Sql Override` is set.

    Returns:
        The translated Cte. Includes a TranslationNote if `Lookup condition`
        is blank (a LEFT JOIN can't be generated without one - a genuine
        authoring mistake, unlike Aggregator's blank-Group-By-Ports case)
        and if `Lookup Policy on Multiple Match` is set to a non-default
        value (a plain LEFT JOIN fans out to every matching row instead of
        applying that policy).
    """
    lookup_alias = snake_case(node.name)
    notes: list[TranslationNote] = []

    output_ports = [p for p in node.ports if p.port_type in _OUTPUT_PORT_TYPES]
    output_columns = [
        f"{lookup_alias}.{port.name} as {snake_case(port.name)}" for port in output_ports
    ]

    override = node.attribute("Sql Override")
    lookup_source = (
        f"({override})"
        if override
        else f"{{{{ source('{lookup_source_system}', '{lookup_table}') }}}}"
    )

    condition = node.attribute("Lookup condition")
    if condition:
        on_clause = _qualify_condition(
            condition,
            ports=node.ports,
            upstream_cte=upstream_cte,
            lookup_alias=lookup_alias,
        )
    else:
        on_clause = _BLANK_CONDITION_TODO
        notes.append(
            TranslationNote(
                transformation=node.name,
                message=(
                    "Lookup condition is empty; a LEFT JOIN needs a join condition - "
                    "left as a TODO placeholder, needs manual review."
                ),
            )
        )

    multi_match_policy = node.attribute("Lookup Policy on Multiple Match")
    if multi_match_policy:
        notes.append(
            TranslationNote(
                transformation=node.name,
                message=(
                    f"Lookup Policy on Multiple Match is set to {multi_match_policy!r}; a "
                    "plain LEFT JOIN returns every matching row instead of applying this "
                    "policy, which changes row cardinality if the lookup key isn't unique "
                    "- needs manual review."
                ),
            )
        )

    columns = ",\n    ".join([f"{upstream_cte}.*", *output_columns])
    sql = (
        f"select\n    {columns}\n"
        f"from {upstream_cte}\n"
        f"left join {lookup_source} as {lookup_alias}\n"
        f"    on {on_clause}"
    )

    return Cte(name=lookup_alias, sql=sql, notes=notes)


def _qualify_condition(
    condition: str,
    *,
    ports: list[Port],
    upstream_cte: str,
    lookup_alias: str,
) -> str:
    """Qualify a `Lookup condition` string's port-name tokens with table aliases.

    Deterministic, based only on information this transformation's own ports
    already carry - no CONNECTOR-graph traversal (no other translator in this
    codebase resolves port names through CONNECTOR edges either; conditions/
    expressions are taken as referring to already-matching column names, the
    same simplification Filter/Aggregator make for their own condition/
    expression strings). A token matching one of this Lookup's own OUTPUT
    port names (which are the physical lookup table's columns) is qualified
    with the lookup alias; a token matching one of its own INPUT port names
    is qualified with the upstream CTE's name, on the assumption the input
    port's name matches the upstream column feeding it (true whenever the
    mapping's authors kept names in sync, not guaranteed otherwise - a known
    limitation, not silently hidden). Anything else (operators, literals,
    unrecognized identifiers) is left untouched.

    Args:
        condition: The raw `Lookup condition` value, e.g.
            `"CUST_ID = IN_CUST_ID"`.
        ports: This Lookup transformation's own ports (both INPUT and
            OUTPUT); the function filters by port type itself.
        upstream_cte: The (already snake_cased) upstream CTE name.
        lookup_alias: The alias assigned to the lookup source in the `FROM`/
            `LEFT JOIN` clause.

    Returns:
        `condition` with recognized port-name tokens qualified.
    """
    input_names = {p.name.upper() for p in ports if p.port_type in _INPUT_PORT_TYPES}
    output_names = {p.name.upper() for p in ports if p.port_type in _OUTPUT_PORT_TYPES}

    def _replace(match: re.Match[str]) -> str:
        token = match.group(0)
        if token.startswith("'"):
            return token
        upper = token.upper()
        if upper in output_names:
            return f"{lookup_alias}.{token}"
        if upper in input_names:
            return f"{upstream_cte}.{token}"
        return token

    return _IDENTIFIER_OR_STRING_LITERAL.sub(_replace, condition)
