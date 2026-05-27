# OCI Cloud Setup Guide

This guide sets up Oracle Cloud Infrastructure for the personal AI-assisted
quant portfolio dashboard.

## Recommendation

Use OCI for this project, but start conservatively:

- Run `datapipe`, `quant`, dashboard jobs, and future MCP services on an OCI
  Compute VM.
- Keep raw market snapshots, backup files, and exported datasets in OCI Object
  Storage.
- Keep the first production database simple: SQLite/DuckDB on a persistent block
  volume, backed up to Object Storage.
- Add Autonomous Database later for portfolio metadata, recommendation records,
  AI narrative records, and account-sync history if the local DB becomes hard to
  manage.

Do not expose databases directly to the internet. Phase 1 is recommend-only.

## Why This Fits

OCI Always Free resources are enough for a personal research deployment:

- Compute VM for scheduled jobs and dashboard services.
- Block Volume for local databases and reports.
- Object Storage for raw data and backups.
- Autonomous Database for a small managed metadata store if needed later.

Important limits to remember:

- Always Free Ampere A1 Compute is capacity-limited by region and can be
  reclaimed if idle.
- Always Free Object Storage has a small free quota, so keep raw snapshots
  compressed and rotate old intermediate files.
- Always Free Autonomous Database has limited storage and sessions, and is not a
  replacement for unlimited intraday raw data storage.

Oracle references:

- OCI Always Free resources:
  <https://docs.oracle.com/en-us/iaas/Content/FreeTier/freetier_topic-Always_Free_Resources.htm>
- Always Free Autonomous Database:
  <https://docs.oracle.com/en/cloud/paas/autonomous-database/serverless/adbsb/autonomous-always-free.html>

## Target Architecture

```text
SSI FastConnect / vnstock / CSV
        |
        v
OCI Compute VM
  - datapipe scheduler
  - quant signal jobs
  - dashboard service/static reports
  - future MCP service
        |
        +--> Block Volume
        |     - SQLite
        |     - DuckDB
        |     - reports
        |
        +--> Object Storage
        |     - raw snapshots
        |     - parquet/csv exports
        |     - database backups
        |
        +--> Optional Autonomous DB
              - portfolio metadata
              - recommendation records
              - AI narrative records
              - audit/event tables
```

## Step 1: Create OCI Resources

Create these in your OCI home region:

1. Compartment: `quant-finance`.
2. VCN: `quant-vcn`.
3. Public subnet for the VM.
4. Compute instance:
   - Shape: Always Free eligible Ampere A1 Flex if available.
   - OS: Ubuntu LTS.
   - Start small: 1 OCPU / 6 GB RAM or 2 OCPU / 12 GB RAM.
   - Boot volume: 50 GB minimum; increase only if you understand Always Free
     block volume limits.
5. Object Storage buckets:
   - `quant-raw`
   - `quant-backups`
   - `quant-reports`

Security list or network security group:

- Allow SSH `22` only from your IP.
- Do not open database ports.
- Later, open dashboard HTTPS `443` only if you deploy a web UI.

## Step 2: SSH Into The VM

```bash
ssh ubuntu@<vm-public-ip>
```

Install base packages:

```bash
sudo apt update
sudo apt install -y git python3 python3-venv python3-pip make curl unzip jq
```

Optional Docker runtime:

```bash
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker ubuntu
```

Log out and back in after adding the user to the `docker` group.

## Step 3: Prepare Directories

```bash
sudo mkdir -p /opt/quant-finance
sudo mkdir -p /opt/quant-finance-data/{raw,sqlite,duckdb,reports,logs,backups}
sudo chown -R ubuntu:ubuntu /opt/quant-finance /opt/quant-finance-data
```

Recommended path contract:

```text
/opt/quant-finance          # repo checkout
/opt/quant-finance-data     # persistent data
```

## Step 4: Deploy The Code

Clone your private repo or copy the workspace:

```bash
cd /opt
git clone <your-private-repo-url> quant-finance
cd /opt/quant-finance
```

Install packages:

```bash
cd datapipe
python3 -m venv .venv
. .venv/bin/activate
pip install -U pip
pip install -e ".[dev]"
python3 -m pytest tests/ -q
deactivate

cd ../quant
python3 -m venv .venv
. .venv/bin/activate
pip install -U pip
pip install -e ".[dev]"
python3 -m pytest tests/ -q
deactivate
```

## Step 5: Configure Secrets

Create an environment file outside git:

```bash
mkdir -p /opt/quant-finance-secrets
chmod 700 /opt/quant-finance-secrets
nano /opt/quant-finance-secrets/quant.env
```

Example:

```bash
SSI_CONSUMER_ID=replace_me
SSI_CONSUMER_SECRET=replace_me

QUANT_DATA_ROOT=/opt/quant-finance-data
QUANT_RAW_DIR=/opt/quant-finance-data/raw
QUANT_SQLITE_DIR=/opt/quant-finance-data/sqlite
QUANT_DUCKDB_DIR=/opt/quant-finance-data/duckdb
QUANT_REPORTS_DIR=/opt/quant-finance-data/reports
```

Permissions:

```bash
chmod 600 /opt/quant-finance-secrets/quant.env
```

Later, move secrets to OCI Vault or instance principals. Do not commit `.env`
files.

## Step 6: Configure OCI CLI For Backups

Install OCI CLI:

```bash
bash -c "$(curl -L https://raw.githubusercontent.com/oracle/oci-cli/master/scripts/install/install.sh)"
```

For a simple first setup, run:

```bash
oci setup config
```

Better production setup:

- Use an instance principal.
- Create a dynamic group for the VM.
- Grant that dynamic group permission to manage objects only in the backup/raw
  buckets.

Example policy idea:

```text
Allow dynamic-group quant-finance-vms to manage objects in compartment quant-finance
```

Tighten this later to bucket-specific permissions.

## Step 7: Backup Script

Create `/opt/quant-finance/scripts/backup_to_oci.sh`:

```bash
#!/usr/bin/env bash
set -euo pipefail

STAMP="$(date +%Y%m%d_%H%M%S)"
BACKUP_DIR="/opt/quant-finance-data/backups/$STAMP"
mkdir -p "$BACKUP_DIR"

cp -a /opt/quant-finance-data/sqlite "$BACKUP_DIR/" 2>/dev/null || true
cp -a /opt/quant-finance-data/duckdb "$BACKUP_DIR/" 2>/dev/null || true

tar -czf "/opt/quant-finance-data/backups/quant-backup-$STAMP.tar.gz" -C "$BACKUP_DIR" .

oci os object put \
  --bucket-name quant-backups \
  --file "/opt/quant-finance-data/backups/quant-backup-$STAMP.tar.gz" \
  --name "quant-backup-$STAMP.tar.gz"
```

Make it executable:

```bash
chmod +x /opt/quant-finance/scripts/backup_to_oci.sh
```

Cron example:

```bash
crontab -e
```

Add:

```text
30 18 * * 1-5 /opt/quant-finance/scripts/backup_to_oci.sh >> /opt/quant-finance-data/logs/backup.log 2>&1
```

## Step 8: Schedule Data Pipeline Jobs

Start with end-of-day jobs, then add intraday 5m/15m once the SSI provider and
schema support it.

Example cron structure:

```text
# Daily after market close
10 15 * * 1-5 cd /opt/quant-finance/datapipe && . .venv/bin/activate && quant-vn-data ingest-daily >> /opt/quant-finance-data/logs/ingest-daily.log 2>&1

# Quant signals after data ingestion
30 15 * * 1-5 cd /opt/quant-finance/quant && . .venv/bin/activate && quant-vn dashboard >> /opt/quant-finance-data/logs/dashboard.log 2>&1
```

Use the exact CLI commands that exist in the repo. If a command does not exist
yet, create it before enabling cron.

## Step 9: Add Intraday 5m/15m Later

Before enabling intraday jobs, define:

- Table/schema for intraday bars.
- `timeframe` column: `5m`, `15m`, `1d`.
- Provider support from SSI FastConnect.
- Dedup/upsert key: `(symbol, timestamp, timeframe, source)`.
- Market session calendar.
- Rate-limit and retry behavior.

Recommended job cadence:

- Fetch raw data every 1-5 minutes during market hours.
- Normalize to 5m/15m bars.
- Write signal snapshots every completed bar.
- Let Claude/MCP read only completed bars to avoid unstable partial-bar signals.

## Step 10: Dashboard Deployment

For phase 1, generate static reports or run a local dashboard service on the VM.

When exposing the dashboard publicly:

- Put it behind Nginx.
- Use HTTPS.
- Add authentication.
- Do not expose raw database files.
- Do not expose SSI credentials.
- Keep broker trading disabled.

## Cost Guardrails

- Use Always Free eligible labels in the OCI Console.
- Keep compute and block volume within Always Free limits.
- Use budget alerts.
- Avoid public buckets.
- Compress raw data.
- Delete old intermediate files after backups are verified.

## Recommended Next Implementation Tasks

1. Add intraday schema to `datapipe`.
2. Add SSI 5m/15m ingestion if the API entitlement supports it.
3. Add portfolio tables.
4. Add recommendation and AI narrative tables.
5. Add MCP read-only tools for Claude.
6. Add a dashboard service after the data contract is stable.
