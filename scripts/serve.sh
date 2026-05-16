#!/usr/bin/env bash
# Operator script — run this on YOUR machine to expose vLLM publicly.
# Prerequisites: docker compose full profile already up (vllm + gateway running).
#
# Usage:
#   bash scripts/serve.sh
#
# What it does:
#   1. Installs cloudflared if missing
#   2. Starts a Cloudflare Quick Tunnel pointing at the nginx gateway (port 8090)
#   3. Prints the public URL — paste it into install.sh as LEXAI_REMOTE_URL
set -euo pipefail

GATEWAY_PORT=8090

_green()  { printf '\033[0;32m%s\033[0m\n' "$*"; }
_yellow() { printf '\033[0;33m%s\033[0m\n' "$*"; }
_bold()   { printf '\033[1m%s\033[0m\n'   "$*"; }
_die()    { printf '\033[0;31mERROR: %s\033[0m\n' "$*"; exit 1; }

# ── Verify gateway is up ───────────────────────────────────────────────────

echo ""
_bold "Checking nginx gateway on port $GATEWAY_PORT…"
curl -sf --max-time 3 "http://localhost:$GATEWAY_PORT/v1/chat/completions" \
    -X POST -H "Content-Type: application/json" \
    -d '{"model":"x","messages":[]}' \
    -o /dev/null || true   # 400 from vLLM is fine — gateway is reachable

if ! curl -sf --max-time 3 -o /dev/null -w "%{http_code}" \
        "http://localhost:$GATEWAY_PORT/" 2>/dev/null | grep -q "403"; then
    _die "Gateway not responding on port $GATEWAY_PORT. Run: docker compose up -d (full profile)"
fi
_green "✓ Gateway is up (port $GATEWAY_PORT)"

# ── Install cloudflared ────────────────────────────────────────────────────

if ! command -v cloudflared &>/dev/null; then
    _yellow "cloudflared not found — installing…"
    OS="$(uname -s)"
    ARCH="$(uname -m)"

    case "$OS" in
        Linux)
            case "$ARCH" in
                x86_64)  PKG="cloudflared-linux-amd64" ;;
                aarch64) PKG="cloudflared-linux-arm64" ;;
                armv7l)  PKG="cloudflared-linux-arm"   ;;
                *)        _die "Unsupported arch: $ARCH" ;;
            esac
            curl -fsSL "https://github.com/cloudflare/cloudflared/releases/latest/download/${PKG}.deb" \
                -o /tmp/cloudflared.deb
            sudo dpkg -i /tmp/cloudflared.deb 2>/dev/null || \
                sudo apt-get install -fy 2>/dev/null || \
                { sudo rpm -i /tmp/cloudflared.deb 2>/dev/null || true; }
            ;;
        Darwin)
            brew install cloudflare/cloudflare/cloudflared
            ;;
        *)
            _die "Unsupported OS: $OS. Install cloudflared manually: https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/"
            ;;
    esac
    _green "✓ cloudflared installed"
fi

# ── Start tunnel ───────────────────────────────────────────────────────────

_bold "Starting Cloudflare Quick Tunnel → http://localhost:$GATEWAY_PORT"
echo ""
_yellow "The public URL will appear below. Copy it into install.sh as LEXAI_REMOTE_URL."
_yellow "Press Ctrl-C to stop serving."
echo ""

# cloudflared prints the URL to stderr; we tee it so it's visible
cloudflared tunnel --url "http://localhost:$GATEWAY_PORT" 2>&1 | \
    while IFS= read -r line; do
        echo "$line"
        # Highlight the URL line
        if echo "$line" | grep -qE 'https://[a-z0-9-]+\.trycloudflare\.com'; then
            URL=$(echo "$line" | grep -oE 'https://[a-z0-9-]+\.trycloudflare\.com')
            echo ""
            _bold  "════════════════════════════════════════════"
            _green "  Public URL:  $URL/v1"
            _bold  "════════════════════════════════════════════"
            _yellow "  Update install.sh:"
            _yellow "  LEXAI_REMOTE_URL=\"$URL/v1\""
            echo ""
        fi
    done
