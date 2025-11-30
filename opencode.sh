#!/bin/bash
# Helper script to run OpenCode in the server container
# Usage: ./opencode.sh "your prompt here"

if [ -z "$1" ]; then
    echo "Usage: $0 \"your prompt here\""
    echo "Example: $0 \"list all files here\""
    exit 1
fi

# Run with sudo if not already root
if [ "$EUID" -ne 0 ]; then
    sudo docker exec lab_server opencode run "$@"
else
    docker exec lab_server opencode run "$@"
fi
