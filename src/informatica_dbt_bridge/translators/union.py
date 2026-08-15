"""Union (a Union-shaped Custom Transformation) -> `UNION ALL` across N input groups.

A real PowerCenter Union has no `TYPE` of its own - it's a `Custom
Transformation` whose `TEMPLATENAME` is `"Union Transformation"`
(`converter.py` checks this before ever calling `translate_union`; anything
else with `TYPE="Custom Transformation"` falls through to the generic
unsupported-TODO path, per the skill file's "Custom/Java transformations
need manual review, never guess"). Structurally, a Union has one `OUTPUT`
port group and N named `INPUT` port groups (`Group` on `TransformationNode`,
from `<GROUP>` children), each with its own independently-named ports - an
input group's ports are *not* name- or position-matched to the OUTPUT
group's ports. `FIELDDEPENDENCY` children (`FieldDependency` on
`TransformationNode`) are the authoritative input-field -> output-field
mapping and are used here as the sole source of column aliasing - never
inferred from naming conventions or declaration order, even where those
happen to align (as they do in the real demo export).
"""

from __future__ import annotations

from informatica_dbt_bridge.cte import Cte, TranslationNote
from informatica_dbt_bridge.models import TransformationNode
from informatica_dbt_bridge.naming import snake_case


def is_union_transformation(node: TransformationNode) -> bool:
    """Whether `node` is a real PowerCenter Union, not just any Custom Transformation.

    A Union has no `TYPE` of its own - it's a `Custom Transformation` whose
    `TEMPLATENAME` happens to be `"Union Transformation"`. Anything else
    with `TYPE == "Custom Transformation"` (arbitrary compiled/Java logic)
    must stay flagged for manual review (skill file §3/§6) - never silently
    treated as a Union just because it shares the same `TYPE`.

    Args:
        node: The transformation to check.

    Returns:
        True if `node.type == "Custom Transformation"` and
        `node.template_name == "Union Transformation"`.
    """
    return node.type == "Custom Transformation" and node.template_name == "Union Transformation"


def translate_union(node: TransformationNode, *, upstream_by_group: dict[str, str]) -> Cte:
    """Translate a Union-shaped Custom Transformation into a `UNION ALL` chain.

    One `select ... from <upstream>` branch per INPUT group, in `GROUP
    ORDER` order (the authoritative ordering signal - never incidental
    dict/list order), with columns in the OUTPUT group's own port
    declaration order, aliased and sourced via `FIELDDEPENDENCY`.

    Args:
        node: The Union `TransformationNode` (a Custom Transformation with
            `template_name == "Union Transformation"`).
        upstream_by_group: The already-snake_cased upstream CTE name for
            every INPUT group on `node`, keyed by group name.

    Returns:
        The translated Cte. Includes a TranslationNote for any output column
        with no resolvable `FIELDDEPENDENCY` entry for a given input group -
        rendered as a flagged `NULL` placeholder (to keep every branch's
        column count/order aligned for the `UNION ALL`) rather than guessed
        or silently dropped.

    Raises:
        ValueError: `node` doesn't have exactly one OUTPUT group, or has no
            INPUT groups - both mean `node` isn't a well-formed Union
            despite being routed here as one.
        KeyError: `upstream_by_group` has no entry for one of `node.groups`'
            INPUT group names.
    """
    output_groups = [g.name for g in node.groups if g.type == "OUTPUT"]
    if len(output_groups) != 1:
        raise ValueError(
            f"{node.name!r} (Union) must have exactly one OUTPUT group; found {output_groups}"
        )
    output_group = output_groups[0]

    input_groups = sorted((g for g in node.groups if g.type == "INPUT"), key=lambda g: g.order)
    if not input_groups:
        raise ValueError(f"{node.name!r} (Union) has no INPUT groups")

    output_ports = [p for p in node.ports if p.group == output_group]
    group_of_port = {p.name: p.group for p in node.ports}

    notes: list[TranslationNote] = []
    branches: list[str] = []
    for group in input_groups:
        upstream_cte = upstream_by_group[group.name]
        columns: list[str] = []
        for output_port in output_ports:
            alias = snake_case(output_port.name)
            input_field = _resolve_input_field(
                node,
                group_name=group.name,
                output_field=output_port.name,
                group_of_port=group_of_port,
            )
            if input_field is None:
                columns.append(
                    f"NULL as {alias}  /* TODO(pc-migration): no FIELDDEPENDENCY maps "
                    f"group {group.name!r} to output field {output_port.name!r}; manual "
                    "review needed */"
                )
                notes.append(
                    TranslationNote(
                        transformation=node.name,
                        message=(
                            f"group {group.name!r} has no FIELDDEPENDENCY entry for output "
                            f"field {output_port.name!r}; rendered as NULL, needs manual "
                            "review."
                        ),
                    )
                )
            else:
                columns.append(f"{input_field} as {alias}")
        columns_block = ",\n    ".join(columns)
        branches.append(f"select\n    {columns_block}\nfrom {upstream_cte}")

    sql = "\nunion all\n".join(branches)
    return Cte(name=snake_case(node.name), sql=sql, notes=notes)


def _resolve_input_field(
    node: TransformationNode,
    *,
    group_name: str,
    output_field: str,
    group_of_port: dict[str, str | None],
) -> str | None:
    """Find the input field, from `group_name`, that feeds `output_field`.

    Args:
        node: The Union TransformationNode (for its `field_dependencies`).
        group_name: The input group currently being rendered.
        output_field: The output port name to resolve a source for.
        group_of_port: Every port's name mapped to its owning group name.

    Returns:
        The matching input field name, or None if no `FIELDDEPENDENCY`
        entry maps an input field belonging to `group_name` to
        `output_field`.
    """
    for dep in node.field_dependencies:
        if dep.output_field != output_field:
            continue
        if group_of_port.get(dep.input_field) == group_name:
            return dep.input_field
    return None
