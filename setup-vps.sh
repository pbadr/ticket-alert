#!/usr/bin/env bash
# One-command setup for running the Doomsday ticket checker on your own server.
#
#   curl -fsSL https://raw.githubusercontent.com/pbadr/ticket-alert/main/setup-vps.sh | NTFY_TOPIC=your-topic bash
#
# Optional: INTERVAL=1 (minutes between checks, default 5).
# Safe to re-run: it updates the code and replaces its own cron line.
set -euo pipefail

: "${NTFY_TOPIC:?Set NTFY_TOPIC, e.g.  ... | NTFY_TOPIC=your-topic bash}"
INTERVAL="${INTERVAL:-5}"
DIR="$HOME/ticket-alert"
STATE="$HOME/.doomsday-state.json"   # outside the repo, so 'git pull' never clashes
LOG="$HOME/doomsday.log"

missing=""
for cmd in git python3 crontab flock; do
  command -v "$cmd" >/dev/null 2>&1 || missing="$missing $cmd"
done
if [ -n "$missing" ]; then
  echo "Missing:$missing"
  echo "On Ubuntu/Debian: sudo apt install -y git python3 python3-venv cron util-linux"
  exit 1
fi

echo "1/4 Getting the code..."
if [ -d "$DIR/.git" ]; then
  git -C "$DIR" pull -q
else
  git clone -q https://github.com/pbadr/ticket-alert.git "$DIR"
fi
cd "$DIR"

echo "2/4 Installing requests..."
if ! python3 -m venv .venv >/dev/null 2>&1; then
  echo "Couldn't create a Python venv. On Ubuntu/Debian: sudo apt install -y python3-venv, then re-run."
  exit 1
fi
.venv/bin/pip install -q --disable-pip-version-check requests

echo "3/4 Checking the pages and sending a test ping..."
if ! NTFY_TOPIC="$NTFY_TOPIC" STATE_FILE="$STATE" TEST_PING=true .venv/bin/python check.py; then
  echo "The test ping failed (see the error above), so the schedule was NOT installed."
  exit 1
fi

echo "4/4 Scheduling a check every $INTERVAL min..."
LINE="*/$INTERVAL * * * * cd $DIR && NTFY_TOPIC=$NTFY_TOPIC STATE_FILE=$STATE flock -n /tmp/doomsday.lock .venv/bin/python check.py >> $LOG 2>&1 # ticket-alert"
( crontab -l 2>/dev/null | grep -v '# ticket-alert$' || true; echo "$LINE" ) | crontab -

echo
echo "Done. Checking every $INTERVAL min. Log: $LOG"
echo "Remove later with: crontab -l | grep -v '# ticket-alert\$' | crontab -"
