from informatica_dbt_bridge.models import Port, TableAttribute, TransformationNode
from informatica_dbt_bridge.translators.source_qualifier import translate_source_qualifier


def test_translate_source_qualifier_selects_output_ports_from_source() -> None:
    node = TransformationNode(
        name="SQ_ORDERS",
        type="Source Qualifier",
        ports=[
            Port(name="ORDER_ID", port_type="OUTPUT"),
            Port(name="STATUS", port_type="OUTPUT"),
        ],
        attributes=[],
    )

    cte = translate_source_qualifier(node, source_system="erp", source_table="orders")

    assert cte.name == "sq_orders"
    assert cte.sql == "select order_id, status\nfrom {{ source('erp', 'orders') }}"
    assert cte.notes == []


def test_translate_source_qualifier_adds_where_from_source_filter() -> None:
    node = TransformationNode(
        name="SQ_ORDERS",
        type="Source Qualifier",
        ports=[Port(name="STATUS", port_type="OUTPUT")],
        attributes=[TableAttribute(name="Source Filter", value="STATUS = 'ACTIVE'")],
    )

    cte = translate_source_qualifier(node, source_system="erp", source_table="orders")

    assert cte.sql == ("select status\nfrom {{ source('erp', 'orders') }}\nwhere STATUS = 'ACTIVE'")


def test_translate_source_qualifier_ignores_blank_source_filter() -> None:
    node = TransformationNode(
        name="SQ_ORDERS",
        type="Source Qualifier",
        ports=[Port(name="STATUS", port_type="OUTPUT")],
        attributes=[TableAttribute(name="Source Filter", value="")],
    )

    cte = translate_source_qualifier(node, source_system="erp", source_table="orders")

    assert "where" not in cte.sql


def test_translate_source_qualifier_uses_sql_query_override_verbatim() -> None:
    override = "SELECT order_id, status FROM orders WHERE status IN ('A', 'B')"
    node = TransformationNode(
        name="SQ_ORDERS",
        type="Source Qualifier",
        ports=[Port(name="ORDER_ID", port_type="OUTPUT")],
        attributes=[TableAttribute(name="Sql Query", value=override)],
    )

    cte = translate_source_qualifier(node, source_system="erp", source_table="orders")

    assert cte.sql == override
