# Topologies

Trident currently ships a single built-in topology defined in `docker-compose.yml` at the repo root. The topology models a small enterprise network where a compromised client can reach a protected server only through a router that captures all traffic.

To start the default topology:
```bash
make up
```

## Networks

The lab declares four Docker networks. Three carry lab traffic; the fourth is used only by the dashboard.

### lab_net_a -- 172.30.0.0/24 (compromised side)

The "untrusted" segment. The compromised host lives here and must traverse the router to reach anything on lab_net_b. Declared with `internal: true` in Compose, so containers on this network have no direct path to the host or the internet.

### lab_net_b -- 172.31.0.0/24 (server side)

The "trusted" segment. The server and any attacker agents that need direct access to the server-side subnet are placed here. Also declared `internal: true` -- no host or internet access.

### lab_egress -- 172.32.0.0/24 (outbound access)

A non-internal bridge network that provides internet connectivity through the host. Only the router and the SLIPS defender are attached to it. All other containers have no routes into lab_egress and therefore cannot reach the internet on their own. The router uses this network when it needs to resolve external DNS or pull updates.

### dashboard_net (lab_dashboard_net)

An isolated bridge network used exclusively by the dashboard container. It has no fixed IPAM configuration and is not part of the lab traffic path.

## Gateway addresses

Each lab network has its Docker bridge gateway set to the `.254` address in its subnet (for example, 172.30.0.254 for lab_net_a). These are the default gateways Docker assigns to the bridge interface on the host side.

Containers that need to route through the lab router override their default route at startup so that traffic flows through the `.1` address (the router) instead of the `.254` bridge gateway. This is what forces all inter-segment traffic through the router for capture.

## IP assignment table

| Container              | Network      | IP address    | Notes                              |
|------------------------|--------------|---------------|------------------------------------|
| lab_router             | lab_net_a    | 172.30.0.1    | Gateway for compromised side       |
| lab_router             | lab_net_b    | 172.31.0.1    | Gateway for server side            |
| lab_router             | lab_egress   | 172.32.0.1    | Outbound internet access           |
| lab_compromised        | lab_net_a    | 172.30.0.10   | DNS set to 172.30.0.1              |
| lab_server             | lab_net_b    | 172.31.0.10   | DNS set to 172.31.0.1              |
| lab_slips_defender     | lab_net_a    | 172.30.0.30   | IDS visibility into compromised side |
| lab_slips_defender     | lab_net_b    | 172.31.0.30   | IDS visibility into server side    |
| lab_slips_defender     | lab_egress   | DHCP          | Outbound access for threat intel   |
| lab_aracne_attacker    | lab_net_b    | 172.31.0.50   | DNS set to 172.31.0.1              |
| lab_dashboard          | dashboard_net| DHCP          | Exposed on host port 8081          |

## Compose profiles

Not every container starts by default. Containers are grouped into profiles:

- **core** (`make up`): router, server, compromised, dashboard.
- **defender** (`make defend`): slips_defender. Runs after core is healthy.
- **attackers** (`make aracne`): aracne_attacker. Depends on compromised being healthy.

## Subnet conflict note

The lab reserves 172.30.0.0/24, 172.31.0.0/24, and 172.32.0.0/24 for its three networks. If any of these subnets overlap with an existing Docker network on your host (or with a VPN/corporate route), `make up` will fail with an address-pool or subnet-conflict error.

To check for conflicts before starting the lab:
```bash
docker network ls
docker network inspect <network_name> | grep Subnet
```

If a conflict exists, either remove the conflicting Docker network or edit the `ipam` blocks in `docker-compose.yml` to use a different private range. Remember to update the static IP assignments for every container if you change a subnet.
