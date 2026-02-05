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
