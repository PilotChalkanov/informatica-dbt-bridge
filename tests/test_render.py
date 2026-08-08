import pytest

from informatica_dbt_bridge.cte import Cte
from informatica_dbt_bridge.render import render_model


def test_render_model_single_cte() -> None:
    ctes = [
        Cte(
            name="sq_orders",
            sql="select order_id, status\nfrom {{ source('erp', 'orders') }}",
        )
    ]

    sql = render_model(ctes, final_columns=["order_id", "status"])

    assert sql == (
        "with sq_orders as (\n"
        "\n"
        "    select order_id, status\n"
        "    from {{ source('erp', 'orders') }}\n"
        "\n"
        ")\n"
        "\n"
        "select\n"
        "    order_id,\n"
        "    status\n"
        "from sq_orders"
    )


def test_render_model_chains_multiple_ctes_in_order() -> None:
    ctes = [
        Cte(name="sq_orders", sql="select order_id, status\nfrom {{ source('erp', 'orders') }}"),
        Cte(name="fil_active", sql="select *\nfrom sq_orders\nwhere status = 'ACTIVE'"),
    ]

    sql = render_model(ctes, final_columns=["order_id", "status"])

    assert sql == (
        "with sq_orders as (\n"
        "\n"
        "    select order_id, status\n"
        "    from {{ source('erp', 'orders') }}\n"
        "\n"
        "),\n"
        "\n"
        "fil_active as (\n"
        "\n"
        "    select *\n"
        "    from sq_orders\n"
        "    where status = 'ACTIVE'\n"
        "\n"
        ")\n"
        "\n"
        "select\n"
        "    order_id,\n"
        "    status\n"
        "from fil_active"
    )


def test_render_model_raises_when_given_no_ctes() -> None:
    with pytest.raises(ValueError, match="at least one CTE"):
        render_model([], final_columns=["order_id"])
