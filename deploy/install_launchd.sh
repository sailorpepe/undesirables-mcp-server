#!/bin/bash
# ─── UNDSR Infrastructure Deploy ───
# Installs launchd plists for persistent MCP + Ollama on Mac Mini.
#
# Usage (on Mac Mini):
#   chmod +x deploy/install_launchd.sh
#   ./deploy/install_launchd.sh
#
# To uninstall:
#   ./deploy/install_launchd.sh --uninstall

set -e

DEPLOY_DIR="$(cd "$(dirname "$0")" && pwd)"
LAUNCH_DIR="$HOME/Library/LaunchAgents"

MCP_PLIST="com.mememerchants.mcp-server.plist"
OLLAMA_PLIST="com.mememerchants.ollama-serve.plist"

if [ "$1" = "--uninstall" ]; then
    echo "🛑 Uninstalling UNDSR launchd services..."
    launchctl unload "$LAUNCH_DIR/$MCP_PLIST" 2>/dev/null || true
    launchctl unload "$LAUNCH_DIR/$OLLAMA_PLIST" 2>/dev/null || true
    rm -f "$LAUNCH_DIR/$MCP_PLIST" "$LAUNCH_DIR/$OLLAMA_PLIST"
    echo "✅ Uninstalled. Services will not auto-restart."
    exit 0
fi

echo "🐸 UNDSR Infrastructure Deploy"
echo "================================"

# Create LaunchAgents dir if missing
mkdir -p "$LAUNCH_DIR"

# Unload existing (ignore errors if not loaded)
launchctl unload "$LAUNCH_DIR/$MCP_PLIST" 2>/dev/null || true
launchctl unload "$LAUNCH_DIR/$OLLAMA_PLIST" 2>/dev/null || true

# Copy plists
cp "$DEPLOY_DIR/$MCP_PLIST" "$LAUNCH_DIR/"
cp "$DEPLOY_DIR/$OLLAMA_PLIST" "$LAUNCH_DIR/"

# Fix permissions
chmod 644 "$LAUNCH_DIR/$MCP_PLIST"
chmod 644 "$LAUNCH_DIR/$OLLAMA_PLIST"

# Load
launchctl load "$LAUNCH_DIR/$OLLAMA_PLIST"
echo "✅ Ollama serve loaded (port 11434, keep-alive 24h)"

sleep 2

launchctl load "$LAUNCH_DIR/$MCP_PLIST"
echo "✅ MCP server loaded (auto-restart on crash)"

echo ""
echo "📊 Status:"
echo "  launchctl list | grep mememerchants"
echo ""
echo "📋 Logs:"
echo "  tail -f /tmp/mcp-server-stdout.log"
echo "  tail -f /tmp/ollama-stdout.log"
echo ""
echo "🛑 To uninstall: $0 --uninstall"
