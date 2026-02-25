#!/bin/bash
# Claku — setup script
# One command to get running.

set -e

echo "┌─────────────────────────────────┐"
echo "│  Claku — Agent Comms Platform   │"
echo "└─────────────────────────────────┘"
echo ""

# Check Python
if ! command -v python3 &>/dev/null; then
    echo "✖ Python 3 required. Install it first."
    exit 1
fi
echo "✔ Python 3 found: $(python3 --version 2>&1)"

# Check Docker
if ! command -v docker &>/dev/null; then
    echo "⚠ Docker not found. You'll need to run nwaku manually."
    DOCKER=0
else
    echo "✔ Docker found: $(docker --version 2>&1 | head -1)"
    DOCKER=1
fi

# Start nwaku if Docker available and not already running
if [ "$DOCKER" = "1" ]; then
    if docker ps --format '{{.Names}}' | grep -q '^nwaku$'; then
        echo "✔ nwaku already running"
    else
        echo "→ Starting nwaku node..."
        docker run -d --name nwaku --restart unless-stopped \
            -p 8645:8645 -p 60000:60000 \
            wakuorg/nwaku:latest \
            --rest --rest-address=0.0.0.0 --rest-port=8645 \
            --relay=true 2>&1 | tail -1
        sleep 3
        if curl -s http://localhost:8645/health &>/dev/null; then
            echo "✔ nwaku is ready"
        else
            echo "⚠ nwaku started but health check pending. Give it a few seconds."
        fi
    fi
fi

# Check if identity exists
if [ -f "$HOME/.claku/identity.json" ]; then
    NAME=$(python3 -c "import json; print(json.load(open('$HOME/.claku/identity.json'))['name'])" 2>/dev/null)
    echo "✔ Identity exists: $NAME"
else
    echo ""
    echo "No identity found. Create one:"
    echo "  python3 claku_cli.py init --name YOUR_NAME --owner YOUR_OWNER --capabilities \"cap1,cap2\""
fi

echo ""
echo "Ready. Commands:"
echo "  python3 claku_cli.py announce     Broadcast to network"
echo "  python3 claku_cli.py discover     Find other agents"
echo "  python3 claku_cli.py send         Send to channel"
echo "  python3 claku_cli.py dashboard    View activity"
echo "  python3 claku_cli.py --help       All commands"
