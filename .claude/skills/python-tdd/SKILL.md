---
name: python-tdd
description: Test-driven development workflow for Python, following modern best practices (pytest, typed code, src layout, ruff, mypy, coverage discipline). Use when writing new Python code test-first, when the user says TDD/"test-driven"/"write the test first", when adding a feature or fixing a bug in a Python project, or when asked to set up or clean up Python test/project structure and tooling.
---

# Python TDD

## The loop

**Red → Green → Refactor, in that order, every time.** Never write production code without a failing test demanding it.

1. **Red** — write the smallest test that expresses the next bit of behavior you want. Run it. Watch it fail, and confirm it fails *for the reason you expect* (a real assertion failure or a clear `AttributeError`/`ImportError` for something not yet built — not a typo in the test itself).
2. **Green** — write the minimum code to pass. Resist the urge to build more than the test demands; a test you haven't written yet doesn't get to influence the implementation.
3. **Refactor** — with the safety net green, clean up (both the test and the code). Re-run to confirm still green. Commit-sized step.

Keep the cycle small: one behavior per test, one test before the code that satisfies it. If you catch yourself writing more than a few lines of production code with no test behind them, stop and back up.

## Project layout

`src/` layout, tests mirroring the package structure, config centralized in `pyproject.toml`:

```
pyproject.toml
src/
  mypackage/
    __init__.py
    core.py
tests/
  conftest.py
  test_core.py
```

`src/` layout (not a flat `mypackage/` at repo root) forces tests to run against the *installed* package, not an accidentally-importable local directory — catches packaging bugs TDD would otherwise miss.

```toml
# pyproject.toml
[tool.pytest.ini_options]
addopts = "-ra --strict-markers --strict-config"
testpaths = ["tests"]

[tool.coverage.run]
source = ["src"]
branch = true

[tool.ruff]
line-length = 100

[tool.ruff.lint]
select = ["E", "F", "I", "UP", "B", "SIM"]

[tool.mypy]
strict = true
```

## Writing the test

**Arrange–Act–Assert**, one behavior per test, name = what's being verified:

```python
def test_discount_applies_ten_percent_over_threshold():
    cart = Cart(items=[Item(price=Decimal("150.00"))])

    total = cart.total_with_discount()

    assert total == Decimal("135.00")
```

- Name tests `test_<unit>_<behavior>_<condition>` — a failing test name should tell you what broke without opening the file.
- One logical assertion per test (multiple `assert` lines are fine if they're all checking the same outcome, e.g. several fields of one result object).
- Test **behavior through the public API**, not internals. If you can't test something without reaching into a private attribute or mocking three collaborators deep, that's usually a design signal — the unit is doing too much or its interface is wrong — not a reason to mock harder.
- Prefer real objects and fakes over mocks. A mock verifies you called a method; a fake (a real, simplified implementation — an in-memory repo instead of a database-backed one) verifies the *outcome*. Reach for `unittest.mock`/`pytest-mock` only at true I/O boundaries (network, filesystem, time, randomness) you can't otherwise control in a test.
- Use `pytest.mark.parametrize` for the same behavior across multiple inputs instead of copy-pasted near-duplicate tests:

```python
@pytest.mark.parametrize(
    ("price", "expected"),
    [
        (Decimal("50.00"), Decimal("50.00")),  # under threshold: no discount
        (Decimal("150.00"), Decimal("135.00")),  # over threshold: 10% off
    ],
)
def test_discount_by_price_tier(price, expected):
    assert Cart(items=[Item(price=price)]).total_with_discount() == expected
```

- Fixtures for setup, in `conftest.py` when shared across files; keep fixture scope as narrow as correctness allows (`function` default; widen to `module`/`session` only for genuinely expensive, side-effect-free setup).
- Built-in fixtures over hand-rolled ones: `tmp_path` for filesystem tests, `monkeypatch` for env vars/attributes/`sys.path`, `capsys` for stdout/stderr — don't reinvent these.

## Typed from the start

Write the function signature — types included — as part of "Red," before the body:

```python
def total_with_discount(self) -> Decimal: ...
```

The test is the first caller of that signature; writing types first means the test catches interface mistakes (wrong param, wrong return type) before you've invested in an implementation. Run `mypy --strict` alongside pytest — a green test suite with type errors is not actually green.

## Refactor discipline

- Refactor only under green. If refactor breaks a test, that test was pinning behavior you just changed — decide if the new behavior is correct (update the test) or you introduced a regression (revert).
- Rename freely; tests that reference internals by name will need updating, which is a good forcing function to check step 3 of the loop (testing behavior, not internals) actually held.
- Delete tests that no longer describe a behavior anyone cares about — a test suite is a liability too, not just an asset.

## Coverage

Coverage is a smell detector, not a target. Run `coverage run -m pytest && coverage report -m` and look at **which lines are uncovered**, not the percentage. Chasing 100% produces tests that assert a mock was called and nothing else — worse than no test, because it's a false sense of safety. New/changed code should be covered because you wrote the test first; don't backfill coverage after the fact by writing tests to lines instead of to behavior.

## Property-based tests for algorithmic code

For pure functions with a clear invariant (parsers, encoders, math), add a `hypothesis` test alongside the example-based ones once the example-based tests are green — it finds edge cases you won't think to enumerate by hand:

```python
from hypothesis import given, strategies as st


@given(st.decimals(min_value=0, allow_nan=False, allow_infinity=False))
def test_discount_never_increases_price(price):
    assert Cart(items=[Item(price=price)]).total_with_discount() <= price
```

Don't reach for this by default — it's for the subset of code with a real invariant to state, not a replacement for example-based TDD.

## Before calling it done

- `ruff check . && ruff format --check .` — lint and formatting clean.
- `mypy --strict src tests` — no type errors.
- `pytest --strict-markers` — full suite green, no skipped tests you forgot about.
- `coverage report -m` — skim uncovered lines; either add the missing test or confirm they're genuinely untestable (e.g. a defensive branch that can't be reached) and say so in a comment.

If the project doesn't yet have this tooling wired up, add it to `pyproject.toml` as shown above rather than reaching for per-tool config files (`setup.cfg`, `.flake8`, `mypy.ini`) — one file, one source of truth.
