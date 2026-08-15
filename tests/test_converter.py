import pytest

from informatica_dbt_bridge.converter import convert_mapping

GOLDEN_MAPPING_XML = """
<POWERMART CREATION_DATE="01/01/2024" REPOSITORY_VERSION="1">
  <REPOSITORY NAME="REPO" VERSION="1">
    <FOLDER NAME="MyFolder">

      <SOURCE NAME="ORDERS" DATABASETYPE="Oracle">
        <SOURCEFIELD NAME="ORDER_ID" DATATYPE="decimal" PRECISION="10" SCALE="0"
                      KEYTYPE="PRIMARY KEY" NULLABLE="NOTNULL"/>
        <SOURCEFIELD NAME="STATUS" DATATYPE="string" PRECISION="20" NULLABLE="NULL"/>
        <SOURCEFIELD NAME="AMOUNT" DATATYPE="decimal" PRECISION="15" SCALE="2"/>
      </SOURCE>

      <TARGET NAME="TGT_ORDERS" DATABASETYPE="Oracle">
        <TARGETFIELD NAME="ORDER_ID" DATATYPE="decimal"/>
        <TARGETFIELD NAME="STATUS" DATATYPE="varchar"/>
        <TARGETFIELD NAME="IS_LARGE" DATATYPE="varchar"/>
      </TARGET>

      <MAPPING NAME="m_LOAD_ORDERS">
        <TRANSFORMATION NAME="SQ_ORDERS" TYPE="Source Qualifier">
          <TRANSFORMFIELD NAME="ORDER_ID" PORTTYPE="OUTPUT" DATATYPE="decimal"/>
          <TRANSFORMFIELD NAME="STATUS" PORTTYPE="OUTPUT" DATATYPE="string"/>
          <TRANSFORMFIELD NAME="AMOUNT" PORTTYPE="OUTPUT" DATATYPE="decimal"/>
        </TRANSFORMATION>

        <TRANSFORMATION NAME="FIL_ACTIVE" TYPE="Filter">
          <TRANSFORMFIELD NAME="ORDER_ID" PORTTYPE="INPUT/OUTPUT" DATATYPE="decimal"/>
          <TRANSFORMFIELD NAME="STATUS" PORTTYPE="INPUT/OUTPUT" DATATYPE="string"/>
          <TRANSFORMFIELD NAME="AMOUNT" PORTTYPE="INPUT/OUTPUT" DATATYPE="decimal"/>
          <TABLEATTRIBUTE NAME="Filter Condition" VALUE="STATUS = 'ACTIVE'"/>
        </TRANSFORMATION>

        <TRANSFORMATION NAME="EXP_CALC" TYPE="Expression">
          <TRANSFORMFIELD NAME="ORDER_ID" PORTTYPE="INPUT/OUTPUT" DATATYPE="decimal"/>
          <TRANSFORMFIELD NAME="STATUS" PORTTYPE="INPUT/OUTPUT" DATATYPE="string"/>
          <TRANSFORMFIELD NAME="AMOUNT" PORTTYPE="INPUT/OUTPUT" DATATYPE="decimal"/>
          <TRANSFORMFIELD NAME="IS_LARGE" PORTTYPE="OUTPUT" DATATYPE="string"
                           EXPRESSION="IIF(AMOUNT &gt; 1000, 'Y', 'N')"/>
        </TRANSFORMATION>

        <CONNECTOR FROMINSTANCE="SQ_ORDERS" FROMFIELD="ORDER_ID"
                    TOINSTANCE="FIL_ACTIVE" TOFIELD="ORDER_ID"/>
        <CONNECTOR FROMINSTANCE="SQ_ORDERS" FROMFIELD="STATUS"
                    TOINSTANCE="FIL_ACTIVE" TOFIELD="STATUS"/>
        <CONNECTOR FROMINSTANCE="SQ_ORDERS" FROMFIELD="AMOUNT"
                    TOINSTANCE="FIL_ACTIVE" TOFIELD="AMOUNT"/>
        <CONNECTOR FROMINSTANCE="FIL_ACTIVE" FROMFIELD="ORDER_ID"
                    TOINSTANCE="EXP_CALC" TOFIELD="ORDER_ID"/>
        <CONNECTOR FROMINSTANCE="FIL_ACTIVE" FROMFIELD="STATUS"
                    TOINSTANCE="EXP_CALC" TOFIELD="STATUS"/>
        <CONNECTOR FROMINSTANCE="FIL_ACTIVE" FROMFIELD="AMOUNT"
                    TOINSTANCE="EXP_CALC" TOFIELD="AMOUNT"/>
      </MAPPING>

    </FOLDER>
  </REPOSITORY>
</POWERMART>
"""

EXPECTED_SQL = """\
with sq_orders as (

    select order_id, status, amount
    from {{ source('erp', 'orders') }}

),

fil_active as (

    select *
    from sq_orders
    where STATUS = 'ACTIVE'

),

exp_calc as (

    select
        *,
        CASE WHEN AMOUNT > 1000 THEN 'Y' ELSE 'N' END as is_large
    from fil_active

)

select
    order_id,
    status,
    is_large
from exp_calc\
"""


def test_convert_mapping_produces_expected_sql_for_sq_filter_expression_chain() -> None:
    result = convert_mapping(GOLDEN_MAPPING_XML, source_system="erp")

    assert result.mapping_name == "m_LOAD_ORDERS"
    assert result.sql == EXPECTED_SQL
    assert result.notes == []


def test_convert_mapping_flags_unsupported_transformation_type_with_todo() -> None:
    # Router isn't wired into _SIMPLE_TRANSLATORS yet (see architecture.md's
    # build order) - used here only as a stand-in "some unsupported type",
    # not to test Router-specific behavior.
    xml = GOLDEN_MAPPING_XML.replace('TYPE="Filter"', 'TYPE="Router"')

    result = convert_mapping(xml, source_system="erp")

    assert "TODO(pc-migration): Router not translated" in result.sql
    assert any("Router" in note.message for note in result.notes)


def test_convert_mapping_raises_on_transformation_with_no_upstream() -> None:
    xml = GOLDEN_MAPPING_XML.replace(
        "</MAPPING>",
        '<TRANSFORMATION NAME="FIL_ORPHAN" TYPE="Filter">'
        '<TABLEATTRIBUTE NAME="Filter Condition" VALUE="1=1"/>'
        "</TRANSFORMATION></MAPPING>",
    )

    with pytest.raises(ValueError, match="FIL_ORPHAN"):
        convert_mapping(xml, source_system="erp")


def test_convert_mapping_raises_on_multiple_sources() -> None:
    xml = GOLDEN_MAPPING_XML.replace(
        "</SOURCE>",
        '</SOURCE><SOURCE NAME="CUSTOMERS" DATABASETYPE="Oracle"></SOURCE>',
        1,
    )

    with pytest.raises(NotImplementedError, match="multiple sources"):
        convert_mapping(xml, source_system="erp")


def test_convert_mapping_raises_on_fan_in_from_two_upstream_transformations() -> None:
    xml = GOLDEN_MAPPING_XML.replace(
        "</MAPPING>",
        '<CONNECTOR FROMINSTANCE="SQ_ORDERS" FROMFIELD="ORDER_ID" '
        'TOINSTANCE="EXP_CALC" TOFIELD="ORDER_ID"/></MAPPING>',
    )

    with pytest.raises(NotImplementedError, match="multiple upstream"):
        convert_mapping(xml, source_system="erp")


LOOKUP_MAPPING_XML = """
<POWERMART CREATION_DATE="01/01/2024" REPOSITORY_VERSION="1">
  <REPOSITORY NAME="REPO" VERSION="1">
    <FOLDER NAME="MyFolder">

      <SOURCE NAME="ORDERS" DATABASETYPE="Oracle">
        <SOURCEFIELD NAME="ORDER_ID" DATATYPE="decimal" PRECISION="10" SCALE="0"/>
        <SOURCEFIELD NAME="CUST_ID" DATATYPE="decimal" PRECISION="10" SCALE="0"/>
      </SOURCE>

      <TARGET NAME="TGT_ORDERS" DATABASETYPE="Oracle">
        <TARGETFIELD NAME="ORDER_ID" DATATYPE="decimal"/>
        <TARGETFIELD NAME="REGION" DATATYPE="varchar"/>
      </TARGET>

      <MAPPING NAME="m_LOAD_ORDERS_WITH_LOOKUP">
        <TRANSFORMATION NAME="SQ_ORDERS" TYPE="Source Qualifier">
          <TRANSFORMFIELD NAME="ORDER_ID" PORTTYPE="OUTPUT" DATATYPE="decimal"/>
          <TRANSFORMFIELD NAME="CUST_ID" PORTTYPE="OUTPUT" DATATYPE="decimal"/>
        </TRANSFORMATION>

        <TRANSFORMATION NAME="LKP_CUSTOMER" TYPE="Lookup Procedure">
          <TRANSFORMFIELD NAME="IN_CUST_ID" PORTTYPE="INPUT"/>
          <TRANSFORMFIELD NAME="REGION" PORTTYPE="OUTPUT"/>
          <TABLEATTRIBUTE NAME="Lookup condition" VALUE="CUST_ID = IN_CUST_ID"/>
          <TABLEATTRIBUTE NAME="Lookup table name" VALUE="CUSTOMER"/>
        </TRANSFORMATION>

        <CONNECTOR FROMINSTANCE="SQ_ORDERS" FROMFIELD="CUST_ID"
                    TOINSTANCE="LKP_CUSTOMER" TOFIELD="IN_CUST_ID"/>
      </MAPPING>

    </FOLDER>
  </REPOSITORY>
</POWERMART>
"""


def test_convert_mapping_translates_lookup_with_left_join() -> None:
    result = convert_mapping(LOOKUP_MAPPING_XML, source_system="erp")

    assert result.mapping_name == "m_LOAD_ORDERS_WITH_LOOKUP"
    assert "left join {{ source('erp', 'customer') }} as lkp_customer" in result.sql
    assert "on lkp_customer.REGION = sq_orders.IN_CUST_ID" not in result.sql
    assert result.notes == []


def test_convert_mapping_raises_when_lookup_table_name_attribute_missing() -> None:
    xml = LOOKUP_MAPPING_XML.replace(
        '<TABLEATTRIBUTE NAME="Lookup table name" VALUE="CUSTOMER"/>', ""
    )

    with pytest.raises(ValueError, match="Lookup table name"):
        convert_mapping(xml, source_system="erp")


def test_convert_mapping_raises_on_lookup_with_no_upstream() -> None:
    xml = LOOKUP_MAPPING_XML.replace(
        '<CONNECTOR FROMINSTANCE="SQ_ORDERS" FROMFIELD="CUST_ID"\n'
        '                    TOINSTANCE="LKP_CUSTOMER" TOFIELD="IN_CUST_ID"/>',
        "",
    )

    with pytest.raises(ValueError, match="LKP_CUSTOMER"):
        convert_mapping(xml, source_system="erp")
