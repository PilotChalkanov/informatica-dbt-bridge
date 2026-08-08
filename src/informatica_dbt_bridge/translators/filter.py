"""Filter -> `where <Filter Condition>` over the upstream CTE."""

from __future__ import annotations

from informatica_dbt_bridge.cte import Cte, TranslationNote
from informatica_dbt_bridge.models import TransformationNode
from informatica_dbt_bridge.naming import snake_case


def translate_filter(node: TransformationNode, *, upstream_cte: str) -> Cte:
    """Translate a Filter into `select * from <upstream> where <Filter Condition>`.

    An empty Filter Condition is treated as a pass-through, flagged with a
    TranslationNote since it's unusual rather than actively wrong.

    Args:
        node: The Filter `TransformationNode`.
        upstream_cte: The (already snake_cased) name of the CTE this filter
            reads from.

    Returns:
        The translated Cte.
    """
    sql = f"select *\nfrom {upstream_cte}"

    condition = node.attribute("Filter Condition")
    notes: list[TranslationNote] = []
    if condition:
        sql += f"\nwhere {condition}"
    else:
        notes.append(
            TranslationNote(
                transformation=node.name,
                message="Filter Condition is empty; treating as a pass-through.",
            )
        )

    return Cte(name=snake_case(node.name), sql=sql, notes=notes)
