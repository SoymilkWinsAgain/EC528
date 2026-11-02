#!/usr/bin/env bash
set -euo pipefail

APP_DIR="/opt/hw5"
LOCK_FILE="/var/log/startup_already_done"

mkdir -p "$APP_DIR/service1" "$APP_DIR/service2"

# Install system packages and create the virtual environment once.
if [ ! -f "$LOCK_FILE" ]; then
    export DEBIAN_FRONTEND=noninteractive
    apt-get update
    apt-get -o DPkg::Lock::Timeout=180 install -y python3-venv curl
    python3 -m venv "$APP_DIR/venv"
fi

# Read files provided through VM metadata.
get_metadata() {
    curl --fail --silent --show-error \
        -H "Metadata-Flavor: Google" \
        "http://metadata.google.internal/computeMetadata/v1/instance/attributes/$1"
}

for module in main database db_pool request_data timing; do
    get_metadata "service1-$module" \
        > "$APP_DIR/service1/$module.py"
done

get_metadata service2-main > "$APP_DIR/service2/main.py"
get_metadata requirements > "$APP_DIR/requirements.txt"
get_metadata app-env > "$APP_DIR/app.env"

sed -i 's/\r$//' "$APP_DIR/requirements.txt" "$APP_DIR/app.env"
chmod 600 "$APP_DIR/app.env"

# Install Python dependencies once.
if [ ! -f "$LOCK_FILE" ]; then
    "$APP_DIR/venv/bin/python" -m pip install \
        -r "$APP_DIR/requirements.txt"
fi

# Register both applications as system services.
for app in service1 service2; do
    cat > "/etc/systemd/system/hw5-$app.service" <<EOF
[Unit]
Description=EC528 HW5 $app
Wants=network-online.target
After=network-online.target

[Service]
WorkingDirectory=$APP_DIR
EnvironmentFile=$APP_DIR/app.env
Environment=PYTHONUNBUFFERED=1
ExecStart=$APP_DIR/venv/bin/python $APP_DIR/$app/main.py
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF
done

systemctl daemon-reload
systemctl enable hw5-service1.service hw5-service2.service
systemctl restart hw5-service1.service hw5-service2.service

touch "$LOCK_FILE"
echo "HW5 startup completed."