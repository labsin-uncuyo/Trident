# SLIPS Pipeline (Trident Lab)

## What runs
- Core modules enabled: arp, flow_alerts, http_analyzer, ip_info, network_discovery, riskiq, evidence/profiler/input processes.
- Disabled to keep runs fast/stable: rnn_cc_detection, flowmldetection, threat_intelligence, update_manager, virustotal, timeline, blocking, template.

## Capture & ingest flow
- Router tcpdump rotates every 30s (`images/router/entrypoint.sh`), writing `router_*.pcap` to `outputs/<RUN_ID>/pcaps` (mounted as `/StratosphereLinuxIPS/dataset`).
- Watcher (`watch_pcaps.py`) polls every 5s, ignores live stream files, and processes only completed rotated PCAPs.
- Per-PCAP processing timeout: 60s. If exceeded, the run is marked timed out and the watcher moves on.
- SLIPS outputs per PCAP land in `outputs/<RUN_ID>/slips_output/<pcap_ts>/` (alerts.log/json, zeek_files, flows.sqlite, errors.log, etc.), with sentinels in `_watch_events/alerts.log`.

## Zeek preprocessing settings (`images/slips_defender/slips.yaml`)
- `pcapfilter`: `not port 5353 and not port 67 and not port 68` (keeps ICMP/ARP; avoids link-layer multicast/broadcast keywords that break on SLL captures).
- `tcp_inactivity_timeout`: 1 minute (speeds tiny rotations).

## Fixed defaults (no env overrides)
- Dataset/output paths: `/StratosphereLinuxIPS/dataset` and `/StratosphereLinuxIPS/output`.
- Watcher: poll 5s, no stream snapshots, 60s per-PCAP timeout.
- Router rotation: 30s.

## If you change things
- To re-enable heavy modules, edit `modules.disable` in `images/slips_defender/slips.yaml`.
- For different rotation or timeouts, edit `entrypoint.sh` (router) or `watch_pcaps.py` and rebuild/recreate `router` and `slips_defender`.
