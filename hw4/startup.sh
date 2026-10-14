#!/bin/bash
set -euo pipefail

export DEBIAN_FRONTEND=noninteractive
APP_DIR=/opt/hw4

# Install required packages for the first time
if [ ! -x "$APP_DIR/venv/bin/python" ]; then
    apt-get -o DPkg::Lock::Timeout=180 update
    apt-get -o DPkg::Lock::Timeout=180 install -y \
        python3 python3-venv curl ca-certificates
fi

# Create a system user
if ! id hw4-app >/dev/null 2>&1; then
    useradd --system --user-group \
        --home-dir "$APP_DIR" \
        --shell /usr/sbin/nologin hw4-app
fi

install -d -m 755 "$APP_DIR"

# Stop the service when the script is re-run
if systemctl cat hw4-app.service >/dev/null 2>&1; then
    systemctl stop hw4-app.service
fi

# Fetch metadata
get_metadata() {
    curl --fail --silent --show-error \
        --retry 5 --connect-timeout 5 --max-time 30 \
        -H "Metadata-Flavor: Google" \
        "http://metadata.google.internal/computeMetadata/v1/instance/attributes/$1"
}

get_metadata app-code > "$APP_DIR/main.py"
get_metadata app-requirements > "$APP_DIR/requirements.txt"
get_metadata app-env > /etc/hw4-app.env

# Remove Windows-style line endings
sed -i 's/\r$//' \
    "$APP_DIR/main.py" \
    "$APP_DIR/requirements.txt" \
    /etc/hw4-app.env

chown root:hw4-app /etc/hw4-app.env
chmod 640 /etc/hw4-app.env

if [ ! -x "$APP_DIR/venv/bin/python" ]; then
    python3 -m venv "$APP_DIR/venv"
fi

# Install the dependencies
"$APP_DIR/venv/bin/python" -m pip install \
    --no-cache-dir --only-binary=:all: \
    -r "$APP_DIR/requirements.txt"

cat > /etc/systemd/system/hw4-app.service <<'UNIT'
[Unit]
Description=EC528 HW4 Python service
Wants=network-online.target
After=network-online.target

[Service]
Type=simple
User=hw4-app
Group=hw4-app
WorkingDirectory=/opt/hw4
EnvironmentFile=/etc/hw4-app.env
Environment=PYTHONUNBUFFERED=1
Environment=PYTHONDONTWRITEBYTECODE=1
ExecStart=/opt/hw4/venv/bin/python /opt/hw4/main.py
Restart=on-failure
RestartSec=5
TimeoutStopSec=30
StandardOutput=journal
StandardError=journal
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=full
ProtectHome=true

[Install]
WantedBy=multi-user.target
UNIT

systemctl daemon-reload
systemctl enable hw4-app.service
systemctl restart hw4-app.service
systemctl --no-pager status hw4-app.service