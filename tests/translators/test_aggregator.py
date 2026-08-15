import pytest

from informatica_dbt_bridge.models import Port, TableAttribute, TransformationNode
from informatica_dbt_bridge.translators.aggregator import translate_aggregator


def test_translate_aggregator_groups_by_single_column_with_one_aggregate() -> None:
    node = TransformationNode(
        name="AGG_BY_REGION",
        type="Aggregator",
        ports=[
            Port(name="REGION", port_type="OUTPUT"),
            Port(name="TOTAL_AMOUNT", port_type="OUTPUT", expression="SUM(AMOUNT)"),
        ],
        attributes=[TableAttribute(name="Group By Ports", value="REGION")],
    )

    cte = translate_aggregator(node, upstream_cte="fil_active")

    assert cte.name == "agg_by_region"
    assert cte.sql == (
        "select REGION, SUM(AMOUNT) as total_amount\nfrom fil_active\ngroup by REGION"
    )
    assert cte.notes == []


@pytest.mark.parametrize(
    "group_by_value",
    [
        "REGION,PRODUCT",
        "REGION, PRODUCT",
        "REGION\nPRODUCT",
        "REGION,\nPRODUCT",
    ],
)
def test_translate_aggregator_splits_group_by_ports_on_comma_or_newline(
    group_by_value: str,
) -> None:
    node = TransformationNode(
        name="AGG_BY_REGION_PRODUCT",
        type="Aggregator",
        ports=[
            Port(name="REGION", port_type="OUTPUT"),
            Port(name="PRODUCT", port_type="OUTPUT"),
            Port(name="TOTAL_AMOUNT", port_type="OUTPUT", expression="SUM(AMOUNT)"),
        ],
        attributes=[TableAttribute(name="Group By Ports", value=group_by_value)],
    )

    cte = translate_aggregator(node, upstream_cte="fil_active")

    assert cte.sql == (
        "select REGION, PRODUCT, SUM(AMOUNT) as total_amount\n"
        "from fil_active\n"
        "group by REGION, PRODUCT"
    )


def test_translate_aggregator_with_multiple_aggregate_output_ports() -> None:
    node = TransformationNode(
        name="AGG_BY_REGION",
        type="Aggregator",
        ports=[
            Port(name="REGION", port_type="OUTPUT"),
            Port(name="TOTAL_AMOUNT", port_type="OUTPUT", expression="SUM(AMOUNT)"),
            Port(name="ORDER_COUNT", port_type="OUTPUT", expression="COUNT(ORDER_ID)"),
        ],
        attributes=[TableAttribute(name="Group By Ports", value="REGION")],
    )

    cte = translate_aggregator(node, upstream_cte="fil_active")

    assert cte.sql == (
        "select REGION, SUM(AMOUNT) as total_amount, COUNT(ORDER_ID) as order_count\n"
        "from fil_active\n"
        "group by REGION"
    )
    assert cte.notes == []


def test_translate_aggregator_without_group_by_ports_is_global_aggregate() -> None:
    node = TransformationNode(
        name="AGG_TOTAL",
        type="Aggregator",
        ports=[Port(name="TOTAL_AMOUNT", port_type="OUTPUT", expression="SUM(AMOUNT)")],
        attributes=[],
    )

    cte = translate_aggregator(node, upstream_cte="fil_active")

    assert cte.sql == "select SUM(AMOUNT) as total_amount\nfrom fil_active"
    assert "group by" not in cte.sql
    # A global aggregate (no Group By Ports) is a legitimate, common PowerCenter
    # pattern -- unlike Filter's blank-condition case, it isn't a red flag on its
    # own, so it doesn't need a TranslationNote.
    assert cte.notes == []


def test_translate_aggregator_with_blank_group_by_ports_value_is_global_aggregate() -> None:
    node = TransformationNode(
        name="AGG_TOTAL",
        type="Aggregator",
        ports=[Port(name="TOTAL_AMOUNT", port_type="OUTPUT", expression="SUM(AMOUNT)")],
        attributes=[TableAttribute(name="Group By Ports", value="")],
    )

    cte = translate_aggregator(node, upstream_cte="fil_active")

    assert cte.sql == "select SUM(AMOUNT) as total_amount\nfrom fil_active"
    assert cte.notes == []


def test_translate_aggregator_records_note_for_unrecognized_aggregate_function() -> None:
    node = TransformationNode(
        name="AGG_BY_REGION",
        type="Aggregator",
        ports=[
            Port(name="REGION", port_type="OUTPUT"),
            Port(name="MEDIAN_AMOUNT", port_type="OUTPUT", expression="MEDIAN(AMOUNT)"),
        ],
        attributes=[TableAttribute(name="Group By Ports", value="REGION")],
    )

    cte = translate_aggregator(node, upstream_cte="fil_active")

    assert len(cte.notes) == 1
    assert cte.notes[0].transformation == "AGG_BY_REGION"
    assert "MEDIAN" in cte.notes[0].message
    assert "MEDIAN_AMOUNT" in cte.notes[0].message


@pytest.mark.parametrize("expression", ["FIRST(AMOUNT)", "LAST(AMOUNT)"])
def test_translate_aggregator_records_note_for_first_and_last_functions(expression: str) -> None:
    # FIRST/LAST are Aggregator-only, row-order-dependent functions that need a
    # FIRST_VALUE()/LAST_VALUE() OVER (...) rewrite (skill file SS4) -- out of
    # scope for a first pass, so they're expected to surface as TODO-worthy
    # unrecognized functions rather than be silently mistranslated.
    node = TransformationNode(
        name="AGG_BY_REGION",
        type="Aggregator",
        ports=[
            Port(name="REGION", port_type="OUTPUT"),
            Port(name="FIRST_AMOUNT", port_type="OUTPUT", expression=expression),
        ],
        attributes=[TableAttribute(name="Group By Ports", value="REGION")],
    )

    cte = translate_aggregator(node, upstream_cte="fil_active")

    assert len(cte.notes) == 1
    assert cte.notes[0].transformation == "AGG_BY_REGION"


def test_translate_aggregator_ignores_input_ports_without_expression() -> None:
    node = TransformationNode(
        name="AGG_BY_REGION",
        type="Aggregator",
        ports=[
            Port(name="AMOUNT", port_type="INPUT"),
            Port(name="REGION", port_type="OUTPUT"),
            Port(name="TOTAL_AMOUNT", port_type="OUTPUT", expression="SUM(AMOUNT)"),
        ],
        attributes=[TableAttribute(name="Group By Ports", value="REGION")],
    )

    cte = translate_aggregator(node, upstream_cte="fil_active")

    assert cte.sql == (
        "select REGION, SUM(AMOUNT) as total_amount\nfrom fil_active\ngroup by REGION"
    )


def test_translate_aggregator_supports_conditional_clause_on_aggregate_function() -> None:
    node = TransformationNode(
        name="AGG_BY_REGION",
        type="Aggregator",
        ports=[
            Port(name="REGION", port_type="OUTPUT"),
            Port(
                name="ACTIVE_AMOUNT",
                port_type="OUTPUT",
                expression="SUM(AMOUNT, STATUS = 'ACTIVE')",
            ),
        ],
        attributes=[TableAttribute(name="Group By Ports", value="REGION")],
    )

    cte = translate_aggregator(node, upstream_cte="fil_active")

    assert cte.sql == (
        "select REGION, SUM(CASE WHEN STATUS = 'ACTIVE' THEN AMOUNT END) as active_amount\n"
        "from fil_active\n"
        "group by REGION"
    )
    assert cte.notes == []


def test_translate_aggregator_flags_non_aggregate_non_group_by_expression() -> None:
    node = TransformationNode(
        name="AGG_BY_REGION",
        type="Aggregator",
        ports=[
            Port(name="REGION", port_type="OUTPUT"),
            Port(
                name="REGION_DESC_UPPER",
                port_type="OUTPUT",
                expression="UPPER(REGION_DESC)",
            ),
        ],
        attributes=[TableAttribute(name="Group By Ports", value="REGION")],
    )

    cte = translate_aggregator(node, upstream_cte="fil_active")

    assert len(cte.notes) == 1
    assert cte.notes[0].transformation == "AGG_BY_REGION"
    assert "REGION_DESC_UPPER" in cte.notes[0].message
    assert "last" in cte.notes[0].message.lower()
    assert "TODO(pc-migration)" in cte.sql
    assert "UPPER(REGION_DESC)" in cte.sql


def test_translate_aggregator_flags_bare_non_aggregate_port_reference() -> None:
    node = TransformationNode(
        name="AGG_BY_REGION",
        type="Aggregator",
        ports=[
            Port(name="REGION", port_type="OUTPUT"),
            Port(name="LAST_STATUS", port_type="OUTPUT", expression="STATUS"),
        ],
        attributes=[TableAttribute(name="Group By Ports", value="REGION")],
    )

    cte = translate_aggregator(node, upstream_cte="fil_active")

    assert len(cte.notes) == 1
    assert cte.notes[0].transformation == "AGG_BY_REGION"
    assert "LAST_STATUS" in cte.notes[0].message
    assert "TODO(pc-migration)" in cte.sql


def test_translate_aggregator_does_not_flag_group_by_port_with_redundant_expression() -> None:
    node = TransformationNode(
        name="AGG_BY_REGION",
        type="Aggregator",
        ports=[
            Port(name="REGION", port_type="OUTPUT", expression="REGION"),
            Port(name="TOTAL_AMOUNT", port_type="OUTPUT", expression="SUM(AMOUNT)"),
        ],
        attributes=[TableAttribute(name="Group By Ports", value="REGION")],
    )

    cte = translate_aggregator(node, upstream_cte="fil_active")

    assert cte.notes == []
    assert "TODO(pc-migration)" not in cte.sql
    assert cte.sql == (
        "select REGION, SUM(AMOUNT) as total_amount\nfrom fil_active\ngroup by REGION"
    )


def test_translate_aggregator_does_not_flag_recognized_aggregate_function_call() -> None:
    node = TransformationNode(
        name="AGG_BY_REGION",
        type="Aggregator",
        ports=[
            Port(name="REGION", port_type="OUTPUT"),
            Port(name="TOTAL_AMOUNT", port_type="OUTPUT", expression="SUM(AMOUNT)"),
        ],
        attributes=[TableAttribute(name="Group By Ports", value="REGION")],
    )

    cte = translate_aggregator(node, upstream_cte="fil_active")

    assert cte.notes == []
    assert "TODO(pc-migration)" not in cte.sql


def test_translate_aggregator_name_is_snake_cased() -> None:
    node = TransformationNode(
        name="AGG BY-REGION",
        type="Aggregator",
        ports=[Port(name="TOTAL_AMOUNT", port_type="OUTPUT", expression="SUM(AMOUNT)")],
        attributes=[],
    )

    cte = translate_aggregator(node, upstream_cte="fil_active")

    assert cte.name == "agg_by_region"
