## Summary

Adds five new PowerCenter transformation translators — **Aggregator**, **Lookup** (connected),
**Joiner** (connected), **Union**, and **Router** — continuing the TDD build order set out in
`architecture.md`. Each was built test-first against the real demo export
(`src/example/FLOWLINE_DEMO_JAFFLESHOP.xml`), not just synthetic fixtures, and cross-checked
against the official PowerCenter Transformation Guide where the skill file's summary didn't
cover a real edge case (aggregate conditional-clause args, non-aggregate Aggregator output
ports, the `/MASTER` port-type marker, Union's `TEMPLATENAME`/`GROUP`/`FIELDDEPENDENCY` shape,
Router's `REF_FIELD`).

Union and Router required real architecture changes, not just new translator modules:

- **Joiner**: `converter.py`'s fan-in restriction now carves out an exact-2-predecessor case,
  resolved into master/detail via the `/MASTER` port-type marker.
- **Union**: a second, N-ary fan-in carve-out, resolved via which named `GROUP` each
  predecessor's `CONNECTOR` edges land on. Required new domain-model support
  (`Group`, `FieldDependency`, `Port.group`, `TransformationNode.template_name`) since nothing
  needed multi-group ports before this.
- **Router**: the reverse problem — fan-*out*, not fan-in. `_translate_node` now returns
  `list[Cte]` uniformly (a Router becomes multiple CTEs, one per group), and downstream
  transformations resolve their upstream to the specific Router branch they're actually
  connected to.

## PowerCenter -> dbt mapping

| `TYPE` | SQL shape |
| --- | --- |
| `Aggregator` | `select <group cols>, <agg fn> as <alias> from <upstream> group by <group cols>`. Conditional-clause aggregate args (`SUM(x, cond)`) rewrite to `SUM(CASE WHEN cond THEN x END)`. A non-aggregate, non-group-by output port (no safe `GROUP BY` equivalent) is flagged with an inline TODO + `TranslationNote`, never guessed. |
| `Lookup Procedure` (connected) | `select <upstream>.*, <lkp>.col as alias, ... from <upstream> left join {{ source(...) }} as <lkp> on <qualified condition>`. |
| `Joiner` (connected) | `from <master> [inner\|left\|right\|full] join <detail> on <qualified condition>`, explicit column list (a Joiner redeclares its own output row). |
| `Union` (a `Custom Transformation` with `TEMPLATENAME="Union Transformation"`) | One `select` per input group (ordered by `GROUP ORDER`, columns aliased via `FIELDDEPENDENCY`) joined by `union all`. |
| `Router` | One CTE per non-`INPUT` group: each OUTPUT group's own filter `EXPRESSION`, plus a synthesized `not (...) and not (...)` default group for whatever matches none of the others. Columns aliased via `REF_FIELD`. |

## Testing

- [x] Tests written first (red), then made to pass (green) - per this repo's
      TDD convention
- [x] `uv run pytest` passes (196 tests)
- [x] `uv run coverage report -m` - 98% overall, 100% on every new translator module
- [x] `uv run mypy --strict` passes
- [x] `uv run ruff check .` / `ruff format --check .` pass
- [x] Verified against a real/representative export where applicable (e.g.
      `src/example/FLOWLINE_DEMO_JAFFLESHOP.xml`), not just a synthetic
      fixture — every translator's output was checked directly against the
      demo XML's real transformations (`AGG_BY_REGION`-shaped aggregates,
      `LKP_CUSTOMER`, `JNR_SUPPLIES_PRODUCTS`/`JNR_ITEMS_ORDERS`, `UN_REGIONS`,
      `RTR_REGION`)

## Manual-review scope

- `FIRST`/`LAST` Aggregator functions are row-order-dependent and have no
  translation yet (would need a `FIRST_VALUE()/LAST_VALUE() OVER (...)`
  rewrite) — flagged as unrecognized, not guessed.
- A Lookup's `Lookup Policy on Multiple Match`, when set to a non-default
  value, is flagged (a plain `LEFT JOIN` fans out to every match instead of
  applying the policy) rather than reconciled automatically.
- **Deferred, not fixed**: `_resolve_single_source` still restricts a
  mapping to exactly one `SOURCE` — a true multi-source mapping (e.g. the
  full demo file) needs new `INSTANCE`/alias-resolution parsing this model
  doesn't have yet. Every new translator's own tests exercise real
  multi-upstream shapes directly; only the full-mapping, all-6-sources
  end-to-end conversion of the demo file is still blocked on this.
- Sorter, Rank, and Sequence Generator translators are intentionally not in
  this PR — tracked in the README as a later development stage.

## Checklist

- [x] No unrelated changes bundled in
- [x] `architecture.md` / `README.md` updated if this changes status, scope,
      or design — README's Status section updated
- [x] No secrets, credentials, or real customer data in fixtures/examples
