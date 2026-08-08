# Low-level design: the converter

Internal structure of `src/informatica_dbt_bridge/`. Ground truth is the code; if this
drifts from it, trust the code and fix this file.

## Domain model

`parser.py` builds this from the raw XML; everything downstream operates on it instead of
`ElementTree` elements.

```mermaid
classDiagram
    class Mapping {
      +str name
      +list~SourceDef~ sources
      +list~TargetDef~ targets
      +list~TransformationNode~ transformations
      +list~Connector~ connectors
      +transformation(name) TransformationNode
    }
    class TransformationNode {
      +str name
      +str type
      +list~Port~ ports
      +list~TableAttribute~ attributes
      +attribute(name) str|None
    }
    class Port {
      +str name
      +str port_type
      +str datatype
      +str expression
    }
    class Connector {
      +str from_instance
      +str from_field
      +str to_instance
      +str to_field
    }
    class SourceDef {
      +str name
      +str database_type
      +list~SourceField~ fields
    }
    class TargetDef {
      +str name
      +list~TargetField~ fields
    }

    Mapping "1" *-- "*" TransformationNode
    Mapping "1" *-- "*" SourceDef
    Mapping "1" *-- "*" TargetDef
    Mapping "1" *-- "*" Connector
    TransformationNode "1" *-- "*" Port
```

## Translation intermediate representation

Every translator (`translators/*.py`) returns a `Cte`; `converter.py` collects their
`TranslationNote`s into the final `ConversionResult`.

```mermaid
classDiagram
    class Cte {
      +str name
      +str sql
      +list~TranslationNote~ notes
    }
    class TranslationNote {
      +str transformation
      +str message
    }
    class ConversionResult {
      +str mapping_name
      +str sql
      +list~TranslationNote~ notes
    }

    Cte "1" *-- "*" TranslationNote
    ConversionResult "1" *-- "*" TranslationNote
```

## `convert_mapping()` call sequence

```mermaid
sequenceDiagram
    participant Caller
    participant convert_mapping
    participant parse_mapping
    participant topological_order
    participant translator as translator (per node.type)
    participant render_model

    Caller->>convert_mapping: (xml_text, source_system)
    convert_mapping->>parse_mapping: parse_mapping(xml_text)
    parse_mapping-->>convert_mapping: Mapping
    convert_mapping->>topological_order: topological_order(mapping)
    topological_order-->>convert_mapping: ordered instance names

    loop each transformation, in order
        convert_mapping->>translator: translate_*(node, upstream_cte)
        Note right of translator: Expression also calls<br/>translate_expression() per port
        translator-->>convert_mapping: Cte
    end

    convert_mapping->>render_model: render_model(ctes, final_columns)
    render_model-->>convert_mapping: SQL text
    convert_mapping-->>Caller: ConversionResult
```

Notes on the dispatch step (`converter._translate_node`):

- `Source Qualifier` always goes to `translate_source_qualifier` — it has no upstream CTE.
- `Filter`/`Expression` require an upstream CTE, resolved from `CONNECTOR` edges
  (`converter._build_upstream_map`). Fan-in (two upstreams into one node) raises
  `NotImplementedError` — that needs Joiner/Union support, which doesn't exist yet.
- Any other `TYPE` falls back to `converter._unsupported`: a `TODO`-commented passthrough
  CTE plus a `TranslationNote`, never a silently dropped node.

## Module dependencies

```mermaid
flowchart TB
    parser[parser.py] --> models[models.py]
    dag[dag.py] --> models
    converter[converter.py] --> models
    converter --> dag
    converter --> render[render.py]
    converter --> translators

    subgraph translators [translators/*.py]
        sq[source_qualifier.py]
        fil[filter.py]
        exp[expression.py]
    end

    translators --> naming[naming.py]
    translators --> cte[cte.py]
    exp --> expressions[expressions.py]
    render --> cte
```
