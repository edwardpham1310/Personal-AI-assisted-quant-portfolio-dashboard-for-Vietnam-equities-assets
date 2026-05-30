# apps/api

FastAPI service for the Quant VN Dashboard. Sole gateway to SSI FastConnect.

## Install

```bash
python3 -m pip install -e ".[dev]"
```

## Run (dev)

```bash
# From quant-vn-dashboard/apps/api
uvicorn main:app --reload --host 0.0.0.0 --port 8000

# or from quant-vn-dashboard/
make dev-api
```

Open <http://localhost:8000/docs> for Swagger and <http://localhost:8000/health>
for the liveness check.

## Tests

```bash
python3 -m pytest tests/ -v
```

## Project layout

```
apps/api/
├── pyproject.toml
├── Dockerfile
├── src/
│   ├── main.py                  Entry point — uvicorn main:app
│   ├── core/
│   │   ├── config.py            Pydantic Settings
│   │   ├── security.py          JWT verification scaffold
│   │   └── logging.py           Structured stdlib logging
│   ├── api/routes/              Routers (health, auth, market, …)
│   ├── services/                Application services (SSI gateway, etc.)
│   ├── providers/               External-system clients
│   ├── models/                  ORM / dataclasses
│   ├── schemas/                 Pydantic request/response DTOs
│   ├── repositories/            DB access
│   ├── workers/                 Background jobs (poller, ingest)
│   └── utils/                   Small helpers
└── tests/                       Pytest
```
