---
name: etl-pipeline-design
description: Tool-agnostic ETL/data pipeline design principles — idempotency, incremental loading, slowly changing dimensions, data quality, orchestration, lineage, and error handling. Use when designing or reviewing a data pipeline regardless of tool (Informatica, dbt, Airflow, Fivetran, Spark, custom scripts), or when asked about incremental loads, SCD, data quality checks, backfills, pipeline idempotency, or orchestration/scheduling design.
---

# ETL / data pipeline design principles

These hold regardless of tool — apply them whether the pipeline is PowerCenter, dbt, Airflow, Fivetran, or a hand-rolled script. Tool-specific translation (e.g. PowerCenter → dbt) lives in other skills in this repo; this one is the underlying design judgment those translations should preserve.

## 1. Idempotency — the load-bearing property

**Running a job twice with the same input must leave the system in the same state as running it once.** Every other guideline here exists in service of this one. Concretely:

- Load by **merge/upsert on a business key**, not blind `INSERT`. A re-run (retry after failure, backfill, manual replay) must not duplicate rows.
- If a target genuinely must be append-only (immutable event log), make the *producer* responsible for not re-sending, or dedupe on a natural event id downstream before it matters.
- Full-refresh ("truncate + reload") is a valid idempotent strategy for small/slow-changing tables — prefer it over a fragile incremental when volume doesn't demand incremental.
- Test idempotency explicitly: run the load twice in a row in a lower environment and diff the result. If a pipeline design can't survive that, it can't survive production retries either.

## 2. Incremental loading

- Drive incrementality off a **high-water-mark** column (`updated_at`, a monotonic sequence, or true CDC log position) — not off wall-clock time ("load from midnight"). Wall-clock windows silently drop late-arriving rows.
- Always load with a small overlap/look-back window past the last watermark, and rely on the merge-on-business-key from §1 to make re-processing that overlap a no-op. This is what makes incremental loads robust to late-arriving or out-of-order data.
- Persist the watermark **after** a load succeeds, not before — a mid-load failure must not advance the watermark past unprocessed data.
- Keep a documented backfill procedure for every incremental pipeline: how to reprocess a date range or full history on demand. If backfill requires hand-editing state, that's a design gap, not a one-off inconvenience — fix it before it's needed under pressure.

## 3. Slowly Changing Dimensions

Pick the type per attribute, not per table — a customer table might need Type 2 on `address` and Type 1 on `email_opt_in`.

- **Type 1 (overwrite)** — no history kept. Default for corrections and attributes where only the current value ever matters.
- **Type 2 (historized rows)** — new row per change, `effective_from`/`effective_to` (or `valid_from`/`valid_to`) + `is_current` flag, surrogate key per version. Use when downstream analysis needs "what was true at the time" (e.g. "what tier was this customer in when they placed this order"). In dbt this is a `snapshot`; in PowerCenter it's typically an Update-Strategy-driven mapping with explicit expire/insert logic — same underlying pattern either way.
- **Type 3 (limited history — previous value column)** — rare; only when exactly one prior value matters and full history is overkill.
- Whatever type, the join key downstream must be explicit about which one it wants: current-state joins use the natural key + `is_current`, point-in-time joins use the surrogate key + date range containment. Getting this wrong silently fabricates history or silently loses it — it won't error.

## 4. Data quality

- **Validate at the boundary.** Check schema/contract (types, required fields, expected value ranges) as data enters the pipeline, not three transformations downstream where the failure is hard to trace back.
- **Business-rule tests belong on the model, close to the logic that assumes them** — not-null, unique, referential integrity, accepted-values checks. Every tool has an equivalent (dbt tests, Informatica session-level reject handling, Great Expectations, custom assertions) — the point is the checks exist and run every run, not that they live in a particular tool.
- **Reject vs. quarantine vs. fail-loud** is a decision, not a default: silently dropping bad rows is almost always wrong (it hides a real upstream problem behind a smaller-than-expected row count). Prefer routing bad rows to a quarantine table with the reason attached, and alert on quarantine volume, over either silent drop or a hard pipeline failure for the whole batch — unless the bad data is genuinely unsafe to process partially, in which case fail loud on purpose.
- Row-count and null-rate anomaly checks between source and target catch entire classes of bugs (a broken join fanning out, a filter condition inverted) that per-column tests miss.

## 5. Orchestration & scheduling

- Express dependencies as **DAG edges** ("this job runs after that job completes"), not as **time offsets** ("this runs at 2:15am because the other one usually finishes by 2am"). Time-based coupling breaks silently the day upstream runs late.
- Because loads are idempotent (§1), retries are safe by construction — configure retry-with-backoff as the default failure response, not a manual re-run.
- A failed job should block only its actual downstream dependents, not the whole pipeline, unless there's a real reason (e.g. shared expensive resource) to serialize further than the DAG requires.
- Make "did last night's run succeed, and how many rows moved" answerable in one glance (orchestrator UI, dashboard, or at minimum a queryable run-log table) — don't make debugging start with "let me check if the job even ran."

## 6. Lineage & observability

- Every pipeline should be able to answer, for any row in a target: **which source row(s) produced it, and which transformation(s) touched it.** dbt gets this largely for free via `ref()`/the DAG; hand-rolled or Informatica-style pipelines need it captured deliberately (a `_source_system`/`_load_id` column, or an external lineage tool).
- Log run metadata every run: start/end time, row counts in/out/rejected, and the watermark/parameters used. This is what makes an anomaly ("today's load moved 10x the usual rows") detectable without re-deriving it from the data itself.
- Treat pipeline code changes like any other production change — versioned, reviewed, deployed through the same path as application code. A dashboard number changing because someone edited a mapping in a shared dev environment is a lineage failure at the *process* level, not just the data level.

## 7. Error handling

- Partial-batch failure semantics must be a deliberate choice: all-or-nothing (transactional load, safest but coarser retries) vs. row-level quarantine (finer-grained, requires the quarantine pattern from §4) vs. best-effort (rarely right — usually hides data loss).
- Never let a transformation error for one row silently null out or drop that row without a trace — route it to quarantine with the error reason, don't swallow it.
- Alert on the failure, not just on the retry exhausting — a job that "succeeds" after 4 silent retries hid a real intermittent problem that deserves visibility.

## 8. Schema evolution

- Additive changes (new nullable column, new table) are safe to ship without coordinating downstream consumers.
- Renames, type narrowing, and drops are not — they need a migration plan that accounts for every downstream reader (other pipelines, BI tools, reverse-ETL), not just the one you're looking at. When in doubt, add-then-deprecate rather than rename-in-place.
- Version transformation logic changes the same way — a mapping/model whose logic changed should be identifiable from run metadata (§6), so a metric shift can be traced to "the definition changed on date X," not mistaken for a data anomaly.

## Design checklist for a new pipeline

- [ ] What's the idempotency mechanism (merge key, or full-refresh)? Has it been tested by running twice?
- [ ] Incremental or full? If incremental: what's the watermark, and what's the backfill procedure?
- [ ] Does any target attribute need SCD Type 2? Which ones, specifically?
- [ ] Where are the data-quality checks, and what happens to a row that fails one (quarantine/reject/fail-loud) — was that a deliberate choice?
- [ ] Are dependencies expressed as DAG edges or as time offsets?
- [ ] Can you answer "did last night's run succeed and how many rows moved" without querying the data itself?
- [ ] Can you trace a target row back to its source row(s)?
- [ ] What's the plan the day someone needs to rename or drop a column this pipeline produces?
