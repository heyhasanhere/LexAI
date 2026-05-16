#!/usr/bin/env bash
# deploy.sh — start a Cloudflare Quick Tunnel as a background daemon, publish
# the live URL to README.md, commit and push to GitHub, then exit.
# The tunnel keeps running after this script exits.
#
# Usage:
#   bash scripts/deploy.sh          # start tunnel and update README
#   bash scripts/deploy.sh stop     # kill the running tunnel
#   bash scripts/deploy.sh status   # show whether the tunnel is running
#
# Prerequisites:
#   - docker compose services up (COMPOSE_PROFILES=lite docker compose up -d)
#   - git remote 'origin' configured with push access
#   - cloudflared installed (auto-installed if missing)

set -euo pipefail

UI_PORT=8501
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
README="$REPO_ROOT/README.md"
PID_FILE="/tmp/lexai-tunnel.pid"
LOG_FILE="/tmp/lexai-tunnel.log"

_green()  { printf '\033[0;32m%s\033[0m\n' "$*"; }
_yellow() { printf '\033[0;33m%s\033[0m\n' "$*"; }
_bold()   { printf '\033[1m%s\033[0m\n'   "$*"; }
_red()    { printf '\033[0;31m%s\033[0m\n' "$*"; }
_die()    { _red "ERROR: $*"; exit 1; }

# ── stop / status sub-commands ──────────────────────────────────────────────

if [[ "${1:-}" == "stop" ]]; then
    if [[ -f "$PID_FILE" ]]; then
        PID=$(cat "$PID_FILE")
        kill "$PID" 2>/dev/null && _green "Tunnel (PID $PID) stopped." || _yellow "Process $PID was not running."
        rm -f "$PID_FILE"
    else
        _yellow "No PID file found — tunnel may not be running."
    fi
    exit 0
fi

if [[ "${1:-}" == "status" ]]; then
    if [[ -f "$PID_FILE" ]] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
        _green "Tunnel is running (PID $(cat "$PID_FILE"))."
        grep -oE 'https://[a-z0-9-]+\.trycloudflare\.com' "$LOG_FILE" 2>/dev/null | tail -1 \
            && true || _yellow "URL not yet captured."
    else
        _yellow "Tunnel is not running."
    fi
    exit 0
fi

# ── stop any existing tunnel first ─────────────────────────────────────────

if [[ -f "$PID_FILE" ]] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
    _yellow "Stopping previous tunnel (PID $(cat "$PID_FILE"))…"
    kill "$(cat "$PID_FILE")" 2>/dev/null || true
    rm -f "$PID_FILE"
fi

# ── verify UI is up ─────────────────────────────────────────────────────────

echo ""
_bold "Checking services…"
curl -sf --max-time 5 "http://localhost:$UI_PORT" -o /dev/null \
    || _die "Streamlit UI not responding on port $UI_PORT. Run: COMPOSE_PROFILES=lite docker compose up -d"
_green "✓ UI is up (port $UI_PORT)"

# ── install cloudflared if missing ──────────────────────────────────────────

if ! command -v cloudflared &>/dev/null; then
    _yellow "cloudflared not found — installing…"
    ARCH="$(uname -m)"
    case "$ARCH" in
        x86_64)  PKG="cloudflared-linux-amd64" ;;
        aarch64) PKG="cloudflared-linux-arm64" ;;
        armv7l)  PKG="cloudflared-linux-arm"   ;;
        *)        _die "Unsupported arch: $ARCH" ;;
    esac
    curl -fsSL "https://github.com/cloudflare/cloudflared/releases/latest/download/${PKG}.deb" \
        -o /tmp/cloudflared.deb
    sudo dpkg -i /tmp/cloudflared.deb 2>/dev/null || sudo apt-get install -fy 2>/dev/null || true
    _green "✓ cloudflared installed"
fi

# ── start tunnel as a detached daemon ──────────────────────────────────────

echo ""
_bold "Starting Cloudflare tunnel (daemon mode)…"

# Truncate log so we scan only this session's output
> "$LOG_FILE"

nohup cloudflared tunnel --url "http://localhost:$UI_PORT" \
    >"$LOG_FILE" 2>&1 &
TUNNEL_PID=$!
echo "$TUNNEL_PID" > "$PID_FILE"
disown "$TUNNEL_PID"

_green "✓ Tunnel started (PID $TUNNEL_PID, log: $LOG_FILE)"
_yellow "Waiting for tunnel URL (up to 60 s)…"

# Poll the log file for the URL
LIVE_URL=""
for i in $(seq 1 30); do
    sleep 2
    LIVE_URL=$(grep -oE 'https://[a-z0-9-]+\.trycloudflare\.com' "$LOG_FILE" 2>/dev/null | head -1 || true)
    [[ -n "$LIVE_URL" ]] && break
done

[[ -n "$LIVE_URL" ]] || _die "Timed out waiting for tunnel URL. Check $LOG_FILE for details."

echo ""
_bold "════════════════════════════════════════════"
_green "  LIVE URL  →  $LIVE_URL"
_yellow "  Share this link — users open LexAI here"
_bold "════════════════════════════════════════════"
echo ""

# ── update README.md ────────────────────────────────────────────────────────

_yellow "Updating README.md with new live URL…"

if grep -q "live-demo-url:" "$README"; then
    # Replace the entire live-demo blockquote line
    sed -i "s|> \*\*\[▶ Open Live Demo\]([^)]*)\*\*.*|> **[▶ Open Live Demo]($LIVE_URL)** <!-- live-demo-url: $LIVE_URL -->|" "$README"
else
    # Insert after the first H1 line
    sed -i "0,/^# /{s|^# \(.*\)|# \1\n\n> **[▶ Open Live Demo]($LIVE_URL)** <!-- live-demo-url: $LIVE_URL -->|}" "$README"
fi

_green "✓ README.md updated"

# ── commit and push ─────────────────────────────────────────────────────────

cd "$REPO_ROOT"

if ! git diff --quiet README.md; then
    git add README.md
    git commit -m "deploy: update live demo URL to $LIVE_URL"
    git push origin main
    _green "✓ README.md committed and pushed to GitHub"
else
    _yellow "README.md unchanged (URL was already up to date)"
fi

echo ""
_bold "Tunnel is running in the background."
_yellow "  Stop:    bash scripts/deploy.sh stop"
_yellow "  Status:  bash scripts/deploy.sh status"
_yellow "  Log:     $LOG_FILE"
echo ""
