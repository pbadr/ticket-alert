#!/usr/bin/env bash
# One-command setup for running a Doomsday ticket checker on your own server.
#
#   Cue / Cinestar (default):
#   curl -fsSL https://raw.githubusercontent.com/pbadr/ticket-alert/main/setup-vps.sh | NTFY_TOPIC=your-topic bash
#
#   Nueplex / Cinepax:
#   curl -fsSL https://raw.githubusercontent.com/pbadr/ticket-alert/main/setup-vps.sh | WATCHER=nueplex-cinepax NTFY_TOPIC=other-topic bash
#
# Optional: INTERVAL=1 (minutes between checks, default 5).
# Safe to re-run: it updates the code and replaces only its own cron line,
# so the two watchers can run side by side.
set -euo pipefail

: "${NTFY_TOPIC:?Set NTFY_TOPIC, e.g.  ... | NTFY_TOPIC=your-topic bash}"
INTERVAL="${INTERVAL:-5}"
WATCHER="${WATCHER:-cue-cinestar}"
DIR="$HOME/ticket-alert"
case "$WATCHER" in
  cue-cinestar)
    SCRIPT=check.py
    STATE="$HOME/.doomsday-state.json"   # outside the repo, so 'git pull' never clashes
    LOG="$HOME/doomsday.log"
    LOCK=/tmp/doomsday.lock
    TAG="# ticket-alert" ;;
  nueplex-cinepax)
    SCRIPT=check_nueplex_cinepax.py
    STATE="$HOME/.doomsday-nueplex-cinepax-state.json"
    LOG="$HOME/doomsday-nueplex-cinepax.log"
    LOCK=/tmp/doomsday-nueplex-cinepax.lock
    TAG="# ticket-alert-nueplex-cinepax" ;;
  *)
    echo "Unknown WATCHER '$WATCHER' (use cue-cinestar or nueplex-cinepax)"
    exit 1 ;;
esac

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

echo "3/4 Checking the sites and sending a test ping ($WATCHER)..."
if ! NTFY_TOPIC="$NTFY_TOPIC" STATE_FILE="$STATE" TEST_PING=true .venv/bin/python "$SCRIPT"; then
  echo "The test ping failed (see the error above), so the schedule was NOT installed."
  exit 1
fi

echo "4/4 Scheduling a check every $INTERVAL min..."
LINE="*/$INTERVAL * * * * cd $DIR && NTFY_TOPIC=$NTFY_TOPIC STATE_FILE=$STATE flock -n $LOCK .venv/bin/python $SCRIPT >> $LOG 2>&1 $TAG"
( crontab -l 2>/dev/null | grep -v -- "${TAG}\$" || true; echo "$LINE" ) | crontab -

echo
echo "Done ($WATCHER). Checking every $INTERVAL min. Log: $LOG"
echo "Remove later with: crontab -l | grep -v -- '${TAG}\$' | crontab -"
