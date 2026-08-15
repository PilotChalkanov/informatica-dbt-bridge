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
    # Sorter isn't wired into _SIMPLE_TRANSLATORS yet (see architecture.md's
    # build order) - used here only as a stand-in "some unsupported type",
    # not to test Sorter-specific behavior. (Router - the previous stand-in -
    # is now genuinely supported, which is exactly why it had to be swapped
    # out here: it stopped being an "unsupported type" example.)
    xml = GOLDEN_MAPPING_XML.replace('TYPE="Filter"', 'TYPE="Sorter"')

    result = convert_mapping(xml, source_system="erp")

    assert "TODO(pc-migration): Sorter not translated" in result.sql
    assert any("Sorter" in note.message for note in result.notes)


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


# Both Source Qualifiers read the same single SOURCE (a valid, if unusual,
# "join a source against itself" pattern) - deliberately, so this fixture
# doesn't trip `_resolve_single_source`'s still-in-place multi-SOURCE
# restriction (see the project report on why that fix was deferred this
# round) while still exercising a real two-upstream Joiner end to end.
JOINER_MAPPING_XML = """
<POWERMART CREATION_DATE="01/01/2024" REPOSITORY_VERSION="1">
  <REPOSITORY NAME="REPO" VERSION="1">
    <FOLDER NAME="MyFolder">

      <SOURCE NAME="ORDERS" DATABASETYPE="Oracle">
        <SOURCEFIELD NAME="ORDER_ID" DATATYPE="decimal" PRECISION="10" SCALE="0"/>
        <SOURCEFIELD NAME="AMOUNT" DATATYPE="decimal" PRECISION="10" SCALE="2"/>
      </SOURCE>

      <TARGET NAME="TGT_ORDERS" DATABASETYPE="Oracle">
        <TARGETFIELD NAME="ORDER_ID" DATATYPE="decimal"/>
        <TARGETFIELD NAME="AMOUNT" DATATYPE="decimal"/>
      </TARGET>

      <MAPPING NAME="m_LOAD_ORDERS_WITH_JOINER">
        <TRANSFORMATION NAME="SQ_ORDERS_MASTER" TYPE="Source Qualifier">
          <TRANSFORMFIELD NAME="ORDER_ID" PORTTYPE="OUTPUT" DATATYPE="decimal"/>
        </TRANSFORMATION>

        <TRANSFORMATION NAME="SQ_ORDERS_DETAIL" TYPE="Source Qualifier">
          <TRANSFORMFIELD NAME="ORDER_ID" PORTTYPE="OUTPUT" DATATYPE="decimal"/>
          <TRANSFORMFIELD NAME="AMOUNT" PORTTYPE="OUTPUT" DATATYPE="decimal"/>
        </TRANSFORMATION>

        <TRANSFORMATION NAME="JNR_ORDERS" TYPE="Joiner">
          <TRANSFORMFIELD NAME="ORDER_ID" PORTTYPE="INPUT/OUTPUT" DATATYPE="decimal"/>
          <TRANSFORMFIELD NAME="AMOUNT" PORTTYPE="INPUT/OUTPUT" DATATYPE="decimal"/>
          <TRANSFORMFIELD NAME="ORDER_ID1" PORTTYPE="INPUT/OUTPUT/MASTER" DATATYPE="decimal"/>
          <TABLEATTRIBUTE NAME="Join Condition" VALUE="ORDER_ID1 = ORDER_ID"/>
          <TABLEATTRIBUTE NAME="Join Type" VALUE="Normal Join"/>
        </TRANSFORMATION>

        <CONNECTOR FROMINSTANCE="SQ_ORDERS_MASTER" FROMFIELD="ORDER_ID"
                    TOINSTANCE="JNR_ORDERS" TOFIELD="ORDER_ID1"/>
        <CONNECTOR FROMINSTANCE="SQ_ORDERS_DETAIL" FROMFIELD="ORDER_ID"
                    TOINSTANCE="JNR_ORDERS" TOFIELD="ORDER_ID"/>
        <CONNECTOR FROMINSTANCE="SQ_ORDERS_DETAIL" FROMFIELD="AMOUNT"
                    TOINSTANCE="JNR_ORDERS" TOFIELD="AMOUNT"/>
      </MAPPING>

    </FOLDER>
  </REPOSITORY>
</POWERMART>
"""


def test_convert_mapping_translates_joiner_with_master_and_detail_ctes() -> None:
    result = convert_mapping(JOINER_MAPPING_XML, source_system="erp")

    assert result.mapping_name == "m_LOAD_ORDERS_WITH_JOINER"
    assert "from sq_orders_master\n    inner join sq_orders_detail" in result.sql
    assert "on sq_orders_master.ORDER_ID1 = sq_orders_detail.ORDER_ID" in result.sql
    assert result.notes == []


def test_convert_mapping_raises_on_joiner_with_ambiguous_master_detail_split() -> None:
    # Both predecessors feed only non-MASTER ports once this is stripped out -
    # nothing left to resolve which upstream is master vs detail.
    xml = JOINER_MAPPING_XML.replace('PORTTYPE="INPUT/OUTPUT/MASTER"', 'PORTTYPE="INPUT/OUTPUT"')

    with pytest.raises(ValueError, match="JNR_ORDERS"):
        convert_mapping(xml, source_system="erp")


def test_convert_mapping_raises_on_joiner_with_only_one_predecessor() -> None:
    # A Joiner fed by only one transformation is structurally malformed (a
    # real Joiner always has master + detail pipelines) - must fail loud
    # with a clear message, not silently treat the lone predecessor as both.
    xml = JOINER_MAPPING_XML.replace(
        '<CONNECTOR FROMINSTANCE="SQ_ORDERS_DETAIL" FROMFIELD="ORDER_ID"\n'
        '                    TOINSTANCE="JNR_ORDERS" TOFIELD="ORDER_ID"/>\n'
        '        <CONNECTOR FROMINSTANCE="SQ_ORDERS_DETAIL" FROMFIELD="AMOUNT"\n'
        '                    TOINSTANCE="JNR_ORDERS" TOFIELD="AMOUNT"/>\n',
        "",
    )

    with pytest.raises(ValueError, match="JNR_ORDERS"):
        convert_mapping(xml, source_system="erp")


def test_convert_mapping_joiner_resolution_ignores_unrelated_connectors() -> None:
    # Extra noise connectors - one unrelated to the Joiner entirely, one
    # landing on the Joiner directly from a SOURCE instance (not a
    # transformation) - must not confuse master/detail resolution.
    xml = JOINER_MAPPING_XML.replace(
        '<CONNECTOR FROMINSTANCE="SQ_ORDERS_MASTER" FROMFIELD="ORDER_ID"\n'
        '                    TOINSTANCE="JNR_ORDERS" TOFIELD="ORDER_ID1"/>',
        '<CONNECTOR FROMINSTANCE="SQ_ORDERS_MASTER" FROMFIELD="ORDER_ID"\n'
        '                    TOINSTANCE="JNR_ORDERS" TOFIELD="ORDER_ID1"/>\n'
        '        <CONNECTOR FROMINSTANCE="SQ_ORDERS_MASTER" FROMFIELD="ORDER_ID"\n'
        '                    TOINSTANCE="SQ_ORDERS_DETAIL" TOFIELD="ORDER_ID"/>\n'
        '        <CONNECTOR FROMINSTANCE="ORDERS" FROMFIELD="ORDER_ID"\n'
        '                    TOINSTANCE="JNR_ORDERS" TOFIELD="ORDER_ID1"/>',
    )

    result = convert_mapping(xml, source_system="erp")

    assert "from sq_orders_master\n    inner join sq_orders_detail" in result.sql
    assert result.notes == []


# All three Source Qualifiers read the same single SOURCE (same "join/union a
# source against itself" pattern used for JOINER_MAPPING_XML, for the same
# reason - avoids tripping `_resolve_single_source`'s still-in-place
# multi-SOURCE restriction while still exercising a real N-ary-fan-in Union
# end to end).
UNION_MAPPING_XML = """
<POWERMART CREATION_DATE="01/01/2024" REPOSITORY_VERSION="1">
  <REPOSITORY NAME="REPO" VERSION="1">
    <FOLDER NAME="MyFolder">

      <SOURCE NAME="ORDERS" DATABASETYPE="Oracle">
        <SOURCEFIELD NAME="ORDER_ID" DATATYPE="decimal" PRECISION="10" SCALE="0"/>
      </SOURCE>

      <TARGET NAME="TGT_ORDERS" DATABASETYPE="Oracle">
        <TARGETFIELD NAME="ORDER_ID" DATATYPE="decimal"/>
      </TARGET>

      <MAPPING NAME="m_LOAD_ORDERS_WITH_UNION">
        <TRANSFORMATION NAME="SQ_ORDERS_A" TYPE="Source Qualifier">
          <TRANSFORMFIELD NAME="ORDER_ID" PORTTYPE="OUTPUT" DATATYPE="decimal"/>
        </TRANSFORMATION>

        <TRANSFORMATION NAME="SQ_ORDERS_B" TYPE="Source Qualifier">
          <TRANSFORMFIELD NAME="ORDER_ID" PORTTYPE="OUTPUT" DATATYPE="decimal"/>
        </TRANSFORMATION>

        <TRANSFORMATION NAME="SQ_ORDERS_C" TYPE="Source Qualifier">
          <TRANSFORMFIELD NAME="ORDER_ID" PORTTYPE="OUTPUT" DATATYPE="decimal"/>
        </TRANSFORMATION>

        <TRANSFORMATION NAME="UN_ORDERS" TYPE="Custom Transformation"
                         TEMPLATEID="303001" TEMPLATENAME="Union Transformation">
          <GROUP NAME="OUTPUT" TYPE="OUTPUT" ORDER="1"/>
          <GROUP NAME="A" TYPE="INPUT" ORDER="2"/>
          <GROUP NAME="B" TYPE="INPUT" ORDER="3"/>
          <GROUP NAME="C" TYPE="INPUT" ORDER="4"/>
          <TRANSFORMFIELD NAME="ORDER_ID" GROUP="OUTPUT" PORTTYPE="OUTPUT" DATATYPE="decimal"/>
          <TRANSFORMFIELD NAME="ORDER_ID_A" GROUP="A" PORTTYPE="INPUT" DATATYPE="decimal"/>
          <TRANSFORMFIELD NAME="ORDER_ID_B" GROUP="B" PORTTYPE="INPUT" DATATYPE="decimal"/>
          <TRANSFORMFIELD NAME="ORDER_ID_C" GROUP="C" PORTTYPE="INPUT" DATATYPE="decimal"/>
          <FIELDDEPENDENCY INPUTFIELD="ORDER_ID_A" OUTPUTFIELD="ORDER_ID"/>
          <FIELDDEPENDENCY INPUTFIELD="ORDER_ID_B" OUTPUTFIELD="ORDER_ID"/>
          <FIELDDEPENDENCY INPUTFIELD="ORDER_ID_C" OUTPUTFIELD="ORDER_ID"/>
        </TRANSFORMATION>

        <CONNECTOR FROMINSTANCE="SQ_ORDERS_A" FROMFIELD="ORDER_ID"
                    TOINSTANCE="UN_ORDERS" TOFIELD="ORDER_ID_A"/>
        <CONNECTOR FROMINSTANCE="SQ_ORDERS_B" FROMFIELD="ORDER_ID"
                    TOINSTANCE="UN_ORDERS" TOFIELD="ORDER_ID_B"/>
        <CONNECTOR FROMINSTANCE="SQ_ORDERS_C" FROMFIELD="ORDER_ID"
                    TOINSTANCE="UN_ORDERS" TOFIELD="ORDER_ID_C"/>
      </MAPPING>

    </FOLDER>
  </REPOSITORY>
</POWERMART>
"""


def test_convert_mapping_translates_union_with_three_upstreams() -> None:
    result = convert_mapping(UNION_MAPPING_XML, source_system="erp")

    # The three Source Qualifiers are mutually independent, so their
    # relative CTE-declaration order is topological-sort-implementation-
    # defined, not a meaningful invariant - assert on the parts that are:
    # the mapping name, that each SQ CTE exists, and that the Union CTE
    # branches (in GROUP ORDER) each read from the right one.
    assert result.mapping_name == "m_LOAD_ORDERS_WITH_UNION"
    for cte_name in ("sq_orders_a", "sq_orders_b", "sq_orders_c"):
        assert f"{cte_name} as (\n\n    select order_id\n" in result.sql
    assert (
        "un_orders as (\n\n"
        "    select\n"
        "        ORDER_ID_A as order_id\n"
        "    from sq_orders_a\n"
        "    union all\n"
        "    select\n"
        "        ORDER_ID_B as order_id\n"
        "    from sq_orders_b\n"
        "    union all\n"
        "    select\n"
        "        ORDER_ID_C as order_id\n"
        "    from sq_orders_c\n\n"
        ")"
    ) in result.sql
    assert result.sql.endswith("select\n    order_id\nfrom un_orders")
    assert result.notes == []


def test_convert_mapping_raises_on_union_with_ambiguous_group_split() -> None:
    # Redirect SQ_ORDERS_B's connector to also land on group A's port -
    # group A now has two claimed predecessors and group B has none.
    xml = UNION_MAPPING_XML.replace(
        '<CONNECTOR FROMINSTANCE="SQ_ORDERS_B" FROMFIELD="ORDER_ID"\n'
        '                    TOINSTANCE="UN_ORDERS" TOFIELD="ORDER_ID_B"/>',
        '<CONNECTOR FROMINSTANCE="SQ_ORDERS_B" FROMFIELD="ORDER_ID"\n'
        '                    TOINSTANCE="UN_ORDERS" TOFIELD="ORDER_ID_A"/>',
    )

    with pytest.raises(ValueError, match="UN_ORDERS"):
        convert_mapping(xml, source_system="erp")


def test_convert_mapping_non_union_custom_transformation_with_fan_in_still_raises() -> None:
    # No TEMPLATENAME at all - a generic Custom Transformation, not a Union -
    # fan-in must still hit the pre-existing NotImplementedError, not be
    # force-fit through the Union-specific carve-out.
    xml = UNION_MAPPING_XML.replace(' TEMPLATEID="303001" TEMPLATENAME="Union Transformation"', "")

    with pytest.raises(NotImplementedError, match="UN_ORDERS"):
        convert_mapping(xml, source_system="erp")


def test_convert_mapping_non_union_custom_transformation_falls_through_to_unsupported() -> None:
    # Single upstream, no fan-in, no TEMPLATENAME - should hit the generic
    # unsupported-TODO fallback untouched, same as any other unknown TYPE.
    xml = UNION_MAPPING_XML.replace(
        ' TEMPLATEID="303001" TEMPLATENAME="Union Transformation"', ""
    ).replace(
        '<CONNECTOR FROMINSTANCE="SQ_ORDERS_B" FROMFIELD="ORDER_ID"\n'
        '                    TOINSTANCE="UN_ORDERS" TOFIELD="ORDER_ID_B"/>\n'
        '        <CONNECTOR FROMINSTANCE="SQ_ORDERS_C" FROMFIELD="ORDER_ID"\n'
        '                    TOINSTANCE="UN_ORDERS" TOFIELD="ORDER_ID_C"/>\n',
        "",
    )

    result = convert_mapping(xml, source_system="erp")

    assert "TODO(pc-migration): Custom Transformation not translated" in result.sql
    assert any("Custom Transformation" in note.message for note in result.notes)


def test_convert_mapping_raises_on_union_with_no_input_groups() -> None:
    xml = UNION_MAPPING_XML.replace(
        '<GROUP NAME="A" TYPE="INPUT" ORDER="2"/>\n'
        '          <GROUP NAME="B" TYPE="INPUT" ORDER="3"/>\n'
        '          <GROUP NAME="C" TYPE="INPUT" ORDER="4"/>\n',
        "",
    )

    with pytest.raises(ValueError, match="UN_ORDERS"):
        convert_mapping(xml, source_system="erp")


def test_convert_mapping_raises_on_union_with_a_predecessor_feeding_two_groups() -> None:
    # SQ_ORDERS_A now also feeds group B's port, in addition to its own
    # group A port - its edges land on two different groups, unresolvable.
    xml = UNION_MAPPING_XML.replace(
        '<CONNECTOR FROMINSTANCE="SQ_ORDERS_A" FROMFIELD="ORDER_ID"\n'
        '                    TOINSTANCE="UN_ORDERS" TOFIELD="ORDER_ID_A"/>',
        '<CONNECTOR FROMINSTANCE="SQ_ORDERS_A" FROMFIELD="ORDER_ID"\n'
        '                    TOINSTANCE="UN_ORDERS" TOFIELD="ORDER_ID_A"/>\n'
        '        <CONNECTOR FROMINSTANCE="SQ_ORDERS_A" FROMFIELD="ORDER_ID"\n'
        '                    TOINSTANCE="UN_ORDERS" TOFIELD="ORDER_ID_B"/>',
    )

    with pytest.raises(ValueError, match="UN_ORDERS"):
        convert_mapping(xml, source_system="erp")


def test_convert_mapping_raises_on_union_with_an_uncovered_input_group() -> None:
    # Group C simply has no predecessor at all - no ambiguity, just missing.
    xml = UNION_MAPPING_XML.replace(
        '<CONNECTOR FROMINSTANCE="SQ_ORDERS_C" FROMFIELD="ORDER_ID"\n'
        '                    TOINSTANCE="UN_ORDERS" TOFIELD="ORDER_ID_C"/>',
        "",
    )

    with pytest.raises(ValueError, match="UN_ORDERS"):
        convert_mapping(xml, source_system="erp")


def test_convert_mapping_union_resolution_ignores_unrelated_connectors() -> None:
    xml = UNION_MAPPING_XML.replace(
        '<CONNECTOR FROMINSTANCE="SQ_ORDERS_A" FROMFIELD="ORDER_ID"\n'
        '                    TOINSTANCE="UN_ORDERS" TOFIELD="ORDER_ID_A"/>',
        '<CONNECTOR FROMINSTANCE="SQ_ORDERS_A" FROMFIELD="ORDER_ID"\n'
        '                    TOINSTANCE="UN_ORDERS" TOFIELD="ORDER_ID_A"/>\n'
        '        <CONNECTOR FROMINSTANCE="SQ_ORDERS_A" FROMFIELD="ORDER_ID"\n'
        '                    TOINSTANCE="SQ_ORDERS_B" TOFIELD="ORDER_ID"/>\n'
        '        <CONNECTOR FROMINSTANCE="ORDERS" FROMFIELD="ORDER_ID"\n'
        '                    TOINSTANCE="UN_ORDERS" TOFIELD="ORDER_ID_A"/>',
    )

    result = convert_mapping(xml, source_system="erp")

    assert "ORDER_ID_A as order_id\n    from sq_orders_a" in result.sql
    assert result.notes == []


ROUTER_MAPPING_XML = """
<POWERMART CREATION_DATE="01/01/2024" REPOSITORY_VERSION="1">
  <REPOSITORY NAME="REPO" VERSION="1">
    <FOLDER NAME="MyFolder">

      <SOURCE NAME="ORDERS" DATABASETYPE="Oracle">
        <SOURCEFIELD NAME="REGION" DATATYPE="string" PRECISION="10" SCALE="0"/>
      </SOURCE>

      <TARGET NAME="TGT_ORDERS" DATABASETYPE="Oracle">
        <TARGETFIELD NAME="REGION1" DATATYPE="varchar"/>
      </TARGET>

      <MAPPING NAME="m_LOAD_ORDERS_WITH_ROUTER">
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

        <TRANSFORMATION NAME="FIL_APAC" TYPE="Filter">
          <TRANSFORMFIELD NAME="REGION1" PORTTYPE="INPUT/OUTPUT" DATATYPE="string"/>
          <TABLEATTRIBUTE NAME="Filter Condition" VALUE="1=1"/>
        </TRANSFORMATION>

        <CONNECTOR FROMINSTANCE="SQ_ORDERS" FROMFIELD="REGION"
                    TOINSTANCE="RTR_REGION" TOFIELD="REGION"/>
        <CONNECTOR FROMINSTANCE="RTR_REGION" FROMFIELD="REGION1"
                    TOINSTANCE="FIL_APAC" TOFIELD="REGION1"/>
      </MAPPING>

    </FOLDER>
  </REPOSITORY>
</POWERMART>
"""


def test_convert_mapping_translates_router_with_downstream_resolving_correct_group() -> None:
    result = convert_mapping(ROUTER_MAPPING_XML, source_system="erp")

    assert result.mapping_name == "m_LOAD_ORDERS_WITH_ROUTER"
    assert (
        "rtr_region_g_apac as (\n\n"
        "    select\n"
        "        REGION as region1\n"
        "    from sq_orders\n"
        "    where REGION = 'APAC'\n\n"
        ")"
    ) in result.sql
    assert (
        "rtr_region_default1 as (\n\n"
        "    select\n"
        "        REGION as region2\n"
        "    from sq_orders\n"
        "    where not (REGION = 'APAC')\n\n"
        ")"
    ) in result.sql
    assert (
        "fil_apac as (\n\n    select *\n    from rtr_region_g_apac\n    where 1=1\n\n)"
    ) in result.sql
    assert result.sql.endswith("select\n    region1\nfrom fil_apac")
    assert result.notes == []


def test_convert_mapping_raises_when_router_downstream_group_unresolvable() -> None:
    # FIL_APAC now also reads a DEFAULT1-group field, in addition to its
    # existing G_APAC-group field - its edges land on two different groups.
    xml = ROUTER_MAPPING_XML.replace(
        '<CONNECTOR FROMINSTANCE="RTR_REGION" FROMFIELD="REGION1"\n'
        '                    TOINSTANCE="FIL_APAC" TOFIELD="REGION1"/>',
        '<CONNECTOR FROMINSTANCE="RTR_REGION" FROMFIELD="REGION1"\n'
        '                    TOINSTANCE="FIL_APAC" TOFIELD="REGION1"/>\n'
        '        <CONNECTOR FROMINSTANCE="RTR_REGION" FROMFIELD="REGION2"\n'
        '                    TOINSTANCE="FIL_APAC" TOFIELD="REGION1"/>',
    )

    with pytest.raises(ValueError, match="FIL_APAC"):
        convert_mapping(xml, source_system="erp")


def test_convert_mapping_raises_on_router_with_no_upstream() -> None:
    xml = ROUTER_MAPPING_XML.replace(
        '<CONNECTOR FROMINSTANCE="SQ_ORDERS" FROMFIELD="REGION"\n'
        '                    TOINSTANCE="RTR_REGION" TOFIELD="REGION"/>',
        "",
    )

    with pytest.raises(ValueError, match="RTR_REGION"):
        convert_mapping(xml, source_system="erp")


def test_convert_mapping_raises_when_router_downstream_reads_only_input_group_port() -> None:
    # FIL_APAC now reads the Router's own INPUT-group port ("REGION") rather
    # than a renamed OUTPUT-group one ("REGION1") - not a real branch.
    xml = ROUTER_MAPPING_XML.replace(
        '<CONNECTOR FROMINSTANCE="RTR_REGION" FROMFIELD="REGION1"\n'
        '                    TOINSTANCE="FIL_APAC" TOFIELD="REGION1"/>',
        '<CONNECTOR FROMINSTANCE="RTR_REGION" FROMFIELD="REGION"\n'
        '                    TOINSTANCE="FIL_APAC" TOFIELD="REGION1"/>',
    )

    with pytest.raises(ValueError, match="FIL_APAC"):
        convert_mapping(xml, source_system="erp")


def test_convert_mapping_router_resolution_ignores_connector_to_non_transformation() -> None:
    # A connector from the Router straight to a TARGET name (not a
    # transformation) must not confuse the real FIL_APAC resolution.
    xml = ROUTER_MAPPING_XML.replace(
        '<CONNECTOR FROMINSTANCE="RTR_REGION" FROMFIELD="REGION1"\n'
        '                    TOINSTANCE="FIL_APAC" TOFIELD="REGION1"/>',
        '<CONNECTOR FROMINSTANCE="RTR_REGION" FROMFIELD="REGION1"\n'
        '                    TOINSTANCE="FIL_APAC" TOFIELD="REGION1"/>\n'
        '        <CONNECTOR FROMINSTANCE="RTR_REGION" FROMFIELD="REGION2"\n'
        '                    TOINSTANCE="TGT_ORDERS" TOFIELD="REGION2"/>',
    )

    result = convert_mapping(xml, source_system="erp")

    assert "from rtr_region_g_apac" in result.sql
    assert result.notes == []
