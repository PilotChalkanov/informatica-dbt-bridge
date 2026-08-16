"""Command-line interface: the only filesystem I/O boundary in this project.

Thin by design (architecture.md's "Interfaces" section): parses args, reads
the input file, calls `convert_mapping` (a pure function with zero
filesystem I/O of its own), writes the result to disk, and prints a summary.
All translation logic lives elsewhere and stays I/O-free - this module never
does any of it itself.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from informatica_dbt_bridge.converter import convert_mapping
from informatica_dbt_bridge.dag import CycleError
from informatica_dbt_bridge.naming import snake_case
from informatica_dbt_bridge.parser import PowerCenterParseError

# Every exception `convert_mapping` documents raising (architecture.md's
# "Interfaces" section: "exit non-zero with a clear message on
# unparseable/unsupported input" - never a raw traceback for one of these).
_CONVERSION_ERRORS = (PowerCenterParseError, CycleError, ValueError, NotImplementedError)


def run(argv: list[str]) -> int:
    """Run the CLI for the given arguments and return a process exit code.

    Unit-testable directly (no `sys.argv`/`sys.exit` patching needed) -
    `main()` is the thin `sys.exit(run(sys.argv[1:]))` wrapper actually
    registered as the console entry point.

    Args:
        argv: Command-line arguments, excluding the program name (e.g.
            `sys.argv[1:]`).

    Returns:
        0 on success; a non-zero exit code if the input couldn't be read or
        `convert_mapping` raised one of its documented exceptions.

    Raises:
        SystemExit: `argv` is missing a required argument, or passes an
            unrecognized one - argparse's own error handling, deliberately
            not intercepted (its usage/error message is already the right
            UX for that case).
    """
    args = _build_arg_parser().parse_args(argv)

    try:
        xml_text = Path(args.xml_path).read_text()
    except OSError as exc:
        print(f"error: couldn't read {args.xml_path!r}: {exc}", file=sys.stderr)
        return 1

    try:
        result = convert_mapping(
            xml_text, source_system=args.source_system, mapping_name=args.mapping_name
        )
    except _CONVERSION_ERRORS as exc:
        print(f"error: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1

    out_dir = Path(args.out)
    out_path = out_dir / f"{snake_case(result.target_name)}.sql"
    try:
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path.write_text(result.sql + "\n")
    except OSError as exc:
        print(f"error: couldn't write {out_path}: {exc}", file=sys.stderr)
        return 1

    print(f"wrote {out_path}")
    if result.notes:
        print(f"{len(result.notes)} item(s) need manual review:")
        for note in result.notes:
            print(f"  - {note.transformation}: {note.message}")

    return 0


def _build_arg_parser() -> argparse.ArgumentParser:
    """Build the top-level `idbb` argument parser.

    Returns:
        The configured `ArgumentParser`, with `convert` as its one
        subcommand.
    """
    parser = argparse.ArgumentParser(prog="idbb")
    subparsers = parser.add_subparsers(dest="command", required=True)

    convert = subparsers.add_parser(
        "convert", help="convert a PowerCenter mapping XML export into a dbt model"
    )
    convert.add_argument("xml_path", help="path to the PowerCenter mapping XML export")
    convert.add_argument(
        "--out", required=True, help="output directory for the generated .sql model"
    )
    convert.add_argument(
        "--source-system",
        required=True,
        help="dbt source() name to resolve Source Qualifiers/Lookups against",
    )
    convert.add_argument(
        "--mapping-name",
        default=None,
        help="the MAPPING to convert, if the export contains more than one "
        "(default: the first one found)",
    )

    return parser


def main() -> None:
    """Entry point registered in `pyproject.toml`'s `[project.scripts]`."""
    sys.exit(run(sys.argv[1:]))
