import pytest

from informatica_dbt_bridge.models import FieldDependency, Group, Port, TransformationNode
from informatica_dbt_bridge.translators.union import is_union_transformation, translate_union


def _un_regions_node() -> TransformationNode:
    """A trimmed (2-output-column) version of the real demo's UN_REGIONS shape."""
    return TransformationNode(
        name="UN_REGIONS",
        type="Custom Transformation",
        template_name="Union Transformation",
        groups=[
            Group(name="OUTPUT", type="OUTPUT", order=1),
            Group(name="APAC", type="INPUT", order=2),
            Group(name="AMER", type="INPUT", order=3),
            Group(name="EMEA", type="INPUT", order=4),
        ],
        ports=[
            Port(name="LOCATION_ID", port_type="OUTPUT", group="OUTPUT"),
            Port(name="REGION", port_type="OUTPUT", group="OUTPUT"),
            Port(name="LOCATION_ID2", port_type="INPUT", group="APAC"),
            Port(name="REGION2", port_type="INPUT", group="APAC"),
            Port(name="LOCATION_ID3", port_type="INPUT", group="AMER"),
            Port(name="REGION3", port_type="INPUT", group="AMER"),
            Port(name="LOCATION_ID4", port_type="INPUT", group="EMEA"),
            Port(name="REGION4", port_type="INPUT", group="EMEA"),
        ],
        field_dependencies=[
            FieldDependency(input_field="LOCATION_ID2", output_field="LOCATION_ID"),
            FieldDependency(input_field="LOCATION_ID3", output_field="LOCATION_ID"),
            FieldDependency(input_field="LOCATION_ID4", output_field="LOCATION_ID"),
            FieldDependency(input_field="REGION2", output_field="REGION"),
            FieldDependency(input_field="REGION3", output_field="REGION"),
            FieldDependency(input_field="REGION4", output_field="REGION"),
        ],
    )


def test_translate_union_three_group_case_matches_un_regions_shape() -> None:
    node = _un_regions_node()

    cte = translate_union(
        node,
        upstream_by_group={
            "APAC": "exp_apac_rename_trans",
            "AMER": "exp_amer_rename_trans",
            "EMEA": "exp_emea_rename_trans",
        },
    )

    assert cte.name == "un_regions"
    assert cte.sql == (
        "select\n"
        "    LOCATION_ID2 as location_id,\n"
        "    REGION2 as region\n"
        "from exp_apac_rename_trans\n"
        "union all\n"
        "select\n"
        "    LOCATION_ID3 as location_id,\n"
        "    REGION3 as region\n"
        "from exp_amer_rename_trans\n"
        "union all\n"
        "select\n"
        "    LOCATION_ID4 as location_id,\n"
        "    REGION4 as region\n"
        "from exp_emea_rename_trans"
    )
    assert cte.notes == []


def test_translate_union_two_group_case() -> None:
    node = TransformationNode(
        name="UN_ORDERS",
        type="Custom Transformation",
        template_name="Union Transformation",
        groups=[
            Group(name="OUTPUT", type="OUTPUT", order=1),
            Group(name="US", type="INPUT", order=2),
            Group(name="EU", type="INPUT", order=3),
        ],
        ports=[
            Port(name="ORDER_ID", port_type="OUTPUT", group="OUTPUT"),
            Port(name="ORDER_ID_US", port_type="INPUT", group="US"),
            Port(name="ORDER_ID_EU", port_type="INPUT", group="EU"),
        ],
        field_dependencies=[
            FieldDependency(input_field="ORDER_ID_US", output_field="ORDER_ID"),
            FieldDependency(input_field="ORDER_ID_EU", output_field="ORDER_ID"),
        ],
    )

    cte = translate_union(node, upstream_by_group={"US": "sq_orders_us", "EU": "sq_orders_eu"})

    assert cte.sql == (
        "select\n"
        "    ORDER_ID_US as order_id\n"
        "from sq_orders_us\n"
        "union all\n"
        "select\n"
        "    ORDER_ID_EU as order_id\n"
        "from sq_orders_eu"
    )
    assert cte.notes == []


def test_translate_union_aliasing_uses_field_dependency_not_name_or_position_matching() -> None:
    # Deliberately out-of-sync declaration order between the OUTPUT group and
    # each INPUT group's ports, and non-suffix-pattern input field names, so
    # a name- or position-matching implementation would get this wrong.
    node = TransformationNode(
        name="UN_TEST",
        type="Custom Transformation",
        template_name="Union Transformation",
        groups=[
            Group(name="OUTPUT", type="OUTPUT", order=1),
            Group(name="A", type="INPUT", order=2),
        ],
        ports=[
            Port(name="FIRST_COL", port_type="OUTPUT", group="OUTPUT"),
            Port(name="SECOND_COL", port_type="OUTPUT", group="OUTPUT"),
            # Declared in the *opposite* order from the OUTPUT group, with
            # names that don't match by suffix or position.
            Port(name="WEIRD_NAME_FOR_SECOND", port_type="INPUT", group="A"),
            Port(name="WEIRD_NAME_FOR_FIRST", port_type="INPUT", group="A"),
        ],
        field_dependencies=[
            FieldDependency(input_field="WEIRD_NAME_FOR_FIRST", output_field="FIRST_COL"),
            FieldDependency(input_field="WEIRD_NAME_FOR_SECOND", output_field="SECOND_COL"),
        ],
    )

    cte = translate_union(node, upstream_by_group={"A": "upstream_a"})

    assert cte.sql == (
        "select\n"
        "    WEIRD_NAME_FOR_FIRST as first_col,\n"
        "    WEIRD_NAME_FOR_SECOND as second_col\n"
        "from upstream_a"
    )


def test_translate_union_branch_order_follows_group_order_not_dict_order() -> None:
    node = TransformationNode(
        name="UN_TEST",
        type="Custom Transformation",
        template_name="Union Transformation",
        groups=[
            Group(name="OUTPUT", type="OUTPUT", order=1),
            # Declared out of ORDER sequence on purpose.
            Group(name="THIRD", type="INPUT", order=4),
            Group(name="FIRST", type="INPUT", order=2),
            Group(name="SECOND", type="INPUT", order=3),
        ],
        ports=[
            Port(name="COL", port_type="OUTPUT", group="OUTPUT"),
            Port(name="COL_A", port_type="INPUT", group="THIRD"),
            Port(name="COL_B", port_type="INPUT", group="FIRST"),
            Port(name="COL_C", port_type="INPUT", group="SECOND"),
        ],
        field_dependencies=[
            FieldDependency(input_field="COL_A", output_field="COL"),
            FieldDependency(input_field="COL_B", output_field="COL"),
            FieldDependency(input_field="COL_C", output_field="COL"),
        ],
    )

    # Dict insertion order deliberately doesn't match GROUP ORDER either.
    cte = translate_union(
        node,
        upstream_by_group={
            "THIRD": "upstream_third",
            "SECOND": "upstream_second",
            "FIRST": "upstream_first",
        },
    )

    assert cte.sql == (
        "select\n    COL_B as col\nfrom upstream_first\n"
        "union all\n"
        "select\n    COL_C as col\nfrom upstream_second\n"
        "union all\n"
        "select\n    COL_A as col\nfrom upstream_third"
    )


def test_translate_union_flags_output_column_with_no_field_dependency() -> None:
    node = TransformationNode(
        name="UN_TEST",
        type="Custom Transformation",
        template_name="Union Transformation",
        groups=[
            Group(name="OUTPUT", type="OUTPUT", order=1),
            Group(name="A", type="INPUT", order=2),
        ],
        ports=[
            Port(name="COL", port_type="OUTPUT", group="OUTPUT"),
            Port(name="COL_A", port_type="INPUT", group="A"),
        ],
        field_dependencies=[],  # no FIELDDEPENDENCY at all - nothing to resolve COL from
    )

    cte = translate_union(node, upstream_by_group={"A": "upstream_a"})

    assert "NULL as col" in cte.sql
    assert "TODO(pc-migration)" in cte.sql
    assert len(cte.notes) == 1
    assert cte.notes[0].transformation == "UN_TEST"
    assert "COL" in cte.notes[0].message
    assert "A" in cte.notes[0].message


def test_translate_union_name_is_snake_cased() -> None:
    node = TransformationNode(
        name="UN REGIONS-2",
        type="Custom Transformation",
        template_name="Union Transformation",
        groups=[
            Group(name="OUTPUT", type="OUTPUT", order=1),
            Group(name="A", type="INPUT", order=2),
        ],
        ports=[
            Port(name="COL", port_type="OUTPUT", group="OUTPUT"),
            Port(name="COL_A", port_type="INPUT", group="A"),
        ],
        field_dependencies=[FieldDependency(input_field="COL_A", output_field="COL")],
    )

    cte = translate_union(node, upstream_by_group={"A": "upstream_a"})

    assert cte.name == "un_regions_2"


def test_translate_union_raises_when_no_output_group() -> None:
    node = TransformationNode(
        name="UN_TEST",
        type="Custom Transformation",
        template_name="Union Transformation",
        groups=[Group(name="A", type="INPUT", order=1)],
        ports=[Port(name="COL_A", port_type="INPUT", group="A")],
    )

    with pytest.raises(ValueError, match="UN_TEST"):
        translate_union(node, upstream_by_group={"A": "upstream_a"})


def test_translate_union_raises_when_no_input_groups() -> None:
    node = TransformationNode(
        name="UN_TEST",
        type="Custom Transformation",
        template_name="Union Transformation",
        groups=[Group(name="OUTPUT", type="OUTPUT", order=1)],
        ports=[Port(name="COL", port_type="OUTPUT", group="OUTPUT")],
    )

    with pytest.raises(ValueError, match="UN_TEST"):
        translate_union(node, upstream_by_group={})


@pytest.mark.parametrize(
    ("transformation_type", "template_name", "expected"),
    [
        ("Custom Transformation", "Union Transformation", True),
        ("Custom Transformation", None, False),
        ("Custom Transformation", "Some Other Template", False),
        ("Filter", "Union Transformation", False),
        ("Filter", None, False),
    ],
)
def test_is_union_transformation(
    transformation_type: str, template_name: str | None, expected: bool
) -> None:
    node = TransformationNode(name="X", type=transformation_type, template_name=template_name)

    assert is_union_transformation(node) is expected
