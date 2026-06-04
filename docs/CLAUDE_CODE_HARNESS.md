# Claude Code Harness Workflow

This repository uses a disciplined AI coding harness so agents do not make
broad, unsafe, or unreviewed changes.

## Core Loop

1. Plan
2. Work
3. Review
4. Verify
5. Report

## Plan Phase

- Identify the current phase and acceptance criteria.
- Use GitNexus MCP/code graph first.
- Identify the smallest relevant file set.
- Show impacted files before editing.
- Explain why each file is relevant.
- Do not read the whole repository.

## Work Phase

- Make minimal targeted changes.
- Preserve existing runtime behavior unless acceptance criteria require a
  change.
- Do not touch unrelated modules.
- Do not edit trading execution code unless the task explicitly allows it.
- Do not add mock data when the phase requires SSI real data.
- Do not introduce paid provider integrations.

## Review Phase

- Review changed files for correctness, scope creep, safety, and regressions.
- Check that trading safety boundaries are preserved.
- Check that no secrets or local data files were added.

## Verify Phase

- Run the smallest relevant tests, lint, typecheck, or build checks.
- If no tests exist, document that clearly.
- If checks fail, fix only issues related to the current change.

## Report Phase

Report:

- Files changed.
- Why each file changed.
- Tests/checks run.
- Risks.
- Manual follow-up if needed.
- Whether scope boundaries were respected.

## GitNexus Gate

Use GitNexus before planning or editing:

```bash
cd quant-vn-dashboard/apps/web
npm run gitnexus:analyze:fast
```

Agents should query the graph for relevant modules, symbols, imports, and call
chains before opening files. Re-run GitNexus only after module structure,
routes, services, or major imports changed.

Do not use GitNexus to index raw market data, generated files, cache folders,
or local DuckDB/SQLite files.

## Selected External Harness Ideas

The external `claude-code-harness` project is useful as inspiration, but this
repo uses a smaller local setup to avoid installer side effects, auto hooks,
and broad config overwrites.

Adopted ideas:

- Explicit phase commands for plan, work, review, and verify.
- A written phase/status template before implementation.
- Safety review gates before touching trading-adjacent code.
- Small file sets and acceptance criteria before edits.
- Final reports that include files changed, checks run, and residual risks.

Not adopted by default:

- External install scripts.
- Auto-executing hooks.
- Broad permission changes.
- Global agent/editor config changes.
- Generated state folders that could add noise to git.

## Command Aliases

Claude Code can use either the short commands or harness-style aliases:

- `/plan` or `/harness-plan`
- `/work` or `/harness-work`
- `/review` or `/harness-review`
- `/verify` or `/harness-verify`
- `/harness-status` for a phase checkpoint without edits

## Phase Status Template

Before work starts, capture:

```text
Phase:
Acceptance criteria:
GitNexus/context used:
Impacted files:
Why these files:
Non-goals:
Safety boundaries:
Checks to run:
```

Use this as lightweight state in the conversation or task notes. Do not create
large generated state files unless the user explicitly asks.

## Hook Policy

Hooks are disabled by default for this project. A hook may be added only when it
is small, readable, local-only, and cannot expose secrets or run destructive
commands. Any future hook must be reviewed before use and must never connect to
SSI trading APIs, submit orders, run migrations, or inspect raw data/database
files automatically.

## Safe External Harness Trial

If we later want to test the external harness, use a disposable branch or copy:

```bash
git switch -c chore/test-claude-code-harness
git status --short
```

Then clone or inspect the external repo outside this project, pin the exact
tag/commit, run no installer until its diff is understood, and keep only files
that strengthen this local Plan -> Work -> Review -> Verify workflow.
