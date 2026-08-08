"""Typed domain model for a parsed PowerCenter mapping.

Isolates downstream code (DAG builder, translators) from the raw XML shape —
only `parser.py` should ever touch `xml.etree.ElementTree` elements directly.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Port:
    """One `TRANSFORMFIELD` on a transformation: a named, typed input/output port."""

    name: str
    port_type: str  # "INPUT", "OUTPUT", "INPUT/OUTPUT"
    datatype: str | None = None
    expression: str | None = None


@dataclass(frozen=True)
class TableAttribute:
    """One `TABLEATTRIBUTE` on a transformation, e.g. a Filter's `Filter Condition`."""

    name: str
    value: str


@dataclass(frozen=True)
class TransformationNode:
    """One `TRANSFORMATION` element: a single node in the mapping's dataflow graph."""

    name: str
    type: str
    ports: list[Port] = field(default_factory=list)
    attributes: list[TableAttribute] = field(default_factory=list)

    def attribute(self, name: str) -> str | None:
        """Look up one of this transformation's `TABLEATTRIBUTE` values by name.

        Args:
            name: The `TABLEATTRIBUTE`'s `NAME`, e.g. `"Filter Condition"`.

        Returns:
            The attribute's value, or None if this transformation has no
            attribute with that name.
        """
        for attr in self.attributes:
            if attr.name == name:
                return attr.value
        return None


@dataclass(frozen=True)
class Connector:
    """One `CONNECTOR` edge: a port-to-port link between two transformation instances."""

    from_instance: str
    from_field: str
    to_instance: str
    to_field: str


@dataclass(frozen=True)
class SourceField:
    """One `SOURCEFIELD`: a column on a `SOURCE`, with its type and key/nullability constraints."""

    name: str
    datatype: str
    precision: int | None = None
    scale: int | None = None
    keytype: str | None = None
    nullable: str | None = None


@dataclass(frozen=True)
class SourceDef:
    """One `SOURCE` element: an upstream table this mapping reads from."""

    name: str
    database_type: str | None = None
    fields: list[SourceField] = field(default_factory=list)


@dataclass(frozen=True)
class TargetField:
    """One `TARGETFIELD`: a column on a `TARGET`."""

    name: str
    datatype: str | None = None


@dataclass(frozen=True)
class TargetDef:
    """One `TARGET` element: the table this mapping loads."""

    name: str
    fields: list[TargetField] = field(default_factory=list)


@dataclass(frozen=True)
class Mapping:
    """One `MAPPING` element: sources, target(s), transformations, and the edges between them."""

    name: str
    sources: list[SourceDef]
    targets: list[TargetDef]
    transformations: list[TransformationNode]
    connectors: list[Connector]

    def transformation(self, name: str) -> TransformationNode:
        """Look up a transformation by its instance name.

        Args:
            name: The transformation's `NAME` attribute (its instance name).

        Returns:
            The matching TransformationNode.

        Raises:
            KeyError: No transformation with that name exists in this mapping.
        """
        for node in self.transformations:
            if node.name == name:
                return node
        raise KeyError(name)
