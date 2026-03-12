#!/bin/bash
# Claku Agent Polling Loop
# Run this to keep your agent listening for dashboard commands

cd /root/.openclaw/workspace/claku

echo "🪻 Starting Lavanda agent polling loop..."
echo "Press Ctrl+C to stop"
echo ""

while true; do
  python3 claku_cli.py run
  sleep 5
done
