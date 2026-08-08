"""Assembles an ordered list of CTEs into the final dbt model SQL text."""

from __future__ import annotations

from informatica_dbt_bridge.cte import Cte


def render_model(
    ctes: list[Cte], *, final_columns: list[str], final_from: str | None = None
) -> str:
    if not ctes:
        raise ValueError("render_model requires at least one CTE")

    blocks = [f"with {ctes[0].name} as (\n\n{_indent(ctes[0].sql)}\n\n)"]
    for cte in ctes[1:]:
        blocks.append(f"{cte.name} as (\n\n{_indent(cte.sql)}\n\n)")
    cte_section = ",\n\n".join(blocks)

    final_source = final_from or ctes[-1].name
    columns = ",\n    ".join(final_columns)
    final_select = f"select\n    {columns}\nfrom {final_source}"

    return f"{cte_section}\n\n{final_select}"


def _indent(sql: str, prefix: str = "    ") -> str:
    return "\n".join(prefix + line if line else line for line in sql.split("\n"))
