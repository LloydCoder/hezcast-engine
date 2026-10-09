#!/bin/bash
# ═══════════════════════════════════════════════════════════════
# HezCast Engine — VPS Setup Script
# Tinlance Limited | Apache 2.0
#
# One command deploys the complete HezCast stack:
#   - Docker + Docker Compose
#   - Clones repo from GitHub
#   - Interactive .env setup
#   - Piper TTS voice models (3 brands)
#   - Whisper base model
#   - Starts all containers
#   - Health check verification
#   - Telegram webhook registration (optional)
#
# Usage:
#   curl -sSL https://raw.githubusercontent.com/LloydCoder/hezcast-engine/main/setup.sh | bash
#
# Or locally:
#   chmod +x setup.sh && ./setup.sh
# ═══════════════════════════════════════════════════════════════

set -e

# ── Colors ────────────────────────────────────────────────────
CYAN='\033[0;36m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
WHITE='\033[1;37m'
RESET='\033[0m'

# ── Config ─────────────────────────────────────────────────────
REPO="https://github.com/LloydCoder/hezcast-engine.git"
INSTALL_DIR="${HOME}/hezcast-engine"
API_PORT="8503"
PIPER_VERSION="2023.11.14-2"
PIPER_BASE="https://github.com/rhasspy/piper/releases/download/${PIPER_VERSION}"

# ── Banner ─────────────────────────────────────────────────────
print_banner() {
    echo -e "${CYAN}"
    echo "  ╦ ╦╔═╗╔═╗╔═╗╔═╗╔═╗╔╦╗"
    echo "  ╠═╣║╣ ╔═╝║  ╠═╣╚═╗ ║ "
    echo "  ╩ ╩╚═╝╚═╝╚═╝╩ ╩╚═╝ ╩ "
    echo -e "${WHITE}  AI Content Broadcasting System${RESET}"
    echo -e "${CYAN}  by Tinlance Limited${RESET}"
    echo ""
    echo -e "${CYAN}════════════════════════════════════════${RESET}"
    echo ""
}

log()     { echo -e "${GREEN}✓${RESET} $1"; }
info()    { echo -e "${CYAN}→${RESET} $1"; }
warn()    { echo -e "${YELLOW}⚠${RESET}  $1"; }
error()   { echo -e "${RED}✗${RESET} $1"; exit 1; }
section() { echo -e "\n${CYAN}── $1 ──────────────────────────────${RESET}"; }

# ── OS Check ───────────────────────────────────────────────────
check_os() {
    section "System Check"
    if [[ "$(uname)" != "Linux" ]]; then
        error "HezCast setup requires Linux (Ubuntu 22.04+ recommended)"
    fi
    if ! command -v apt-get &>/dev/null; then
        warn "apt-get not found — assuming manual package management"
    fi
    log "OS: $(uname -srm)"
    log "User: $(whoami)"
    log "Home: ${HOME}"
}

# ── Docker Install ─────────────────────────────────────────────
install_docker() {
    section "Docker"

    if command -v docker &>/dev/null; then
        log "Docker already installed: $(docker --version)"
        return
    fi

    info "Installing Docker..."
    curl -fsSL https://get.docker.com | sh
    usermod -aG docker "$USER" 2>/dev/null || true
    log "Docker installed"

    if ! command -v docker compose &>/dev/null; then
        info "Installing Docker Compose plugin..."
        apt-get install -y docker-compose-plugin 2>/dev/null || \
        pip install docker-compose --break-system-packages 2>/dev/null || \
        warn "Could not install docker-compose — install manually"
    fi
    log "Docker Compose ready"
}

# ── Clone Repo ─────────────────────────────────────────────────
clone_repo() {
    section "Repository"

    if [[ -d "${INSTALL_DIR}" ]]; then
        info "Directory exists — pulling latest..."
        cd "${INSTALL_DIR}"
        git pull origin main
        log "Repository updated"
    else
        info "Cloning HezCast Engine..."
        git clone "${REPO}" "${INSTALL_DIR}"
        log "Repository cloned to ${INSTALL_DIR}"
    fi

    cd "${INSTALL_DIR}"
}

# ── Environment Setup ──────────────────────────────────────────
setup_env() {
    section "Environment Configuration"

    if [[ -f ".env" ]]; then
        warn ".env already exists — skipping (delete it to reconfigure)"
        return
    fi

    cp .env.example .env
    info "Configuring .env — enter your API keys:"
    echo ""

    # Claude API Key
    echo -e "${WHITE}Claude API Key${RESET} (primary LLM — get from console.anthropic.com):"
    read -r -p "  CLAUDE_API_KEY= " CLAUDE_KEY
    sed -i "s|CLAUDE_API_KEY=.*|CLAUDE_API_KEY=${CLAUDE_KEY}|" .env

    # OpenAI (optional)
    echo -e "${WHITE}OpenAI API Key${RESET} (GPT-4o fallback — press Enter to skip):"
    read -r -p "  OPENAI_API_KEY= " OPENAI_KEY
    if [[ -n "${OPENAI_KEY}" ]]; then
        sed -i "s|OPENAI_API_KEY=.*|OPENAI_API_KEY=${OPENAI_KEY}|" .env
    fi

    # Pexels API Key
    echo -e "${WHITE}Pexels API Key${RESET} (free at pexels.com/api — for stock video clips):"
    read -r -p "  PEXELS_API_KEY= " PEXELS_KEY
    sed -i "s|PEXELS_API_KEY=.*|PEXELS_API_KEY=${PEXELS_KEY}|" .env

    # DB Password
    DB_PASS=$(openssl rand -hex 16 2>/dev/null || echo "hezcast_$(date +%s)")
    sed -i "s|DB_PASSWORD=.*|DB_PASSWORD=${DB_PASS}|" .env

    # Telegram (optional)
    echo -e "${WHITE}Telegram Bot Token${RESET} (from @BotFather — press Enter to skip):"
    read -r -p "  TELEGRAM_BOT_TOKEN= " TG_TOKEN
    if [[ -n "${TG_TOKEN}" ]]; then
        sed -i "s|TELEGRAM_BOT_TOKEN=.*|TELEGRAM_BOT_TOKEN=${TG_TOKEN}|" .env
        echo -e "${WHITE}Telegram Channel ID${RESET} (e.g. @hezcast_content):"
        read -r -p "  TELEGRAM_CHAT_ID= " TG_CHAT
        sed -i "s|TELEGRAM_CHAT_ID=.*|TELEGRAM_CHAT_ID=${TG_CHAT}|" .env
    fi

    # B2 (optional)
    echo -e "${WHITE}Backblaze B2 Key ID${RESET} (optional — for video archiving, press Enter to skip):"
    read -r -p "  B2_KEY_ID= " B2_KEY
    if [[ -n "${B2_KEY}" ]]; then
        sed -i "s|B2_KEY_ID=.*|B2_KEY_ID=${B2_KEY}|" .env
        echo -e "${WHITE}Backblaze B2 App Key:${RESET}"
        read -r -p "  B2_APP_KEY= " B2_APP
        sed -i "s|B2_APP_KEY=.*|B2_APP_KEY=${B2_APP}|" .env
    fi

    sed -i "s|ENVIRONMENT=.*|ENVIRONMENT=production|" .env
    log ".env configured"
}

# ── Piper TTS Models ───────────────────────────────────────────
download_voice_models() {
    section "Voice Models (Piper TTS)"

    mkdir -p config/voices

    # Brand voice models
    declare -A VOICE_MODELS=(
        ["en_US-lessac-medium"]="giftmode"       # Maya — warm emotional
        ["en_US-ryan-medium"]="tinlance"          # Lloyd — authoritative
        ["en_US-arctic-medium"]="hezcast"         # HezCast — founder energy
    )

    PIPER_BIN=""
    if command -v piper &>/dev/null; then
        PIPER_BIN="piper"
        log "Piper TTS binary found: $(piper --version 2>/dev/null || echo 'installed')"
    else
        info "Piper TTS not in PATH — downloading binary..."
        ARCH=$(uname -m)
        case "${ARCH}" in
            x86_64)  PIPER_ARCH="amd64" ;;
            aarch64) PIPER_ARCH="arm64" ;;
            *)       warn "Unsupported arch ${ARCH} — install Piper manually"; return ;;
        esac

        PIPER_URL="${PIPER_BASE}/piper_linux_${PIPER_ARCH}.tar.gz"
        mkdir -p models/piper/bin
        curl -L "${PIPER_URL}" | tar -xz -C models/piper/bin --strip-components=1
        PIPER_BIN="$(pwd)/models/piper/bin/piper"
        sed -i "s|PIPER_BIN=.*|PIPER_BIN=${PIPER_BIN}|" .env 2>/dev/null || \
            echo "PIPER_BIN=${PIPER_BIN}" >> .env
        log "Piper TTS binary installed"
    fi

    # Download voice models
    for MODEL_NAME in "${!VOICE_MODELS[@]}"; do
        BRAND="${VOICE_MODELS[$MODEL_NAME]}"
        ONNX_PATH="config/voices/${BRAND}.onnx"
        JSON_PATH="config/voices/${BRAND}.onnx.json"

        if [[ -f "${ONNX_PATH}" ]]; then
            log "Voice model already exists: ${BRAND}"
            continue
        fi

        info "Downloading voice model: ${MODEL_NAME} → ${BRAND}..."
        MODEL_URL="https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/${MODEL_NAME}/${MODEL_NAME}.onnx"
        CONFIG_URL="https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/${MODEL_NAME}/${MODEL_NAME}.onnx.json"

        curl -L --progress-bar "${MODEL_URL}" -o "${ONNX_PATH}" || \
            warn "Could not download ${MODEL_NAME} — voice will use fallback"
        curl -L --silent "${CONFIG_URL}" -o "${JSON_PATH}" || true

        if [[ -f "${ONNX_PATH}" ]]; then
            log "Voice model ready: ${BRAND} (${MODEL_NAME})"
        fi
    done

    # Copy hezcast model for webtemify too
    if [[ -f "config/voices/hezcast.onnx" ]]; then
        cp config/voices/hezcast.onnx config/voices/webtemify.onnx 2>/dev/null || true
        cp config/voices/hezcast.onnx.json config/voices/webtemify.onnx.json 2>/dev/null || true
    fi
}

# ── Whisper Model ──────────────────────────────────────────────
download_whisper_model() {
    section "Whisper Model"

    mkdir -p models/whisper

    if [[ -f "models/whisper/base.pt" ]] || [[ -f "models/whisper/base.bin" ]]; then
        log "Whisper model already downloaded"
        return
    fi

    info "Whisper model will download on first subtitle job (faster-whisper auto-downloads)"
    info "Model: faster-whisper base (CPU optimized, ~140MB)"
    log "Whisper configured for auto-download"
}

# ── Storage Directories ────────────────────────────────────────
setup_storage() {
    section "Storage"

    mkdir -p storage/{inputs,clips,outputs,clip_index}
    mkdir -p config/{personas,voices}
    mkdir -p models/{musetalk,sadtalker,piper,whisper}
    mkdir -p logs

    log "Storage directories created"
}

# ── Docker Stack ───────────────────────────────────────────────
start_docker_stack() {
    section "Starting HezCast Stack"

    cd "${INSTALL_DIR}"

    info "Pulling Docker images..."
    docker compose pull --quiet 2>/dev/null || docker-compose pull --quiet 2>/dev/null

    info "Starting containers..."
    docker compose up -d 2>/dev/null || docker-compose up -d 2>/dev/null

    log "Containers started"

    # Wait for API to be ready
    info "Waiting for API to be ready..."
    MAX_WAIT=60
    WAITED=0
    while [[ ${WAITED} -lt ${MAX_WAIT} ]]; do
        if curl -sf "http://localhost:${API_PORT}/health" &>/dev/null; then
            log "API is healthy"
            break
        fi
        sleep 2
        WAITED=$((WAITED + 2))
        echo -n "."
    done
    echo ""

    if [[ ${WAITED} -ge ${MAX_WAIT} ]]; then
        warn "API did not respond in ${MAX_WAIT}s — check logs: docker compose logs api"
    fi
}

# ── Telegram Webhook ───────────────────────────────────────────
register_telegram_webhook() {
    section "Telegram Webhook"

    TG_TOKEN=$(grep "TELEGRAM_BOT_TOKEN=" .env | cut -d'=' -f2)
    DOMAIN=$(grep "DOMAIN=" .env | cut -d'=' -f2)

    if [[ -z "${TG_TOKEN}" ]] || [[ "${TG_TOKEN}" == "your_bot_token" ]]; then
        info "No Telegram token configured — skipping webhook registration"
        return
    fi

    if [[ -z "${DOMAIN}" ]]; then
        warn "DOMAIN not set in .env — skipping webhook registration"
        info "Set DOMAIN=cast.tinlance.com and re-run to register webhook"
        return
    fi

    WEBHOOK_URL="https://${DOMAIN}/telegram/webhook"
    info "Registering Telegram webhook: ${WEBHOOK_URL}"

    RESULT=$(curl -sf "https://api.telegram.org/bot${TG_TOKEN}/setWebhook?url=${WEBHOOK_URL}" || echo "failed")

    if echo "${RESULT}" | grep -q '"ok":true'; then
        log "Telegram webhook registered: ${WEBHOOK_URL}"
    else
        warn "Webhook registration failed — register manually:"
        warn "  curl 'https://api.telegram.org/bot<TOKEN>/setWebhook?url=${WEBHOOK_URL}'"
    fi
}

# ── Health Check ───────────────────────────────────────────────
run_health_check() {
    section "Health Check"

    # API health
    if curl -sf "http://localhost:${API_PORT}/health" | grep -q '"status"'; then
        log "API: ✓ healthy at http://localhost:${API_PORT}"
    else
        warn "API: not responding — check: docker compose logs api"
    fi

    # Brands endpoint
    BRANDS=$(curl -sf "http://localhost:${API_PORT}/brands" 2>/dev/null | grep -o '"name"' | wc -l)
    if [[ "${BRANDS}" -gt 0 ]]; then
        log "Brands: ✓ ${BRANDS} brands configured"
    fi

    # Test job submission
    JOB_RESP=$(curl -sf -X POST "http://localhost:${API_PORT}/generate" \
        -H "Content-Type: application/json" \
        -d '{"topic":"hezcast test job","brand":"HezCast"}' 2>/dev/null || echo "")

    if echo "${JOB_RESP}" | grep -q '"job_id"'; then
        JOB_ID=$(echo "${JOB_RESP}" | grep -o '"job_id":"[^"]*"' | cut -d'"' -f4)
        log "Pipeline: ✓ test job submitted — job_id: ${JOB_ID}"
    else
        warn "Pipeline: test job submission failed"
    fi
}

# ── Summary ────────────────────────────────────────────────────
print_summary() {
    section "Setup Complete"

    echo ""
    echo -e "${GREEN}╔═══════════════════════════════════════╗${RESET}"
    echo -e "${GREEN}║     HezCast Engine is LIVE  ⚡        ║${RESET}"
    echo -e "${GREEN}╚═══════════════════════════════════════╝${RESET}"
    echo ""
    echo -e "${WHITE}API:${RESET}         http://localhost:${API_PORT}"
    echo -e "${WHITE}Health:${RESET}      http://localhost:${API_PORT}/health"
    echo -e "${WHITE}Brands:${RESET}      http://localhost:${API_PORT}/brands"
    echo -e "${WHITE}Dashboard:${RESET}   http://localhost:5556 (Flower — dev mode)"
    echo ""
    echo -e "${WHITE}Generate your first video:${RESET}"
    echo ""
    echo "  curl -X POST http://localhost:${API_PORT}/generate \\"
    echo "    -H 'Content-Type: application/json' \\"
    echo "    -d '{\"topic\":\"forgot birthday gift\",\"brand\":\"GiftMode\"}'"
    echo ""
    echo -e "${WHITE}View logs:${RESET}"
    echo "  docker compose logs -f api"
    echo "  docker compose logs -f worker"
    echo ""
    echo -e "${WHITE}Stop stack:${RESET}"
    echo "  docker compose down"
    echo ""
    echo -e "${CYAN}God strengthens. So does your content. — HezCast${RESET}"
    echo ""
}

# ── Main ───────────────────────────────────────────────────────
main() {
    print_banner
    check_os
    install_docker
    clone_repo
    setup_env
    setup_storage
    download_voice_models
    download_whisper_model
    start_docker_stack
    register_telegram_webhook
    run_health_check
    print_summary
}

main "$@"
EOF