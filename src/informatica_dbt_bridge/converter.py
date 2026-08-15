"""Orchestrates parse -> DAG order -> per-node translation -> render into one
dbt model. Pure function, no filesystem I/O — the CLI is the only I/O boundary.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from informatica_dbt_bridge.cte import Cte, TranslationNote
from informatica_dbt_bridge.dag import topological_order
from informatica_dbt_bridge.models import Connector, Mapping, SourceDef, TransformationNode
from informatica_dbt_bridge.naming import snake_case
from informatica_dbt_bridge.parser import parse_mapping
from informatica_dbt_bridge.render import render_model
from informatica_dbt_bridge.translators.aggregator import translate_aggregator
from informatica_dbt_bridge.translators.expression import translate_expression_transformation
from informatica_dbt_bridge.translators.filter import translate_filter
from informatica_dbt_bridge.translators.joiner import is_master_port_type, translate_joiner
from informatica_dbt_bridge.translators.lookup import translate_lookup
from informatica_dbt_bridge.translators.router import (
    is_output_group,
    router_group_cte_name,
    translate_router,
)
from informatica_dbt_bridge.translators.source_qualifier import translate_source_qualifier
from informatica_dbt_bridge.translators.union import is_union_transformation, translate_union

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


@dataclass(frozen=True)
class _JoinerUpstream:
    """A Joiner's two resolved upstream transformations (raw, not yet snake_cased)."""

    master: str
    detail: str


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
        ValueError: The mapping has no SOURCE, no TARGET, a transformation
            with no upstream feeding it, a Joiner whose master/detail split
            couldn't be resolved, a Union whose INPUT groups couldn't be
            cleanly matched one-to-one with upstream transformations, or a
            transformation downstream of a Router whose specific branch
            couldn't be resolved.
        NotImplementedError: The mapping has more than one SOURCE (per-SQ
            multi-source resolution is a known, separately-scoped follow-up
            - see the project report), or a transformation has fan-in from
            more than one upstream and isn't a Joiner with a resolvable
            master/detail split or a Union with a resolvable group split.
    """
    mapping = parse_mapping(xml_text, mapping_name=mapping_name)
    order = topological_order(mapping)
    upstream_of = _build_upstream_map(mapping)
    joiner_upstreams = _build_joiner_upstream_map(mapping)
    union_upstreams = _build_union_upstream_map(mapping)
    router_downstream_cte = _resolve_router_downstream_ctes(mapping)
    router_names = {t.name for t in mapping.transformations if t.type == "Router"}
    source = _resolve_single_source(mapping)

    ctes: list[Cte] = []
    notes: list[TranslationNote] = []
    for name in order:
        node = mapping.transformation(name)
        upstream_cte = _resolve_upstream_cte(
            name, upstream_of.get(name), router_names, router_downstream_cte
        )
        translated = _translate_node(
            node,
            upstream_cte,
            source,
            source_system,
            joiner_upstreams.get(name),
            union_upstreams.get(name),
        )
        ctes.extend(translated)
        for cte in translated:
            notes.extend(cte.notes)

    if not mapping.targets:
        raise ValueError(f"mapping {mapping.name!r} has no TARGET")
    final_columns = [snake_case(f.name) for f in mapping.targets[0].fields]

    sql = render_model(ctes, final_columns=final_columns)
    return ConversionResult(mapping_name=mapping.name, sql=sql, notes=notes)


def _translate_node(
    node: TransformationNode,
    upstream_cte: str | None,
    source: SourceDef,
    source_system: str,
    joiner_upstream: _JoinerUpstream | None,
    union_upstream: dict[str, str] | None,
) -> list[Cte]:
    """Dispatch one transformation to its translator.

    Returns a list, not a single `Cte`, because a Router becomes multiple
    CTEs (one per non-INPUT group) - every other translator's result is
    wrapped in a one-element list so `convert_mapping`'s loop can always
    `.extend(...)` uniformly.

    Args:
        node: The transformation to translate.
        upstream_cte: `node`'s single upstream CTE name, already resolved
            (snake_cased, and - if the raw upstream happens to be a Router -
            already group-qualified via `_resolve_upstream_cte`), or None if
            `node` has no single upstream (only valid for a Source
            Qualifier, or a Joiner/Union - which use
            `joiner_upstream`/`union_upstream` instead).
        source: The mapping's resolved SOURCE, used when `node` is a Source
            Qualifier.
        source_system: The dbt `source()` name to pass through to a Source
            Qualifier translation.
        joiner_upstream: `node`'s resolved master/detail upstream
            transformations, if `node` is a Joiner with a resolvable
            two-predecessor fan-in; None otherwise (including for a Joiner
            whose master/detail split couldn't be resolved).
        union_upstream: `node`'s resolved INPUT-group -> upstream
            transformation mapping (raw, not yet snake_cased), if `node` is
            a Union-shaped Custom Transformation with a resolvable group
            split; None otherwise.

    Returns:
        The translated Cte(s), from the matching translator, or from the
        unsupported-type fallback if `node.type` has no translator
        registered.

    Raises:
        ValueError: `node.type` has a translator but `upstream_cte` is None,
            `node.type` is `"Lookup Procedure"` with no `Lookup table name`
            attribute (there's no reliable way to resolve which table it
            joins against otherwise - see `translators/lookup.py`),
            `node.type` is `"Joiner"` with no resolvable `joiner_upstream`,
            or `node` is a Union with no resolvable `union_upstream`.
    """
    if node.type == "Source Qualifier":
        return [
            translate_source_qualifier(
                node, source_system=source_system, source_table=source.name.lower()
            )
        ]
    if node.type == "Joiner":
        return [_translate_joiner_node(node, joiner_upstream)]
    if is_union_transformation(node):
        return [_translate_union_node(node, union_upstream)]
    if node.type == "Router":
        return translate_router(node, upstream_cte=_require_upstream_cte(node, upstream_cte))
    if node.type == "Lookup Procedure":
        return [_translate_lookup_node(node, upstream_cte, source_system)]
    translator = _SIMPLE_TRANSLATORS.get(node.type)
    if translator is not None:
        return [translator(node, upstream_cte=_require_upstream_cte(node, upstream_cte))]
    return [_unsupported(node, upstream_cte=upstream_cte)]


def _require_upstream_cte(node: TransformationNode, upstream_cte: str | None) -> str:
    """Return `upstream_cte`, raising a clear error if `node` has none.

    Shared by every translator that requires exactly one upstream CTE
    (Router and every `_SIMPLE_TRANSLATORS` entry) - `_unsupported()` is the
    one deliberate exception, since it must still emit a fallback CTE even
    with no upstream to read from.

    Args:
        node: The transformation being translated (only used for the error
            message).
        upstream_cte: `node`'s resolved upstream CTE name, or None.

    Returns:
        `upstream_cte`, guaranteed non-None.

    Raises:
        ValueError: `upstream_cte` is None.
    """
    if upstream_cte is None:
        raise ValueError(f"{node.name!r} ({node.type}) has no upstream transformation feeding it")
    return upstream_cte


def _translate_joiner_node(
    node: TransformationNode, joiner_upstream: _JoinerUpstream | None
) -> Cte:
    """Dispatch a Joiner node, given its resolved master/detail upstreams.

    Args:
        node: The Joiner `TransformationNode`.
        joiner_upstream: `node`'s resolved master/detail upstream
            transformations, or None if unresolvable.

    Returns:
        The translated Cte.

    Raises:
        ValueError: `joiner_upstream` is None.
    """
    if joiner_upstream is None:
        raise ValueError(
            f"{node.name!r} (Joiner) needs exactly two resolvable upstream "
            "transformations (one clearly master, one clearly detail); none found, "
            "or the master/detail split is ambiguous"
        )
    return translate_joiner(
        node,
        master_cte=snake_case(joiner_upstream.master),
        detail_cte=snake_case(joiner_upstream.detail),
    )


def _translate_union_node(node: TransformationNode, union_upstream: dict[str, str] | None) -> Cte:
    """Dispatch a Union node, given its resolved per-INPUT-group upstreams.

    Args:
        node: The Union `TransformationNode`.
        union_upstream: `node`'s resolved INPUT-group -> upstream
            transformation mapping (raw, not yet snake_cased), or None if
            unresolvable.

    Returns:
        The translated Cte.

    Raises:
        ValueError: `union_upstream` is None.
    """
    if union_upstream is None:
        raise ValueError(
            f"{node.name!r} (Union) needs a clean one-to-one mapping between its "
            "INPUT groups and upstream transformations; none found, or the split "
            "is ambiguous"
        )
    return translate_union(
        node,
        upstream_by_group={
            group: snake_case(predecessor) for group, predecessor in union_upstream.items()
        },
    )


def _translate_lookup_node(
    node: TransformationNode, upstream_cte: str | None, source_system: str
) -> Cte:
    """Dispatch a Lookup Procedure node, given its single (already-resolved) upstream.

    Args:
        node: The Lookup `TransformationNode`.
        upstream_cte: `node`'s already-resolved upstream CTE name, or None
            if there isn't one.
        source_system: The dbt `source()` name for the lookup table.

    Returns:
        The translated Cte.

    Raises:
        ValueError: `upstream_cte` is None, or `node` has no
            `Lookup table name` attribute.
    """
    if upstream_cte is None:
        raise ValueError(f"{node.name!r} ({node.type}) has no upstream transformation feeding it")
    lookup_table = node.attribute("Lookup table name")
    if not lookup_table:
        raise ValueError(
            f"{node.name!r} (Lookup Procedure) has no 'Lookup table name' attribute; "
            "cannot resolve which table to join against"
        )
    return translate_lookup(
        node,
        upstream_cte=upstream_cte,
        lookup_source_system=source_system,
        lookup_table=lookup_table.lower(),
    )


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


def _resolve_upstream_cte(
    node_name: str,
    upstream: str | None,
    router_names: set[str],
    router_downstream_cte: dict[str, str],
) -> str | None:
    """Resolve `node_name`'s single upstream transformation to its actual CTE name.

    Almost always just `snake_case(upstream)` - the one exception is when
    `upstream` is a Router, which never produces a single CTE of its own
    (it fans out into one CTE per non-INPUT group - see
    `translators/router.py`). In that case the correct upstream is the
    specific group-qualified CTE `node_name`'s own CONNECTOR edges actually
    land on, pre-resolved by `_resolve_router_downstream_ctes`.

    Args:
        node_name: The transformation being resolved (only used for a clear
            error message).
        upstream: The (raw, not yet snake_cased) single upstream
            transformation name, or None if there isn't one.
        router_names: Every Router transformation's instance name in the
            mapping.
        router_downstream_cte: `node_name` -> its resolved group-qualified
            upstream CTE name, for every node whose upstream is a Router
            with a cleanly resolvable branch (see
            `_resolve_router_downstream_ctes`).

    Returns:
        The upstream CTE name `node_name` should read from, or None if
        `node_name` has no upstream at all.

    Raises:
        ValueError: `upstream` is a Router but `node_name`'s specific branch
            couldn't be resolved.
    """
    if upstream is None:
        return None
    if upstream in router_names:
        resolved = router_downstream_cte.get(node_name)
        if resolved is None:
            raise ValueError(
                f"{node_name!r} reads from Router {upstream!r} but its specific OUTPUT "
                "group couldn't be resolved (its CONNECTOR edges must land entirely "
                "within one of the Router's own OUTPUT groups); needs manual review"
            )
        return resolved
    return snake_case(upstream)


def _build_upstream_map(mapping: Mapping) -> dict[str, str]:
    """Map each transformation to its single upstream transformation's name.

    A Joiner is the one deliberate exception: it always has exactly two
    upstream predecessors by construction (master + detail pipelines), so a
    Joiner with exactly two predecessors is skipped here rather than raising
    - `_build_joiner_upstream_map` resolves those two separately. Any other
    fan-in (a non-Joiner with 2+ predecessors, or a Joiner with other than
    exactly two) still isn't supported.

    Args:
        mapping: The mapping whose CONNECTOR edges should be reduced to a
            single predecessor per transformation.

    Returns:
        A dict from transformation instance name to its one upstream
        transformation's instance name. Transformations with no upstream
        (a Source Qualifier, or an unconnected node) have no entry, and
        Joiners/Unions with a structurally-plausible predecessor count have
        no entry either (see `_build_joiner_upstream_map`/
        `_build_union_upstream_map`, which resolve those separately and may
        still fail to fully resolve them - `_translate_node` is what raises
        for that case).

    Raises:
        NotImplementedError: A transformation fed by more than one upstream
            transformation is neither a Joiner with exactly two predecessors
            nor a Union-shaped Custom Transformation - true n-ary fan-in
            outside those two shapes still isn't supported.
    """
    transformation_names = {t.name for t in mapping.transformations}
    joiner_names = {t.name for t in mapping.transformations if t.type == "Joiner"}
    union_names = {t.name for t in mapping.transformations if is_union_transformation(t)}
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
            if to_instance in joiner_names and len(froms) == 2:
                continue
            if to_instance in union_names:
                continue
            raise NotImplementedError(
                f"{to_instance!r} has multiple upstream transformations {sorted(froms)} "
                "(Joiner/Union-style fan-in isn't supported yet)"
            )
        upstream_of[to_instance] = next(iter(froms))
    return upstream_of


def _build_joiner_upstream_map(mapping: Mapping) -> dict[str, _JoinerUpstream]:
    """Resolve the master/detail upstream transformations for each two-predecessor Joiner.

    For each Joiner transformation with exactly two upstream predecessors,
    decides which predecessor is master and which is detail by checking
    which of the Joiner's own ports (`Port.port_type`, via
    `is_master_port_type`) each predecessor's CONNECTOR edges land on. A
    predecessor is master only if *all* of its edges into this Joiner land
    on master-tagged ports, and detail only if *none* of them do - a
    predecessor landing on a mix of both is treated as unresolvable (never
    guessed) rather than arbitrarily assigned a side.

    Args:
        mapping: The mapping to resolve Joiner master/detail upstreams for.

    Returns:
        A dict from Joiner instance name to its resolved `_JoinerUpstream`.
        Only includes Joiners with exactly two upstream predecessors where
        the master/detail split is unambiguous. Anything else (a different
        predecessor count, or an ambiguous split) is simply absent here -
        `_translate_node` raises a clear error for a Joiner with no entry.
    """
    transformation_names = {t.name for t in mapping.transformations}
    result: dict[str, _JoinerUpstream] = {}
    for node in mapping.transformations:
        if node.type != "Joiner":
            continue
        resolved = _resolve_joiner_sides(node, mapping.connectors, transformation_names)
        if resolved is not None:
            result[node.name] = resolved
    return result


def _resolve_joiner_sides(
    node: TransformationNode,
    connectors: list[Connector],
    transformation_names: set[str],
) -> _JoinerUpstream | None:
    """Resolve one Joiner's master/detail predecessors from its CONNECTOR edges.

    Args:
        node: The Joiner `TransformationNode`.
        connectors: The mapping's full CONNECTOR list.
        transformation_names: Every transformation instance name in the
            mapping (used to ignore edges from a SOURCE/TARGET instance).

    Returns:
        The resolved `_JoinerUpstream`, or None if `node` doesn't have
        exactly two predecessors, or their master/detail split is
        ambiguous (see `_build_joiner_upstream_map`).
    """
    master_port_names = {p.name for p in node.ports if is_master_port_type(p.port_type)}

    sides: dict[str, set[bool]] = {}
    for connector in connectors:
        if connector.to_instance != node.name:
            continue
        if connector.from_instance not in transformation_names:
            continue
        is_master_edge = connector.to_field in master_port_names
        sides.setdefault(connector.from_instance, set()).add(is_master_edge)

    if len(sides) != 2:
        return None
    master_candidates = [name for name, flags in sides.items() if flags == {True}]
    detail_candidates = [name for name, flags in sides.items() if flags == {False}]
    if len(master_candidates) != 1 or len(detail_candidates) != 1:
        return None
    return _JoinerUpstream(master=master_candidates[0], detail=detail_candidates[0])


def _build_union_upstream_map(mapping: Mapping) -> dict[str, dict[str, str]]:
    """Resolve the per-INPUT-group upstream transformation for each Union.

    For each Union-shaped Custom Transformation, decides which predecessor
    feeds which named INPUT group by checking which of the Union's own ports
    (`Port.group`) each predecessor's CONNECTOR edges land on - the same
    deterministic, no-guessing approach `_resolve_joiner_sides` uses for
    Joiner's fixed master/detail pair, generalized to an arbitrary number of
    named groups.

    Args:
        mapping: The mapping to resolve Union upstreams for.

    Returns:
        A dict from Union instance name to a dict of INPUT group name ->
        upstream transformation instance name (raw, not yet snake_cased).
        Only includes Unions where every declared INPUT group resolves to
        exactly one predecessor and every predecessor's edges land entirely
        within a single group. Anything else is simply absent here -
        `_translate_node` raises a clear error for a Union with no entry.
    """
    transformation_names = {t.name for t in mapping.transformations}
    result: dict[str, dict[str, str]] = {}
    for node in mapping.transformations:
        if not is_union_transformation(node):
            continue
        resolved = _resolve_union_groups(node, mapping.connectors, transformation_names)
        if resolved is not None:
            result[node.name] = resolved
    return result


def _resolve_union_groups(
    node: TransformationNode,
    connectors: list[Connector],
    transformation_names: set[str],
) -> dict[str, str] | None:
    """Resolve one Union's per-INPUT-group upstream predecessors from its CONNECTOR edges.

    Args:
        node: The Union `TransformationNode`.
        connectors: The mapping's full CONNECTOR list.
        transformation_names: Every transformation instance name in the
            mapping (used to ignore edges from a SOURCE/TARGET instance).

    Returns:
        A dict of INPUT group name -> upstream transformation instance name,
        or None if the split couldn't be cleanly resolved: a predecessor's
        edges land on more than one group, a predecessor feeds something
        other than a declared INPUT group, two predecessors claim the same
        group, or some INPUT group ends up with no predecessor at all.
    """
    input_group_names = {g.name for g in node.groups if g.type == "INPUT"}
    if not input_group_names:
        return None
    group_of_port = {p.name: p.group for p in node.ports}

    groups_fed_by: dict[str, set[str | None]] = {}
    for connector in connectors:
        if connector.to_instance != node.name:
            continue
        if connector.from_instance not in transformation_names:
            continue
        target_group = group_of_port.get(connector.to_field)
        groups_fed_by.setdefault(connector.from_instance, set()).add(target_group)

    result: dict[str, str] = {}
    for predecessor, groups in groups_fed_by.items():
        if len(groups) != 1:
            return None
        (group,) = groups
        if group not in input_group_names or group in result:
            return None
        result[group] = predecessor

    if set(result) != input_group_names:
        return None
    return result


def _resolve_router_downstream_ctes(mapping: Mapping) -> dict[str, str]:
    """Resolve, for every transformation fed by a Router, the specific branch it reads.

    Router is the mirror image of Union: instead of many predecessors
    merging into one node, it's one node fanning out into many CTEs (one
    per non-INPUT group - see `translators/router.py`). A downstream
    transformation's `upstream` name (from `_build_upstream_map`) is only
    ever the Router's raw instance name, which doesn't correspond to any
    single CTE - the actual CTE depends on which of the Router's own
    OUTPUT-group ports the downstream's CONNECTOR edges land on (found via
    `Port.group`, the same mechanism `_resolve_union_groups` uses, just
    read off the *source* side of the edge instead of the target side).

    Args:
        mapping: The mapping to resolve Router downstream branches for.

    Returns:
        A dict from downstream transformation instance name to its resolved
        group-qualified upstream CTE name (via `router_group_cte_name`).
        Only includes downstream nodes whose edges from a given Router land
        entirely within one of that Router's own declared OUTPUT-ish
        groups. A downstream node reading from more than one group (or from
        the Router's own INPUT group, or from an unrecognized port) is
        simply absent here - `_resolve_upstream_cte` raises a clear error
        for that case.
    """
    transformation_names = {t.name for t in mapping.transformations}
    result: dict[str, str] = {}
    for router_node in mapping.transformations:
        if router_node.type != "Router":
            continue
        group_of_port = {p.name: p.group for p in router_node.ports}
        valid_group_names = {g.name for g in router_node.groups if is_output_group(g.type)}

        groups_fed_to: dict[str, set[str | None]] = {}
        for connector in mapping.connectors:
            if connector.from_instance != router_node.name:
                continue
            if connector.to_instance not in transformation_names:
                continue
            source_group = group_of_port.get(connector.from_field)
            groups_fed_to.setdefault(connector.to_instance, set()).add(source_group)

        for downstream_name, groups in groups_fed_to.items():
            if len(groups) != 1:
                continue
            (group,) = groups
            if group not in valid_group_names:
                continue
            result[downstream_name] = router_group_cte_name(router_node.name, group)
    return result


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
