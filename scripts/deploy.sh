#!/usr/bin/env bash
# deploy.sh — start a Cloudflare Quick Tunnel, publish the live URL to README.md,
# commit and push to GitHub, then keep the tunnel running until Ctrl-C.
#
# Prerequisites:
#   - docker compose services up (COMPOSE_PROFILES=lite docker compose up -d)
#   - git remote 'origin' configured with push access
#   - cloudflared installed (auto-installed if missing)
#
# Usage:
#   bash scripts/deploy.sh
set -euo pipefail

UI_PORT=8501
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
README="$REPO_ROOT/README.md"

_green()  { printf '\033[0;32m%s\033[0m\n' "$*"; }
_yellow() { printf '\033[0;33m%s\033[0m\n' "$*"; }
_bold()   { printf '\033[1m%s\033[0m\n'   "$*"; }
_die()    { printf '\033[0;31mERROR: %s\033[0m\n' "$*"; exit 1; }

# ── Verify UI is up ─────────────────────────────────────────────────────────

echo ""
_bold "Checking services…"
curl -sf --max-time 5 "http://localhost:$UI_PORT" -o /dev/null \
    || _die "Streamlit UI not responding on port $UI_PORT. Run: COMPOSE_PROFILES=lite docker compose up -d"
_green "✓ UI is up (port $UI_PORT)"

# ── Install cloudflared if missing ──────────────────────────────────────────

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

# ── Named pipe for URL handoff ──────────────────────────────────────────────

URL_PIPE="$(mktemp -u)"
mkfifo "$URL_PIPE"
trap 'rm -f "$URL_PIPE"' EXIT

# ── Start tunnel in background ──────────────────────────────────────────────

echo ""
_bold "Starting Cloudflare tunnel…"

TUNNEL_PID=""
(
    cloudflared tunnel --url "http://localhost:$UI_PORT" 2>&1 | while IFS= read -r line; do
        echo "$line" >&2
        if echo "$line" | grep -qE 'https://[a-z0-9-]+\.trycloudflare\.com'; then
            URL=$(echo "$line" | grep -oE 'https://[a-z0-9-]+\.trycloudflare\.com')
            # Send URL to main process once
            echo "$URL" > "$URL_PIPE" 2>/dev/null || true
        fi
    done
) &
TUNNEL_PID=$!

trap 'kill "$TUNNEL_PID" 2>/dev/null; rm -f "$URL_PIPE"; echo ""; _yellow "Tunnel stopped."; exit 0' INT TERM

# ── Wait for URL ────────────────────────────────────────────────────────────

_yellow "Waiting for tunnel URL…"
LIVE_URL=""
read -t 60 LIVE_URL < "$URL_PIPE" || _die "Timed out waiting for tunnel URL. Is cloudflared reachable?"
rm -f "$URL_PIPE"

echo ""
_bold "════════════════════════════════════════════"
_green "  LIVE URL  →  $LIVE_URL"
_yellow "  Share this link — users open LexAI here"
_bold "════════════════════════════════════════════"
echo ""

# ── Update README.md ────────────────────────────────────────────────────────

_yellow "Updating README.md with new live URL…"

# If a live-demo line already exists, replace the URL in it.
# Otherwise, insert a "Live Demo" line after the first H1 heading.
if grep -q "<!-- live-demo -->" "$README"; then
    sed -i "s|<!-- live-demo -->.*|<!-- live-demo --> **[▶ Open Live Demo]($LIVE_URL)**|" "$README"
else
    # Insert after the first H1 line
    sed -i "0,/^# /{s|^# \(.*\)|# \1\n\n<!-- live-demo --> **[▶ Open Live Demo]($LIVE_URL)**|}" "$README"
fi

_green "✓ README.md updated"

# ── Commit and push ─────────────────────────────────────────────────────────

cd "$REPO_ROOT"

if ! git diff --quiet README.md; then
    git add README.md
    git commit -m "deploy: update live demo URL to $LIVE_URL"
    git push origin main
    _green "✓ README.md committed and pushed to GitHub"
else
    _yellow "README.md unchanged (URL was already up to date)"
fi

# ── Keep tunnel alive ───────────────────────────────────────────────────────

_bold "Tunnel is running. Press Ctrl-C to stop."
wait "$TUNNEL_PID"
