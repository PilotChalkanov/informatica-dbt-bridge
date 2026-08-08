"""Builds the transformation dataflow DAG from CONNECTOR edges and orders it."""

from __future__ import annotations

import graphlib

from informatica_dbt_bridge.models import Mapping


class CycleError(Exception):
    """Raised when the mapping's CONNECTOR edges form a cycle (a malformed export)."""


def topological_order(mapping: Mapping) -> list[str]:
    """Return transformation instance names ordered so every upstream node precedes
    the downstream nodes that consume its output."""
    names = {node.name for node in mapping.transformations}
    graph: dict[str, set[str]] = {name: set() for name in names}
    for connector in mapping.connectors:
        if connector.from_instance in names and connector.to_instance in names:
            graph[connector.to_instance].add(connector.from_instance)

    sorter: graphlib.TopologicalSorter[str] = graphlib.TopologicalSorter(graph)
    try:
        return list(sorter.static_order())
    except graphlib.CycleError as exc:
        raise CycleError(f"mapping {mapping.name!r} has a cyclic dataflow: {exc}") from exc
