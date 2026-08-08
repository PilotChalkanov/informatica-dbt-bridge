import pytest

from informatica_dbt_bridge.models import Connector
from informatica_dbt_bridge.parser import PowerCenterParseError, parse_mapping

SIMPLE_MAPPING_XML = """
<POWERMART CREATION_DATE="01/01/2024" REPOSITORY_VERSION="1">
  <REPOSITORY NAME="REPO" VERSION="1">
    <FOLDER NAME="MyFolder">

      <SOURCE NAME="ORDERS" DATABASETYPE="Oracle">
        <SOURCEFIELD NAME="ORDER_ID" DATATYPE="decimal" PRECISION="10" SCALE="0"
                      KEYTYPE="PRIMARY KEY" NULLABLE="NOTNULL"/>
        <SOURCEFIELD NAME="STATUS" DATATYPE="string" PRECISION="20" NULLABLE="NULL"/>
      </SOURCE>

      <TARGET NAME="TGT_ORDERS" DATABASETYPE="Oracle">
        <TARGETFIELD NAME="ORDER_ID" DATATYPE="decimal"/>
        <TARGETFIELD NAME="STATUS" DATATYPE="varchar"/>
      </TARGET>

      <MAPPING NAME="m_LOAD_ORDERS">
        <TRANSFORMATION NAME="SQ_ORDERS" TYPE="Source Qualifier">
          <TRANSFORMFIELD NAME="ORDER_ID" PORTTYPE="OUTPUT" DATATYPE="decimal"/>
          <TRANSFORMFIELD NAME="STATUS" PORTTYPE="OUTPUT" DATATYPE="string"/>
          <TABLEATTRIBUTE NAME="Source Filter" VALUE=""/>
        </TRANSFORMATION>

        <TRANSFORMATION NAME="FIL_ACTIVE" TYPE="Filter">
          <TRANSFORMFIELD NAME="ORDER_ID" PORTTYPE="INPUT/OUTPUT" DATATYPE="decimal"/>
          <TRANSFORMFIELD NAME="STATUS" PORTTYPE="INPUT/OUTPUT" DATATYPE="string"/>
          <TABLEATTRIBUTE NAME="Filter Condition" VALUE="STATUS = 'ACTIVE'"/>
        </TRANSFORMATION>

        <CONNECTOR FROMINSTANCE="SQ_ORDERS" FROMFIELD="ORDER_ID"
                    TOINSTANCE="FIL_ACTIVE" TOFIELD="ORDER_ID"/>
        <CONNECTOR FROMINSTANCE="SQ_ORDERS" FROMFIELD="STATUS"
                    TOINSTANCE="FIL_ACTIVE" TOFIELD="STATUS"/>
      </MAPPING>

    </FOLDER>
  </REPOSITORY>
</POWERMART>
"""


def test_parse_mapping_reads_mapping_name() -> None:
    mapping = parse_mapping(SIMPLE_MAPPING_XML)

    assert mapping.name == "m_LOAD_ORDERS"


def test_parse_mapping_reads_sources_with_fields() -> None:
    mapping = parse_mapping(SIMPLE_MAPPING_XML)

    assert len(mapping.sources) == 1
    source = mapping.sources[0]
    assert source.name == "ORDERS"
    assert source.database_type == "Oracle"
    assert [f.name for f in source.fields] == ["ORDER_ID", "STATUS"]
    order_id = source.fields[0]
    assert order_id.datatype == "decimal"
    assert order_id.precision == 10
    assert order_id.scale == 0
    assert order_id.keytype == "PRIMARY KEY"
    assert order_id.nullable == "NOTNULL"


def test_parse_mapping_reads_targets_with_fields() -> None:
    mapping = parse_mapping(SIMPLE_MAPPING_XML)

    assert len(mapping.targets) == 1
    target = mapping.targets[0]
    assert target.name == "TGT_ORDERS"
    assert [f.name for f in target.fields] == ["ORDER_ID", "STATUS"]


def test_parse_mapping_reads_transformations_with_ports_and_attributes() -> None:
    mapping = parse_mapping(SIMPLE_MAPPING_XML)

    fil = mapping.transformation("FIL_ACTIVE")
    assert fil.type == "Filter"
    assert [p.name for p in fil.ports] == ["ORDER_ID", "STATUS"]
    assert fil.attribute("Filter Condition") == "STATUS = 'ACTIVE'"


def test_parse_mapping_reads_connectors() -> None:
    mapping = parse_mapping(SIMPLE_MAPPING_XML)

    assert mapping.connectors == [
        Connector(
            from_instance="SQ_ORDERS",
            from_field="ORDER_ID",
            to_instance="FIL_ACTIVE",
            to_field="ORDER_ID",
        ),
        Connector(
            from_instance="SQ_ORDERS",
            from_field="STATUS",
            to_instance="FIL_ACTIVE",
            to_field="STATUS",
        ),
    ]


def test_parse_mapping_raises_when_no_folder() -> None:
    with pytest.raises(PowerCenterParseError, match="FOLDER"):
        parse_mapping("<POWERMART><REPOSITORY NAME='R' VERSION='1'/></POWERMART>")


def test_parse_mapping_raises_when_no_mapping_element() -> None:
    xml = """
    <POWERMART>
      <REPOSITORY NAME="R" VERSION="1">
        <FOLDER NAME="F"></FOLDER>
      </REPOSITORY>
    </POWERMART>
    """
    with pytest.raises(PowerCenterParseError, match="MAPPING"):
        parse_mapping(xml)


def test_parse_mapping_selects_named_mapping_when_multiple_present() -> None:
    xml = SIMPLE_MAPPING_XML.replace(
        "</FOLDER>",
        '<MAPPING NAME="m_OTHER"></MAPPING></FOLDER>',
    )

    mapping = parse_mapping(xml, mapping_name="m_OTHER")

    assert mapping.name == "m_OTHER"


def test_parse_mapping_raises_when_named_mapping_not_found() -> None:
    with pytest.raises(PowerCenterParseError, match="m_NOPE"):
        parse_mapping(SIMPLE_MAPPING_XML, mapping_name="m_NOPE")
