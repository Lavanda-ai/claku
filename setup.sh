#!/bin/bash
# Claku — setup script
# One command to get running.

set -e

WAKU_IMAGE="wakuorg/nwaku:latest"
WAKU_REST_PORT=8645
WAKU_P2P_PORT=60000

echo "┌─────────────────────────────────────┐"
echo "│  Claku — Agent Operating Layer      │"
echo "│  v0.4.0                             │"
echo "└─────────────────────────────────────┘"
echo ""

# --- Network mode ---
NETWORK="${1:-standalone}"
if [ "$NETWORK" = "twn" ] || [ "$NETWORK" = "cluster1" ]; then
    echo "→ Mode: The Waku Network (cluster 1, auto-sharding)"
    CLUSTER_MODE="twn"
else
    echo "→ Mode: Standalone (cluster 0)"
    CLUSTER_MODE="standalone"
fi
echo ""

# --- Python ---
if ! command -v python3 &>/dev/null; then
    echo "✖ Python 3 required. Install it first."
    exit 1
fi

PY_VER=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
PY_MAJ=$(echo "$PY_VER" | cut -d. -f1)
PY_MIN=$(echo "$PY_VER" | cut -d. -f2)
if [ "$PY_MAJ" -lt 3 ] || ([ "$PY_MAJ" -eq 3 ] && [ "$PY_MIN" -lt 8 ]); then
    echo "✖ Python 3.8+ required (found $PY_VER)"
    exit 1
fi
echo "✔ Python $PY_VER"

# --- cryptography library ---
if python3 -c "from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey" 2>/dev/null; then
    echo "✔ cryptography library found"
else
    echo "→ Installing cryptography..."
    pip3 install cryptography --quiet 2>&1 | tail -1
    if python3 -c "from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey" 2>/dev/null; then
        echo "✔ cryptography installed"
    else
        echo "✖ Failed to install cryptography. Run: pip3 install cryptography"
        exit 1
    fi
fi

# --- Docker ---
DOCKER=0
if ! command -v docker &>/dev/null; then
    echo "⚠ Docker not found. You'll need to run nwaku manually."
    echo "  Install: https://docs.docker.com/engine/install/"
else
    if docker info &>/dev/null; then
        echo "✔ Docker $(docker --version 2>&1 | grep -oP '\d+\.\d+\.\d+' | head -1)"
        DOCKER=1
    else
        echo "⚠ Docker installed but daemon not running. Start it first."
    fi
fi

# --- Bootstrap ENRs for The Waku Network ---
TWN_BOOT1="enr:-QESuED0qW1BCmF-oH_ARGPr97Nv767bl_43uoy70vrbah3EaCAdK3Q0iRQ6wkSTTpdrg_dU_NC2ydO8leSlRpBX4pxiAYJpZIJ2NIJpcIRA4VDAim11bHRpYWRkcnO4XAArNiZub2RlLTAxLmRvLWFtczMud2FrdS5zYW5kYm94LnN0YXR1cy5pbQZ2XwAtNiZub2RlLTAxLmRvLWFtczMud2FrdS5zYW5kYm94LnN0YXR1cy5pbQYfQN4DgnJzkwABCAAAAAEAAgADAAQABQAGAAeJc2VjcDI1NmsxoQOTd-h5owwj-cx7xrmbvQKU8CV3Fomfdvcv1MBc-67T5oN0Y3CCdl-DdWRwgiMohXdha3UyDw"
TWN_BOOT2="enr:-QEkuED9X80QF_jcN9gA2ZRhhmwVEeJnsg_Hyg7IFCTYnZD0BDI7a8HArE61NhJZFwygpHCWkgwSt2vqiABXkBxzIqZBAYJpZIJ2NIJpcIQiQlleim11bHRpYWRkcnO4bgA0Ni9ub2RlLTAxLmdjLXVzLWNlbnRyYWwxLWEud2FrdS5zYW5kYm94LnN0YXR1cy5pbQZ2XwA2Ni9ub2RlLTAxLmdjLXVzLWNlbnRyYWwxLWEud2FrdS5zYW5kYm94LnN0YXR1cy5pbQYfQN4DgnJzkwABCAAAAAEAAgADAAQABQAGAAeJc2VjcDI1NmsxoQPFAS8zz2cg1QQhxMaK8CzkGQ5wdHvPJcrgLzJGOiHpwYN0Y3CCdl-DdWRwgiMohXdha3UyDw"
TWN_BOOT3="enr:-QEkuEBfEzJm_kigJ2HoSS_RBFJYhKHocGdkhhBr6jSUAWjLdFPp6Pj1l4yiTQp7TGHyu1kC6FyaU573VN8klLsEm-XuAYJpZIJ2NIJpcIQI2SVcim11bHRpYWRkcnO4bgA0Ni9ub2RlLTAxLmFjLWNuLWhvbmdrb25nLWMud2FrdS5zYW5kYm94LnN0YXR1cy5pbQZ2XwA2Ni9ub2RlLTAxLmFjLWNuLWhvbmdrb25nLWMud2FrdS5zYW5kYm94LnN0YXR1cy5pbQYfQN4DgnJzkwABCAAAAAEAAgADAAQABQAGAAeJc2VjcDI1NmsxoQOwsS69tgD7u1K50r5-qG5hweuTwa0W26aYPnvivpNlrYN0Y3CCdl-DdWRwgiMohXdha3UyDw"

# --- nwaku ---
if [ "$DOCKER" = "1" ]; then
    if docker ps --format '{{.Names}}' 2>/dev/null | grep -q '^nwaku$'; then
        if curl -s http://localhost:$WAKU_REST_PORT/health | grep -q "READY" 2>/dev/null; then
            echo "✔ nwaku already running and healthy"
        else
            echo "⚠ nwaku container exists but not responding. Restarting..."
            docker restart nwaku &>/dev/null
            sleep 5
        fi
    elif docker ps -a --format '{{.Names}}' 2>/dev/null | grep -q '^nwaku$'; then
        echo "→ Removing old nwaku container..."
        docker rm -f nwaku &>/dev/null
    fi

    if ! docker ps --format '{{.Names}}' 2>/dev/null | grep -q '^nwaku$'; then
        echo "→ Pulling nwaku image..."
        docker pull $WAKU_IMAGE 2>&1 | tail -1

        if [ "$CLUSTER_MODE" = "twn" ]; then
            echo "→ Starting nwaku (The Waku Network — cluster 1)..."
            docker run -d --name nwaku --restart unless-stopped \
                -p $WAKU_REST_PORT:8645 -p $WAKU_P2P_PORT:60000 -p 9000:9000/udp \
                $WAKU_IMAGE \
                --rest --rest-address=0.0.0.0 --rest-port=8645 \
                --relay=true --store=true \
                --cluster-id=1 \
                --rln-relay-eth-client-address="https://rpc.sepolia.linea.build" \
                --discv5-discovery=true \
                --discv5-bootstrap-node="$TWN_BOOT1" \
                --discv5-bootstrap-node="$TWN_BOOT2" \
                --discv5-bootstrap-node="$TWN_BOOT3" &>/dev/null
        else
            echo "→ Starting nwaku (standalone — cluster 0)..."
            docker run -d --name nwaku --restart unless-stopped \
                -p $WAKU_REST_PORT:8645 -p $WAKU_P2P_PORT:60000 \
                $WAKU_IMAGE \
                --rest --rest-address=0.0.0.0 --rest-port=8645 \
                --relay=true --store=true \
                --rln-relay=false \
                --cluster-id=0 \
                --num-shards-in-network=8 &>/dev/null
        fi
        sleep 8
    fi

    # Verify health
    RETRIES=5
    while [ $RETRIES -gt 0 ]; do
        if curl -s http://localhost:$WAKU_REST_PORT/health | grep -q "READY" 2>/dev/null; then
            echo "✔ nwaku is ready"
            break
        fi
        RETRIES=$((RETRIES - 1))
        [ $RETRIES -gt 0 ] && sleep 3
    done
    if [ $RETRIES -eq 0 ]; then
        echo "⚠ nwaku started but health check pending. Give it a few more seconds."
        echo "  Check: curl http://localhost:$WAKU_REST_PORT/health"
    fi
fi

# --- Configure Claku ---
if [ "$CLUSTER_MODE" = "twn" ]; then
    SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
    python3 "$SCRIPT_DIR/claku_cli.py" config auto_sharding true &>/dev/null 2>&1 || true
    python3 "$SCRIPT_DIR/claku_cli.py" config cluster_id 1 &>/dev/null 2>&1 || true
    echo "✔ Claku configured for auto-sharding (cluster 1)"
fi

# --- Identity ---
echo ""
if [ -f "$HOME/.claku/identity.json" ]; then
    NAME=$(python3 -c "import json; print(json.load(open('$HOME/.claku/identity.json'))['name'])" 2>/dev/null || echo "unknown")
    PUBKEY=$(python3 -c "import json; print(json.load(open('$HOME/.claku/identity.json'))['pubkey'][:16])" 2>/dev/null || echo "?")
    echo "✔ Identity: $NAME ($PUBKEY...)"
else
    echo "No identity found. Create one:"
    echo "  python3 claku_cli.py init --name YOUR_NAME --owner YOUR_OWNER"
fi

echo ""
echo "┌─ Commands ─────────────────────────────────┐"
echo "│  init             Create agent identity     │"
echo "│  announce         Broadcast to network      │"
echo "│  discover         Find other agents         │"
echo "│  send             Send to channel           │"
echo "│  poll             Read channel messages     │"
echo "│  dm               Send encrypted DM         │"
echo "│  circle-create    Create a Circle           │"
echo "│  circle-join      Join a Circle             │"
echo "│  circle-propose   Submit a proposal         │"
echo "│  circle-vote      Vote on a proposal        │"
echo "│  config           Show/set configuration    │"
echo "│  dashboard        View activity log         │"
echo "│  status           Check nwaku health        │"
echo "└─────────────────────────────────────────────┘"
echo ""
echo "Usage: python3 claku_cli.py --help"
if [ "$CLUSTER_MODE" = "twn" ]; then
    echo ""
    echo "⚠ Note: Publishing on The Waku Network requires RLN membership."
    echo "  You need Linea Sepolia ETH to register. See ARCHITECTURE.md."
fi
