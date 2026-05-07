# LLM Proxy Setup

The LLM proxy is located at `/home/diego/Trident/external/aracne/infra/`.

## Starting the LLM Proxy

```bash
cd /home/diego/Trident/external/aracne/infra
docker compose --profile core up -d
```

## Services

- **proxy**: Port 8080 - Main LLM proxy endpoint
- **worker**: Internal worker (port 8081)
- **dashboard**: Port 8082 - Admin dashboard
- **postgres**: TimescaleDB for metrics
- **redis**: Queue/storage
- **migrations**: Database setup

## Networks

- **edge_net**: External access (proxy exposed here)
- **data_net**: Internal data layer
- **obs_net**: Observability (Prometheus, Grafana)

## Environment Variables (in .env)

- `UPSTREAM_BASE_URL`: The actual LLM API endpoint
- `UI_ENABLED`: Enable/disable UI
- `DB_NAME`, `DB_USER`: Database config
- Keys and secrets in `./secrets/` directory

## Accessing from Trident containers

The proxy runs on `10.0.0.49:8080` (host IP). Trident containers access it via:
- `OPENAI_BASE_URL=http://host-internal:8080/p/diego/v1` (container)
- `HOST_INTERNAL_IP=10.0.0.49` (maps host-internal to host IP)

## Stopping

```bash
docker compose --profile core down
```
