"""Run the converter against the demo PowerCenter export, as shown in the README."""

from __future__ import annotations

from pathlib import Path

from informatica_dbt_bridge.converter import convert_mapping

DEMO_XML_PATH = Path(__file__).parent / "FLOWLINE_DEMO_JAFFLESHOP.xml"


def run_example(mapping_name: str | None = None, source_system: str = "erp") -> str:
    """Convert one mapping from the demo export and return the generated dbt model SQL.

    Args:
        mapping_name: The `NAME` of the `MAPPING` to convert, if the export
            contains more than one. Defaults to the first mapping found.
        source_system: The dbt `source()` name to resolve Source Qualifiers
            against.

    Returns:
        The generated dbt model SQL text.
    """
    xml_text = DEMO_XML_PATH.read_text()
    result = convert_mapping(xml_text, source_system=source_system, mapping_name=mapping_name)
    return result.sql


if __name__ == "__main__":
    print(run_example())
