# Audit Note: OCI Cloud Setup Guide

Date: 2026-05-27
Agent: Codex

## Intent

Document whether and how to use Oracle Cloud Infrastructure for the personal
AI-assisted quant portfolio dashboard.

## Files Changed

- `guide/oci-cloud-setup.md`: added OCI architecture recommendation and setup
  steps for Compute VM, Object Storage, backups, secrets, scheduling, and future
  intraday work.
- `quant/docs/audit/2026-05-27-oci-cloud-setup-guide.md`: audit note for this
  documentation change.

## Behavior Changed

No runtime behavior changed. Agents and humans now have a recommended OCI setup
path for deploying data pipeline, quant jobs, backups, and future dashboard/MCP
services.

## Verification

- Documentation-only change.

## Follow-Ups

- Add Terraform or OCI Resource Manager templates if the manual setup becomes
  repetitive.
- Add systemd service and timer files once production CLI commands are finalized.
