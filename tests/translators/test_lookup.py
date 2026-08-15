import pytest

from informatica_dbt_bridge.models import Port, TableAttribute, TransformationNode
from informatica_dbt_bridge.translators.lookup import translate_lookup


def test_translate_lookup_basic_single_condition_produces_left_join() -> None:
    node = TransformationNode(
        name="LKP_CUSTOMER",
        type="Lookup Procedure",
        ports=[
            Port(name="IN_CUST_ID", port_type="INPUT"),
            Port(name="CUST_ID", port_type="OUTPUT"),
            Port(name="REGION", port_type="OUTPUT"),
        ],
        attributes=[TableAttribute(name="Lookup condition", value="CUST_ID = IN_CUST_ID")],
    )

    cte = translate_lookup(
        node,
        upstream_cte="sq_orders",
        lookup_source_system="erp",
        lookup_table="customer",
    )

    assert cte.name == "lkp_customer"
    assert cte.sql == (
        "select\n"
        "    sq_orders.*,\n"
        "    lkp_customer.CUST_ID as cust_id,\n"
        "    lkp_customer.REGION as region\n"
        "from sq_orders\n"
        "left join {{ source('erp', 'customer') }} as lkp_customer\n"
        "    on lkp_customer.CUST_ID = sq_orders.IN_CUST_ID"
    )
    assert cte.notes == []


def test_translate_lookup_multi_condition_is_anded_and_each_side_qualified() -> None:
    node = TransformationNode(
        name="LKP_CUSTOMER",
        type="Lookup Procedure",
        ports=[
            Port(name="IN_CUST_ID", port_type="INPUT"),
            Port(name="IN_REGION_CODE", port_type="INPUT"),
            Port(name="CUST_ID", port_type="OUTPUT"),
            Port(name="REGION_CODE", port_type="OUTPUT"),
        ],
        attributes=[
            TableAttribute(
                name="Lookup condition",
                value="CUST_ID = IN_CUST_ID AND REGION_CODE = IN_REGION_CODE",
            )
        ],
    )

    cte = translate_lookup(
        node, upstream_cte="sq_orders", lookup_source_system="erp", lookup_table="customer"
    )

    assert (
        "on lkp_customer.CUST_ID = sq_orders.IN_CUST_ID AND "
        "lkp_customer.REGION_CODE = sq_orders.IN_REGION_CODE"
    ) in cte.sql
    assert cte.notes == []


def test_translate_lookup_condition_literal_values_left_unqualified() -> None:
    node = TransformationNode(
        name="LKP_CUSTOMER",
        type="Lookup Procedure",
        ports=[Port(name="CUST_ID", port_type="OUTPUT")],
        attributes=[TableAttribute(name="Lookup condition", value="STATUS = 'ACTIVE'")],
    )

    cte = translate_lookup(
        node, upstream_cte="sq_orders", lookup_source_system="erp", lookup_table="customer"
    )

    assert "on STATUS = 'ACTIVE'" in cte.sql


@pytest.mark.parametrize(
    "attributes",
    [
        [TableAttribute(name="Lookup condition", value="")],
        [],
    ],
)
def test_translate_lookup_blank_or_missing_condition_flags_note(
    attributes: list[TableAttribute],
) -> None:
    node = TransformationNode(
        name="LKP_CUSTOMER",
        type="Lookup Procedure",
        ports=[Port(name="REGION", port_type="OUTPUT")],
        attributes=attributes,
    )

    cte = translate_lookup(
        node, upstream_cte="sq_orders", lookup_source_system="erp", lookup_table="customer"
    )

    assert len(cte.notes) == 1
    assert cte.notes[0].transformation == "LKP_CUSTOMER"
    assert "empty" in cte.notes[0].message.lower()
    assert "TODO(pc-migration)" in cte.sql


def test_translate_lookup_uses_sql_override_verbatim_in_place_of_table_reference() -> None:
    override = "SELECT cust_id, region FROM customer_v2 WHERE active = 1"
    node = TransformationNode(
        name="LKP_CUSTOMER",
        type="Lookup Procedure",
        ports=[
            Port(name="IN_CUST_ID", port_type="INPUT"),
            Port(name="CUST_ID", port_type="OUTPUT"),
            Port(name="REGION", port_type="OUTPUT"),
        ],
        attributes=[
            TableAttribute(name="Lookup condition", value="CUST_ID = IN_CUST_ID"),
            TableAttribute(name="Sql Override", value=override),
        ],
    )

    cte = translate_lookup(
        node, upstream_cte="sq_orders", lookup_source_system="erp", lookup_table="customer"
    )

    assert f"left join ({override}) as lkp_customer" in cte.sql
    assert "{{ source(" not in cte.sql


def test_translate_lookup_ignores_blank_sql_override() -> None:
    node = TransformationNode(
        name="LKP_CUSTOMER",
        type="Lookup Procedure",
        ports=[
            Port(name="IN_CUST_ID", port_type="INPUT"),
            Port(name="CUST_ID", port_type="OUTPUT"),
        ],
        attributes=[
            TableAttribute(name="Lookup condition", value="CUST_ID = IN_CUST_ID"),
            TableAttribute(name="Sql Override", value=""),
        ],
    )

    cte = translate_lookup(
        node, upstream_cte="sq_orders", lookup_source_system="erp", lookup_table="customer"
    )

    assert "left join {{ source('erp', 'customer') }} as lkp_customer" in cte.sql


def test_translate_lookup_multiple_output_ports_all_appended_as_new_columns() -> None:
    node = TransformationNode(
        name="LKP_CUSTOMER",
        type="Lookup Procedure",
        ports=[
            Port(name="IN_CUST_ID", port_type="INPUT"),
            Port(name="CUST_ID", port_type="OUTPUT"),
            Port(name="REGION", port_type="OUTPUT"),
            Port(name="SEGMENT", port_type="OUTPUT"),
        ],
        attributes=[TableAttribute(name="Lookup condition", value="CUST_ID = IN_CUST_ID")],
    )

    cte = translate_lookup(
        node, upstream_cte="sq_orders", lookup_source_system="erp", lookup_table="customer"
    )

    assert "lkp_customer.CUST_ID as cust_id" in cte.sql
    assert "lkp_customer.REGION as region" in cte.sql
    assert "lkp_customer.SEGMENT as segment" in cte.sql


def test_translate_lookup_input_only_ports_are_not_selected_as_columns() -> None:
    node = TransformationNode(
        name="LKP_CUSTOMER",
        type="Lookup Procedure",
        ports=[
            Port(name="IN_CUST_ID", port_type="INPUT"),
            Port(name="REGION", port_type="OUTPUT"),
        ],
        attributes=[TableAttribute(name="Lookup condition", value="CUST_ID = IN_CUST_ID")],
    )

    cte = translate_lookup(
        node, upstream_cte="sq_orders", lookup_source_system="erp", lookup_table="customer"
    )

    assert "IN_CUST_ID as" not in cte.sql


def test_translate_lookup_flags_non_default_multiple_match_policy() -> None:
    node = TransformationNode(
        name="LKP_CUSTOMER",
        type="Lookup Procedure",
        ports=[
            Port(name="IN_CUST_ID", port_type="INPUT"),
            Port(name="CUST_ID", port_type="OUTPUT"),
        ],
        attributes=[
            TableAttribute(name="Lookup condition", value="CUST_ID = IN_CUST_ID"),
            TableAttribute(name="Lookup Policy on Multiple Match", value="Report Error"),
        ],
    )

    cte = translate_lookup(
        node, upstream_cte="sq_orders", lookup_source_system="erp", lookup_table="customer"
    )

    assert len(cte.notes) == 1
    assert cte.notes[0].transformation == "LKP_CUSTOMER"
    assert "Report Error" in cte.notes[0].message


def test_translate_lookup_name_is_snake_cased() -> None:
    node = TransformationNode(
        name="LKP CUSTOMER-INFO",
        type="Lookup Procedure",
        ports=[Port(name="REGION", port_type="OUTPUT")],
        attributes=[TableAttribute(name="Lookup condition", value="1=1")],
    )

    cte = translate_lookup(
        node, upstream_cte="sq_orders", lookup_source_system="erp", lookup_table="customer"
    )

    assert cte.name == "lkp_customer_info"
