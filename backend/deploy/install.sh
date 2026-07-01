#!/bin/bash
# VMTools Next — One-click install script for Linux
# Usage: curl -sSL https://example.com/install.sh | bash

set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

log() { echo -e "${GREEN}[vmtools-next]${NC} $1"; }
warn() { echo -e "${YELLOW}[vmtools-next]${NC} $1"; }
error() { echo -e "${RED}[vmtools-next]${NC} $1"; exit 1; }

# Check root
if [ "$EUID" -ne 0 ]; then
    error "Please run as root (sudo ./install.sh)"
fi

# Config
INSTALL_DIR="/opt/vmtools-next"
SERVICE_USER="vmtools"
SERVICE_GROUP="vmtools"
PYTHON_VERSION="3.11"

log "Installing VMTools Next..."

# 1. Install system dependencies
log "Installing system dependencies..."
apt-get update -qq
apt-get install -y -qq python3 python3-pip python3-venv git curl

# 2. Create service user
if ! id "$SERVICE_USER" &>/dev/null; then
    log "Creating service user: $SERVICE_USER"
    useradd -r -s /bin/false -d "$INSTALL_DIR" "$SERVICE_USER"
fi

# 3. Create installation directory
log "Creating installation directory: $INSTALL_DIR"
mkdir -p "$INSTALL_DIR"
cd "$INSTALL_DIR"

# 4. Clone or update repository
if [ -d ".git" ]; then
    log "Updating existing installation..."
    git pull
else
    log "Cloning repository..."
    # Replace with actual repo URL
    # git clone https://github.com/your-org/vmtools-next.git .
    warn "No git repo configured. Please copy project files to $INSTALL_DIR"
fi

# 5. Create virtual environment
log "Creating Python virtual environment..."
python3 -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -e "."

# 6. Create data directories
log "Creating data directories..."
mkdir -p data logs config
chown -R "$SERVICE_USER:$SERVICE_GROUP" data logs

# 7. Copy default config if not exists
if [ ! -f "config/config.yaml" ]; then
    log "Creating default config..."
    cat > config/config.yaml << 'EOF'
server:
  host: 0.0.0.0
  port: 8080
  database_url: sqlite:///data/vmtools-next.db
  secret_key: change-me-in-production

generic:
  enabled: true
  debug_logging: false

mcc:
  protocol: mcp
  mcp_endpoint: http://127.0.0.1:33333/mcp
EOF
fi

# 8. Install systemd service
log "Installing systemd service..."
cp deploy/systemd/vmtools-next.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable vmtools-next

# 9. Set permissions
chown -R "$SERVICE_USER:$SERVICE_GROUP" "$INSTALL_DIR"

# 10. Start service
log "Starting VMTools Next..."
systemctl start vmtools-next

# 11. Check status
sleep 3
if systemctl is-active --quiet vmtools-next; then
    log "✅ VMTools Next installed and running!"
    log ""
    log "  API:  http://$(hostname -I | awk '{print $1}'):8080/api"
    log "  Docs: http://$(hostname -I | awk '{print $1}'):8080/docs"
    log ""
    log "  systemctl status vmtools-next"
    log "  journalctl -u vmtools-next -f"
else
    error "Service failed to start. Check: journalctl -u vmtools-next"
fi
