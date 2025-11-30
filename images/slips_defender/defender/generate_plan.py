#!/usr/bin/env python3

from app.planner import IncidentPlanner

# The alerts
alert = """2024/01/15 10:30:45.123456+0000 (TW 1): Src IP 172.30.0.10             . Detected Horizontal port scan to port Secure Shell (SSH) Protocol 22/TCP. From 172.30.0.10 to 5 unique destination IPs. Total packets sent: 25. Confidence: 0.8. by Slips threat level: high.
2024/01/15 10:32:18.654321+0000 (TW 1): Src IP 172.30.0.10             . Detected SSH password guessing to IP 172.31.0.10. Detected by Slips threat level: high."""

planner = IncidentPlanner()
result = planner.plan(alert)

import json
print(json.dumps(result, indent=2))