# Setup & Architecture

## System Architecture

```
┌─────────────────────────────────────────────────────────────┐
│  Lab Infrastructure (make up)                               │
├─────────────────────────────────────────────────────────────┤
│  lab_router (172.30.0.1, 172.31.0.1)                       │
│  lab_server (172.31.0.10) - PostgreSQL:5432, HTTP:8080     │
│  lab_compromised (172.30.0.10) - SSH:2223                  │
└─────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────┐
│  GHOSTS Driver (./start_ghosts.sh)                         │
├─────────────────────────────────────────────────────────────┤
│  lab_ghosts_driver (172.30.0.20)                           │
│    ├─ Connects to lab_compromised via SSH                  │
│    ├─ Executes SQL queries as john_scott user              │
│    └─ Logs to /outputs/$RUN_ID/ghosts/                     │
└─────────────────────────────────────────────────────────────┘
                            ↓ (if shadows mode)
┌─────────────────────────────────────────────────────────────┐
│  Shadows API (optional, started by start_ghosts.sh)        │
├─────────────────────────────────────────────────────────────┤
│  ghosts-shadows (5900) - API for LLM query generation      │
│  ghosts-postgres (5433) - GHOSTS database                  │
│  ghosts-grafana (3000) - Metrics dashboard                 │
└─────────────────────────────────────────────────────────────┘
```

## Port Mapping

### Lab Infrastructure
- 8080 - lab_server HTTP
- 5432 - lab_server PostgreSQL
- 2223 - lab_compromised SSH

### GHOSTS Infrastructure (when using shadows mode)
- 5900 - Shadows API
- 7860 - Shadows Gradio UI
- 5433 - GHOSTS PostgreSQL
- 3000 - Grafana

### Not Working (ARM64 incompatibility)
- 8081 - GHOSTS UI (AMD64 image)
- 5000 - GHOSTS API (AMD64 image)

## File Structure

```
images/ghosts_driver/
├── README.md                           # This file
├── SETUP.md                            # Architecture & setup
├── docker-compose-ghosts-api.yml       # Shadows API infrastructure
├── entrypoint.sh                       # Container startup logic
├── Dockerfile                          # Image definition
├── start_ghosts_api.sh                 # Start Shadows services
├── stop_ghosts_api.sh                  # Stop Shadows services
├── test_shadows_api.sh                 # Test Shadows endpoints
├── verify_setup.sh                     # Installation verification
├── ghosts_api_config/
│   └── appsettings.json                # GHOSTS API config
├── john_scott_llm/
│   ├── timeline_john_scott_llm.json    # Static timeline (10 commands)
│   ├── application_llm.json            # LLM mode config
│   ├── application_shadows.json        # Shadows mode config
│   ├── generate_timeline_john_scott.sh # Timeline generator (llm_v2)
│   └── generate_queries_shadows.sh     # Query generator (shadows)
└── shadows_openai_adapter/
    ├── Dockerfile                      # Custom Shadows container
    ├── src/api.py                      # Modified for OpenAI
    └── src/requirements.txt            # Fixed dependencies
```

## Environment Variables

Required in `/home/shared/Trident/.env`:
```bash
# OpenAI API Configuration
OPENAI_API_KEY=sk-...
OPENAI_BASE_URL=https://chat.ai.e-infra.cz/api/
LLM_MODEL=qwen3-coder

# Lab Credentials
LAB_PASSWORD=adminadmin
```

## First-Time Setup

```bash
cd /home/shared/Trident/images/ghosts_driver

# 1. Verify configuration
./verify_setup.sh

# 2. (Optional) Start Shadows API
./start_ghosts_api.sh

# 3. Test Shadows (if started)
./test_shadows_api.sh

# 4. Return to root and start lab
cd /home/shared/Trident
make up

# 5. Start John Scott
export GHOSTS_MODE=shadows
export RUN_ID="test_$(date +%Y%m%d_%H%M%S)"
./start_ghosts.sh
```

## How It Works

1. **Lab Infrastructure** - Core network services (router, server, compromised host)
2. **GHOSTS Driver** - Container running GHOSTS client with John Scott's timeline
3. **Entrypoint Logic** - Selects mode (shadows/llm_v2/dummy), checks dependencies, starts client
4. **Timeline Execution** - GHOSTS client executes commands from timeline.json with delays
5. **SSH + SQL** - Commands SSH to compromised host, then execute psql queries
6. **Logging** - All activity logged to `/outputs/$RUN_ID/ghosts/`

## Key Fixes Applied

1. **JSON Timeline** - Removed double commas in static template
2. **envsubst** - Limited to `$SSH_*` variables only (preserves SQL `$$` quotes)
3. **Dependencies** - Created `start_ghosts.sh` with proper profile handling
4. **Image Rebuild** - Used `--no-cache` to ensure fixes applied

## Security Notes

- **Never commit `.env`** - Contains API keys
- **`.env` in .gitignore** - Already configured
- **Shared credentials** - LAB_PASSWORD used for SSH and database
- **Read-only queries** - John Scott only performs SELECT statements
