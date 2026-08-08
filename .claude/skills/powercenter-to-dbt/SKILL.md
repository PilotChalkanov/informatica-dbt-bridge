---
name: powercenter-to-dbt
description: Convert Informatica PowerCenter 10.x mapping/workflow/mapplet XML exports into dbt models, sources, and schema tests. Use when the user mentions Informatica, PowerCenter, pmrep/pmcmd, mapping XML exports, mapplets, sessions, workflows, transformations (Source Qualifier, Expression, Filter, Router, Joiner, Lookup, Aggregator, Rank, Sequence Generator, Union, Update Strategy, Normalizer), or asks to migrate/convert/port PowerCenter ETL to dbt.
---

# PowerCenter 10.x → dbt conversion

> **Provenance note:** this skill is built from PowerCenter 10.x documentation and
> the known `powrmart.dtd` export schema, not verified against a live customer
> export (none was available when this was authored). Element/attribute names are
> stable across 10.1–10.5.x for the core objects covered here, but always confirm
> against the actual XML you're given — open it and check tag names before
> assuming this doc is 100% literal. If you find a discrepancy, fix this file.

## When to use this

The user gives you a PowerCenter **Repository Manager / Designer XML export**
(Export Objects → `.xml`, or a `pmrep objectexport` output) containing folders,
sources, targets, mappings, mapplets, sessions, and workflows, and wants it
translated into a working dbt project (models + `schema.yml` + sources).

## 1. Export XML anatomy

```xml
<POWERMART CREATION_DATE="..." REPOSITORY_VERSION="...">
  <REPOSITORY NAME="..." VERSION="...">
    <FOLDER NAME="MyFolder">

      <SOURCE NAME="SRC_ORDERS" DATABASETYPE="Oracle">
        <SOURCEFIELD NAME="ORDER_ID"   DATATYPE="decimal" PRECISION="10" SCALE="0" KEYTYPE="PRIMARY KEY" NULLABLE="NOTNULL"/>
        <SOURCEFIELD NAME="CUST_ID"    DATATYPE="decimal" PRECISION="10" SCALE="0" NULLABLE="NOTNULL"/>
        <SOURCEFIELD NAME="ORDER_DATE" DATATYPE="date/time" PRECISION="29" SCALE="9" NULLABLE="NULL"/>
        <SOURCEFIELD NAME="STATUS"     DATATYPE="string" PRECISION="20"/>
        <SOURCEFIELD NAME="AMOUNT"     DATATYPE="decimal" PRECISION="15" SCALE="2"/>
      </SOURCE>

      <TARGET NAME="TGT_REGION_SUMMARY" DATABASETYPE="Oracle">
        <TARGETFIELD NAME="REGION" DATATYPE="varchar" .../>
        <TARGETFIELD NAME="TOTAL_AMOUNT" DATATYPE="decimal" .../>
      </TARGET>

      <MAPPING NAME="m_LOAD_REGION_SUMMARY">
        <!-- one <TRANSFORMATION> block per node in the dataflow -->
        <TRANSFORMATION NAME="SQ_SRC_ORDERS" TYPE="Source Qualifier">
          <TRANSFORMFIELD NAME="ORDER_ID" PORTTYPE="OUTPUT" DATATYPE="decimal"/>
          <TABLEATTRIBUTE NAME="Sql Query" VALUE=""/>
          <TABLEATTRIBUTE NAME="Source Filter" VALUE=""/>
          <TABLEATTRIBUTE NAME="User Defined Join" VALUE=""/>
        </TRANSFORMATION>

        <TRANSFORMATION NAME="LKP_CUSTOMER" TYPE="Lookup Procedure">
          <TRANSFORMFIELD NAME="CUST_ID" PORTTYPE="INPUT"/>
          <TRANSFORMFIELD NAME="REGION" PORTTYPE="OUTPUT"/>
          <TABLEATTRIBUTE NAME="Lookup condition" VALUE="CUST_ID = IN_CUST_ID"/>
          <TABLEATTRIBUTE NAME="Sql Override" VALUE=""/>
        </TRANSFORMATION>

        <TRANSFORMATION NAME="EXP_CALC" TYPE="Expression">
          <TRANSFORMFIELD NAME="OUT_IS_LARGE" PORTTYPE="OUTPUT" DATATYPE="string"
                           EXPRESSION="IIF(AMOUNT &gt; 1000, 'Y', 'N')"/>
        </TRANSFORMATION>

        <TRANSFORMATION NAME="FIL_ACTIVE" TYPE="Filter">
          <TABLEATTRIBUTE NAME="Filter Condition" VALUE="STATUS = 'ACTIVE'"/>
        </TRANSFORMATION>

        <TRANSFORMATION NAME="AGG_BY_REGION" TYPE="Aggregator">
          <TRANSFORMFIELD NAME="TOTAL_AMOUNT" PORTTYPE="OUTPUT" EXPRESSION="SUM(AMOUNT)"/>
          <TABLEATTRIBUTE NAME="Group By Ports" VALUE="REGION"/>
        </TRANSFORMATION>

        <!-- INSTANCE ties a TRANSFORMATION/SOURCE/TARGET into this mapping's graph -->
        <INSTANCE NAME="SQ_SRC_ORDERS" TRANSFORMATION_TYPE="Source Qualifier" TYPE="SOURCE QUALIFIER"/>
        <INSTANCE NAME="TGT_REGION_SUMMARY" TYPE="TARGET"/>

        <!-- CONNECTOR edges define the dataflow graph -- build a DAG from these -->
        <CONNECTOR FROMINSTANCE="SQ_SRC_ORDERS" FROMFIELD="CUST_ID"  TOINSTANCE="LKP_CUSTOMER" TOFIELD="IN_CUST_ID"/>
        <CONNECTOR FROMINSTANCE="SQ_SRC_ORDERS" FROMFIELD="AMOUNT"   TOINSTANCE="EXP_CALC"      TOFIELD="AMOUNT"/>
        <CONNECTOR FROMINSTANCE="EXP_CALC"      FROMFIELD="AMOUNT"   TOINSTANCE="FIL_ACTIVE"     TOFIELD="AMOUNT"/>
        <CONNECTOR FROMINSTANCE="LKP_CUSTOMER"  FROMFIELD="REGION"   TOINSTANCE="AGG_BY_REGION"  TOFIELD="REGION"/>
        <CONNECTOR FROMINSTANCE="FIL_ACTIVE"    FROMFIELD="AMOUNT"   TOINSTANCE="AGG_BY_REGION"  TOFIELD="AMOUNT"/>
        <CONNECTOR FROMINSTANCE="AGG_BY_REGION" FROMFIELD="REGION"       TOINSTANCE="TGT_REGION_SUMMARY" TOFIELD="REGION"/>
        <CONNECTOR FROMINSTANCE="AGG_BY_REGION" FROMFIELD="TOTAL_AMOUNT" TOINSTANCE="TGT_REGION_SUMMARY" TOFIELD="TOTAL_AMOUNT"/>
      </MAPPING>

      <SESSION NAME="s_m_LOAD_REGION_SUMMARY" MAPPINGNAME="m_LOAD_REGION_SUMMARY">
        <ATTRIBUTE NAME="..." VALUE="..."/>
        <SESSTRANSFORMATIONINST TRANSFORMATIONNAME="LKP_CUSTOMER">
          <ATTRIBUTE NAME="Lookup cache directory name" VALUE="$PMCacheDir"/>
        </SESSTRANSFORMATIONINST>
      </SESSION>

      <WORKFLOW NAME="wf_LOAD_REGION_SUMMARY">
        <TASK NAME="s_m_LOAD_REGION_SUMMARY" TASKTYPE="Session"/>
        <WORKFLOWLINK FROMTASK="Start" TOTASK="s_m_LOAD_REGION_SUMMARY"/>
      </WORKFLOW>

    </FOLDER>
  </REPOSITORY>
</POWERMART>
```

**What matters for conversion:**
- `MAPPING` = the unit of transformation logic → becomes one (or a few) dbt models.
- `TRANSFORMATION` = one dataflow node. `TYPE` attribute selects the translation rule (§3).
- `CONNECTOR` edges = the DAG. Build it (`FROMINSTANCE`/`FROMFIELD` → `TOINSTANCE`/`TOFIELD`), topologically sort, then walk it to build a chain of CTEs.
- `TABLEATTRIBUTE` = transformation-level config (filter conditions, join conditions, SQL overrides, group-by ports).
- `TRANSFORMFIELD EXPRESSION="..."` = the per-port formula on Expression/Aggregator/Rank transformations — this is Informatica's expression-language string; translate function calls per §4.
- `SESSION`/`WORKFLOW` = **orchestration**, not transformation logic. They map to dbt job scheduling (dbt Cloud jobs, Airflow, `dbt build --select`), not to SQL. Don't try to encode session/workflow XML as models — summarize their run order and any mapping variables/parameters instead (see §7).
- A `MAPPLET` element (reusable transformation graph, referenced from mappings via `INSTANCE TYPE="MAPPLET"`) → a dbt **macro** with the same input parameters, since both exist to be reused across multiple call sites.

## 2. Conversion procedure

1. Parse the XML (Python `xml.etree.ElementTree`/`lxml`, or `xmllint --xpath` for quick lookups).
2. For each `MAPPING`, collect its `TRANSFORMATION` elements and `CONNECTOR` edges.
3. Build the DAG and topologically sort by instance name.
4. Walk it in order, emitting one CTE per transformation node, named `<snake_case(transformation_name)>`. Apply the translation rule for that node's `TYPE` (§3), substituting upstream CTE/column references per the CONNECTOR edges feeding it.
5. The final SELECT maps the last CTE's output ports onto the `TARGET`'s `TARGETFIELD` names/order.
6. Wrap in a dbt model file. Source-adjacent mappings (first thing touching a `SOURCE`) become `stg_<source>__<mapping>.sql` and read via `{{ source(...) }}`; mappings that consume another mapping's target become `{{ ref(...) }}` instead of a raw table name.
7. Emit `schema.yml`: declare the `source()` from `SOURCE`/`SOURCEFIELD`, and add tests derived from constraints — `KEYTYPE="PRIMARY KEY"` → `unique` + `not_null`, `NULLABLE="NOTNULL"` → `not_null`.
8. Anything you can't translate mechanically (§6), leave as a `-- TODO(pc-migration): ...` comment in the SQL and log it in the migration report (§7) — never silently drop logic.

## 3. Transformation → dbt/SQL translation

| `TYPE` | dbt/SQL equivalent | Notes |
|---|---|---|
| `Source Qualifier` | Base `SELECT ... FROM {{ source(...) }}` | `Sql Query` (full override) replaces the generated SELECT verbatim; `Source Filter` → `WHERE`; `User Defined Join` → `JOIN ... ON` when qualifying 2+ sources. |
| `Expression` | Derived columns in the SELECT list | One output column per `TRANSFORMFIELD` with an `EXPRESSION`; translate the formula per §4. Passive — row count unchanged. |
| `Filter` | `WHERE <Filter Condition>` | Single boolean `TABLEATTRIBUTE`. |
| `Router` | One dbt model (or CTE) per output group | Each `GROUP` has its own filter condition (group name + condition live in `TABLEATTRIBUTE`/group-specific elements) — same as N Filters against the same upstream. Keep the "default" group as the catch-all `ELSE`. |
| `Joiner` | `JOIN` on the `Join condition` attribute | `Join Type` attribute: `Normal Join`→`INNER JOIN`, `Master Outer Join`→`RIGHT JOIN` (all detail rows kept — master is the side allowed nulls), `Detail Outer Join`→`LEFT JOIN`, `Full Outer Join`→`FULL JOIN`. Master/detail assignment matters for which side is `LEFT`/`RIGHT` — check which input group is flagged master. |
| `Lookup Procedure` (connected) | `LEFT JOIN <lookup_table> ON <Lookup condition>` | Cache settings (`Lookup cache directory name`, persistent cache, etc., all live under the `SESSION`'s `SESSTRANSFORMATIONINST`) are execution-tuning, not logic — drop them; the warehouse doesn't need a client-side cache. |
| `Lookup Procedure` (unconnected, called via `:LKP.name(args)` inside an Expression) | Correlated scalar subquery or `LEFT JOIN` + column reference, depending on call site | If called conditionally (`IIF(cond, :LKP.x(...), NULL)`), a `LEFT JOIN` + `CASE` is usually cleaner than a subquery. |
| `Aggregator` | `GROUP BY` + aggregate functions | `Group By Ports` attribute lists the GROUP BY columns; non-grouped output ports with an `EXPRESSION` become the aggregate expressions. |
| `Sorter` | `ORDER BY` | Often droppable — SQL result sets are unordered by contract. Keep only if immediately followed by a windowed/ranked consumer that actually depends on order (rare after translation, since Rank supplies its own ORDER). |
| `Rank` | `QUALIFY ROW_NUMBER() OVER (PARTITION BY <group ports> ORDER BY <rank port> DESC/ASC) <= <Number of Ranks>` | Direction comes from whether the rank port is flagged top/bottom. `QUALIFY` works on Snowflake/BigQuery/Databricks; on Postgres/Redshift wrap in a subquery + `WHERE rn <= N` instead. |
| `Sequence Generator` | Prefer `{{ dbt_utils.generate_surrogate_key([...]) }}` over a literal sequence | A literal `NEXTVAL`-style integer sequence isn't idempotent across `dbt run`s; a hash surrogate key is. If the business genuinely needs a monotonic integer id, use the warehouse's native `SEQUENCE`/`IDENTITY`, not application-level state. |
| `Union` | `UNION ALL` | One `SELECT` per input group, in group order. |
| `Update Strategy` | dbt incremental model | `{{ config(materialized='incremental', unique_key=<pk>, incremental_strategy='merge') }}` + `{% if is_incremental() %} WHERE ... {% endif %}`. `DD_INSERT`/`DD_UPDATE` map to the merge itself; `DD_DELETE` has no direct dbt equivalent — needs a post-hook `DELETE` or a snapshot-based soft-delete pattern (flag for manual review, §6); `DD_REJECT` → just excluded by the WHERE/CASE logic upstream. |
| `Normalizer` | `LATERAL FLATTEN`/`UNNEST` (warehouse-specific) or split into multiple models | Denormalizing repeated fields into rows. Get the exact warehouse (Snowflake vs BigQuery vs Databricks) before writing this — syntax differs a lot. |
| `Stored Procedure` | ⚠️ Manual review | dbt doesn't call a proc mid-`SELECT`. If it's a pure function, replicate as a UDF/macro; if it has side effects, it likely belongs outside dbt (upstream ingestion or an orchestrator step). |
| `Transaction Control` | ⚠️ No dbt equivalent | Warehouses commit per-statement/per-model already; there is no mid-mapping commit boundary in dbt. Note in the migration report and confirm downstream doesn't depend on partial commits. |
| `External Procedure` / `Custom`/`Java` Transformation | ⚠️ Manual review | Arbitrary compiled/Java logic — read what it does, reimplement as SQL/a UDF, or as a pre-processing step outside dbt. Never guess; ask for the procedure's logic if it isn't self-evident. |
| `MAPPLET` reference | dbt macro | Same inputs/outputs as the mapplet's own ports; call it from every mapping that referenced the mapplet. |

## 4. Expression-language → SQL function translation

| Informatica | SQL |
|---|---|
| `IIF(cond, a, b)` | `CASE WHEN cond THEN a ELSE b END` |
| `DECODE(val, s1,r1, s2,r2, ..., default)` | `CASE val WHEN s1 THEN r1 WHEN s2 THEN r2 ... ELSE default END` |
| `NVL(val, default)` | `COALESCE(val, default)` |
| `NVL2(val, a, b)` | `CASE WHEN val IS NOT NULL THEN a ELSE b END` |
| `ISNULL(val)` | `val IS NULL` |
| `IS_SPACES(val)` / `IS_NUMBER(val)` | Warehouse-specific regex/`TRY_CAST`; no direct 1:1, translate by intent |
| `TO_CHAR(val, fmt)` / `TO_DATE(val, fmt)` / `TO_DECIMAL(val)` | `CAST`/`TO_VARCHAR`/`TO_DATE`/`TO_NUMBER` — format-string tokens differ per warehouse, translate carefully token-by-token |
| `SUBSTR(str, start, len)` | `SUBSTRING(str, start, len)` (both 1-indexed; PowerCenter allows negative `start` from the end — check) |
| `INSTR(str, search)` | `POSITION(search IN str)` (Snowflake/Postgres) or `CHARINDEX(search, str)` (SQL Server-family) |
| `LTRIM`/`RTRIM`/`TRIM` | same |
| `str1 \|\| str2` or `CONCAT(a,b)` | same, or `CONCAT()` |
| `SYSDATE` / `SYSTIMESTAMP` | `CURRENT_TIMESTAMP` |
| `LOOKUP` (via `:LKP.name(args)`) | see Lookup row in §3 |
| `MAX`/`MIN`/`SUM`/`AVG`/`COUNT` | same, only valid inside Aggregator/Rank context |
| `FIRST`/`LAST` (Aggregator-only functions) | `FIRST_VALUE()`/`LAST_VALUE() OVER (...)` — Informatica's `FIRST`/`LAST` are row-order-dependent within a group, so the window needs an explicit `ORDER BY` matching whatever feeds the Aggregator's input order (often a preceding Sorter) |
| `ERROR(msg)` / `ABORT(msg)` | ⚠️ No SQL equivalent — these halt the session. Translate as a `dbt test` (e.g. a singular test asserting the bad condition never occurs) rather than in-model logic. |

## 5. Datatype mapping

PowerCenter transformation-level datatypes (the `DATATYPE` attribute on `SOURCEFIELD`/`TARGETFIELD`/`TRANSFORMFIELD`) are engine-agnostic; map to your target warehouse's types:

| PowerCenter | Generic SQL | Notes |
|---|---|---|
| `string`, `nstring`, `text`, `ntext` | `VARCHAR(n)` | `PRECISION` = max length |
| `integer` | `INTEGER` / `NUMBER(38,0)` | |
| `decimal` | `NUMBER(precision,scale)` / `NUMERIC(p,s)` | Use `PRECISION`/`SCALE` attrs directly |
| `double`, `real` | `FLOAT` / `DOUBLE` | |
| `date/time` | `TIMESTAMP` (or `DATE` if no time component is ever populated) | Informatica always carries sub-second precision (`PRECISION` 26-29); confirm whether the business actually uses it before dropping to `DATE` |
| `binary`, `raw` | `BINARY` / `VARBINARY` | rare in analytics-oriented mappings |

## 6. Cannot be auto-converted — always flag, never guess

- `Stored Procedure`, `External Procedure`, `Custom`/`Java` transformations — arbitrary code
- `Transaction Control` — no dbt equivalent
- `Update Strategy` rows marked `DD_DELETE` — needs an explicit deletion strategy decision
- `ERROR()`/`ABORT()` calls — session-halting, not representable as a value expression
- `Normalizer` on deeply nested/variable-occurs sources — verify the warehouse-specific unpivot syntax against the actual field-occurrence structure, don't assume
- Mapping variables/parameters (`$$VarName`, parameter files) driving conditional logic — trace where they're set (workflow-level, session-level, or `pmcmd` at invocation) and translate to dbt `vars`/env-based logic explicitly; don't silently hardcode the default

For every one of these, leave `-- TODO(pc-migration): <what's missing and why>` in the SQL, and add a line to the migration report.

## 7. Migration report

For each converted mapping, keep a short `migration_notes/<mapping_name>.md`:

```markdown
# <mapping_name>

**Source object(s):** ...
**Target object(s):** ...
**Session/workflow:** <session name> in <workflow name> — orchestration notes (schedule, run order, dependencies)
**Mapping variables/parameters used:** ...

## Manual review needed
- <transformation name> (<TYPE>): <why it couldn't be auto-translated>

## Assumptions made
- ...
```

This is the handoff artifact — it's what lets a human confirm nothing was silently dropped.

## 8. Worked example

The mapping XML in §1 (`m_LOAD_REGION_SUMMARY`) becomes:

```sql
-- models/marts/region_order_summary.sql
with sq_src_orders as (

    select order_id, cust_id, order_date, status, amount
    from {{ source('erp', 'orders') }}

),

lkp_customer as (

    select
        sq_src_orders.*,
        customer.region
    from sq_src_orders
    left join {{ source('erp', 'customer') }} as customer
        on sq_src_orders.cust_id = customer.cust_id

),

exp_calc as (

    select
        *,
        case when amount > 1000 then 'Y' else 'N' end as is_large
    from lkp_customer

),

fil_active as (

    select *
    from exp_calc
    where status = 'ACTIVE'

),

agg_by_region as (

    select
        lkp_customer.region,
        sum(fil_active.amount) as total_amount
    from fil_active
    left join lkp_customer using (order_id)
    group by lkp_customer.region

)

select
    region,
    total_amount
from agg_by_region
```

Note the CTE chain mirrors the `CONNECTOR` DAG order exactly (`sq_src_orders` → `lkp_customer` / `exp_calc` → `fil_active` → `agg_by_region`), and each CTE name is the transformation's own name, snake_cased — that traceability back to the original mapping is deliberate: it's what makes the migration reviewable by someone who knows the original PowerCenter mapping but not dbt.

`s_m_LOAD_REGION_SUMMARY` / `wf_LOAD_REGION_SUMMARY` (§1's SESSION/WORKFLOW) don't produce any SQL — they'd show up in the migration report as "runs on workflow `wf_LOAD_REGION_SUMMARY`'s schedule, no dependencies," informing how this model gets tagged/scheduled in dbt (e.g. `{{ config(tags=['wf_LOAD_REGION_SUMMARY']) }}` or an Airflow task selector).
