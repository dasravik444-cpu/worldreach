#!/usr/bin/env bash
# WorldReach on a small online server (Ubuntu 22.04 or 24.04), instead of the tablet. docs/HOSTING.md has the steps.
# On the server, signed in as root, paste:
#   curl -fsSL https://raw.githubusercontent.com/dasravik444-cpu/worldreach/main/server/setup.sh | bash
# It installs Python and WorldReach into /opt/worldreach, adds the command  wr , and sets the robot up as a
# service that starts by itself after a restart of the server. Run it again any time: it only updates.
set -e
REPO=https://github.com/dasravik444-cpu/worldreach
DIR=/opt/worldreach
[ "$(id -u)" = 0 ] || { echo "Run this as root (sudo -i first)."; exit 1; }
export DEBIAN_FRONTEND=noninteractive
echo "== 1/4 What it needs..."
apt-get -y -o Acquire::Retries=5 update
apt-get -y -o Acquire::Retries=5 install --no-install-recommends python3 python3-venv git nano ca-certificates curl
echo "== 2/4 WorldReach..."
if [ -d "$DIR/.git" ]; then git -C "$DIR" pull --ff-only; else git clone "$REPO" "$DIR"; fi
mkdir -p "$DIR/data" "$DIR/secrets"
chmod 700 "$DIR/secrets"
echo "== 3/4 The  wr  command and the service..."
install -m 755 "$DIR/server/wr.sh" /usr/local/bin/wr
cat > /etc/systemd/system/worldreach.service <<UNIT
[Unit]
Description=WorldReach robot
After=network-online.target
Wants=network-online.target

[Service]
WorkingDirectory=$DIR
ExecStartPre=/bin/rm -f $DIR/data/robot.stop
ExecStart=/bin/bash $DIR/scripts/run.sh robot serve
Restart=always
RestartSec=20
TimeoutStopSec=200
KillSignal=SIGTERM

[Install]
WantedBy=multi-user.target
UNIT
systemctl daemon-reload
echo "== 4/4 Installing what Python needs (a few minutes the first time)..."
(cd "$DIR" && bash scripts/run.sh preview gym >/dev/null) || echo "(The first start had a problem: type  wr check  to see it.)"
echo
echo "Done. Next:   wr settings   then   wr check     (docs/HOSTING.md)"
