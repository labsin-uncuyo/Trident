# Lab Networking Contract

This lab expects two pre-created Docker bridge networks so that multiple stacks can coexist without Docker automatically provisioning overlapping CIDRs:

| Name       | Subnet         | Purpose                  |
|------------|----------------|--------------------------|
| lab_net_a  | 172.30.0.0/24  | Attacker/clients/defender|
| lab_net_b  | 172.31.0.0/24  | Server-side segment      |

Guidelines:
- Create them once via `./scripts/create_lab_networks.sh` (idempotent) before running `make up` or `make verify`.
- Do **not** alter the CIDRs. The docker-compose file pins static IPs and the pytest suite validates those exact ranges.
- Other local labs must reuse these external networks. Avoid creating additional networks with the same subnets—use `./scripts/cleanup_conflicting_networks.sh` to prune leftovers from older stacks.
- When troubleshooting, verify their presence with `docker network inspect lab_net_a` and `docker network inspect lab_net_b`.
- Primary observation point for SLIPS: `lab_server` captures its own traffic to `outputs/<RUN_ID>/pcaps/server.pcap`, which the defender consumes via the shared dataset mount.

Changing the subnetting requires updating docker-compose IP assignments, router rules, and the automated tests; such changes are outside the supported Phase-1 scope.

## Data Exfiltration Simulation

The lab includes a simulated data exfiltration setup that routes traffic to a fake public IP through the router for realistic PCAP captures.

### Fake Public IP

- **IP**: `137.184.126.86:8000`
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
                                      netcat listener (port 8000)
```

### Configuration Details

**Server Route** (`images/server/entrypoint.sh`):
```bash
ip route add 137.184.126.86 via 172.31.0.1 dev eth0
```

**Router DNAT** (`images/router/entrypoint.sh`):
```bash
iptables-legacy -t nat -A PREROUTING -d 137.184.126.86 -p tcp --dport 8000 \
  -j DNAT --to-destination 172.31.0.1:8000
```

**Router Listener**:
```bash
nc -lvnp 8000 > /tmp/exfil/labdb_dump.sql
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
- **Destination**: `137.184.126.86:8000` (fake external IP)
- **Location**: `/outputs/<RUN_ID>/pcaps/router_*.pccap`
