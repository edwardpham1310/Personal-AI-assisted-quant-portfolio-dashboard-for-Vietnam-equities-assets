# GitNexus Agent Prompts

Use these prompts when asking AI coding agents to work in this repository.

## A. General Repo Review

```text
Use GitNexus MCP/code graph first. Build an architecture map of this repository.
Do not read unrelated files. Identify modules, dependencies, risks, and the
smallest set of files needed for the task.
```

## B. Backend Task

```text
Use GitNexus to locate API route -> service -> repository/data connector flow.
Inspect only connected files. Implement the requested backend change with tests.
Do not read raw market data, database files, caches, or generated indexes.
```

## C. Data Pipeline Task

```text
Use GitNexus to locate ingestion, validation, schema, and storage modules. Do
not read raw market data or database files. Implement changes using
DuckDB/SQLite boundaries, small fixtures, and focused tests.
```

## D. Frontend Chart Task

```text
Use GitNexus to locate chart components, API clients, hooks, and market data
stores. Implement near-real-time candlestick chart changes without touching
backend trading execution.
```

## E. Trading Safety Task

```text
Use GitNexus to map all files related to order preview, order placement, auth,
toggle/password gate, audit log, and risk checks. Do not enable live order
placement unless explicitly requested.
```
