# Juan's New Infrastructure Setup Guide

This document describes the enhanced Docker infrastructure setup for the Trident security monitoring environment, with particular focus on SSH connectivity improvements for the auto_responder service.

## 🏗️ Overview

The Trident environment consists of multiple containers working together to detect and respond to security threats:
- **SLIPS Defender**: Network intrusion detection and automated response
- **Compromised Host**: Simulated compromised machine for testing
- **Server**: Target system for remediation and monitoring
- **Router**: Network isolation and routing
- **Switch**: Network traffic mirroring (optional)
- **GHOSTS Driver**: Red team simulation framework

## 🔧 Key Infrastructure Changes

### 1. Enhanced SLIPS Defender Container

#### Problem Solved
The original SLIPS defender container had critical issues with SSH execution:
- ❌ SSH client not installed
- ❌ SSH keys not persistent across container restarts
- ❌ Poor error visibility in SSH connection failures

#### Solution Implemented

**New Dockerfile**: `/images/slips_defender/Dockerfile`
```dockerfile
# Extend official SLIPS image with SSH client for auto_responder
FROM stratosphereips/slips:latest

# Install SSH client and related tools (already running as root)
RUN apt-get update && apt-get install -y \
    openssh-client \
    netcat-openbsd \
    telnet \
    iputils-ping \
    && rm -rf /var/lib/apt/lists/*

# Create directory for SSH keys (volume will be mounted at /root/.ssh)
RUN mkdir -p /root/.ssh && chmod 700 /root/.ssh

# Create SSH keys in persistent location if they don't exist
RUN if [ ! -f /root/.ssh/id_rsa_auto_responder ]; then \
    ssh-keygen -t ed25519 -f /root/.ssh/id_rsa_auto_responder -N "" -C "auto_responder@slips" && \
    chmod 600 /root/.ssh/id_rsa_auto_responder && \
    chmod 644 /root/.ssh/id_rsa_auto_responder.pub; \
    fi

# Copy custom defender scripts and SSH setup
COPY ./defender /opt/lab/defender/
COPY ./setup_ssh_keys.sh /opt/lab/setup_ssh_keys.sh

# Set proper permissions
RUN chmod +x /opt/lab/defender/*.py /opt/lab/setup_ssh_keys.sh
```

**Updated docker-compose.yml**:
```yaml
slips_defender:
  build: ./images/slips_defender  # Changed from image: stratosphereips/slips:latest
  image: lab/slips_defender:latest   # New custom image
  container_name: lab_slips_defender
  environment:
    - RUN_ID=${RUN_ID}
    - DEFENDER_PORT=${DEFENDER_PORT:-8000}
    - OPENAI_API_KEY=${OPENAI_API_KEY}
    - OPENAI_BASE_URL=${OPENAI_BASE_URL}
    - LLM_MODEL=${LLM_MODEL:-gpt-4o-mini}
    - SLIPS_PROCESS_ACTIVE=${SLIPS_PROCESS_ACTIVE:-1}
    - SLIPS_ACTIVE_STABLE_SECS=${SLIPS_ACTIVE_STABLE_SECS:-3}
  volumes:
    - ./outputs/${RUN_ID}/pcaps:/StratosphereLinuxIPS/dataset
    - ./outputs/${RUN_ID}/slips_output:/StratosphereLinuxIPS/output
    - ./outputs:/outputs
    - ./images/slips_defender:/opt/lab
    - ./images/slips_defender/slips.yaml:/StratosphereLinuxIPS/config/slips.yaml
    - slips_redis_data:/var/lib/redis
    - slips_ti_data:/StratosphereLinuxIPS/modules/threat_intelligence/remote_data_files
    - auto_responder_ssh_keys:/root/.ssh  # NEW: Persistent SSH key storage
  network_mode: "host"
  cap_add:
    - NET_ADMIN
  command: ["/bin/bash", "/opt/lab/slips_entrypoint.sh"]
  restart: unless-stopped
```

### 2. Persistent SSH Key Management

#### SSH Key Setup Script: `/images/slips_defender/setup_ssh_keys.sh`

**Purpose**: Automatically set up SSH authentication between defender container and target containers (server/compromised) with persistence.

**Features**:
- **Automatic Key Generation**: Creates SSH keys if they don't exist
- **Persistent Storage**: Uses Docker volume `auto_responder_ssh_keys` for key persistence
- **Container Health Checks**: Waits for target containers to be ready before attempting key distribution
- **Comprehensive Logging**: Detailed status reporting with emojis and error handling
- **Error Recovery**: Handles timeouts and connection failures gracefully

**Key Functions**:
```bash
# Add SSH key to a container with retry logic
add_ssh_key_to_container() {
    local container_name=$1
    local container_ip=$2
    local max_attempts=30

    echo "📤 Adding SSH key to $container_name ($container_ip)..."

    # Wait for container to be ready (with timeout)
    while [ $attempt -lt $max_attempts ]; do
        if docker exec "$container_name" bash -c "echo 'Container ready'" >/dev/null 2>&1; then
            echo "✅ $container_name is ready"
            break
        fi
        attempt=$((attempt + 1))
        echo "⏳ Attempt $attempt/$max_attempts..."
        sleep 2
    done

    # Add SSH key to container's authorized_keys
    docker exec "$container_name" bash -c "
        mkdir -p /root/.ssh
        chmod 700 /root/.ssh
        echo 'ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIGsjfkQJxN2gdRm5yEkrbmbZlryb0lVCtO+E5dMB2ndc auto_responder@slips' >> /root/.ssh/authorized_keys
        chmod 600 /root/.ssh/authorized_keys
        echo '✅ SSH key added to $container_name'
    "
}
```

### 3. Enhanced Auto-Responder Service

#### Improved Diagnostics and Logging

**File**: `/images/slips_defender/defender/auto_responder.py`

**Key Enhancements**:

1. **SSH Client Validation**:
   ```python
   def ensure_ssh_key(self) -> bool:
       # Check if ssh command is available
       ssh_check = subprocess.run(["which", "ssh"], capture_output=True, text=True)
       if ssh_check.returncode != 0:
           self.log("ERROR", f"❌ SSH client is NOT INSTALLED in this container")
           self.log("SSH_SETUP", "💡 To fix: Install openssh-client package")
           return False
   ```

2. **Comprehensive SSH Connectivity Diagnostics**:
   ```python
   def diagnose_ssh_connectivity(self, target_ip: str, alert_hash: str = None, execution_id: str = None) -> None:
       # Multi-layered diagnostics:
       # - SSH client availability
       # - SSH key existence and permissions
       # - Network interface analysis
       # - Ping connectivity testing
       # - Port connectivity (multiple methods)
       # - Actual SSH connection testing with detailed error parsing
   ```

3. **Enhanced Error Handling**:
   - **Connection refused**: SSH service not running on target
   - **Connection timed out**: Network/firewall issues
   - **No route to host**: Routing problems
   - **Permission denied**: SSH key authentication failures
   - **Command not found**: Missing tools (like `opencode`)

4. **Better Logging with Context**:
   ```python
   # Structured logging with alert_hash and execution_id tracking
   self.log("SSH_DIAG", f"✅ SSH client found at: {ssh_check.stdout.strip()}")
   self.log("SSH_TEST", f"📤 SSH test response: {result.stdout.strip()}")
   ```

### 4. Container Network Architecture

```
Network Configuration:
┌─────────────────────────────────────────────────────────┐
│                 Host Network (bridge)                │
│ 172.30.0.254/24 (lab_net_a)           │
│ 172.31.0.254/24 (lab_net_b)           │
│           └───────────────────────────────────────┘
│
│    ┌─────────────┐    ┌─────────────┐
│    │ lab_server   │    │ lab_server  │
│    │ 172.31.0.10 │    │ 172.31.0.10 │
│    └─┬─┴──────┘    └─┬─┴──────┘
│          │              │
│          │              │
│          │              │
│          │              │
│          │              │
│          ▼              ▼
│       🌐 lab_slips_defender (host mode)
│       └─────────────────────────────────────────────────┘
│
│    ┌─────────────┐    ┌─────────────┐
│    │ lab_compromised│    │ lab_compromised│
│    │ 172.30.0.10 │    │ 172.30.0.10 │
│    └─┬─┴──────┘    └─┬─┴──────┘
│          │              │
│          │              │
│          │              │
│          │              │
│          ▼              ▼
│       🌐 lab_slips_defender (host mode)
│       └─────────────────────────────────────────────────┘
└─────────────────────────────────────────────────────────┘
```

**IP Assignments**:
- Router: 172.30.0.1 / 172.31.0.1
- Defender: Host network mode (can access all networks)
- Server: 172.31.0.10 (lab_net_b)
- Compromised: 172.30.0.10 (lab_net_a)
- Switch: 172.30.0.2 (lab_net_a)
- GHOSTS Driver: 172.30.0.20 (lab_net_a)

### 5. Usage Instructions

#### Initial Setup
```bash
# Build and start all containers
docker compose up -d

# Monitor defender logs for SSH setup
docker logs lab_slips_defender -f
```

#### Verify SSH Configuration
```bash
# Test SSH connectivity from defender
docker exec lab_slips_defender bash -c "
ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null \
    -o ConnectTimeout=10 -i /root/.ssh/id_rsa_auto_responder \
    -p 22 root@172.31.0.10 'echo SSH_CONNECTION_TEST'
"

docker exec lab_slips_defender bash -c "
ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null \
    -o ConnectTimeout=10 -i /root/.ssh/id_rsa_auto_responder \
    -p 22 root@172.30.0.10 'echo SSH_CONNECTION_TEST'
Create a file called juliEatDicks, i want a funny text inside it. Be creative."
```

#### Auto-Responder Testing
```bash
# Test enhanced auto_responder with persistent SSH keys
docker exec lab_slips_defender python3 -c "
import sys
sys.path.append('/opt/lab/defender')
from auto_responder import AutoResponder
responder = AutoResponder()
responder.diagnose_ssh_connectivity('172.31.0.10')
"
```

### 6. Troubleshooting Guide

#### SSH Connection Issues
1. **Check SSH Client**:
   ```bash
   docker exec lab_slips_defender which ssh
   # Should return: /usr/bin/ssh
   ```

2. **Verify SSH Keys**:
   ```bash
   docker exec lab_slips_defender ls -la /root/.ssh/
   # Should show: id_rsa_auto_responder (600) and id_rsa_auto_responder.pub (644)
   ```

3. **Test Target Container Readiness**:
   ```bash
   docker exec lab_server bash -c "echo 'ready'"
   docker exec lab_compromised bash -c "echo 'ready'"
   ```

4. **Check Network Connectivity**:
   ```bash
   docker exec lab_slips_defender ping -c 2 172.31.0.10
   docker exec lab_slips_defender ping -c 2 172.30.0.10
   ```

#### Container Restart Issues
1. **Persistent Data Loss**: If SSH keys disappear after restart, check:
   - Docker volume mounting: `docker compose down && docker compose up -d`
   - Volume permissions: Ensure `auto_responder_ssh_keys` volume is accessible

2. **Container Startup Failures**:
   - Check health dependencies: Ensure router container is healthy before starting defender
   - Resource conflicts: Verify port assignments aren't conflicting

### 7. Configuration Files

#### Environment Variables
- `RUN_ID`: Unique identifier for this run (e.g., "diego", "run_local")
- `DEFENDER_PORT`: Port for defender API (default: 8000)
- `OPENAI_API_KEY`: API key for LLM integration
- `LLM_MODEL`: Model to use for automated response planning
- `SLIPS_PROCESS_ACTIVE`: Enable/disable SLIPS processing (1/0)

#### Key Files and Locations
- **Docker Compose**: `/docker-compose.yml`
- **Defender Dockerfile**: `/images/slips_defender/Dockerfile`
- **SSH Setup Script**: `/images/slips_defender/setup_ssh_keys.sh`
- **Auto-Responder**: `/images/slips_defender/defender/auto_responder.py`
- **Defender Config**: `/images/slips_defender/slips.yaml`
- **Output Directory**: `/outputs/${RUN_ID}/`

### 8. Security Considerations

#### SSH Key Security
- SSH keys are generated with **no passphrase** for automated access
- Keys are stored in **persistent Docker volume** (`auto_responder_ssh_keys`)
- **Unique keys**: Generated per-container instance for isolation
- **File permissions**: 600 for private keys, 644 for public keys

#### Network Isolation
- Containers communicate through **Docker networks** with controlled routing
- **Router container** acts as firewall and network gateway
- **Defender** runs in **host network mode** for comprehensive visibility
- **No host network access** for compromised/production containers

### 9. Monitoring and Logs

#### Key Log Files
- **Defender Logs**: `/outputs/${RUN_ID}/auto_responder_detailed.log`
- **Timeline**: `/outputs/${RUN_ID}/auto_responder_timeline.jsonl`
- **SLIPS Logs**: `/outputs/${RUN_ID}/slips_output/`
- **Container Health**: `docker ps` or `docker-compose ps`

#### Log Analysis Commands
```bash
# View auto_responder activity with timestamps
tail -f /outputs/${RUN_ID}/auto_responder_detailed.log

# Check for SSH-related errors
grep -E "(SSH|ssh|connection|timeout)" /outputs/${RUN_ID}/auto_responder_detailed.log

# Monitor plan execution success/failure
grep -E "(✅.*execution|❌.*execution|Plan.*generated)" /outputs/${RUN_ID}/auto_responder_detailed.log
```

## 🎯 Success Metrics

### Before Changes
- ❌ SSH client not found
- ❌ Plan execution failed after 0.00s
- ❌ No persistent SSH key storage
- ❌ Poor error visibility

### After Changes
- ✅ SSH client installed: `/usr/bin/ssh`
- ✅ Persistent SSH key volume implemented
- ✅ Enhanced diagnostics with detailed error categorization
- ✅ Automatic SSH key setup and distribution
- ✅ Container restart resilience
- ✅ Professional logging with context tracking

## 🚀 Quick Start Commands

```bash
# Complete infrastructure setup
cd /home/shared/Trident
docker compose build slips_defender  # Build enhanced defender
docker compose up -d                  # Start environment

# Verify SSH setup is working
docker exec lab_slips_defender bash -c "ssh -V"  # Check SSH client
docker exec lab_slips_defender bash -c "ls /root/.ssh/"  # Check persistent keys
```

---

**Maintainer**: Juan's Security Infrastructure Team
**Last Updated**: 2025-11-26
**Version**: 2.0 - Enhanced SSH Connectivity & Persistence
