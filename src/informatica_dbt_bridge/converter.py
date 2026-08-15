"""Orchestrates parse -> DAG order -> per-node translation -> render into one
dbt model. Pure function, no filesystem I/O — the CLI is the only I/O boundary.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from informatica_dbt_bridge.cte import Cte, TranslationNote
from informatica_dbt_bridge.dag import topological_order
from informatica_dbt_bridge.models import Mapping, SourceDef, TransformationNode
from informatica_dbt_bridge.naming import snake_case
from informatica_dbt_bridge.parser import parse_mapping
from informatica_dbt_bridge.render import render_model
from informatica_dbt_bridge.translators.aggregator import translate_aggregator
from informatica_dbt_bridge.translators.expression import translate_expression_transformation
from informatica_dbt_bridge.translators.filter import translate_filter
from informatica_dbt_bridge.translators.lookup import translate_lookup
from informatica_dbt_bridge.translators.source_qualifier import translate_source_qualifier

_SIMPLE_TRANSLATORS = {
    "Filter": translate_filter,
    "Expression": translate_expression_transformation,
    "Aggregator": translate_aggregator,
}


@dataclass(frozen=True)
class ConversionResult:
    """The output of converting one PowerCenter mapping: the generated dbt model SQL
    plus every TranslationNote raised along the way."""

    mapping_name: str
    sql: str
    notes: list[TranslationNote] = field(default_factory=list)


def convert_mapping(
    xml_text: str, *, source_system: str, mapping_name: str | None = None
) -> ConversionResult:
    """Convert a PowerCenter mapping XML export into one dbt model.

    Parses the mapping, orders its transformations via the DAG, translates
    each into a CTE, and renders the chain into the final "with ... select"
    SQL text mapped onto the target's field order.

    Args:
        xml_text: The full POWERMART export XML, as text.
        source_system: The dbt `source()` name this mapping's Source
            Qualifier reads from.
        mapping_name: The `NAME` of the `MAPPING` to convert, if the export
            contains more than one. Defaults to the first mapping found.

    Returns:
        A ConversionResult with the generated SQL and every TranslationNote
        raised by its translators (empty if nothing needed manual review).

    Raises:
        PowerCenterParseError: The XML doesn't match the expected shape.
        CycleError: The mapping's dataflow graph has a cycle.
        ValueError: The mapping has no SOURCE, no TARGET, or a transformation
            with no upstream feeding it.
        NotImplementedError: The mapping has more than one SOURCE, or a
            transformation with fan-in from more than one upstream - both
            need Joiner/Union support that doesn't exist yet.
    """
    mapping = parse_mapping(xml_text, mapping_name=mapping_name)
    order = topological_order(mapping)
    upstream_of = _build_upstream_map(mapping)
    source = _resolve_single_source(mapping)

    ctes: list[Cte] = []
    notes: list[TranslationNote] = []
    for name in order:
        node = mapping.transformation(name)
        cte = _translate_node(node, upstream_of.get(name), source, source_system)
        ctes.append(cte)
        notes.extend(cte.notes)

    if not mapping.targets:
        raise ValueError(f"mapping {mapping.name!r} has no TARGET")
    final_columns = [snake_case(f.name) for f in mapping.targets[0].fields]

    sql = render_model(ctes, final_columns=final_columns)
    return ConversionResult(mapping_name=mapping.name, sql=sql, notes=notes)


def _translate_node(
    node: TransformationNode, upstream: str | None, source: SourceDef, source_system: str
) -> Cte:
    """Dispatch one transformation to its translator.

    Args:
        node: The transformation to translate.
        upstream: The (raw, not yet snake_cased) name of the single upstream
            transformation feeding `node`, or None if it has none (only
            valid for a Source Qualifier).
        source: The mapping's resolved SOURCE, used when `node` is a Source
            Qualifier.
        source_system: The dbt `source()` name to pass through to a Source
            Qualifier translation.

    Returns:
        The translated Cte, from the matching translator, or from the
        unsupported-type fallback if `node.type` has no translator
        registered.

    Raises:
        ValueError: `node.type` has a translator but `upstream` is None, or
            `node.type` is `"Lookup Procedure"` with no `Lookup table name`
            attribute (there's no reliable way to resolve which table it
            joins against otherwise - see `translators/lookup.py`).
    """
    if node.type == "Source Qualifier":
        return translate_source_qualifier(
            node, source_system=source_system, source_table=source.name.lower()
        )
    if node.type == "Lookup Procedure":
        if upstream is None:
            raise ValueError(
                f"{node.name!r} ({node.type}) has no upstream transformation feeding it"
            )
        lookup_table = node.attribute("Lookup table name")
        if not lookup_table:
            raise ValueError(
                f"{node.name!r} (Lookup Procedure) has no 'Lookup table name' attribute; "
                "cannot resolve which table to join against"
            )
        return translate_lookup(
            node,
            upstream_cte=snake_case(upstream),
            lookup_source_system=source_system,
            lookup_table=lookup_table.lower(),
        )
    translator = _SIMPLE_TRANSLATORS.get(node.type)
    if translator is not None:
        if upstream is None:
            raise ValueError(
                f"{node.name!r} ({node.type}) has no upstream transformation feeding it"
            )
        return translator(node, upstream_cte=snake_case(upstream))
    return _unsupported(node, upstream_cte=snake_case(upstream) if upstream else None)


def _unsupported(node: TransformationNode, *, upstream_cte: str | None) -> Cte:
    """Fallback for a TYPE with no translator.

    Never silently drops the node: emits a TODO-commented passthrough CTE
    plus a manual-review TranslationNote.

    Args:
        node: The transformation with no registered translator.
        upstream_cte: The (already snake_cased) upstream CTE name, or None
            if there isn't one.

    Returns:
        The fallback Cte, with one TranslationNote flagging it for review.
    """
    from_clause = f"from {upstream_cte}" if upstream_cte else "-- TODO: no upstream resolved"
    sql = (
        f"select *  -- TODO(pc-migration): {node.type} not translated, manual review needed\n"
        f"{from_clause}"
    )
    note = TranslationNote(
        transformation=node.name,
        message=f"{node.type} transformation not auto-translated; manual review needed.",
    )
    return Cte(name=snake_case(node.name), sql=sql, notes=[note])


def _build_upstream_map(mapping: Mapping) -> dict[str, str]:
    """Map each transformation to its single upstream transformation's name.

    Args:
        mapping: The mapping whose CONNECTOR edges should be reduced to a
            single predecessor per transformation.

    Returns:
        A dict from transformation instance name to its one upstream
        transformation's instance name. Transformations with no upstream
        (a Source Qualifier, or an unconnected node) have no entry.

    Raises:
        NotImplementedError: A transformation is fed by more than one
            upstream transformation (fan-in) - that needs Joiner/Union
            support, which doesn't exist yet.
    """
    transformation_names = {t.name for t in mapping.transformations}
    predecessors: dict[str, set[str]] = {}
    for connector in mapping.connectors:
        if (
            connector.to_instance in transformation_names
            and connector.from_instance in transformation_names
        ):
            predecessors.setdefault(connector.to_instance, set()).add(connector.from_instance)

    upstream_of: dict[str, str] = {}
    for to_instance, froms in predecessors.items():
        if len(froms) > 1:
            raise NotImplementedError(
                f"{to_instance!r} has multiple upstream transformations {sorted(froms)} "
                "(Joiner/Union-style fan-in isn't supported yet)"
            )
        upstream_of[to_instance] = next(iter(froms))
    return upstream_of


def _resolve_single_source(mapping: Mapping) -> SourceDef:
    """Return the mapping's one SOURCE.

    Args:
        mapping: The mapping to resolve a source for.

    Returns:
        The mapping's single SourceDef.

    Raises:
        ValueError: The mapping has no SOURCE.
        NotImplementedError: The mapping has more than one SOURCE - that
            needs Joiner support, which doesn't exist yet.
    """
    if not mapping.sources:
        raise ValueError(f"mapping {mapping.name!r} has no SOURCE")
    if len(mapping.sources) > 1:
        raise NotImplementedError(
            f"mapping {mapping.name!r} has multiple sources "
            f"{[s.name for s in mapping.sources]}; multi-source mappings (Joiner) "
            "aren't supported yet"
        )
    return mapping.sources[0]
