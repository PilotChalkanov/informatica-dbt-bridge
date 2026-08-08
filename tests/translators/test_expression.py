from informatica_dbt_bridge.models import Port, TransformationNode
from informatica_dbt_bridge.translators.expression import translate_expression_transformation


def test_translate_expression_adds_derived_column_alongside_star() -> None:
    node = TransformationNode(
        name="EXP_CALC",
        type="Expression",
        ports=[
            Port(name="AMOUNT", port_type="INPUT/OUTPUT"),
            Port(
                name="IS_LARGE",
                port_type="OUTPUT",
                expression="IIF(AMOUNT > 1000, 'Y', 'N')",
            ),
        ],
        attributes=[],
    )

    cte = translate_expression_transformation(node, upstream_cte="lkp_customer")

    assert cte.name == "exp_calc"
    assert cte.sql == (
        "select\n"
        "    *,\n"
        "    CASE WHEN AMOUNT > 1000 THEN 'Y' ELSE 'N' END as is_large\n"
        "from lkp_customer"
    )
    assert cte.notes == []


def test_translate_expression_is_pure_passthrough_when_no_ports_have_expressions() -> None:
    node = TransformationNode(
        name="EXP_NOOP",
        type="Expression",
        ports=[Port(name="AMOUNT", port_type="INPUT/OUTPUT")],
        attributes=[],
    )

    cte = translate_expression_transformation(node, upstream_cte="sq_orders")

    assert cte.sql == "select *\nfrom sq_orders"


def test_translate_expression_records_note_for_unrecognized_function() -> None:
    node = TransformationNode(
        name="EXP_CALC",
        type="Expression",
        ports=[
            Port(name="WEIRD", port_type="OUTPUT", expression="MY_CUSTOM_FUNC(AMOUNT)"),
        ],
        attributes=[],
    )

    cte = translate_expression_transformation(node, upstream_cte="sq_orders")

    assert len(cte.notes) == 1
    assert cte.notes[0].transformation == "EXP_CALC"
    assert "MY_CUSTOM_FUNC" in cte.notes[0].message
