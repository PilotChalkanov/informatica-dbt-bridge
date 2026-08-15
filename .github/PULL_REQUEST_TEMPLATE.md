## Summary

<!-- What does this PR do, and why? Link to the relevant section of
architecture.md if this changes design, scope, or a documented trade-off. -->

## PowerCenter -> dbt mapping

<!-- If this adds/changes a translator: which TYPE(s), and the SQL shape it
produces. A short before/after example (PowerCenter XML snippet -> generated
SQL) is the fastest way to review this. -->

## Testing

- [ ] Tests written first (red), then made to pass (green) - per this repo's
      TDD convention
- [ ] `uv run pytest` passes
- [ ] `uv run coverage report -m` - no unexplained coverage drop
- [ ] `uv run mypy --strict` passes
- [ ] `uv run ruff check .` / `ruff format --check .` pass
- [ ] Verified against a real/representative export where applicable (e.g.
      `src/example/FLOWLINE_DEMO_JAFFLESHOP.xml`), not just a synthetic
      fixture

## Manual-review scope

<!-- Anything this PR intentionally leaves as a TranslationNote/TODO rather
than translating, and why (see architecture.md's "flag, never guess"
stance). Anything explicitly deferred as follow-up work? -->

## Checklist

- [ ] No unrelated changes bundled in
- [ ] `architecture.md` / `README.md` updated if this changes status, scope,
      or design
- [ ] No secrets, credentials, or real customer data in fixtures/examples
