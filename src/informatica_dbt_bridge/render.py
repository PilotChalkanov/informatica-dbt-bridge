"""Assembles an ordered list of CTEs into the final dbt model SQL text."""

from __future__ import annotations

from informatica_dbt_bridge.cte import Cte


def render_model(
    ctes: list[Cte], *, final_columns: list[str], final_from: str | None = None
) -> str:
    """Chain `ctes` into a single "with ... select" dbt model.

    The final select maps `final_columns` (in order) onto `final_from`, which
    defaults to the last CTE in the list.

    Args:
        ctes: The transformation chain's CTEs, in dependency order (upstream
            first). Must be non-empty.
        final_columns: Output column names, in order, for the final select.
        final_from: The CTE (or table) the final select reads from. Defaults
            to the name of the last entry in `ctes`.

    Returns:
        The complete dbt model SQL text.

    Raises:
        ValueError: `ctes` is empty.
    """
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
    """Indent every non-blank line of `sql` by `prefix`.

    Args:
        sql: The text to indent.
        prefix: The string prepended to each non-blank line.

    Returns:
        The indented text.
    """
    return "\n".join(prefix + line if line else line for line in sql.split("\n"))
