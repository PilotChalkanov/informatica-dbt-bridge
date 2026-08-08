from informatica_dbt_bridge.models import (
    Mapping,
    TableAttribute,
    TransformationNode,
)


def test_transformation_node_attribute_returns_value_by_name() -> None:
    node = TransformationNode(
        name="FIL_ACTIVE",
        type="Filter",
        ports=[],
        attributes=[TableAttribute(name="Filter Condition", value="STATUS = 'ACTIVE'")],
    )

    assert node.attribute("Filter Condition") == "STATUS = 'ACTIVE'"


def test_transformation_node_attribute_returns_none_when_missing() -> None:
    node = TransformationNode(name="FIL_ACTIVE", type="Filter", ports=[], attributes=[])

    assert node.attribute("Filter Condition") is None


def test_mapping_transformation_looks_up_node_by_name() -> None:
    sq = TransformationNode(name="SQ_ORDERS", type="Source Qualifier", ports=[], attributes=[])
    mapping = Mapping(
        name="m_LOAD",
        sources=[],
        targets=[],
        transformations=[sq],
        connectors=[],
    )

    assert mapping.transformation("SQ_ORDERS") is sq


def test_mapping_transformation_raises_key_error_when_missing() -> None:
    mapping = Mapping(name="m_LOAD", sources=[], targets=[], transformations=[], connectors=[])

    try:
        mapping.transformation("MISSING")
    except KeyError:
        pass
    else:
        raise AssertionError("expected KeyError")
