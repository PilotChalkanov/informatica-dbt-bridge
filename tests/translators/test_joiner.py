import pytest

from informatica_dbt_bridge.models import Port, TableAttribute, TransformationNode
from informatica_dbt_bridge.translators.joiner import is_master_port_type, translate_joiner


def test_translate_joiner_normal_join_produces_inner_join() -> None:
    node = TransformationNode(
        name="JNR_SUPPLIES_PRODUCTS",
        type="Joiner",
        ports=[
            Port(name="ID", port_type="INPUT/OUTPUT"),
            Port(name="NAME", port_type="INPUT/OUTPUT"),
            Port(name="COST", port_type="INPUT/OUTPUT"),
            Port(name="PERISHABLE", port_type="INPUT/OUTPUT"),
            Port(name="SKU", port_type="INPUT/OUTPUT"),
            Port(name="SKU1", port_type="INPUT/OUTPUT/MASTER"),
        ],
        attributes=[
            TableAttribute(name="Join Condition", value="SKU1 = SKU"),
            TableAttribute(name="Join Type", value="Normal Join"),
        ],
    )

    cte = translate_joiner(node, master_cte="sq_raw_products1", detail_cte="sq_raw_supplies")

    assert cte.name == "jnr_supplies_products"
    assert cte.sql == (
        "select\n"
        "    sq_raw_supplies.ID as id,\n"
        "    sq_raw_supplies.NAME as name,\n"
        "    sq_raw_supplies.COST as cost,\n"
        "    sq_raw_supplies.PERISHABLE as perishable,\n"
        "    sq_raw_supplies.SKU as sku,\n"
        "    sq_raw_products1.SKU1 as sku1\n"
        "from sq_raw_products1\n"
        "inner join sq_raw_supplies\n"
        "    on sq_raw_products1.SKU1 = sq_raw_supplies.SKU"
    )
    assert cte.notes == []


@pytest.mark.parametrize(
    ("join_type", "keyword"),
    [
        ("Normal Join", "inner join"),
        ("Master Outer Join", "right join"),
        ("Detail Outer Join", "left join"),
        ("Full Outer Join", "full join"),
    ],
)
def test_translate_joiner_join_type_maps_to_correct_keyword(join_type: str, keyword: str) -> None:
    node = TransformationNode(
        name="JNR_TEST",
        type="Joiner",
        ports=[
            Port(name="ID", port_type="INPUT/OUTPUT"),
            Port(name="ID1", port_type="INPUT/OUTPUT/MASTER"),
        ],
        attributes=[
            TableAttribute(name="Join Condition", value="ID1 = ID"),
            TableAttribute(name="Join Type", value=join_type),
        ],
    )

    cte = translate_joiner(node, master_cte="master", detail_cte="detail")

    assert f"\n{keyword} detail\n" in cte.sql
    assert cte.notes == []


def test_translate_joiner_multi_condition_is_anded_and_each_side_qualified() -> None:
    node = TransformationNode(
        name="JNR_ITEMS_ORDERS",
        type="Joiner",
        ports=[
            Port(name="ORDER_ID", port_type="INPUT/OUTPUT/MASTER"),
            Port(name="PRODUCT_ID", port_type="INPUT/OUTPUT/MASTER"),
            Port(name="ORDER_ID1", port_type="INPUT"),
            Port(name="PRODUCT_ID1", port_type="INPUT"),
        ],
        attributes=[
            TableAttribute(
                name="Join Condition",
                value="ORDER_ID = ORDER_ID1 AND PRODUCT_ID = PRODUCT_ID1",
            ),
            TableAttribute(name="Join Type", value="Normal Join"),
        ],
    )

    cte = translate_joiner(node, master_cte="sq_stg_order_items", detail_cte="sq_stg_orders")

    assert (
        "on sq_stg_order_items.ORDER_ID = sq_stg_orders.ORDER_ID1 AND "
        "sq_stg_order_items.PRODUCT_ID = sq_stg_orders.PRODUCT_ID1"
    ) in cte.sql


def test_translate_joiner_condition_literal_values_left_unqualified() -> None:
    node = TransformationNode(
        name="JNR_TEST",
        type="Joiner",
        ports=[
            Port(name="ID", port_type="INPUT/OUTPUT"),
            Port(name="ID1", port_type="INPUT/OUTPUT/MASTER"),
        ],
        attributes=[
            TableAttribute(name="Join Condition", value="ID1 = ID AND STATUS = 'ACTIVE'"),
            TableAttribute(name="Join Type", value="Normal Join"),
        ],
    )

    cte = translate_joiner(node, master_cte="master", detail_cte="detail")

    assert "AND STATUS = 'ACTIVE'" in cte.sql


@pytest.mark.parametrize(
    "attributes",
    [
        [
            TableAttribute(name="Join Condition", value=""),
            TableAttribute(name="Join Type", value="Normal Join"),
        ],
        [TableAttribute(name="Join Type", value="Normal Join")],
    ],
)
def test_translate_joiner_blank_or_missing_condition_flags_note(
    attributes: list[TableAttribute],
) -> None:
    node = TransformationNode(
        name="JNR_TEST",
        type="Joiner",
        ports=[
            Port(name="ID", port_type="INPUT/OUTPUT"),
            Port(name="ID1", port_type="INPUT/OUTPUT/MASTER"),
        ],
        attributes=attributes,
    )

    cte = translate_joiner(node, master_cte="master", detail_cte="detail")

    assert len(cte.notes) == 1
    assert cte.notes[0].transformation == "JNR_TEST"
    assert "empty" in cte.notes[0].message.lower()
    assert "TODO(pc-migration)" in cte.sql


@pytest.mark.parametrize(
    "attributes",
    [
        [
            TableAttribute(name="Join Condition", value="ID1 = ID"),
            TableAttribute(name="Join Type", value="Weird Join"),
        ],
        [TableAttribute(name="Join Condition", value="ID1 = ID")],
    ],
)
def test_translate_joiner_missing_or_unrecognized_join_type_defaults_to_inner_with_note(
    attributes: list[TableAttribute],
) -> None:
    node = TransformationNode(
        name="JNR_TEST",
        type="Joiner",
        ports=[
            Port(name="ID", port_type="INPUT/OUTPUT"),
            Port(name="ID1", port_type="INPUT/OUTPUT/MASTER"),
        ],
        attributes=attributes,
    )

    cte = translate_joiner(node, master_cte="master", detail_cte="detail")

    assert len(cte.notes) == 1
    assert cte.notes[0].transformation == "JNR_TEST"
    assert "inner join" in cte.sql.lower()
    assert "TODO(pc-migration)" in cte.sql


def test_translate_joiner_all_output_ports_from_both_sides_are_selected() -> None:
    node = TransformationNode(
        name="JNR_TEST",
        type="Joiner",
        ports=[
            Port(name="MASTER_ONLY_OUT", port_type="OUTPUT/MASTER"),
            Port(name="DETAIL_ONLY_OUT", port_type="OUTPUT"),
            Port(name="MASTER_KEY", port_type="INPUT/OUTPUT/MASTER"),
            Port(name="DETAIL_KEY", port_type="INPUT"),
        ],
        attributes=[
            TableAttribute(name="Join Condition", value="MASTER_KEY = DETAIL_KEY"),
            TableAttribute(name="Join Type", value="Normal Join"),
        ],
    )

    cte = translate_joiner(node, master_cte="master", detail_cte="detail")

    assert "master.MASTER_ONLY_OUT as master_only_out" in cte.sql
    assert "detail.DETAIL_ONLY_OUT as detail_only_out" in cte.sql
    assert "master.MASTER_KEY as master_key" in cte.sql
    # DETAIL_KEY is a pure INPUT port (no OUTPUT), so it must not be selected.
    assert "DETAIL_KEY as" not in cte.sql


def test_translate_joiner_name_is_snake_cased() -> None:
    node = TransformationNode(
        name="JNR ITEMS-ORDERS",
        type="Joiner",
        ports=[
            Port(name="ID", port_type="INPUT/OUTPUT"),
            Port(name="ID1", port_type="INPUT/OUTPUT/MASTER"),
        ],
        attributes=[
            TableAttribute(name="Join Condition", value="ID1 = ID"),
            TableAttribute(name="Join Type", value="Normal Join"),
        ],
    )

    cte = translate_joiner(node, master_cte="master", detail_cte="detail")

    assert cte.name == "jnr_items_orders"


@pytest.mark.parametrize(
    ("port_type", "expected"),
    [
        ("INPUT/OUTPUT/MASTER", True),
        ("INPUT/OUTPUT", False),
        ("INPUT", False),
        ("OUTPUT", False),
        ("OUTPUT/MASTER", True),
        ("INPUT/MASTER", True),
    ],
)
def test_is_master_port_type(port_type: str, expected: bool) -> None:
    assert is_master_port_type(port_type) is expected
