# GHOSTS Driver - John Scott NPC

John Scott is a benign NPC simulating a senior developer performing normal database work activities using the GHOSTS framework.

## Quick Start

```bash
cd /home/shared/Trident

# 1. Start lab infrastructure
make up

# 2. Start John Scott
export GHOSTS_MODE=shadows
export RUN_ID="test_$(date +%Y%m%d_%H%M%S)"
./start_ghosts.sh

# 3. Monitor activity
docker compose logs -f ghosts_driver
```

## GHOSTS Mode

John Scott uses **`shadows`** mode - GHOSTS native Shadows API for LLM-based query generation.

If Shadows API is unavailable, falls back to static timeline.

## What John Scott Does

Simulates realistic developer activities:
- Connects via SSH to compromised host (172.30.0.10:2223)
- Queries PostgreSQL database (172.31.0.10:5432) as `john_scott` user
- Performs typical developer tasks: schema exploration, employee queries, salary analysis
- Generates benign traffic for lab baseline

## Configuration

All settings in `/home/shared/Trident/.env`:
```
OPENAI_API_KEY=your_key
OPENAI_BASE_URL=https://chat.ai.e-infra.cz/api/
LLM_MODEL=qwen3-coder
LAB_PASSWORD=adminadmin
```

## Scripts

- `start_ghosts_api.sh` - Start Shadows API infrastructure
- `stop_ghosts_api.sh` - Stop Shadows API infrastructure  
- `test_shadows_api.sh` - Test Shadows API endpoints
- `verify_setup.sh` - Verify complete setup

## Troubleshooting

**Timeline JSON errors**: Fixed - static timeline validated  
**envsubst breaking SQL**: Fixed - only SSH variables expanded  
**Service dependencies**: Use `./start_ghosts.sh` (not direct docker compose)  
**Shadows API unavailable**: Falls back to static timeline automatically

## Logs

Activity logs saved to: `/home/shared/Trident/outputs/$RUN_ID/ghosts/`
