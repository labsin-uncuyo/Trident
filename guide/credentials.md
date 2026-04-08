# Credentials (Lab‑Only Defaults)

These defaults are **for the isolated lab only**. Do not reuse them on real systems. Override via environment variables or `.env`.

## Compromised host (SSH)
- User: `labuser`
- Password: `LAB_PASSWORD` (default `adminadmin` in `.env.example`)

## Server (SSH)
- User: `root`
- Password: `admin123` (set in `images/server/Dockerfile`)

## Web login app
- User: `LOGIN_USER` (default `admin`)
- Password: `LOGIN_PASSWORD` (default `admin`)

## PostgreSQL
- User: `DB_USER` (default `labuser`)
- Password: `DB_PASSWORD` (default `labpass`)

## Where to set overrides
- Copy `.env.example` to `.env` and change values.
- Or export environment variables before `make up`.

## Notes
- The repository ships a `.env` for local dev convenience; treat it as lab-only and replace values in real use.
- If `LAB_PASSWORD` is missing, `lab_compromised` will fail to start (entrypoint requires it).

## Environment variables

All variables are read from `.env` (copy `.env.example` to `.env` before first use).

| Variable | Required | Default | Description |
|---|---|---|---|
| `LAB_PASSWORD` | Yes | `adminadmin` | SSH password for `labuser` on `lab_compromised` |
| `RUN_ID` | No | auto-generated | Scopes output artifacts under `outputs/<RUN_ID>/` |
| `COMPOSE_PROJECT_NAME` | No | `lab` | Docker Compose project name prefix |
| `OPENCODE_API_KEY` | Yes (agents) | — | API key used by OpenCode-based agents |
| `OPENAI_API_KEY` | Yes (agents) | — | OpenAI API key for LLM-driven components |
| `OPENAI_BASE_URL` | No | OpenAI default | Custom base URL for OpenAI-compatible endpoints |
| `LLM_MODEL` | No | `gpt-4o-mini` | Model name passed to LLM calls |
| `DEFENDER_PORT` | No | `8000` | Host port for the SLIPS defender service |
| `PLANNER_PORT` | No | `1654` | Host port for the planner service |
| `PLANNER_URL` | No | `http://127.0.0.1:1654/plan` | Full URL the defender uses to reach the planner |
| `OPENCODE_TIMEOUT` | No | `450` | Timeout in seconds for OpenCode agent sessions |
| `LOGIN_USER` | No | `admin` | Username for the web login app on `lab_server` |
| `LOGIN_PASSWORD` | No | `admin` | Password for the web login app on `lab_server` |
| `DB_USER` | No | `labuser` | PostgreSQL user created on `lab_server` |
| `DB_PASSWORD` | No | `labpass` | PostgreSQL password on `lab_server` |

## Hardcoded credentials

The `lab_server` root SSH password (`admin123`) is set directly in
`images/server/Dockerfile` (line `echo 'root:admin123' | chpasswd`) and
**cannot** be overridden via `.env`. To change it, edit the Dockerfile and
rebuild the image with `make build`.
