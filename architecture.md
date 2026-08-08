# Informatica PowerCenter → dbt Converter — Architecture

## Context & goals

Informatica PowerCenter mappings describe row-level ETL logic (source → chain of
transformations → target) as a proprietary XML export. dbt expresses the same
kind of logic as a single SQL `select` per model, composed via `ref()`/`source()`.

This project builds a **converter**: given a PowerCenter mapping XML export, produce
an equivalent dbt model (`.sql`), its `schema.yml` (sources + tests), and a migration
report — preserving the original business logic, not just producing something that
looks plausible.

No live customer export was available at design time (see provenance note in
`.claude/skills/powercenter-to-dbt/SKILL.md`), so the converter is validated against
a hand-built representative sample XML covering the common transformation types,
plus the `jaffle_shop_duckdb` reference project as the dbt-side sanity check —
generated models must actually execute against DuckDB, not just look right.

## Non-goals

- Full coverage of every PowerCenter transformation type. We convert the common,
  mechanically-translatable ones (Source Qualifier, Expression, Filter, Router,
  Joiner, Lookup, Aggregator, Union, Sorter, Rank, Sequence Generator, basic Update
  Strategy) and **flag, never guess**, the rest (Stored Procedure, Custom/Java,
  Transaction Control, `DD_DELETE`, `ERROR()`/`ABORT()`, Normalizer edge cases).
- Translating `SESSION`/`WORKFLOW` XML into orchestration config. These are
  summarized into the migration report (schedule, run order, variables) — not
  compiled into Airflow DAGs or dbt Cloud job definitions.
- A general Informatica expression-language parser. We translate a documented table
  of common functions (§4 of the skill file); anything outside that table is left
  verbatim with a `TODO` rather than silently mistranslated.
- Multi-mapping repository resolution (deciding `ref()` vs `source()` across an
  entire Informatica repo export). A single-mapping conversion defaults to
  `source()`; resolving cross-mapping lineage is a stated follow-up (§Risks).
- A GUI or interactive migration tool — this is a CLI/library.

## Constraints

- Python ≥3.12, project already scaffolded with `uv` (`pyproject.toml`, empty
  `dependencies`) — prefer the standard library over new dependencies unless a
  dependency earns its cost.
- No sample export exists in-repo; the input schema is trusted from PowerCenter
  10.x documentation + `powrmart.dtd`, not verified against a real file. Assumed,
  flagged explicitly here (not silently baked in as fact).
- Target warehouse for the validation path is **DuckDB**, because that's what
  `jaffle_shop_duckdb` runs on and it needs to run locally in ~a minute per the
  task brief. Dialect-sensitive translations (`QUALIFY`, `LATERAL`/`UNNEST`,
  date-format tokens) are written for DuckDB/ANSI SQL by default; the skill file's
  per-warehouse notes apply if retargeted.
- Time-boxed exercise — breadth of transformation coverage is deliberately
  traded off against correctness and traceability of what *is* covered. This is
  stated explicitly by the task ("handle what you reasonably can").

## Options considered

**XML parsing: `xml.etree.ElementTree` (stdlib) vs. `lxml`.**
ElementTree is sufficient — the export is a plain, non-huge document, and we don't
need XPath beyond simple child/attribute lookups. Chosen: stdlib, zero new
dependency. Revisit only if XPath-heavy lookups (e.g. searching across mapplets)
get unwieldy.

**SQL generation: direct string/CTE templating vs. a SQL AST builder (e.g. `sqlglot`).**
An AST builder buys dialect portability and safer composition, at the cost of
another dependency and a less direct mapping from "transformation → CTE" that a
PowerCenter-literate reviewer can eyeball. Chosen: direct CTE templating, one CTE
per transformation instance, named after the transformation (snake_cased) —
matches the worked example already in the skill file and keeps the generated SQL
traceable to the original mapping graph. `sqlglot` is a reasonable follow-up if
multi-dialect output becomes a real requirement.

**Expression translation: regex/table-driven substitution vs. a full expression-grammar parser.**
Informatica's expression language is Turing-complete-ish (nested `IIF`, unconnected
lookups, arbitrary function nesting) — a full parser is a project on its own.
Chosen: a table-driven translator (skill file §4) that recognizes a documented set
of functions and rewrites their call sites, operating on the already-tokenized
function-call structure rather than blind regex-on-string where possible. Anything
it doesn't recognize passes through **unchanged with an inline `-- TODO` comment**,
never guessed. This is the single biggest coverage/effort trade-off in the project
and is treated as such — not hidden as a silent limitation.

**DAG construction: hand-rolled topo sort vs. `graphlib.TopologicalSorter` (stdlib).**
Chosen: stdlib `graphlib`. It's built for exactly this, detects cycles (which
would indicate a malformed export) for free, and needs no new dependency.

## Architecture

### Components

- **Parser** (`parser.py`) — reads the `POWERMART` XML into typed dataclasses
  (`Mapping`, `TransformationNode`, `Port`, `Connector`, `TableAttribute`,
  `SourceDef`, `TargetDef`). Isolates every place the code depends on PowerCenter's
  actual tag/attribute names, so if a real export's schema drifts from the
  documented one, the fix is localized here, not scattered through the translators.
  Fails loudly (named exception, points at the offending element) on structurally
  unexpected XML rather than guessing.

- **DAG builder** (`dag.py`) — turns `CONNECTOR` edges into a graph keyed by
  instance name, topologically sorts it via `graphlib.TopologicalSorter`. A cycle
  is a hard error (can't happen in a valid mapping; treat as corrupt input).

- **Expression translator** (`expressions.py`) — table-driven translation of
  Informatica expression-language calls (`IIF`, `DECODE`, `NVL`, `SUBSTR`, …) to
  SQL, per skill file §4. Pure function: `str -> (str, list[TranslationNote])`,
  where notes carry any "left as-is" flags forward to the report — this is the
  seam the migration report reads from.

- **Transformation translators** (`translators/*.py`) — one function per
  PowerCenter `TYPE`, dispatched from a lookup table. Each takes a
  `TransformationNode` plus its resolved upstream column references (from the DAG)
  and returns a `Cte` (name, select list, source CTE(s), extra clauses, notes).
  Unsupported types return a `Cte` that's a passthrough `SELECT *` wrapped in a
  loud `-- TODO(pc-migration): <TYPE> not translated, manual review needed` and a
  report entry — never a silently dropped node.

- **SQL renderer** (`render.py`) — assembles the ordered `Cte` list into the final
  `with … select` dbt model text; the terminal `select` maps the last CTE's output
  ports onto the `TARGET`'s field names/order, per the skill's worked example.

- **Source/target classifier** — decides `{{ source(...) }}` vs `{{ ref(...) }}`
  and `models/staging/` vs `models/marts/` placement. For a single-file conversion
  this defaults to `source()` (first touch of a `SOURCE`) unless the caller
  supplies a target-name → model-name map (needed for multi-mapping repos — see
  Risks).

- **schema.yml generator** (`schema_yml.py`) — emits the `source()` declaration
  from `SOURCE`/`SOURCEFIELD`, and tests from constraints: `KEYTYPE="PRIMARY KEY"`
  → `unique` + `not_null`, `NULLABLE="NOTNULL"` → `not_null`.

- **Migration report generator** (`report.py`) — one `migration_notes/<mapping>.md`
  per conversion, per the skill file §7 template: source/target objects, orchestration
  notes, mapping variables, and every manual-review item collected from the
  translators and expression translator along the way.

- **CLI** (`cli.py`) — `informatica-dbt-bridge convert <xml> --out <dbt_project_dir>`.
  Thin: parses args, calls the library function below, writes the returned files to
  disk. All translation logic is filesystem-free and unit-testable without it.

### Data flow

```
mapping.xml
   │
   ▼
Parser ──► domain model (Mapping, TransformationNode[], Connector[])
   │
   ▼
DAG builder ──► topologically ordered instance list
   │
   ▼
for each instance: dispatch to Transformation translator
   │  (translators call the Expression translator for per-port EXPRESSION strings)
   ▼
ordered Cte[] + TranslationNote[]
   │
   ├──► SQL renderer          ──► models/<staging|marts>/<name>.sql
   ├──► schema.yml generator  ──► models/<staging|marts>/schema.yml (sources + tests)
   └──► Report generator      ──► migration_notes/<mapping_name>.md
```

The library entrypoint is a pure function —
`convert_mapping(xml_text: str, *, target_lookup: dict[str, str] | None = None) -> ConversionResult`
(`ConversionResult` = generated SQL text + schema.yml text + report text + a
structured list of TODOs) — so tests exercise it directly without touching the
filesystem; the CLI is the only I/O boundary, per the project's TDD skill guidance
of mocking only at true I/O edges.

### Storage

None. This is a stateless, file-to-file batch converter — no database, no queue,
no persisted run state. Idempotent by construction: converting the same XML twice
produces byte-identical output.

### Interfaces

- **CLI**: `informatica-dbt-bridge convert <xml-path> --out <dbt-project-root>`.
  Exit non-zero with a clear message on unparseable/unsupported input; never exit 0
  having silently dropped transformation logic.
- **Library API**: `convert_mapping(...)` above — the contract the tests target.

### Deployment topology

Local CLI tool, run via `uv run informatica-dbt-bridge convert ...`. No server, no
persistent process. A plausible future home is a one-off CI/pre-commit step for
bulk-migrating an exported Informatica repo folder, but that's out of scope now —
noted so the single-file-first design doesn't accidentally foreclose it (the
library function is already repo-batchable by calling it once per mapping file).

## Cross-cutting concerns

- **Error handling**: unsupported/malformed XML → fail loud with a diagnostic
  naming the offending element (parser layer). Unsupported transformation `TYPE`
  or unrecognized expression function → never dropped silently; always a `TODO`
  comment in the SQL **and** a migration-report line. This mirrors the
  `etl-pipeline-design` skill's stance that silently dropping logic is worse than
  visible ugliness.
- **Testing strategy** (see also `tests/` below):
  - Unit tests per translator and per expression-function mapping, isolated from
    I/O.
  - A golden-file/snapshot test on the full sample mapping (Source Qualifier →
    Lookup/Expression → Filter → Aggregator → Target, mirroring the skill file's
    worked example) — generated `.sql`/`schema.yml` diffed against checked-in
    fixtures.
  - An **executable** integration test: drop the generated model into a minimal
    local dbt+DuckDB project (seeded tables matching the sample mapping's sources,
    or wired into `jaffle_shop_duckdb` directly), run `dbt build`, and assert on
    actual output rows — not just that the SQL text looks plausible. This is the
    real correctness bar per the task brief ("check your output against the jaffle
    shop reference project").
- **Observability**: not a running service, but the migration report + a per-run
  summary (transformations converted vs. flagged) is the "did this migration
  succeed" signal, in the same spirit as the `etl-pipeline-design` skill's
  observability principle — applied to the migration process itself.
- **Security**: local file I/O only, no network calls, no secrets in scope. Worth
  stating once and moving on.

## Risks & open questions

- **Schema drift risk**: the parser is built from documentation, not a verified
  real export. If a real file uses different tag/attribute shapes, the parser will
  fail loudly rather than mis-convert — by design — but will need adaptation.
  Isolated to `parser.py` specifically so that adaptation is cheap.
- **Expression coverage is necessarily partial.** The function table covers the
  common cases from the skill file; anything else is `TODO`'d, not guessed. This is
  the main scope trade-off for the time box.
- **`ref()` vs `source()` resolution** needs cross-mapping context this design
  doesn't have for a single input file. Follow-up: accept a directory of mapping
  exports (or a manifest) and resolve `TARGET` names that are also some other
  mapping's `SOURCE`/`TARGET` into `ref()`.
- **Warehouse dialect**: DuckDB/ANSI is the default target for validation. Rank
  (`QUALIFY`), Normalizer (`UNNEST`/`LATERAL FLATTEN`), and date-format tokens are
  warehouse-sensitive — retargeting to Snowflake/BigQuery/Redshift needs those
  translators revisited, per skill file §3/§5.
- **Session/workflow scope boundary**: orchestration metadata (schedule, mapping
  variables set at session/workflow/`pmcmd` level) is summarized in the report only.
  Wiring it into real scheduling (dbt Cloud jobs, Airflow selectors,
  `config(tags=[...])`) is left to a human, consistent with the skill file's stance
  that orchestration isn't transformation logic.

## Implementation plan (next step)

1. `src/informatica_dbt_bridge/`: `parser.py`, `dag.py`, `expressions.py`,
   `translators/`, `render.py`, `schema_yml.py`, `report.py`, `cli.py`.
2. TDD order (red→green→refactor per transformation type, narrowest first):
   Source Qualifier → Expression → Filter → Aggregator → Lookup (connected) →
   Joiner → Union → Router → Rank → Sequence Generator.
3. Build the representative sample mapping XML (documented as synthetic) covering
   the above, matching the skill file's worked example shape.
4. Golden-file test on the full sample mapping.
5. Wire the DuckDB/`jaffle_shop_duckdb`-based executable integration test last,
   once the SQL shape is stable.
