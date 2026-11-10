#!/usr/bin/env bash
# The  wr  command on a server (installed by server/setup.sh as /usr/local/bin/wr). Type  wr  alone for this list.
#
#   wr on / wr off        start the robot (it then works by itself, also after a restart) / stop it
#   wr status             is it running, the mailboxes' warm-up, leads, e-mails, replies
#   wr log [LINES]        the end of today's log
#   wr settings           open your settings (settings.txt)
#   wr check              test the settings, the Sheet, every mailbox and our own e-mails
#   wr preview [KIND]     show the e-mails a business would get (gym, salon, hotel ...)
#   wr test A@x B@y       spam test: the next first e-mail from every mailbox, only to your own addresses
#   wr emails --dry-run   prepare the e-mails into the Sheet's "Email Preview" tab, send nothing
#   wr report             e-mails per day, bounces, replies and who is waiting for your answer
#   wr resume             end a sending pause now
#   wr outlook-login N    sign an Outlook mailbox in, once
#   wr leads / wr hunt    run the lead search / the e-mail hunt now
#   wr run JOB            one of the robot's jobs now: emails, clients, leads, hunt, update or backup
#   wr client ...         the follow-ups we run for a client
#   wr update             the newest version
DIR=/opt/worldreach
cd "$DIR" || { echo "WorldReach is not installed in $DIR (server/setup.sh)."; exit 1; }
case "${1:-help}" in
  on|start)   rm -f data/robot.stop; systemctl enable --now worldreach >/dev/null 2>&1 &&
              echo "The robot is on. It works by itself from now on, also after a restart of the server." ;;
  off|stop)   touch data/robot.stop; systemctl disable --now worldreach >/dev/null 2>&1
              echo "The robot is off. It stays off until:  wr on" ;;
  status)     if systemctl is-active --quiet worldreach; then echo "Switch: ON"; else echo "Switch: OFF (wr on starts it)"; fi
              exec bash scripts/run.sh robot status ;;
  log|logs)   shift; exec bash scripts/run.sh robot log "$@" ;;
  run)        shift; exec bash scripts/run.sh robot run "$@" ;;
  settings)   [ -f settings.txt ] || cp settings-example.txt settings.txt
              chmod 600 settings.txt; exec nano settings.txt ;;
  getkey)     echo "On a server, copy the Google key file into $DIR/secrets/ (docs/HOSTING.md, step 4)." ;;
  whatsapp)   echo "The WhatsApp queue is worked from the tablet or the Sheet (the WhatsApp Queue tab): a server has no WhatsApp." ;;
  update)     curl -fsSL https://raw.githubusercontent.com/dasravik444-cpu/worldreach/main/server/setup.sh | bash &&
              { systemctl is-active --quiet worldreach && systemctl restart worldreach; echo "Updated."; } ;;
  help|-h|--help|"") sed -n '2,19p' "$0" | sed 's/^# \{0,1\}//' ;;
  *)          exec bash scripts/run.sh "$@" ;;
esac
