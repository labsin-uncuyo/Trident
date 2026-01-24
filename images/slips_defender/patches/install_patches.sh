#!/bin/bash
# Script to install HTTP password guessing detection patches into a running or new Slips container

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PATCH_DIR="$SCRIPT_DIR/http_analyzer"

echo "=========================================="
echo "Slips HTTP Password Guessing Detection"
echo "Patch Installation Script"
echo "=========================================="
echo

# Check if patch files exist
if [ ! -f "$PATCH_DIR/http_analyzer.py" ] || [ ! -f "$PATCH_DIR/set_evidence.py" ]; then
    echo "ERROR: Patch files not found in $PATCH_DIR"
    exit 1
fi

echo "✓ Patch files found"
echo

# Ask for installation mode
echo "Choose installation mode:"
echo "1) Update Dockerfile (persistent for new builds)"
echo "2) Patch running container (temporary, lost on rebuild)"
echo "3) Both"
echo
read -p "Enter choice [1-3]: " choice

case $choice in
    1)
        MODE="dockerfile"
        ;;
    2)
        MODE="container"
        ;;
    3)
        MODE="both"
        ;;
    *)
        echo "Invalid choice. Exiting."
        exit 1
        ;;
esac

echo
echo "Installation mode: $MODE"
echo

# Function to patch Dockerfile
patch_dockerfile() {
    echo "→ Updating Dockerfile..."

    # Try to find Dockerfile at various relative locations
    DOCKERFILE_PATH="$SCRIPT_DIR/Dockerfile"

    if [ ! -f "$DOCKERFILE_PATH" ]; then
        DOCKERFILE_PATH="$SCRIPT_DIR/../../Dockerfile"
    fi

    if [ ! -f "$DOCKERFILE_PATH" ]; then
        echo "  WARNING: Dockerfile not found. Skipping Dockerfile update."
        return
    fi

    # Check if already patched
    if grep -q "http_analyzer/http_analyzer.py" "$DOCKERFILE_PATH"; then
        echo "  ✓ Dockerfile already contains patch instructions"
        return
    fi

    # Create backup
    cp "$DOCKERFILE_PATH" "$DOCKERFILE_PATH.backup"
    echo "  ✓ Backup created: $DOCKERFILE_PATH.backup"

    # Add patch instructions after the SSH key generation section
    cat >> "$DOCKERFILE_PATH" << 'EOF'

# Copy patched HTTP analyzer with password guessing detection
COPY patches/http_analyzer/set_evidence.py /StratosphereLinuxIPS/modules/http_analyzer/
COPY patches/http_analyzer/http_analyzer.py /StratosphereLinuxIPS/modules/http_analyzer/
EOF

    echo "  ✓ Dockerfile updated with patch instructions"
    echo "  → Rebuild the image with: docker build -t lab/slips_defender:latest ."
}

# Function to patch running container
patch_container() {
    echo "→ Patching running container..."

    # Find running Slips container
    CONTAINER_ID=$(docker ps | grep slips_defender | awk '{print $1}' | head -1)

    if [ -z "$CONTAINER_ID" ]; then
        echo "  WARNING: No running slips_defender container found."
        read -p "  Do you want to start a new container? [y/N]: " start_new
        if [[ $start_new =~ ^[Yy]$ ]]; then
            echo "  Please start your container first, then run this script again."
            echo "  Example: docker compose up -d slips_defender"
        fi
        return
    fi

    echo "  Found container: $CONTAINER_ID"

    # Create backup in container
    docker exec "$CONTAINER_ID" cp /StratosphereLinuxIPS/modules/http_analyzer/http_analyzer.py \
        /StratosphereLinuxIPS/modules/http_analyzer/http_analyzer.py.backup 2>/dev/null || true
    docker exec "$CONTAINER_ID" cp /StratosphereLinuxIPS/modules/http_analyzer/set_evidence.py \
        /StratosphereLinuxIPS/modules/http_analyzer/set_evidence.py.backup 2>/dev/null || true

    echo "  ✓ Backups created in container"

    # Copy patched files
    docker cp "$PATCH_DIR/http_analyzer.py" "$CONTAINER_ID:/StratosphereLinuxIPS/modules/http_analyzer/http_analyzer.py"
    docker cp "$PATCH_DIR/set_evidence.py" "$CONTAINER_ID:/StratosphereLinuxIPS/modules/http_analyzer/set_evidence.py"

    echo "  ✓ Patched files copied to container"

    # Verify the patch
    if docker exec "$CONTAINER_ID" grep -q "check_password_guessing" /StratosphereLinuxIPS/modules/http_analyzer/http_analyzer.py; then
        echo "  ✓ Patch verified successfully!"
        echo "  → Container will use the patched code on next analysis cycle"
        echo "  → No restart required for changes to take effect"
    else
        echo "  ✗ Patch verification failed!"
        echo "  → Restoring backups..."
        docker exec "$CONTAINER_ID" mv /StratosphereLinuxIPS/modules/http_analyzer/http_analyzer.py.backup \
            /StratosphereLinuxIPS/modules/http_analyzer/http_analyzer.py 2>/dev/null || true
        docker exec "$CONTAINER_ID" mv /StratosphereLinuxIPS/modules/http_analyzer/set_evidence.py.backup \
            /StratosphereLinuxIPS/modules/http_analyzer/set_evidence.py 2>/dev/null || true
        return 1
    fi
}

# Execute based on mode
case $MODE in
    dockerfile)
        patch_dockerfile
        ;;
    container)
        patch_container
        ;;
    both)
        patch_dockerfile
        echo
        patch_container
        ;;
esac

echo
echo "=========================================="
echo "Installation complete!"
echo "=========================================="
echo
echo "Next steps:"
echo "1. Test the detection with: curl -X POST http://target:443/login -d 'user=test&pass=test'"
echo "2. Monitor alerts: docker logs slips_defender | grep -i password"
echo "3. Read the documentation: $PATCH_DIR/README.md"
echo
echo "Configuration:"
echo "  - Password guessing threshold: 10 attempts (default)"
echo "  - Time window: 5 minutes"
echo "  - Monitored paths: /login, /signin, /auth, etc."
echo
