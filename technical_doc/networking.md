# Lab Networking Contract

This lab uses two Docker bridge networks with fixed CIDRs so the compose file can pin static IPs:

| Name       | Subnet         | Purpose                  |
|------------|----------------|--------------------------|
| lab_net_a  | 172.30.0.0/24  | Attacker/clients/defender|
| lab_net_b  | 172.31.0.0/24  | Server-side segment      |

Guidelines:
- Do **not** alter the CIDRs. The docker-compose file pins static IPs and the pytest suite validates those exact ranges.
- `make up` recreates the networks on each run, so concurrent stacks are not supported without changes.
- Verify their presence with `docker network inspect lab_net_a` and `docker network inspect lab_net_b`.
- Primary observation point for SLIPS: `lab_router` captures routed traffic to `outputs/<RUN_ID>/pcaps/router_*.pcap`, which the defender consumes via the shared dataset mount.
- Compromised and server containers install a default route via `lab_router` so north-south traffic traverses the router before reaching the host NAT.
- The router runs a DNS forwarder and the client/server containers use it as their resolver so DNS traffic shows up in router PCAPs.
- Host access to SSH/HTTP/Postgres is via router port-forwarding so connections traverse the router:
  - `172.30.0.1:22` → `lab_compromised:22`
  - `172.31.0.1:80` → `lab_server:80`
  - `172.31.0.1:5432` → `lab_server:5432`


Changing the subnetting requires updating docker-compose IP assignments, router rules, and the automated tests; such changes are outside the supported Phase-1 scope.

## Data Exfiltration Simulation

The lab includes a simulated data exfiltration setup that routes traffic to a fake public IP through the router for realistic PCAP captures.

### Fake Public IP

- **IP**: `137.184.126.86:443`
- **Purpose**: Simulates an external attacker receiving exfiltrated data
- **Implementation**: DNAT rule on router redirects traffic to local listener

### Traffic Flow

```
lab_server (172.31.0.10) → [route] → lab_router (172.31.0.1)
                                              ↓
                                        [DNAT rule]
                                              ↓
                                   137.184.126.86 → 172.31.0.1
                                              ↓
                                      netcat listener (port 443)
```

### Configuration Details

**Server Route** (`images/server/entrypoint.sh`):
```bash
ip route add 137.184.126.86 via 172.31.0.1 dev eth0
```

**Router DNAT** (`images/router/entrypoint.sh`):
```bash
iptables-legacy -t nat -A PREROUTING -d 137.184.126.86 -p tcp --dport 443 \
  -j DNAT --to-destination 172.31.0.1:443
```

**Router Listener**:
```bash
nc -lvnp 443 > /tmp/exfil/labdb_dump.sql
```

### Exfiltration Commands

See [data_exfiltration_simulation.md](./data_exfiltration_simulation.md) for complete documentation including:

- Multiple exfiltration methods (pg_dump, COPY PROGRAM, manual)
- Retrieving captured data
- PCAP analysis with tcpdump/Wireshark
- Verification and troubleshooting steps

### PCAP Analysis

Router PCAPs capture the exfiltration with the fake public IP as the destination:
- **Source**: `172.31.0.10` (server)
- **Destination**: `137.184.126.86:443` (fake external IP)
- **Location**: `/outputs/<RUN_ID>/pcaps/router_*.pcap`
