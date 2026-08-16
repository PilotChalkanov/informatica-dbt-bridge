import pytest

from informatica_dbt_bridge.models import Connector, FieldDependency, Group
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


def test_parse_mapping_ordinary_transformation_has_no_template_name() -> None:
    mapping = parse_mapping(SIMPLE_MAPPING_XML)

    fil = mapping.transformation("FIL_ACTIVE")

    assert fil.template_name is None


def test_parse_mapping_ordinary_transformation_ports_have_no_group() -> None:
    mapping = parse_mapping(SIMPLE_MAPPING_XML)

    fil = mapping.transformation("FIL_ACTIVE")

    assert all(p.group is None for p in fil.ports)


# A trimmed-down, 2-group version of the real demo export's UN_REGIONS
# (a Custom Transformation shaped like a Union: TEMPLATENAME="Union
# Transformation", GROUP children, TRANSFORMFIELD GROUP attributes, and
# FIELDDEPENDENCY children mapping each input field to its output field).
UNION_SHAPED_MAPPING_XML = """
<POWERMART CREATION_DATE="01/01/2024" REPOSITORY_VERSION="1">
  <REPOSITORY NAME="REPO" VERSION="1">
    <FOLDER NAME="MyFolder">

      <SOURCE NAME="ORDERS" DATABASETYPE="Oracle">
        <SOURCEFIELD NAME="ORDER_ID" DATATYPE="decimal" PRECISION="10" SCALE="0"/>
      </SOURCE>

      <TARGET NAME="TGT_ORDERS" DATABASETYPE="Oracle">
        <TARGETFIELD NAME="ORDER_ID" DATATYPE="decimal"/>
      </TARGET>

      <MAPPING NAME="m_LOAD_ORDERS">
        <TRANSFORMATION NAME="SQ_ORDERS" TYPE="Source Qualifier">
          <TRANSFORMFIELD NAME="ORDER_ID" PORTTYPE="OUTPUT" DATATYPE="decimal"/>
        </TRANSFORMATION>

        <TRANSFORMATION NAME="UN_REGIONS" TYPE="Custom Transformation"
                         TEMPLATEID="303001" TEMPLATENAME="Union Transformation">
          <GROUP NAME="OUTPUT" TYPE="OUTPUT" ORDER="1"/>
          <GROUP NAME="APAC" TYPE="INPUT" ORDER="2"/>
          <GROUP NAME="AMER" TYPE="INPUT" ORDER="3"/>
          <TRANSFORMFIELD NAME="LOCATION_ID" GROUP="OUTPUT" PORTTYPE="OUTPUT" DATATYPE="string"/>
          <TRANSFORMFIELD NAME="LOCATION_ID2" GROUP="APAC" PORTTYPE="INPUT" DATATYPE="string"/>
          <TRANSFORMFIELD NAME="LOCATION_ID3" GROUP="AMER" PORTTYPE="INPUT" DATATYPE="string"/>
          <FIELDDEPENDENCY INPUTFIELD="LOCATION_ID2" OUTPUTFIELD="LOCATION_ID"/>
          <FIELDDEPENDENCY INPUTFIELD="LOCATION_ID3" OUTPUTFIELD="LOCATION_ID"/>
        </TRANSFORMATION>

        <CONNECTOR FROMINSTANCE="SQ_ORDERS" FROMFIELD="ORDER_ID"
                    TOINSTANCE="UN_REGIONS" TOFIELD="LOCATION_ID2"/>
      </MAPPING>

    </FOLDER>
  </REPOSITORY>
</POWERMART>
"""


def test_parse_mapping_reads_template_name_on_custom_transformation() -> None:
    mapping = parse_mapping(UNION_SHAPED_MAPPING_XML)

    union = mapping.transformation("UN_REGIONS")

    assert union.template_name == "Union Transformation"


def test_parse_mapping_reads_groups_in_declaration_order() -> None:
    mapping = parse_mapping(UNION_SHAPED_MAPPING_XML)

    union = mapping.transformation("UN_REGIONS")

    assert union.groups == [
        Group(name="OUTPUT", type="OUTPUT", order=1),
        Group(name="APAC", type="INPUT", order=2),
        Group(name="AMER", type="INPUT", order=3),
    ]


def test_parse_mapping_reads_group_attribute_on_ports() -> None:
    mapping = parse_mapping(UNION_SHAPED_MAPPING_XML)

    union = mapping.transformation("UN_REGIONS")

    groups_by_port = {p.name: p.group for p in union.ports}
    assert groups_by_port == {
        "LOCATION_ID": "OUTPUT",
        "LOCATION_ID2": "APAC",
        "LOCATION_ID3": "AMER",
    }


def test_parse_mapping_reads_field_dependencies() -> None:
    mapping = parse_mapping(UNION_SHAPED_MAPPING_XML)

    union = mapping.transformation("UN_REGIONS")

    assert union.field_dependencies == [
        FieldDependency(input_field="LOCATION_ID2", output_field="LOCATION_ID"),
        FieldDependency(input_field="LOCATION_ID3", output_field="LOCATION_ID"),
    ]


# A trimmed-down version of the real demo export's RTR_REGION (a Router: one
# INPUT group, two filtered OUTPUT groups each with a GROUP-level EXPRESSION,
# and a TYPE="OUTPUT/DEFAULT" catch-all group, with REF_FIELD on every
# OUTPUT-group TRANSFORMFIELD).
ROUTER_SHAPED_MAPPING_XML = """
<POWERMART CREATION_DATE="01/01/2024" REPOSITORY_VERSION="1">
  <REPOSITORY NAME="REPO" VERSION="1">
    <FOLDER NAME="MyFolder">

      <SOURCE NAME="ORDERS" DATABASETYPE="Oracle">
        <SOURCEFIELD NAME="ORDER_ID" DATATYPE="decimal" PRECISION="10" SCALE="0"/>
      </SOURCE>

      <TARGET NAME="TGT_ORDERS" DATABASETYPE="Oracle">
        <TARGETFIELD NAME="ORDER_ID" DATATYPE="decimal"/>
      </TARGET>

      <MAPPING NAME="m_LOAD_ORDERS">
        <TRANSFORMATION NAME="SQ_ORDERS" TYPE="Source Qualifier">
          <TRANSFORMFIELD NAME="REGION" PORTTYPE="OUTPUT" DATATYPE="string"/>
        </TRANSFORMATION>

        <TRANSFORMATION NAME="RTR_REGION" TYPE="Router">
          <GROUP NAME="INPUT" TYPE="INPUT" ORDER="1"/>
          <GROUP NAME="G_APAC" TYPE="OUTPUT" ORDER="2" EXPRESSION="REGION = 'APAC'"/>
          <GROUP NAME="DEFAULT1" TYPE="OUTPUT/DEFAULT" ORDER="3"/>
          <TRANSFORMFIELD NAME="REGION" GROUP="INPUT" PORTTYPE="INPUT" DATATYPE="string"/>
          <TRANSFORMFIELD NAME="REGION1" GROUP="G_APAC" PORTTYPE="OUTPUT" DATATYPE="string"
                           REF_FIELD="REGION"/>
          <TRANSFORMFIELD NAME="REGION2" GROUP="DEFAULT1" PORTTYPE="OUTPUT" DATATYPE="string"
                           REF_FIELD="REGION"/>
        </TRANSFORMATION>

        <CONNECTOR FROMINSTANCE="SQ_ORDERS" FROMFIELD="REGION"
                    TOINSTANCE="RTR_REGION" TOFIELD="REGION"/>
      </MAPPING>

    </FOLDER>
  </REPOSITORY>
</POWERMART>
"""


def test_parse_mapping_reads_group_expression() -> None:
    mapping = parse_mapping(ROUTER_SHAPED_MAPPING_XML)

    router = mapping.transformation("RTR_REGION")

    assert router.groups == [
        Group(name="INPUT", type="INPUT", order=1, expression=None),
        Group(name="G_APAC", type="OUTPUT", order=2, expression="REGION = 'APAC'"),
        Group(name="DEFAULT1", type="OUTPUT/DEFAULT", order=3, expression=None),
    ]


def test_parse_mapping_reads_ref_field_on_ports() -> None:
    mapping = parse_mapping(ROUTER_SHAPED_MAPPING_XML)

    router = mapping.transformation("RTR_REGION")

    ref_fields = {p.name: p.ref_field for p in router.ports}
    assert ref_fields == {"REGION": None, "REGION1": "REGION", "REGION2": "REGION"}


def test_parse_mapping_ordinary_group_has_no_expression() -> None:
    mapping = parse_mapping(UNION_SHAPED_MAPPING_XML)

    union = mapping.transformation("UN_REGIONS")

    assert all(g.expression is None for g in union.groups)


def test_parse_mapping_ordinary_port_has_no_ref_field() -> None:
    mapping = parse_mapping(SIMPLE_MAPPING_XML)

    fil = mapping.transformation("FIL_ACTIVE")

    assert all(p.ref_field is None for p in fil.ports)


def test_parse_mapping_without_instance_elements_has_empty_source_aliases() -> None:
    mapping = parse_mapping(SIMPLE_MAPPING_XML)

    assert mapping.source_aliases == {}


# Mirrors the real demo export's RAW_PRODUCTS/RAW_PRODUCTS1 shape: a second
# mapping-local INSTANCE alias of the same physical SOURCE, used to read it
# twice in one mapping (e.g. a self-join), plus a non-aliased INSTANCE where
# NAME and TRANSFORMATION_NAME coincide (the common case).
INSTANCE_ALIAS_MAPPING_XML = """
<POWERMART CREATION_DATE="01/01/2024" REPOSITORY_VERSION="1">
  <REPOSITORY NAME="REPO" VERSION="1">
    <FOLDER NAME="MyFolder">

      <SOURCE NAME="PRODUCTS" DATABASETYPE="Oracle">
        <SOURCEFIELD NAME="SKU" DATATYPE="string" PRECISION="50" SCALE="0"/>
      </SOURCE>

      <TARGET NAME="TGT_PRODUCTS" DATABASETYPE="Oracle">
        <TARGETFIELD NAME="SKU" DATATYPE="varchar"/>
      </TARGET>

      <MAPPING NAME="m_LOAD_PRODUCTS">
        <TRANSFORMATION NAME="SQ_PRODUCTS" TYPE="Source Qualifier">
          <TRANSFORMFIELD NAME="SKU" PORTTYPE="OUTPUT" DATATYPE="string"/>
        </TRANSFORMATION>
        <TRANSFORMATION NAME="SQ_PRODUCTS1" TYPE="Source Qualifier">
          <TRANSFORMFIELD NAME="SKU" PORTTYPE="OUTPUT" DATATYPE="string"/>
        </TRANSFORMATION>

        <INSTANCE NAME="PRODUCTS" TRANSFORMATION_NAME="PRODUCTS"
                   TRANSFORMATION_TYPE="Source Definition" TYPE="SOURCE"/>
        <INSTANCE NAME="PRODUCTS1" TRANSFORMATION_NAME="PRODUCTS"
                   TRANSFORMATION_TYPE="Source Definition" TYPE="SOURCE"/>

        <CONNECTOR FROMINSTANCE="PRODUCTS" FROMFIELD="SKU"
                    TOINSTANCE="SQ_PRODUCTS" TOFIELD="SKU"/>
        <CONNECTOR FROMINSTANCE="PRODUCTS1" FROMFIELD="SKU"
                    TOINSTANCE="SQ_PRODUCTS1" TOFIELD="SKU"/>
      </MAPPING>

    </FOLDER>
  </REPOSITORY>
</POWERMART>
"""


def test_parse_mapping_reads_source_type_instance_aliases() -> None:
    mapping = parse_mapping(INSTANCE_ALIAS_MAPPING_XML)

    assert mapping.source_aliases == {"PRODUCTS": "PRODUCTS", "PRODUCTS1": "PRODUCTS"}


def test_parse_mapping_ignores_non_source_instance_elements() -> None:
    xml = INSTANCE_ALIAS_MAPPING_XML.replace(
        '<INSTANCE NAME="PRODUCTS1" TRANSFORMATION_NAME="PRODUCTS"\n'
        '                   TRANSFORMATION_TYPE="Source Definition" TYPE="SOURCE"/>',
        '<INSTANCE NAME="PRODUCTS1" TRANSFORMATION_NAME="PRODUCTS"\n'
        '                   TRANSFORMATION_TYPE="Source Definition" TYPE="SOURCE"/>\n'
        '        <INSTANCE NAME="SQ_PRODUCTS" TRANSFORMATION_NAME="SQ_PRODUCTS"\n'
        '                   TRANSFORMATION_TYPE="Source Qualifier" TYPE="TRANSFORMATION"/>\n'
        '        <INSTANCE NAME="TGT_PRODUCTS" TRANSFORMATION_NAME="TGT_PRODUCTS"\n'
        '                   TRANSFORMATION_TYPE="Target Definition" TYPE="TARGET"/>',
    )

    mapping = parse_mapping(xml)

    assert mapping.source_aliases == {"PRODUCTS": "PRODUCTS", "PRODUCTS1": "PRODUCTS"}


def test_parse_mapping_skips_source_instance_missing_transformation_name() -> None:
    xml = INSTANCE_ALIAS_MAPPING_XML.replace(
        '<INSTANCE NAME="PRODUCTS1" TRANSFORMATION_NAME="PRODUCTS"\n'
        '                   TRANSFORMATION_TYPE="Source Definition" TYPE="SOURCE"/>',
        '<INSTANCE NAME="PRODUCTS1" TRANSFORMATION_TYPE="Source Definition" TYPE="SOURCE"/>',
    )

    mapping = parse_mapping(xml)

    assert mapping.source_aliases == {"PRODUCTS": "PRODUCTS"}
