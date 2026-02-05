# Topologies

Trident currently ships a single built-in topology defined in `docker-compose.yml` at the repo root.

## Default topology (core)
- `lab_net_a` (172.30.0.0/24): compromised side.
- `lab_net_b` (172.31.0.0/24): server side.
- `lab_router` routes between the two networks and captures PCAPs.

To start the default topology:
```bash
make up
```
