"""Source Qualifier -> base `select ... from {{ source(...) }}`."""

from __future__ import annotations

from informatica_dbt_bridge.cte import Cte
from informatica_dbt_bridge.models import TransformationNode
from informatica_dbt_bridge.naming import snake_case

_OUTPUT_PORT_TYPES = {"OUTPUT", "INPUT/OUTPUT"}


def translate_source_qualifier(
    node: TransformationNode, *, source_system: str, source_table: str
) -> Cte:
    """Translate a Source Qualifier into a base `select ... from {{ source(...) }}` CTE.

    A `Sql Query` override, if present, replaces the generated select verbatim.
    A `Source Filter`, if present, becomes a `where` clause.

    Args:
        node: The Source Qualifier `TransformationNode`.
        source_system: The dbt `source()` name to read from, e.g. `"erp"`.
        source_table: The dbt `source()` table name, e.g. `"orders"`.

    Returns:
        The translated Cte.
    """
    override = node.attribute("Sql Query")
    if override:
        return Cte(name=snake_case(node.name), sql=override)

    columns = [snake_case(p.name) for p in node.ports if p.port_type in _OUTPUT_PORT_TYPES]
    sql = f"select {', '.join(columns)}\nfrom {{{{ source('{source_system}', '{source_table}') }}}}"

    source_filter = node.attribute("Source Filter")
    if source_filter:
        sql += f"\nwhere {source_filter}"

    return Cte(name=snake_case(node.name), sql=sql)
