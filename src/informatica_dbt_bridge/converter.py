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
from informatica_dbt_bridge.translators.expression import translate_expression_transformation
from informatica_dbt_bridge.translators.filter import translate_filter
from informatica_dbt_bridge.translators.source_qualifier import translate_source_qualifier

_SIMPLE_TRANSLATORS = {
    "Filter": translate_filter,
    "Expression": translate_expression_transformation,
}


@dataclass(frozen=True)
class ConversionResult:
    mapping_name: str
    sql: str
    notes: list[TranslationNote] = field(default_factory=list)


def convert_mapping(
    xml_text: str, *, source_system: str, mapping_name: str | None = None
) -> ConversionResult:
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
    if node.type == "Source Qualifier":
        return translate_source_qualifier(
            node, source_system=source_system, source_table=source.name.lower()
        )
    translator = _SIMPLE_TRANSLATORS.get(node.type)
    if translator is not None:
        assert upstream is not None, f"{node.name!r} has no upstream but isn't a Source Qualifier"
        return translator(node, upstream_cte=snake_case(upstream))
    return _unsupported(node, upstream_cte=snake_case(upstream) if upstream else None)


def _unsupported(node: TransformationNode, *, upstream_cte: str | None) -> Cte:
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
    if not mapping.sources:
        raise ValueError(f"mapping {mapping.name!r} has no SOURCE")
    if len(mapping.sources) > 1:
        raise NotImplementedError(
            f"mapping {mapping.name!r} has multiple sources "
            f"{[s.name for s in mapping.sources]}; multi-source mappings (Joiner) "
            "aren't supported yet"
        )
    return mapping.sources[0]
