import pytest

from informatica_dbt_bridge.models import Group, Port, TransformationNode
from informatica_dbt_bridge.translators.router import (
    is_default_group,
    is_input_group,
    is_output_group,
    router_group_cte_name,
    translate_router,
)


def _rtr_region_node() -> TransformationNode:
    """A trimmed (2-output-column) version of the real demo's RTR_REGION shape."""
    return TransformationNode(
        name="RTR_REGION",
        type="Router",
        groups=[
            Group(name="INPUT", type="INPUT", order=1),
            Group(name="G_APAC", type="OUTPUT", order=2, expression="REGION = 'APAC'"),
            Group(name="DEFAULT1", type="OUTPUT/DEFAULT", order=5),
            Group(name="G_AMER", type="OUTPUT", order=3, expression="REGION = 'AMER'"),
            Group(name="G_EMEA", type="OUTPUT", order=4, expression="REGION = 'EMEA'"),
        ],
        ports=[
            Port(name="LOCATION_ID", port_type="INPUT", group="INPUT"),
            Port(name="REGION", port_type="INPUT", group="INPUT"),
            Port(name="LOCATION_ID1", port_type="OUTPUT", group="G_APAC", ref_field="LOCATION_ID"),
            Port(name="REGION1", port_type="OUTPUT", group="G_APAC", ref_field="REGION"),
            Port(name="LOCATION_ID3", port_type="OUTPUT", group="G_AMER", ref_field="LOCATION_ID"),
            Port(name="REGION3", port_type="OUTPUT", group="G_AMER", ref_field="REGION"),
            Port(name="LOCATION_ID4", port_type="OUTPUT", group="G_EMEA", ref_field="LOCATION_ID"),
            Port(name="REGION4", port_type="OUTPUT", group="G_EMEA", ref_field="REGION"),
            Port(
                name="LOCATION_ID2",
                port_type="OUTPUT",
                group="DEFAULT1",
                ref_field="LOCATION_ID",
            ),
            Port(name="REGION2", port_type="OUTPUT", group="DEFAULT1", ref_field="REGION"),
        ],
    )


def test_translate_router_three_groups_plus_default_matches_rtr_region_shape() -> None:
    node = _rtr_region_node()

    ctes = translate_router(node, upstream_cte="srt_loc_before")

    assert [cte.name for cte in ctes] == [
        "rtr_region_g_apac",
        "rtr_region_g_amer",
        "rtr_region_g_emea",
        "rtr_region_default1",
    ]
    apac, amer, emea, default = ctes

    assert apac.sql == (
        "select\n"
        "    LOCATION_ID as location_id1,\n"
        "    REGION as region1\n"
        "from srt_loc_before\n"
        "where REGION = 'APAC'"
    )
    assert amer.sql == (
        "select\n"
        "    LOCATION_ID as location_id3,\n"
        "    REGION as region3\n"
        "from srt_loc_before\n"
        "where REGION = 'AMER'"
    )
    assert emea.sql == (
        "select\n"
        "    LOCATION_ID as location_id4,\n"
        "    REGION as region4\n"
        "from srt_loc_before\n"
        "where REGION = 'EMEA'"
    )
    assert default.sql == (
        "select\n"
        "    LOCATION_ID as location_id2,\n"
        "    REGION as region2\n"
        "from srt_loc_before\n"
        "where not (REGION = 'APAC') and not (REGION = 'AMER') and not (REGION = 'EMEA')"
    )
    assert all(cte.notes == [] for cte in ctes)


def test_translate_router_strips_trailing_crlf_from_group_expression() -> None:
    # The real demo XML has a literal trailing CRLF on G_APAC's EXPRESSION
    # (an &#xD;&#xA; artifact) - must not leak into the generated SQL.
    node = TransformationNode(
        name="RTR_TEST",
        type="Router",
        groups=[
            Group(name="INPUT", type="INPUT", order=1),
            Group(name="G_A", type="OUTPUT", order=2, expression="REGION = 'APAC'\r\n"),
        ],
        ports=[
            Port(name="REGION", port_type="INPUT", group="INPUT"),
            Port(name="REGION1", port_type="OUTPUT", group="G_A", ref_field="REGION"),
        ],
    )

    (cte,) = translate_router(node, upstream_cte="srt_loc_before")

    assert cte.sql.endswith("where REGION = 'APAC'")


def test_translate_router_ref_field_driven_aliasing_not_name_or_position_matching() -> None:
    # Deliberately mismatched names/positions between the INPUT group's ports
    # and this OUTPUT group's ports, so a name- or position-based
    # implementation would get this wrong.
    node = TransformationNode(
        name="RTR_TEST",
        type="Router",
        groups=[
            Group(name="INPUT", type="INPUT", order=1),
            Group(name="G_A", type="OUTPUT", order=2, expression="1=1"),
        ],
        ports=[
            Port(name="FIRST_COL", port_type="INPUT", group="INPUT"),
            Port(name="SECOND_COL", port_type="INPUT", group="INPUT"),
            Port(
                name="WEIRD_NAME_FOR_SECOND",
                port_type="OUTPUT",
                group="G_A",
                ref_field="SECOND_COL",
            ),
            Port(
                name="WEIRD_NAME_FOR_FIRST",
                port_type="OUTPUT",
                group="G_A",
                ref_field="FIRST_COL",
            ),
        ],
    )

    (cte,) = translate_router(node, upstream_cte="upstream")

    assert cte.sql == (
        "select\n"
        "    SECOND_COL as weird_name_for_second,\n"
        "    FIRST_COL as weird_name_for_first\n"
        "from upstream\n"
        "where 1=1"
    )


def test_translate_router_flags_output_port_with_no_ref_field() -> None:
    node = TransformationNode(
        name="RTR_TEST",
        type="Router",
        groups=[
            Group(name="INPUT", type="INPUT", order=1),
            Group(name="G_A", type="OUTPUT", order=2, expression="1=1"),
        ],
        ports=[
            Port(name="COL", port_type="INPUT", group="INPUT"),
            Port(name="COL1", port_type="OUTPUT", group="G_A", ref_field=None),
        ],
    )

    (cte,) = translate_router(node, upstream_cte="upstream")

    assert "NULL as col1" in cte.sql
    assert "TODO(pc-migration)" in cte.sql
    assert len(cte.notes) == 1
    assert cte.notes[0].transformation == "RTR_TEST"
    assert "COL1" in cte.notes[0].message


def test_translate_router_blank_group_expression_is_passthrough_with_note() -> None:
    node = TransformationNode(
        name="RTR_TEST",
        type="Router",
        groups=[
            Group(name="INPUT", type="INPUT", order=1),
            Group(name="G_A", type="OUTPUT", order=2, expression=""),
        ],
        ports=[
            Port(name="COL", port_type="INPUT", group="INPUT"),
            Port(name="COL1", port_type="OUTPUT", group="G_A", ref_field="COL"),
        ],
    )

    (cte,) = translate_router(node, upstream_cte="upstream")

    assert cte.sql == "select\n    COL as col1\nfrom upstream"
    assert len(cte.notes) == 1
    assert cte.notes[0].transformation == "RTR_TEST"
    assert "empty" in cte.notes[0].message.lower()


def test_translate_router_default_only_has_no_where_clause() -> None:
    node = TransformationNode(
        name="RTR_TEST",
        type="Router",
        groups=[
            Group(name="INPUT", type="INPUT", order=1),
            Group(name="DEFAULT1", type="OUTPUT/DEFAULT", order=2),
        ],
        ports=[
            Port(name="COL", port_type="INPUT", group="INPUT"),
            Port(name="COL2", port_type="OUTPUT", group="DEFAULT1", ref_field="COL"),
        ],
    )

    (cte,) = translate_router(node, upstream_cte="upstream")

    assert cte.sql == "select\n    COL as col2\nfrom upstream"
    assert cte.notes == []


def test_translate_router_groups_ordered_by_group_order_not_declaration_order() -> None:
    node = TransformationNode(
        name="RTR_TEST",
        type="Router",
        groups=[
            Group(name="INPUT", type="INPUT", order=1),
            Group(name="G_B", type="OUTPUT", order=3, expression="2=2"),
            Group(name="G_A", type="OUTPUT", order=2, expression="1=1"),
        ],
        ports=[
            Port(name="COL", port_type="INPUT", group="INPUT"),
            Port(name="COL_B", port_type="OUTPUT", group="G_B", ref_field="COL"),
            Port(name="COL_A", port_type="OUTPUT", group="G_A", ref_field="COL"),
        ],
    )

    ctes = translate_router(node, upstream_cte="upstream")

    assert [cte.name for cte in ctes] == ["rtr_test_g_a", "rtr_test_g_b"]


@pytest.mark.parametrize(
    ("router_name", "group_name", "expected"),
    [
        ("RTR_REGION", "G_APAC", "rtr_region_g_apac"),
        ("RTR_REGION", "DEFAULT1", "rtr_region_default1"),
        ("RTR ROUTER-2", "G_A", "rtr_router_2_g_a"),
    ],
)
def test_router_group_cte_name(router_name: str, group_name: str, expected: str) -> None:
    assert router_group_cte_name(router_name, group_name) == expected


@pytest.mark.parametrize(
    ("group_type", "expected"),
    [
        ("INPUT", True),
        ("OUTPUT", False),
        ("OUTPUT/DEFAULT", False),
    ],
)
def test_is_input_group(group_type: str, expected: bool) -> None:
    assert is_input_group(group_type) is expected


@pytest.mark.parametrize(
    ("group_type", "expected"),
    [
        ("INPUT", False),
        ("OUTPUT", True),
        ("OUTPUT/DEFAULT", True),
    ],
)
def test_is_output_group(group_type: str, expected: bool) -> None:
    assert is_output_group(group_type) is expected


@pytest.mark.parametrize(
    ("group_type", "expected"),
    [
        ("INPUT", False),
        ("OUTPUT", False),
        ("OUTPUT/DEFAULT", True),
    ],
)
def test_is_default_group(group_type: str, expected: bool) -> None:
    assert is_default_group(group_type) is expected
