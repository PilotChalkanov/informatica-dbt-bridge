# Informatica dbt Bridge

This project serves as a bridge for mapping **Informatica PowerCenter** workflows and mappings into their equivalent **dbt** models.

## Purpose

Informatica PowerCenter is a widely used ETL tool for building and orchestrating data integration workflows. dbt (data build tool) has become the standard for transforming data using SQL directly in the warehouse, following software engineering best practices such as version control, testing, and modularity.

This project aims to bridge the gap between the two by:

- Parsing PowerCenter mapping and workflow metadata (e.g., XML exports).
- Translating PowerCenter transformations (Source Qualifier, Expression, Aggregator, Joiner, Lookup, Filter, Router, etc.) into equivalent dbt constructs (models, CTEs, macros, tests).
- Producing dbt-compatible SQL models that preserve the original business logic.
- Helping teams migrate legacy ETL pipelines to a modern, SQL-first, ELT approach.

## Status

This project is in early development.

## Getting Started

More details on setup, usage, and supported mappings will be added as the project evolves.
