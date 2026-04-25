#!/usr/bin/env bash
# Instalador do BrownieSystem para Armbian / Debian-based Linux
set -euo pipefail

# ── Cores ────────────────────────────────────────────────────
GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'
CYAN='\033[0;36m'; BOLD='\033[1m'; NC='\033[0m'

ok()   { echo -e "${GREEN}  ✓ $*${NC}"; }
info() { echo -e "${YELLOW}  → $*${NC}"; }
warn() { echo -e "${YELLOW}  ! $*${NC}"; }
err()  { echo -e "${RED}  ✗ $*${NC}" >&2; exit 1; }

# ── Configuração ─────────────────────────────────────────────
APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_NAME="BrownieSystem"
SERVICE_FILE="/etc/systemd/system/${APP_NAME}.service"
VENV_DIR="${APP_DIR}/venv"
ENV_FILE="${APP_DIR}/.env"
CONFIG_FILE="${APP_DIR}/config.ini"

# Lê a porta do config.ini; variável de ambiente PORT tem prioridade
_cfg_port() {
    sed -n '/^\[server\]/,/^\[/{
        /^[[:space:]]*port[[:space:]]*=/{
            s/^[^=]*=[[:space:]]*//; s/[[:space:]]*[#;].*//; s/[[:space:]]//g; p
        }
    }' "${CONFIG_FILE}" 2>/dev/null | head -1
}
_FILE_PORT=$( [[ -f "${CONFIG_FILE}" ]] && _cfg_port || echo "" )
PORT="${PORT:-${_FILE_PORT:-5000}}"

# Usuário que vai executar o serviço (o que chamou sudo, ou root)
RUN_USER="${SUDO_USER:-$(whoami)}"
RUN_HOME=$(getent passwd "${RUN_USER}" | cut -d: -f6)

# ── Banner ───────────────────────────────────────────────────
echo -e "\n${CYAN}${BOLD}"
echo "  ╔══════════════════════════════════════╗"
echo "  ║         BrownieSystem  —  Instalador        ║"
echo "  ╚══════════════════════════════════════╝"
echo -e "${NC}"

# ── Requer root ──────────────────────────────────────────────
[[ $EUID -ne 0 ]] && err "Execute com privilégios root:  sudo bash install.sh"

echo -e "  Diretório : ${CYAN}${APP_DIR}${NC}"
echo -e "  Serviço   : ${CYAN}${APP_NAME}${NC}"
echo -e "  Usuário   : ${CYAN}${RUN_USER}${NC}"
echo -e "  Porta     : ${CYAN}${PORT}${NC}  (configurável em config.ini → [server] port)"
echo ""

# ── Dependências do sistema ──────────────────────────────────
info "Verificando dependências do sistema..."

command -v python3 &>/dev/null \
    || err "python3 não encontrado. Instale com:  apt install python3 python3-venv"

python3 -m venv --help &>/dev/null 2>&1 \
    || err "python3-venv não encontrado. Instale com:  apt install python3-venv"

ok "Python $(python3 --version) disponível"

# ── Para serviço existente ───────────────────────────────────
if systemctl is-active --quiet "${APP_NAME}" 2>/dev/null; then
    info "Parando serviço existente..."
    systemctl stop "${APP_NAME}"
    ok "Serviço parado"
fi

# ── Ambiente virtual ─────────────────────────────────────────
if [[ -d "${VENV_DIR}" ]]; then
    info "Removendo venv anterior..."
    rm -rf "${VENV_DIR}"
fi

info "Criando ambiente virtual..."
python3 -m venv "${VENV_DIR}"
chown -R "${RUN_USER}:${RUN_USER}" "${VENV_DIR}"
ok "Ambiente virtual criado em ${VENV_DIR}"

# ── Dependências Python ──────────────────────────────────────
info "Atualizando pip..."
"${VENV_DIR}/bin/pip" install --upgrade pip --quiet

info "Instalando requirements.txt..."
"${VENV_DIR}/bin/pip" install -r "${APP_DIR}/requirements.txt" --quiet
chown -R "${RUN_USER}:${RUN_USER}" "${VENV_DIR}"
ok "Dependências instaladas"

# ── Chave secreta ────────────────────────────────────────────
if [[ -f "${ENV_FILE}" ]]; then
    warn ".env já existe — mantendo chave secreta atual"
else
    info "Gerando chave secreta aleatória..."
    SECRET=$(python3 -c "import secrets; print(secrets.token_hex(32))")
    echo "SECRET_KEY=${SECRET}" > "${ENV_FILE}"
    chown "${RUN_USER}:${RUN_USER}" "${ENV_FILE}" 2>/dev/null || true
    chmod 600 "${ENV_FILE}"
    ok "Chave secreta salva em .env"
fi

# ── Serviço systemd ──────────────────────────────────────────
info "Criando serviço systemd em ${SERVICE_FILE}..."

# Número de workers: 2 para dispositivos ARM com memória limitada
WORKERS=2

cat > "${SERVICE_FILE}" <<EOF
[Unit]
Description=BrownieSystem
After=network.target

[Service]
Type=simple
User=${RUN_USER}
Group=${RUN_USER}
WorkingDirectory=${APP_DIR}
EnvironmentFile=${ENV_FILE}
ExecStart=${VENV_DIR}/bin/gunicorn \\
    --workers ${WORKERS} \\
    --bind 0.0.0.0:${PORT} \\
    --access-logfile - \\
    --error-logfile - \\
    --timeout 60 \\
    app:app
Restart=on-failure
RestartSec=5
StandardOutput=journal
StandardError=journal
SyslogIdentifier=${APP_NAME}

[Install]
WantedBy=multi-user.target
EOF

ok "Arquivo de serviço criado"

# ── Habilita na inicialização ────────────────────────────────
info "Recarregando systemd e habilitando serviço..."
systemctl daemon-reload
systemctl enable "${APP_NAME}"
ok "Serviço habilitado (inicia automaticamente no boot)"

# ── Iniciar agora? ───────────────────────────────────────────
echo ""
read -r -p "  Iniciar o BrownieSystem agora? [S/n] " REPLY
REPLY="${REPLY:-S}"
if [[ "${REPLY}" =~ ^[Ss]$ ]]; then
    info "Iniciando serviço..."
    systemctl start "${APP_NAME}"
    sleep 2
    if systemctl is-active --quiet "${APP_NAME}"; then