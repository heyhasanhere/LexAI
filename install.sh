#!/usr/bin/env bash
# LexAI installer
# Usage:  curl -fsSL https://raw.githubusercontent.com/heyhasanhere/LexAI/main/install.sh | bash
#         — or —
#         bash install.sh
set -euo pipefail

# Open fd 3 to the terminal for interactive prompts.
# When run as `curl | bash`, stdin is the pipe so read would get EOF; /dev/tty
# is the controlling terminal regardless of how stdin is wired.
exec 3</dev/tty

REPO_URL="https://github.com/heyhasanhere/LexAI.git"
INSTALL_DIR="${LEXAI_DIR:-$HOME/lexai}"
LEXAI_REMOTE_URL="${LEXAI_REMOTE_URL:-}"       # set by operator via serve.sh; empty = ask at prompt
LEXAI_REMOTE_MODEL="Qwen/Qwen3-4B-AWQ"

# ── helpers ────────────────────────────────────────────────────────────────────

_green()  { printf '\033[0;32m%s\033[0m\n' "$*"; }
_yellow() { printf '\033[0;33m%s\033[0m\n' "$*"; }
_red()    { printf '\033[0;31m%s\033[0m\n' "$*"; }
_bold()   { printf '\033[1m%s\033[0m\n'   "$*"; }
_die()    { _red "ERROR: $*"; exit 1; }

_require() {
    command -v "$1" &>/dev/null || _die "'$1' is required but not found. $2"
}

# ── OS detection ───────────────────────────────────────────────────────────────

OS="$(uname -s)"
case "$OS" in
    Linux)  DISTRO="$(. /etc/os-release 2>/dev/null && echo "$ID" || echo unknown)" ;;
    Darwin) DISTRO="macos" ;;
    *)      _die "Unsupported OS: $OS. LexAI supports Linux and macOS." ;;
esac

# ── install Docker if missing ──────────────────────────────────────────────────

install_docker() {
    if command -v docker &>/dev/null; then
        _green "✓ Docker already installed ($(docker --version | cut -d' ' -f3 | tr -d ','))"
        return
    fi

    _yellow "Docker not found — installing…"

    case "$DISTRO" in
        ubuntu|debian|linuxmint|pop)
            sudo apt-get update -q
            sudo apt-get install -y -q ca-certificates curl gnupg
            sudo install -m 0755 -d /etc/apt/keyrings
            curl -fsSL https://download.docker.com/linux/ubuntu/gpg \
                | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
            echo \
                "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
                https://download.docker.com/linux/ubuntu \
                $(. /etc/os-release && echo "$VERSION_CODENAME") stable" \
                | sudo tee /etc/apt/sources.list.d/docker.list >/dev/null
            sudo apt-get update -q
            sudo apt-get install -y -q docker-ce docker-ce-cli containerd.io docker-compose-plugin
            sudo usermod -aG docker "$USER"
            _yellow "Added $USER to docker group. You may need to log out and back in."
            ;;
        fedora|rhel|centos|rocky|almalinux)
            sudo dnf -y install dnf-plugins-core
            sudo dnf config-manager --add-repo https://download.docker.com/linux/fedora/docker-ce.repo
            sudo dnf -y install docker-ce docker-ce-cli containerd.io docker-compose-plugin
            sudo systemctl enable --now docker
            sudo usermod -aG docker "$USER"
            ;;
        arch|manjaro)
            sudo pacman -Sy --noconfirm docker docker-compose
            sudo systemctl enable --now docker
            sudo usermod -aG docker "$USER"
            ;;
        macos)
            _die "On macOS, please install Docker Desktop from https://www.docker.com/products/docker-desktop and re-run this script."
            ;;
        *)
            _yellow "Unknown distro '$DISTRO'. Trying generic get.docker.com installer…"
            curl -fsSL https://get.docker.com | sudo sh
            sudo usermod -aG docker "$USER"
            ;;
    esac

    _green "✓ Docker installed"
}

# ── install git if missing ────────────────────────────────────────────────────

install_git() {
    command -v git &>/dev/null && return
    _yellow "git not found — installing…"
    case "$DISTRO" in
        ubuntu|debian|linuxmint|pop) sudo apt-get install -y -q git ;;
        fedora|rhel|centos|rocky|almalinux) sudo dnf -y install git ;;
        arch|manjaro) sudo pacman -Sy --noconfirm git ;;
        macos) xcode-select --install 2>/dev/null || true ;;
        *) _die "Cannot auto-install git on $DISTRO. Please install it manually." ;;
    esac
}

# ── clone or update repo ───────────────────────────────────────────────────────

fetch_repo() {
    if [[ -d "$INSTALL_DIR/.git" ]]; then
        _yellow "LexAI already cloned — pulling latest…"
        git -C "$INSTALL_DIR" pull --ff-only
    else
        _yellow "Cloning LexAI into $INSTALL_DIR…"
        git clone "$REPO_URL" "$INSTALL_DIR"
    fi
    _green "✓ Repository ready"
}

# ── interactive setup ──────────────────────────────────────────────────────────

choose_mode() {
    echo ""
    _bold "How do you want to run the LLM?"
    echo ""
    echo "  Free cloud (no GPU needed):"
    echo "  1) Groq          — free tier, llama-3.1-8b-instant (fastest)"
    echo "  2) OpenRouter    — free models (llama-3.1-8b, gemma-3, qwen3 etc.)"
    echo "  3) Google Gemini — free tier, gemini-2.0-flash-lite"
    echo "  4) Mistral       — free tier, mistral-small-latest"
    echo ""
    echo "  Paid cloud:"
    echo "  5) OpenAI        — your key, gpt-4o-mini"
    echo ""
    echo "  Self-hosted:"
    echo "  6) LexAI remote GPU — free, rate-limited Qwen3-4B hosted by the operator"
    echo "  7) Local GPU        — run Qwen3-4B on your own NVIDIA GPU (~5 GB VRAM)"
    echo ""
    printf 'Enter choice [1-7]: '
    read -r MODE_CHOICE <&3

    HF_TOKEN=""

    case "$MODE_CHOICE" in
        1)
            echo ""
            printf 'Groq API key (get one free at console.groq.com): '
            read -r LLM_API_KEY <&3
            [[ -z "$LLM_API_KEY" ]] && _die "API key cannot be empty."
            printf 'Model [llama-3.1-8b-instant]: '
            read -r _M <&3
            LLM_PROVIDER="groq"
            LLM_BASE_URL="https://api.groq.com/openai/v1"
            LLM_MODEL="${_M:-llama-3.1-8b-instant}"
            COMPOSE_PROFILES="lite"
            ;;
        2)
            echo ""
            printf 'OpenRouter API key (get one free at openrouter.ai): '
            read -r LLM_API_KEY <&3
            [[ -z "$LLM_API_KEY" ]] && _die "API key cannot be empty."
            printf 'Model [meta-llama/llama-3.1-8b-instruct:free]: '
            read -r _M <&3
            LLM_PROVIDER="openrouter"
            LLM_BASE_URL="https://openrouter.ai/api/v1"
            LLM_MODEL="${_M:-meta-llama/llama-3.1-8b-instruct:free}"
            COMPOSE_PROFILES="lite"
            ;;
        3)
            echo ""
            printf 'Google AI Studio API key (get one free at aistudio.google.com): '
            read -r LLM_API_KEY <&3
            [[ -z "$LLM_API_KEY" ]] && _die "API key cannot be empty."
            printf 'Model [gemini-2.0-flash-lite]: '
            read -r _M <&3
            LLM_PROVIDER="gemini"
            LLM_BASE_URL="https://generativelanguage.googleapis.com/v1beta/openai/"
            LLM_MODEL="${_M:-gemini-2.0-flash-lite}"
            COMPOSE_PROFILES="lite"
            ;;
        4)
            echo ""
            printf 'Mistral API key (get one free at console.mistral.ai): '
            read -r LLM_API_KEY <&3
            [[ -z "$LLM_API_KEY" ]] && _die "API key cannot be empty."
            printf 'Model [mistral-small-latest]: '
            read -r _M <&3
            LLM_PROVIDER="mistral"
            LLM_BASE_URL="https://api.mistral.ai/v1"
            LLM_MODEL="${_M:-mistral-small-latest}"
            COMPOSE_PROFILES="lite"
            ;;
        5)
            echo ""
            printf 'OpenAI API key (sk-…): '
            read -r LLM_API_KEY <&3
            [[ -z "$LLM_API_KEY" ]] && _die "API key cannot be empty."
            printf 'Model [gpt-4o-mini]: '
            read -r _M <&3
            LLM_PROVIDER="openai"
            LLM_BASE_URL="https://api.openai.com/v1"
            LLM_MODEL="${_M:-gpt-4o-mini}"
            COMPOSE_PROFILES="lite"
            ;;
        6)
            echo ""
            if [[ -z "$LEXAI_REMOTE_URL" ]]; then
                printf 'Remote GPU URL (ask the operator running serve.sh): '
                read -r LEXAI_REMOTE_URL <&3
                [[ -z "$LEXAI_REMOTE_URL" ]] && _die "Remote URL cannot be empty."
            fi
            _yellow "Using remote GPU at: $LEXAI_REMOTE_URL"
            LLM_PROVIDER="vllm"
            LLM_BASE_URL="$LEXAI_REMOTE_URL"
            LLM_MODEL="$LEXAI_REMOTE_MODEL"
            LLM_API_KEY="lexai-public"
            COMPOSE_PROFILES="lite"
            ;;
        7)
            echo ""
            _yellow "Checking for NVIDIA GPU…"
            command -v nvidia-smi &>/dev/null || _die "nvidia-smi not found. Install NVIDIA drivers first."
            VRAM=$(nvidia-smi --query-gpu=memory.total --format=csv,noheader,nounits | awk '{s+=$1} END {print s}')
            _green "Total VRAM: ${VRAM} MiB across $(nvidia-smi --list-gpus | wc -l) GPU(s)"
            (( VRAM < 5000 )) && _yellow "Warning: Qwen3-4B-AWQ needs ~5 GB VRAM. Detected ${VRAM} MiB."

            LLM_PROVIDER="vllm"
            LLM_BASE_URL="http://vllm:8000/v1"
            LLM_MODEL="Qwen/Qwen3-4B-AWQ"
            LLM_API_KEY="local"
            COMPOSE_PROFILES="full"

            printf 'HuggingFace token (optional, speeds up model download) [skip]: '
            read -r HF_TOKEN <&3
            HF_TOKEN="${HF_TOKEN:-}"
            ;;
        *)
            _die "Invalid choice '$MODE_CHOICE'. Run install.sh again."
            ;;
    esac
}

write_env() {
    cat > "$INSTALL_DIR/.env" <<EOF
# Generated by install.sh on $(date -u +"%Y-%m-%dT%H:%M:%SZ")
COMPOSE_PROFILES=${COMPOSE_PROFILES}

LD_LLM__PROVIDER=${LLM_PROVIDER}
LD_LLM__BASE_URL=${LLM_BASE_URL}
LD_LLM__MODEL=${LLM_MODEL}
LD_LLM__API_KEY=${LLM_API_KEY}

HF_TOKEN=${HF_TOKEN:-}
EOF
    _green "✓ .env written"
}

# ── bring up services ──────────────────────────────────────────────────────────

start_services() {
    cd "$INSTALL_DIR"
    _yellow "Building application image (first run takes ~3 min)…"
    docker compose build --quiet api

    _yellow "Starting services (profile: $COMPOSE_PROFILES)…"
    docker compose up -d

    _yellow "Waiting for API to become healthy…"
    for i in $(seq 1 30); do
        sleep 5
        STATUS=$(curl -sf http://localhost:8000/health 2>/dev/null | grep -o '"status":"ok"' || true)
        if [[ -n "$STATUS" ]]; then
            _green "✓ API is healthy"
            break
        fi
        printf '.'
    done
    echo ""
}

# ── summary ────────────────────────────────────────────────────────────────────

print_summary() {
    echo ""
    _bold "══════════════════════════════════════"
    _bold "  LexAI is running"
    _bold "══════════════════════════════════════"
    echo ""
    _green "  UI:   http://localhost:8501"
    _green "  API:  http://localhost:8000"
    _green "  Docs: http://localhost:8000/docs"
    echo ""
    echo "  To stop:    docker compose --project-directory $INSTALL_DIR down"
    echo "  To restart: docker compose --project-directory $INSTALL_DIR up -d"
    echo ""
}

# ── main ───────────────────────────────────────────────────────────────────────

main() {
    echo ""
    _bold "LexAI — Legal Document Analysis Platform"
    _bold "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo ""

    install_git
    install_docker
    fetch_repo
    choose_mode
    write_env
    start_services
    print_summary
}

main "$@"
