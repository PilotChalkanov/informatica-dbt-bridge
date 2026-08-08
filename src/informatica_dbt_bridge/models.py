"""Typed domain model for a parsed PowerCenter mapping.

Isolates downstream code (DAG builder, translators) from the raw XML shape —
only `parser.py` should ever touch `xml.etree.ElementTree` elements directly.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Port:
    name: str
    port_type: str  # "INPUT", "OUTPUT", "INPUT/OUTPUT"
    datatype: str | None = None
    expression: str | None = None


@dataclass(frozen=True)
class TableAttribute:
    name: str
    value: str


@dataclass(frozen=True)
class TransformationNode:
    name: str
    type: str
    ports: list[Port] = field(default_factory=list)
    attributes: list[TableAttribute] = field(default_factory=list)

    def attribute(self, name: str) -> str | None:
        for attr in self.attributes:
            if attr.name == name:
                return attr.value
        return None


@dataclass(frozen=True)
class Connector:
    from_instance: str
    from_field: str
    to_instance: str
    to_field: str


@dataclass(frozen=True)
class SourceField:
    name: str
    datatype: str
    precision: int | None = None
    scale: int | None = None
    keytype: str | None = None
    nullable: str | None = None


@dataclass(frozen=True)
class SourceDef:
    name: str
    database_type: str | None = None
    fields: list[SourceField] = field(default_factory=list)


@dataclass(frozen=True)
class TargetField:
    name: str
    datatype: str | None = None


@dataclass(frozen=True)
class TargetDef:
    name: str
    fields: list[TargetField] = field(default_factory=list)


@dataclass(frozen=True)
class Mapping:
    name: str
    sources: list[SourceDef]
    targets: list[TargetDef]
    transformations: list[TransformationNode]
    connectors: list[Connector]

    def transformation(self, name: str) -> TransformationNode:
        for node in self.transformations:
            if node.name == name:
                return node
        raise KeyError(name)
