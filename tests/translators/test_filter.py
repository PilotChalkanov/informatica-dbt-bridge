from informatica_dbt_bridge.models import TableAttribute, TransformationNode
from informatica_dbt_bridge.translators.filter import translate_filter


def test_translate_filter_selects_star_with_where_condition() -> None:
    node = TransformationNode(
        name="FIL_ACTIVE",
        type="Filter",
        ports=[],
        attributes=[TableAttribute(name="Filter Condition", value="STATUS = 'ACTIVE'")],
    )

    cte = translate_filter(node, upstream_cte="sq_orders")

    assert cte.name == "fil_active"
    assert cte.sql == "select *\nfrom sq_orders\nwhere STATUS = 'ACTIVE'"
    assert cte.notes == []


def test_translate_filter_with_blank_condition_is_passthrough_with_note() -> None:
    node = TransformationNode(
        name="FIL_ACTIVE",
        type="Filter",
        ports=[],
        attributes=[TableAttribute(name="Filter Condition", value="")],
    )

    cte = translate_filter(node, upstream_cte="sq_orders")

    assert cte.sql == "select *\nfrom sq_orders"
    assert len(cte.notes) == 1
    assert cte.notes[0].transformation == "FIL_ACTIVE"
    assert "empty" in cte.notes[0].message.lower()
