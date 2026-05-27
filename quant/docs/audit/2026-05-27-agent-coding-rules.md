# Audit Note: Agent Coding Rules

Date: 2026-05-27
Agent: Codex

## Intent

Create a project rule file so coding agents follow the same `quant-vn` concept,
record meaningful actions for quick audit, and update related docs when behavior
changes.

## Files Changed

- `quant-vn/docs/agent-memory/coding-rules.md`: new rule file for coding,
  financial safety, audit notes, and docs update requirements.
- `CLAUDE.md`: linked the coding rules into workspace-level memory.
- `quant-vn/docs/agent-memory/shared-context.md`: added the rule file and audit
  discipline to shared agent context.
- `quant-vn/docs/audit/2026-05-27-agent-coding-rules.md`: first audit note and
  template example.

## Behavior Changed

Agents now have an explicit rule file to read before code changes. Meaningful
future changes should create short audit notes under `quant-vn/docs/audit/` and
update related docs in the same change.

## Verification

- Confirmed files were created and linked through project memory.

## Follow-Ups

- Consider adding a lightweight script later to check whether audit notes exist
  for larger changes.
