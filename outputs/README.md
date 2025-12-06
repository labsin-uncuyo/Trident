# Outputs layout

All artifacts are scoped under `outputs/<RUN_ID>/` and mounted by the containers at runtime. By default the lab auto-generates `logs_<timestamp>` and reuses it until you bring the stack down.

## Directories

- `pcaps/` — Rotated captures from `lab_router` (and optional switch stream). SLIPS ingests files from here. If you copy in a new PCAP, SLIPS will process it automatically.
- `slips/` — Everything SLIPS writes per processed PCAP:
  - `<pcap>_<timestamp>/alerts.log|alerts.json` — alert lines for that PCAP.
  - `flows.sqlite`, `zeek_files/`, `slips.log`, `metadata/` — flow DB, Zeek logs, and run metadata.
  - `_watch_events/alerts.log` — internal watcher events (queueing/completed markers).
  - `defender_alerts.ndjson` — alert feed mirrored by the defender API.
- `aracne/` — ARACNE attacker telemetry:
  - `agent.log` — remote shell transcript (commands + stdout/stderr on the compromised host).
  - `context.log` — LLM prompt/response trace, plan updates, summaries.
  - `experiments/<timestamp_goal>/` — per-session snapshots with `experiment.log` plus copies of `agent.log` and `context.log` for that run.
- `ghosts/` — *(reserved; fill in with GHOSTS details)*.

## Notes

- Every container mounts `./outputs` to `/outputs`; paths above are workspace-relative.
- SLIPS alerts are duplicated: per-PCAP alert files live under `slips`, while the defender API mirrors all alerts into `slips/defender_alerts.ndjson`.
- Keep `RUN_ID` consistent across attacker/defender/router so logs line up; the default `logs_<timestamp>` is stored in `outputs/.current_run` until `make down`.
