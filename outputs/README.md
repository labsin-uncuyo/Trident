# Outputs layout

- `.current_run` – last RUN_ID written by `make up`; removed by `make down`.
- `<RUN_ID>/pcaps/` – router and mirror captures (`router.pcap`, `router_stream.pcap`, `switch_stream.pcap`, rotated `*.pcap*`).
- `<RUN_ID>/slips/` – defender artifacts:
  - `defender_alerts.ndjson` (FastAPI sink)
  - `<pcap>_timestamp*/alerts.log|alerts.json` from SLIPS runs
  - `_watch_events/alerts.log` sentinels from the watcher
- `<RUN_ID>/aracne/` – attacker logs (`agent.log`, `context.log`, `experiments/<timestamp_goal>/...`).
- `<RUN_ID>/ghosts/` – GHOSTS driver logs copied after runs.
- `<RUN_ID>/ghosts_logs/` – legacy/compat logs written by the compromised host (per-driver).
- `backups/john_scott/` – SSH key backups used by the compromised host setup.
