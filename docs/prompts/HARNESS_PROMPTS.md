# Harness Prompts

## A. Strict Phase Prompt

```text
Stop expanding scope.

Before making changes:
- Identify the current phase and acceptance criteria.
- Use GitNexus MCP/code graph first.
- Identify the smallest relevant file set.
- Do not read the whole repository.
- Show impacted files and explain why each file is relevant before editing.

Do not implement:
- full ML training
- full backtesting engine
- new paid provider integrations
- unrelated UI redesign
- auto trading before the current phase is complete
- live order placement unless this exact phase explicitly allows it

Follow only the current prompt acceptance criteria.
Use minimal targeted changes.
Run the smallest relevant tests/lint/typecheck after changes.
Re-run GitNexus analysis only if module structure, routes, services, or major imports changed.
```

## B. Plan-Only Prompt

```text
Use the Claude Code Harness plan phase only.
Do not edit files.
Use GitNexus first.
Return impacted files, implementation steps, tests, risks, and non-goals.
```

## C. Review-Only Prompt

```text
Use the Claude Code Harness review phase only.
Review changed files against acceptance criteria.
Check scope creep, safety boundaries, tests, and secrets.
Do not make changes unless explicitly asked.
```

## D. Trading Safety Prompt

```text
Use the Claude Code Harness safety workflow.
Map all files related to order preview, order placement, auth, toggle/password gate, audit log, and risk checks.
Do not enable live order placement.
Do not enable auto-trading.
Report risks and required guardrails.
```

## E. External Harness Trial Prompt

```text
Compare an external harness against this repo in a disposable branch or copy only.
Do not run installers until the files, hooks, commands, and permission changes are understood.
Pin the exact source tag or commit.
Report the diff before keeping any file.
Keep only docs, command templates, or rules that strengthen Plan -> Work -> Review -> Verify.
Do not accept hooks or permissions that can expose secrets, touch raw data, run migrations, or modify trading execution.
```
