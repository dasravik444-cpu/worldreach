#!/usr/bin/env bash
# Runs one WorldReach command with everything it needs:  bash scripts/run.sh COMMAND [options]   (see  wr help )
# The first time it makes settings.txt and installs what is needed (a few minutes).
cd "$(dirname "$0")/.." || exit 1
if [ ! -f settings.txt ]; then
  cp settings-example.txt settings.txt
  chmod 600 settings.txt
fi
# Installs what it needs the first time, and again after an update that needs something new.
if ! cmp -s requirements.txt .venv/.installed; then
  echo "Installing what it needs - this takes a few minutes..."
  python3 -m venv .venv || { echo "Could not set up Python (on Ubuntu first run: apt install -y python3-venv)"; exit 1; }
  .venv/bin/python -m pip install --quiet --upgrade pip || exit 1
  .venv/bin/python -m pip install --quiet -r requirements.txt || exit 1
  cp requirements.txt .venv/.installed
fi
mkdir -p data
exec .venv/bin/python -m worldreach "$@"
