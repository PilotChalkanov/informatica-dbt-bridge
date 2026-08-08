"""Parses a PowerCenter mapping XML export into the typed domain model.

This is the only module that touches `xml.etree.ElementTree` directly — if a
real export's schema drifts from the documented shape, the fix belongs here.
"""

from __future__ import annotations

# ElementTree is vulnerable to XML attacks (entity expansion, external entity
# resolution) on untrusted input - see bandit B405/B314. Accepted risk: this
# tool's input is a PowerCenter Repository Manager/Designer export, treated
# as a trusted internal artifact within this project's threat model (a
# colleague's own repo export), not attacker-supplied data. If that
# assumption ever changes (e.g. this becomes a service accepting uploads
# from outside the org), switch to defusedxml before then, not after.
import xml.etree.ElementTree as ET  # nosec B405

from informatica_dbt_bridge.models import (
    Connector,
    Mapping,
    Port,
    SourceDef,
    SourceField,
    TableAttribute,
    TargetDef,
    TargetField,
    TransformationNode,
)


class PowerCenterParseError(Exception):
    """Raised when the XML doesn't match the expected PowerCenter export shape."""


def parse_mapping(xml_text: str, mapping_name: str | None = None) -> Mapping:
    """Parse a single MAPPING out of a PowerCenter POWERMART export.

    Args:
        xml_text: The full POWERMART export XML, as text.
        mapping_name: The `NAME` of the `MAPPING` to parse. If None, the first
            `MAPPING` found in the export's folder is used.

    Returns:
        The parsed Mapping, with its sources, targets, transformations, and
        connectors.

    Raises:
        PowerCenterParseError: The export has no `FOLDER`, no `MAPPING`, the
            requested `mapping_name` isn't present, or a required attribute
            is missing somewhere in the tree.
    """
    root = ET.fromstring(xml_text)  # nosec B314 - see accepted-risk note on the import above

    folder = root.find(".//FOLDER")
    if folder is None:
        raise PowerCenterParseError("no <FOLDER> element found in export")

    mapping_elems = folder.findall("MAPPING")
    if not mapping_elems:
        raise PowerCenterParseError(f"no <MAPPING> element found in folder {folder.get('NAME')!r}")

    if mapping_name is None:
        mapping_elem = mapping_elems[0]
    else:
        found = next((m for m in mapping_elems if m.get("NAME") == mapping_name), None)
        if found is None:
            available = [m.get("NAME") for m in mapping_elems]
            raise PowerCenterParseError(
                f"mapping {mapping_name!r} not found in folder; available: {available}"
            )
        mapping_elem = found

    name = mapping_elem.get("NAME")
    if not name:
        raise PowerCenterParseError("<MAPPING> element is missing a NAME attribute")

    return Mapping(
        name=name,
        sources=[_parse_source(elem) for elem in folder.findall("SOURCE")],
        targets=[_parse_target(elem) for elem in folder.findall("TARGET")],
        transformations=[
            _parse_transformation(elem) for elem in mapping_elem.findall("TRANSFORMATION")
        ],
        connectors=[_parse_connector(elem) for elem in mapping_elem.findall("CONNECTOR")],
    )


def _parse_source(elem: ET.Element) -> SourceDef:
    """Parse a `SOURCE` element and its `SOURCEFIELD` children.

    Args:
        elem: The `<SOURCE>` element.

    Returns:
        The parsed SourceDef.
    """
    return SourceDef(
        name=_require(elem, "NAME"),
        database_type=elem.get("DATABASETYPE"),
        fields=[_parse_source_field(f) for f in elem.findall("SOURCEFIELD")],
    )


def _parse_source_field(elem: ET.Element) -> SourceField:
    """Parse a single `SOURCEFIELD` element.

    Args:
        elem: The `<SOURCEFIELD>` element.

    Returns:
        The parsed SourceField.
    """
    precision = elem.get("PRECISION")
    scale = elem.get("SCALE")
    return SourceField(
        name=_require(elem, "NAME"),
        datatype=_require(elem, "DATATYPE"),
        precision=int(precision) if precision is not None else None,
        scale=int(scale) if scale is not None else None,
        keytype=elem.get("KEYTYPE"),
        nullable=elem.get("NULLABLE"),
    )


def _parse_target(elem: ET.Element) -> TargetDef:
    """Parse a `TARGET` element and its `TARGETFIELD` children.

    Args:
        elem: The `<TARGET>` element.

    Returns:
        The parsed TargetDef.
    """
    return TargetDef(
        name=_require(elem, "NAME"),
        fields=[
            TargetField(name=_require(f, "NAME"), datatype=f.get("DATATYPE"))
            for f in elem.findall("TARGETFIELD")
        ],
    )


def _parse_transformation(elem: ET.Element) -> TransformationNode:
    """Parse a `TRANSFORMATION` element: its ports and `TABLEATTRIBUTE` config.

    Args:
        elem: The `<TRANSFORMATION>` element.

    Returns:
        The parsed TransformationNode.
    """
    return TransformationNode(
        name=_require(elem, "NAME"),
        type=_require(elem, "TYPE"),
        ports=[_parse_port(p) for p in elem.findall("TRANSFORMFIELD")],
        attributes=[
            TableAttribute(name=_require(a, "NAME"), value=a.get("VALUE") or "")
            for a in elem.findall("TABLEATTRIBUTE")
        ],
    )


def _parse_port(elem: ET.Element) -> Port:
    """Parse a single `TRANSFORMFIELD` element.

    Args:
        elem: The `<TRANSFORMFIELD>` element.

    Returns:
        The parsed Port.
    """
    return Port(
        name=_require(elem, "NAME"),
        port_type=_require(elem, "PORTTYPE"),
        datatype=elem.get("DATATYPE"),
        expression=elem.get("EXPRESSION"),
    )


def _parse_connector(elem: ET.Element) -> Connector:
    """Parse a single `CONNECTOR` edge.

    Args:
        elem: The `<CONNECTOR>` element.

    Returns:
        The parsed Connector.
    """
    return Connector(
        from_instance=_require(elem, "FROMINSTANCE"),
        from_field=_require(elem, "FROMFIELD"),
        to_instance=_require(elem, "TOINSTANCE"),
        to_field=_require(elem, "TOFIELD"),
    )


def _require(elem: ET.Element, attr: str) -> str:
    """Return one of `elem`'s attributes, raising if it's absent.

    Args:
        elem: The element to read from.
        attr: The attribute name to look up.

    Returns:
        The attribute's string value.

    Raises:
        PowerCenterParseError: `elem` has no `attr` attribute.
    """
    value = elem.get(attr)
    if value is None:
        raise PowerCenterParseError(f"<{elem.tag}> is missing required attribute {attr!r}")
    return value
