#!/usr/bin/env bash
# The  wr  command in Termux (made by android/setup.sh). Type  wr  alone for this list.
#
#   wr on / wr off        start the robot (it then works by itself, every day) / stop it
#   wr status             is it running, the mailboxes' warm-up, leads, e-mails, replies
#   wr log [LINES]        the end of today's log
#   wr settings           open your settings (settings.txt)
#   wr getkey             copy your Google key file (.json) from the Download folder
#   wr check              test the settings, the Sheet, every mailbox and our own e-mails
#   wr preview [KIND]     show the e-mails a business would get (gym, salon, hotel ...)
#   wr test A@x B@y       spam test: the next first e-mail from every mailbox, only to your own addresses
#   wr emails --dry-run   prepare the e-mails into the Sheet's "Email Preview" tab, send nothing
#   wr emails --max 2 --copy-to you@x.com     two real e-mails now, with a copy to you
#   wr report             e-mails per day, bounces, replies and who is waiting for your answer
#   wr resume             end a sending pause now
#   wr outlook-login N    sign an Outlook mailbox in, once
#   wr whatsapp           today's WhatsApp messages, one tap each in WhatsApp Business
#   wr leads / wr hunt    run the lead search / the e-mail hunt now
#   wr run JOB            one of the robot's jobs now: emails, leads, hunt, update or backup
#   wr update             the newest version
#
# It keeps itself running: after a restart of the tablet (Termux:Boot app) and, every 15 minutes, if Android closed
# it (Termux:API app). Your other robots are never touched: this one has its own Ubuntu (worldreach), its own
# folder (~/.worldreach), its own job number (7811) and its own start-up file. Termux's keep-awake lock is shared
# with them, so it is taken here but never released.
NAME=worldreach
DIR=/root/worldreach
SELF="$(readlink -f "${BASH_SOURCE[0]}")"
HOST_DIR="$(dirname "$(dirname "$SELF")")"          # the same folder, seen from Termux
HOME_DIR="$HOME/.worldreach"
PIDFILE="$HOME_DIR/robot.pid"
STOPFLAG="$HOME_DIR/stopped"                        # wr off: stays off, also after a restart of the tablet
LOGF="$HOME_DIR/service.log"
STATUS="$HOST_DIR/data/robot-status.json"
JOB_ID=7811
WAIT=${WR_WAIT_SECONDS:-60}

inside() { proot-distro login "$NAME" -- bash "$DIR/android/inside.sh" "$@"; }
stamp() { date '+%F %T'; }

supervisor() {
  [ -n "$1" ] && kill -0 "$1" 2>/dev/null || return 1
  [ -r "/proc/$1/cmdline" ] || return 0
  tr '\0' ' ' < "/proc/$1/cmdline" | grep -q 'wr\.sh supervise'
}
running() { supervisor "$(cat "$PIDFILE" 2>/dev/null)"; }

# The robot itself (inside Ubuntu) reported in during the last 3 minutes.
robot_alive() {
  local beat
  beat="$(grep -o '"heartbeat": *[0-9]*' "$STATUS" 2>/dev/null | head -n 1 | grep -o '[0-9]*$')"
  [ -n "$beat" ] && [ "$beat" -gt $(( $(date +%s) - 180 )) ]
}

# One supervisor at a time (wr on and the 15-minute check can start at the same moment).
mine() {
  local pid
  pid="$(cat "$PIDFILE" 2>/dev/null)"
  [ "$pid" = "$$" ] && return 0
  supervisor "$pid" && return 1
  echo $$ > "$PIDFILE"
  sleep 1
  [ "$(cat "$PIDFILE" 2>/dev/null)" = "$$" ]
}

supervise() {
  mkdir -p "$HOME_DIR"
  mine || exit 0
  command -v termux-wake-lock >/dev/null 2>&1 && termux-wake-lock
  child=""
  trap 'touch "$STOPFLAG"; touch "$HOST_DIR/data/robot.stop" 2>/dev/null' TERM INT
  fails=0
  while [ ! -f "$STOPFLAG" ] && mine; do
    if robot_alive; then sleep "$WAIT"; continue; fi
    started=$(date +%s)
    echo "$(stamp) robot starting" >> "$LOGF"
    inside robot serve >> "$LOGF" 2>&1 &
    child=$!
    wait "$child"; code=$?
    while kill -0 "$child" 2>/dev/null; do wait "$child"; code=$?; done
    echo "$(stamp) robot stopped (exit code $code)" >> "$LOGF"
    [ -f "$STOPFLAG" ] && break
    if [ "$code" = 75 ]; then fails=0; sleep "$WAIT"; continue; fi   # another copy runs: look again later
    if [ "$code" = 10 ]; then fails=0; sleep 2; continue; fi         # updated itself: start the new version now
    if [ $(( $(date +%s) - started )) -lt 120 ]; then fails=$((fails + 1)); else fails=0; fi
    if [ "$fails" -ge 5 ]; then
      echo "$(stamp) it keeps stopping - next try in 10 minutes (wr log shows why)" >> "$LOGF"
      sleep 600
    else
      sleep 20
    fi
  done
  if [ "$(cat "$PIDFILE" 2>/dev/null)" = "$$" ]; then rm -f "$PIDFILE"; echo "$(stamp) robot off" >> "$LOGF"; fi
}

start() {
  mkdir -p "$HOME_DIR" "$HOST_DIR/data"
  rm -f "$STOPFLAG" "$HOST_DIR/data/robot.stop"
  if running; then echo "The robot is already on."; return 0; fi
  if command -v setsid >/dev/null 2>&1; then
    setsid nohup bash "$SELF" supervise > /dev/null 2>&1 < /dev/null &
  else
    nohup bash "$SELF" supervise > /dev/null 2>&1 < /dev/null &
  fi
  for _ in $(seq 1 15); do running && break; sleep 1; done
  if running; then echo "The robot is on. It works by itself from now on (wr status shows what it does)."
  else echo "Could not start the robot - see $LOGF"; return 1; fi
}

autostart() {
  mkdir -p "$HOME/.termux/boot" "$HOME_DIR"
  printf '#!%s/bin/bash\ntermux-wake-lock\nexec bash "%s" watchdog\n' "$PREFIX" "$SELF" > "$HOME/.termux/boot/worldreach"
  chmod 700 "$HOME/.termux/boot/worldreach"
  printf '#!%s/bin/bash\nexec bash "%s" watchdog\n' "$PREFIX" "$SELF" > "$HOME_DIR/watchdog-job.sh"
  chmod 700 "$HOME_DIR/watchdog-job.sh"
  if command -v termux-job-scheduler >/dev/null 2>&1 &&
     timeout 30 termux-job-scheduler --job-id "$JOB_ID" --period-ms 900000 --persisted true --battery-not-low false \
       --script "$HOME_DIR/watchdog-job.sh" >/dev/null 2>&1; then
    echo "Restarts by itself: after a tablet restart and, if Android closes it, within 15 minutes."
  else
    echo "Restarts by itself after a tablet restart (Termux:Boot app). The 15-minute check needs the Termux:API"
    echo "app and package (pkg install termux-api) - not set now."
  fi
}

stop() {
  mkdir -p "$HOME_DIR" "$HOST_DIR/data"
  touch "$STOPFLAG" "$HOST_DIR/data/robot.stop"
  if command -v termux-job-scheduler >/dev/null 2>&1; then
    timeout 30 termux-job-scheduler --cancel --job-id "$JOB_ID" >/dev/null 2>&1 || true
  fi
  if running || robot_alive; then
    echo "Stopping - the job it is on saves its work first (up to 3 minutes)..."
    for _ in $(seq 1 100); do running || robot_alive || break; sleep 2; done
    if running; then kill -TERM "$(cat "$PIDFILE")" 2>/dev/null; sleep 3; fi
  fi
  running || rm -f "$PIDFILE"
  echo "The robot is off. It stays off (also after a restart of the tablet) until:  wr on"
}

switch_line() {
  if [ -f "$STOPFLAG" ]; then
    if robot_alive; then echo "Switch: OFF - the robot finishes the step it is on, then stops"
    else echo "Switch: OFF (wr on starts it)"; fi
  elif robot_alive; then echo "Switch: ON"
  elif running; then echo "Switch: ON - the robot is starting (if this stays, wr log shows why)"
  else echo "Switch: not running (wr on starts it)"; fi
}

case "${1:-help}" in
  on|start)    autostart; start ;;
  off|stop)    stop ;;
  status)      switch_line; inside robot status ;;
  log|logs)    shift; inside robot log "$@" ;;
  run)         shift; inside robot run "$@" ;;
  supervise)   supervise ;;
  watchdog)    [ -f "$STOPFLAG" ] || running || { echo "$(stamp) watchdog: not running - starting" >> "$LOGF"; start; } ;;
  whatsapp)    shift; exec bash "$HOST_DIR/android/whatsapp.sh" "$@" ;;
  update)      set -o pipefail
               curl -fsSL --retry 5 "https://raw.githubusercontent.com/dasravik444-cpu/worldreach/main/android/setup.sh" | bash -s update ||
                 { echo "The update stopped - check the internet and type  wr update  again."; exit 1; }
               echo "If the robot is on, it takes the new version at its next job (or now:  wr off  then  wr on )." ;;
  leads|emails|hunt)
               termux-wake-lock 2>/dev/null; inside "$@" ;;
  help|-h|--help|"")
               sed -n '2,22p' "$SELF" | sed 's/^# \{0,1\}//' ;;
  *)           inside "$@" ;;
esac
