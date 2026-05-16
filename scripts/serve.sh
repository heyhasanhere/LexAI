#!/usr/bin/env bash
# Operator script — expose LexAI publicly from your own machine.
# Prerequisites: docker compose already up (full profile).
#
# Usage:
#   bash scripts/serve.sh
#
# Starts two Cloudflare Quick Tunnels:
#   UI tunnel  (port 8501) → share this URL so users open LexAI in their browser
#   GPU tunnel (port 8090) → paste into install.sh as LEXAI_REMOTE_URL
#
# Press Ctrl-C to stop both tunnels.
set -euo pipefail

UI_PORT=8501
GATEWAY_PORT=8090

_green()  { printf '\033[0;32m%s\033[0m\n' "$*"; }
_yellow() { printf '\033[0;33m%s\033[0m\n' "$*"; }
_bold()   { printf '\033[1m%s\033[0m\n'   "$*"; }
_die()    { printf '\033[0;31mERROR: %s\033[0m\n' "$*"; exit 1; }

# ── Verify services are up ─────────────────────────────────────────────────

echo ""
_bold "Checking services…"

curl -sf --max-time 5 "http://localhost:$UI_PORT" -o /dev/null \
    || _die "Streamlit UI not responding on port $UI_PORT. Run: docker compose up -d"
_green "✓ UI is up (port $UI_PORT)"

# Gateway returns 403 on / — that is correct behaviour
HTTP=$(curl -sf --max-time 5 -o /dev/null -w "%{http_code}" \
    "http://localhost:$GATEWAY_PORT/" 2>/dev/null || echo "000")
[[ "$HTTP" == "403" ]] \
    || _die "nginx gateway not responding on port $GATEWAY_PORT. Run: docker compose up -d (full profile)"
_green "✓ vLLM gateway is up (port $GATEWAY_PORT)"

# ── Install cloudflared ────────────────────────────────────────────────────

install_cloudflared() {
    command -v cloudflared &>/dev/null && return
    _yellow "cloudflared not found — installing…"
    local OS ARCH PKG
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
            sudo dpkg -i /tmp/cloudflared.deb 2>/dev/null \
                || sudo apt-get install -fy 2>/dev/null \
                || sudo rpm -i /tmp/cloudflared.deb 2>/dev/null \
                || _die "Could not install cloudflared. See https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/"
            ;;
        Darwin)
            brew install cloudflare/cloudflare/cloudflared
            ;;
        *)
            _die "Unsupported OS: $OS. Install cloudflared manually."
            ;;
    esac
    _green "✓ cloudflared installed"
}

install_cloudflared

# ── Tunnel output parser ───────────────────────────────────────────────────
# Reads cloudflared stderr, extracts the trycloudflare URL, and prints a
# highlighted banner. Label arg is used to distinguish the two tunnels.

parse_tunnel() {
    local label="$1"
    while IFS= read -r line; do
        if echo "$line" | grep -qE 'https://[a-z0-9-]+\.trycloudflare\.com'; then
            local URL
            URL=$(echo "$line" | grep -oE 'https://[a-z0-9-]+\.trycloudflare\.com')
            echo ""
            _bold  "════════════════════════════════════════════"
            if [[ "$label" == "UI" ]]; then
                _green "  BROWSER URL  →  $URL"
                _yellow "  Share this link — users open LexAI here"
            else
                _green "  GPU API URL  →  $URL/v1"
                _yellow "  Paste into install.sh as LEXAI_REMOTE_URL"
            fi
            _bold  "════════════════════════════════════════════"
            echo ""
        fi
    done
}

# ── Start both tunnels ─────────────────────────────────────────────────────

echo ""
_bold "Starting tunnels (Ctrl-C to stop)…"
echo ""

# Tunnel for Streamlit UI
cloudflared tunnel --url "http://localhost:$UI_PORT" 2>&1 \
    | parse_tunnel "UI" &
UI_PID=$!

# Tunnel for vLLM gateway
cloudflared tunnel --url "http://localhost:$GATEWAY_PORT" 2>&1 \
    | parse_tunnel "GPU" &
GPU_PID=$!

# Clean up both tunnels on Ctrl-C
trap 'kill $UI_PID $GPU_PID 2>/dev/null; echo ""; _yellow "Tunnels stopped."; exit 0' INT TERM

wait $UI_PID $GPU_PID
