import pytest

from informatica_dbt_bridge.dag import CycleError, topological_order
from informatica_dbt_bridge.models import Connector, Mapping, TransformationNode


def _node(name: str) -> TransformationNode:
    return TransformationNode(name=name, type="Expression", ports=[], attributes=[])


def _mapping(names: list[str], edges: list[tuple[str, str]]) -> Mapping:
    return Mapping(
        name="m_TEST",
        sources=[],
        targets=[],
        transformations=[_node(n) for n in names],
        connectors=[
            Connector(from_instance=a, from_field="X", to_instance=b, to_field="X")
            for a, b in edges
        ],
    )


def test_topological_order_respects_linear_chain() -> None:
    mapping = _mapping(
        ["AGG", "SQ", "FIL"],
        edges=[("SQ", "FIL"), ("FIL", "AGG")],
    )

    order = topological_order(mapping)

    assert order.index("SQ") < order.index("FIL") < order.index("AGG")


def test_topological_order_respects_diamond_dependencies() -> None:
    mapping = _mapping(
        ["SQ", "A", "B", "C"],
        edges=[("SQ", "A"), ("SQ", "B"), ("A", "C"), ("B", "C")],
    )

    order = topological_order(mapping)

    assert order.index("SQ") < order.index("A")
    assert order.index("SQ") < order.index("B")
    assert order.index("A") < order.index("C")
    assert order.index("B") < order.index("C")


def test_topological_order_includes_node_with_no_connectors() -> None:
    mapping = _mapping(["ISOLATED"], edges=[])

    order = topological_order(mapping)

    assert order == ["ISOLATED"]


def test_topological_order_raises_cycle_error_on_a_cycle() -> None:
    mapping = _mapping(["A", "B"], edges=[("A", "B"), ("B", "A")])

    with pytest.raises(CycleError):
        topological_order(mapping)
