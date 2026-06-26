# Local LLM Setup Guide (qwen3.5:9b)

This guide explains how to set up Trident to run the benign agent (db_admin) with a local LLM (qwen3.5:9b) using Ollama on a different machine.

---

## Prerequisites

### Hardware
- **NVIDIA GPU** with at least 8GB VRAM (qwen3.5:9b needs ~6.6GB)
- **NVIDIA drivers** installed on the host
- **nvidia-container-toolkit** installed

### Software
- Docker with compose plugin
- Git (to clone the Trident repo)

---

## Step-by-Step Setup

### 1. Install NVIDIA Container Toolkit

```bash
# Add NVIDIA repository
distribution=$(. /etc/os-release;echo $ID$VERSION_ID)
curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey | sudo gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg
curl -s -L https://nvidia.github.io/libnvidia-container/$distribution/libnvidia-container.list | \
  sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' | \
  sudo tee /etc/apt/sources.list.d/nvidia-container-toolkit.list

# Install
sudo apt-get update
sudo apt-get install -y nvidia-container-toolkit

# Configure Docker
sudo nvidia-ctk runtime configure --runtime=docker
sudo systemctl restart docker
```

### 2. Start Ollama Container with GPU

```bash
# Create volume for model storage
docker volume create ollama

# Run Ollama with GPU access
docker run -d \
  --gpus all \
  --name ollama \
  -v ollama:/root/.ollama \
  -p 11435:11434 \
  ollama/ollama

# Verify GPU access
docker exec ollama nvidia-smi
# Should show your GPU and ollama process
```

### 3. Pull and Configure the Model

```bash
# Pull qwen3.5:9b
docker exec ollama ollama pull qwen3.5:9b

# Create model with larger context window (required for the agent prompt)
docker exec ollama bash -c 'printf "FROM qwen3.5:9b\nPARAMETER num_ctx 32768\n" > /tmp/Modelfile && ollama create qwen3.5:9b -f /tmp/Modelfile'

# Verify
docker exec ollama ollama list
# Should show: qwen3.5:9b  ~6.6 GB
```

### 4. Clone Trident and Configure

```bash
git clone <trident-repo-url> Trident
cd Trident
```

### 5. Configure `.env`

Edit `.env` with these settings:

```bash
# Enable Ollama
OLLAMA_ENABLED=true
OLLAMA_BASE_URL=http://host.docker.internal:11435/v1
OLLAMA_MODEL=qwen3.5:9b
OLLAMA_API_KEY=ollama
BENIGN_USE_OLLAMA=true

# API provider (still needed for other agents)
LLM_API_KEY=your-api-key-here
LLM_BASE_URL=https://api.openai.com/v1
PROVIDER_NAME=openai
LLM_MODEL=gpt-4o
```

### 6. Key Files (Already in Repo)

These files are already present in the Trident repository and work with qwen3.5:9b:

| File | Purpose |
|------|---------|
| `images/compromised/ollama_proxy.py` | Translates OpenCode requests to Ollama native API, injects tool definitions |
| `images/compromised/entrypoint.sh` | Starts proxy, configures OpenCode with Ollama provider |
| `images/compromised/run_benign_experiments.py` | Runs multiple benign agent experiments |
| `images/compromised/db_admin_opencode_client.py` | Client that drives the db_admin agent |

### 7. Build and Start

```bash
make build    # Rebuild images with new config
make up       # Start all containers
```

### 8. Verify Setup

```bash
# Check proxy is running
docker exec lab_compromised curl -sf http://127.0.0.1:11434/health
# Should return: {"status":"ok","proxy":"ollama-native"}

# Check model is reachable
docker exec lab_compromised curl -s http://127.0.0.1:11434/api/chat \
  -H "Content-Type: application/json" \
  -d '{"model":"qwen3.5:9b","messages":[{"role":"user","content":"Run ls /tmp"}],"stream":false}' \
  | python3 -m json.tool
# Should return a response with tool_calls

# Check GPU usage during inference
nvidia-smi
# Should show ollama process using ~12GB VRAM during inference
```

### 9. Run Experiments

```bash
# Run 3 benign agent experiments
python3 images/compromised/run_benign_experiments.py 3

# Results saved to outputs/experiment_*/benign_agent/
```

---

## What the Proxy Does

The `ollama_proxy.py` is critical because:

1. **Tool injection**: OpenCode's `@ai-sdk/openai-compatible` adapter doesn't send tool definitions to custom baseURLs. The proxy injects bash/edit/write tool definitions.

2. **Format translation**: Converts OpenAI-format messages (string tool_call arguments) to Ollama native format (object arguments).

3. **SSE streaming**: Converts non-streaming Ollama responses to SSE format that OpenCode expects.

4. **Context window**: Sets `num_ctx=32768` to prevent prompt truncation.

---

## Troubleshooting

| Problem | Solution |
|---------|----------|
| `docker exec ollama nvidia-smi` shows no GPU | Recreate container with `--gpus all` |
| Proxy health check fails | Check `docker logs lab_compromised \| grep ollama` |
| Agent produces no tool calls | Verify model is pulled: `docker exec ollama ollama list` |
| Slow inference (>30s per request) | GPU not being used; check `nvidia-smi` on host |
| Agent connects but no SQL executed | Model may not understand `-c` flag; try larger model |

---

## Expected Results

With qwen3.5:9b, you should see:
- **20-35 tool calls** per run
- **15-30 SQL queries** with proper `-c` syntax
- **2-8 minute** run durations
- Real database operations (INSERT, SELECT, UPDATE)
- PostgreSQL logs showing `labuser@labdb` connections

---

## Comparison: mistral-nemo vs qwen3.5:9b

Based on testing in this repository:

| Model | Duration | Tool Calls | SQL Queries | DB Connected? |
|-------|----------|------------|-------------|---------------|
| mistral-nemo | 21-33s | 7-15 | 0-3 (failed) | No |
| **qwen3.5:9b** | **2-8 min** | **15-35** | **12-30** | **Yes** |

qwen3.5:9b correctly uses `psql -c '<SQL>'` instead of opening interactive sessions, enabling real database operations.

---

## Additional Notes

- The Ollama container must be started with `--gpus all` for GPU-accelerated inference (CPU inference takes 107s vs 7s on GPU per request)
- The `num_ctx=32768` parameter is preserved in the `ollama` Docker volume across container recreations
- The proxy runs inside `lab_compromised` and is started by `entrypoint.sh`
- Only the benign agent (db_admin) uses Ollama; other agents continue using the API provider
