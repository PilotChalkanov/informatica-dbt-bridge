"""Expression -> derived SELECT columns. Passive: row count is unchanged."""

from __future__ import annotations

from informatica_dbt_bridge.cte import Cte, TranslationNote
from informatica_dbt_bridge.expressions import translate_expression
from informatica_dbt_bridge.models import TransformationNode
from informatica_dbt_bridge.naming import snake_case

_OUTPUT_PORT_TYPES = {"OUTPUT", "INPUT/OUTPUT"}


def translate_expression_transformation(node: TransformationNode, *, upstream_cte: str) -> Cte:
    notes: list[TranslationNote] = []
    derived_columns: list[str] = []

    for port in node.ports:
        if port.port_type not in _OUTPUT_PORT_TYPES or not port.expression:
            continue
        result = translate_expression(port.expression)
        derived_columns.append(f"{result.sql} as {snake_case(port.name)}")
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

    if not derived_columns:
        sql = f"select *\nfrom {upstream_cte}"
    else:
        columns = ",\n    ".join(["*", *derived_columns])
        sql = f"select\n    {columns}\nfrom {upstream_cte}"

    return Cte(name=snake_case(node.name), sql=sql, notes=notes)
