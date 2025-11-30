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
