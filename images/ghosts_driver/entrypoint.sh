#!/bin/bash
set -e

echo "=== GHOSTS Driver Starting ==="

# Determine mode (default: dummy)
MODE="${JOHN_SCOTT_MODE:-dummy}"
echo "John Scott Mode: $MODE"

# Verify SSH key exists
if [ ! -f /root/.ssh/id_rsa ]; then
    echo "✗ SSH private key not found at /root/.ssh/id_rsa"
    exit 1
fi
echo "✓ SSH private key configured"

# Setup timeline based on mode
if [ "$MODE" = "llm" ]; then
    echo "=== LLM Mode: Generating dynamic timeline ==="
    
    # Show LLM configuration
    echo "LLM Configuration:"
    echo "  - API Base: ${OPENAI_BASE_URL:-https://chat.ai.e-infra.cz/api/v1}"
    echo "  - Model: ${LLM_MODEL:-qwen3-coder}"
    echo "  - Temperature: ${LLM_TEMPERATURE:-0.7}"
    
    # Generate timeline using LLM
    cd /opt/john_scott_llm
    if bash ./generate_timeline.sh; then
        echo "✓ Timeline generated successfully with LLM"
        # Copy generated timeline to GHOSTS config
        cp /opt/john_scott_llm/timeline_john_scott_llm.json /opt/ghosts/bin/config/timeline.json
    else
        echo "✗ Failed to generate timeline with LLM, falling back to dummy mode"
        cp /opt/john_scott_dummy/timeline_john_scott.json /opt/ghosts/bin/config/timeline.json
    fi
else
    echo "=== Dummy Mode: Using predefined timeline ==="
    cp /opt/john_scott_dummy/timeline_john_scott.json /opt/ghosts/bin/config/timeline.json
    echo "✓ Dummy timeline configured"
fi

# Wait for compromised machine to be ready
echo "Waiting for compromised machine (172.30.0.10) to be ready..."
for i in {1..30}; do
    if ping -c 1 -W 1 172.30.0.10 > /dev/null 2>&1; then
        echo "✓ Compromised machine is reachable"
        break
    fi
    echo "  Attempt $i/30..."
    sleep 2
done

# Test SSH connectivity
echo "Testing SSH connection to compromised machine..."
if ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o ConnectTimeout=5 -i /root/.ssh/id_rsa labuser@172.30.0.10 "echo 'SSH connection successful'"; then
    echo "✓ SSH connection test passed"
else
    echo "✗ SSH connection test failed"
    echo "  Please verify:"
    echo "  - SSH public key is installed on compromised machine"
    echo "  - labuser exists on compromised machine"
    echo "  - SSH service is running on compromised machine"
fi

# Start GHOSTS client
echo "Starting GHOSTS client..."
cd /opt/ghosts/bin
./Ghosts.Client.Universal

echo "=== GHOSTS Driver Stopped ==="
