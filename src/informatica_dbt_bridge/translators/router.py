"""Router -> one filtered `select` per OUTPUT group, N-ary fan-**out** (the mirror
image of Union's N-ary fan-**in**).

A Router has one `INPUT` group and N named OUTPUT-ish groups (`Group` on
`TransformationNode`, from `<GROUP>` children, same mechanism Union uses):
regular groups (`TYPE="OUTPUT"`) each carry their own filter condition as an
`EXPRESSION` attribute directly on the `<GROUP>` element (not a
`TABLEATTRIBUTE`), and exactly one catch-all default group
(`TYPE="OUTPUT/DEFAULT"`) with no `EXPRESSION` of its own - its filter is
synthesized as the negation of every other group's condition. Each OUTPUT
group's own `TRANSFORMFIELD`s carry a `REF_FIELD` attribute naming which
INPUT-group port they rename/pass through - the authoritative column-source
signal (same category of problem as Union's `FIELDDEPENDENCY`, opposite
direction), never inferred from naming conventions or position.

Unlike every translator before it, one Router instance becomes **multiple**
CTEs (one per non-INPUT group) - `translate_router` returns `list[Cte]`
instead of a single `Cte`. `router_group_cte_name` is exported so
`converter.py` can independently compute the exact same CTE name when
resolving a downstream node's upstream to a specific Router branch.
"""

from __future__ import annotations

from informatica_dbt_bridge.cte import Cte, TranslationNote
from informatica_dbt_bridge.models import Group, TransformationNode
from informatica_dbt_bridge.naming import snake_case


def is_input_group(group_type: str) -> bool:
    """Whether a `Group.type` value marks it as a Router's (single) INPUT group.

    Checked as a `/`-delimited token (mirroring `is_master_port_type` in
    `translators/joiner.py`), not a brittle exact-string or substring match.

    Args:
        group_type: A `Group.type` value, e.g. `"INPUT"`, `"OUTPUT"`, or
            `"OUTPUT/DEFAULT"`.

    Returns:
        True if `group_type` carries the `INPUT` token.
    """
    return "INPUT" in group_type.split("/")


def is_output_group(group_type: str) -> bool:
    """Whether a `Group.type` value marks it as one of a Router's OUTPUT-ish groups.

    True for both a regular group (`"OUTPUT"`) and the default group
    (`"OUTPUT/DEFAULT"`) - both get their own CTE.

    Args:
        group_type: A `Group.type` value.

    Returns:
        True if `group_type` carries the `OUTPUT` token.
    """
    return "OUTPUT" in group_type.split("/")


def is_default_group(group_type: str) -> bool:
    """Whether a `Group.type` value marks it as a Router's catch-all default group.

    Args:
        group_type: A `Group.type` value.

    Returns:
        True if `group_type` carries the `DEFAULT` token (i.e.
        `"OUTPUT/DEFAULT"`).
    """
    return "DEFAULT" in group_type.split("/")


def router_group_cte_name(router_name: str, group_name: str) -> str:
    """The CTE name for one of a Router's group branches.

    Shared, byte-for-byte, between `translate_router` (which names the CTEs
    it returns) and `converter.py` (which must independently resolve what a
    downstream node's upstream CTE name actually is, given only the Router's
    raw instance name and the group its CONNECTOR edges land on).

    Args:
        router_name: The Router transformation's raw instance name.
        group_name: The group's raw name.

    Returns:
        `f"{snake_case(router_name)}_{snake_case(group_name)}"`.
    """
    return f"{snake_case(router_name)}_{snake_case(group_name)}"


def translate_router(node: TransformationNode, *, upstream_cte: str) -> list[Cte]:
    """Translate a Router into one filtered `select` CTE per non-INPUT group.

    Ordered by `Group.order` (deterministic/readable, not correctness-
    critical - each returned Cte is an independently-named branch with no
    ordering dependency on its siblings, unlike Union's `UNION ALL` chain).

    Args:
        node: The Router `TransformationNode`.
        upstream_cte: The (already snake_cased) name of the CTE this router
            reads from.

    Returns:
        One Cte per non-INPUT group (regular groups and the default group
        alike), named via `router_group_cte_name`. Each Cte's notes include
        a TranslationNote for any of that group's output ports with no
        `REF_FIELD` (rendered as a flagged `NULL` placeholder rather than
        guessed) and for a non-default group with a blank `EXPRESSION`
        (rendered as a pass-through, mirroring Filter's blank-condition
        case).
    """
    output_groups = sorted(
        (g for g in node.groups if is_output_group(g.type)), key=lambda g: g.order
    )
    non_default_conditions = [
        g.expression.strip()
        for g in output_groups
        if not is_default_group(g.type) and g.expression and g.expression.strip()
    ]

    return [
        _translate_group(node, group, upstream_cte, non_default_conditions)
        for group in output_groups
    ]


def _translate_group(
    node: TransformationNode,
    group: Group,
    upstream_cte: str,
    non_default_conditions: list[str],
) -> Cte:
    """Translate one of a Router's OUTPUT-ish groups into its own Cte.

    Args:
        node: The Router `TransformationNode`.
        group: The group being translated.
        upstream_cte: The (already snake_cased) upstream CTE name.
        non_default_conditions: Every non-default group's stripped,
            non-blank `EXPRESSION`, used to synthesize the default group's
            negated condition.

    Returns:
        The translated Cte for this one group.
    """
    notes: list[TranslationNote] = []
    columns: list[str] = []
    for port in node.ports:
        if port.group != group.name:
            continue
        alias = snake_case(port.name)
        if port.ref_field is None:
            columns.append(
                f"NULL as {alias}  /* TODO(pc-migration): {port.name} has no REF_FIELD; "
                "manual review needed */"
            )
            notes.append(
                TranslationNote(
                    transformation=node.name,
                    message=(
                        f"port {port.name!r} in group {group.name!r} has no REF_FIELD; "
                        "rendered as NULL, needs manual review."
                    ),
                )
            )
        else:
            columns.append(f"{port.ref_field} as {alias}")

    columns_block = ",\n    ".join(columns)
    sql = f"select\n    {columns_block}\nfrom {upstream_cte}"

    if is_default_group(group.type):
        if non_default_conditions:
            where_clause = " and ".join(f"not ({cond})" for cond in non_default_conditions)
            sql += f"\nwhere {where_clause}"
    elif group.expression and group.expression.strip():
        sql += f"\nwhere {group.expression.strip()}"
    else:
        notes.append(
            TranslationNote(
                transformation=node.name,
                message=(
                    f"group {group.name!r} has an empty EXPRESSION; treating as a pass-through."
                ),
            )
        )

    return Cte(name=router_group_cte_name(node.name, group.name), sql=sql, notes=notes)
