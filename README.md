# Polaris MIS

React/TypeScript frontend and FastAPI backend backed by a local PostgreSQL restore of `LMS_full_backup.dump`. The production source system is not contacted or modified. This is a snapshot application, not a live synchronization service.

## Run locally

- App: http://127.0.0.1:5173
- API documentation: http://127.0.0.1:8001/api/docs
- Login: `local-access.txt` (private local file; do not commit).
- Start both services: `./scripts/dev.sh`. If already running, open the app directly.
- Python environment: `source backend/.venv/bin/activate`.
- PostgreSQL tools: `.runtime/postgres/bin`; Node: `.runtime/node/bin`.

`backend/.env` holds runtime configuration. The database role has limited permissions; schema migrations use the separate private owner credential through `backend/.venv/bin/python scripts/migrate-local.py`. Never publish `.runtime`, `.env`, dumps, or `local-access.txt`.

## Implementation

`frontend/` contains the React UI, global filters, Recharts plots, registers, CSV exports, calendar, record drawers, and persisted workflow forms. `backend/` contains the API, authentication, parameterized database queries, metric definitions, and SQL migrations. `docs/chart-parity.md` maps 97 chart panels to the reference HTML's sections and tabs. Charts use database values; missing source evidence is displayed explicitly.

MIS accounts are separate from LMS identities. Admin, operator, and viewer access is institution-wide. Cookie sessions support revocation, origin/CSRF checks, and rate-limited login. Workflow writes use optimistic concurrency, evidence checks, and an append-only audit API. CSV exports are limited to 10,000 filtered rows and neutralize spreadsheet formulas.

## Production backup integration

See `docs/production-import.md`, `docs/production-import-counts.json`, and `docs/production-chart-validation.json` for import scope, row counts, source gaps, and live chart checks.

The production archive's `LMS` schema is normalized to `public` in a new local database. Schema objects and business data are restored without executing source functions, triggers, policies, or platform jobs. Credential-bearing tables listed in `scripts/restore_dump.py` have their structures retained but their data omitted. Two absent tables are created empty by migration `000_source_compatibility.sql`; they contain no invented historical data.

To restore another snapshot, create an **empty, separate database**, supply its owner connection string via `RESTORE_DATABASE_URL`, then run:

```sh
backend/.venv/bin/python scripts/restore_dump.py --dump LMS_full_backup.dump --source-schema LMS --pg-restore .runtime/postgres/bin/pg_restore
```

Apply migrations with `DATABASE_URL` set to the new database owner's connection string. Provision the runtime role with `scripts/provision_runtime.py` using `OWNER_DATABASE_URL` and `API_DATABASE_PASSWORD`. Configure the runtime `backend/.env` with the limited role, `SOURCE_DUMP`, and `SOURCE_SNAPSHOT`, then restart the API. Existing application accounts/workflows require an explicit migration; the import script does not copy them automatically.

## Validation

```sh
backend/.venv/bin/ruff check backend scripts/restore_dump.py
backend/.venv/bin/pytest backend/tests -q
PATH="$PWD/.runtime/node/bin:$PATH" npm --prefix frontend test
PATH="$PWD/.runtime/node/bin:$PATH" npm --prefix frontend run build
```

Database integration tests are opt-in: set `RUN_DB_TESTS=1`, `DATABASE_URL` to the limited runtime role, and `TEST_OWNER_DATABASE_URL` to the isolated local restore owner. Tests create and remove only their own fixture records. Do not run them against the upstream production database.

Dockerfiles, Nginx configuration, and `compose.yaml` are deployment starting points; Docker deployment has not been exercised on this machine. Deployment still requires HTTPS, secrets management, backups, monitoring, load testing, and agreement on institution-specific access scopes. Historical enrollment transitions and several operational KPI sources are absent from the backup. A successful chart request does not imply that every requested business metric is available.
