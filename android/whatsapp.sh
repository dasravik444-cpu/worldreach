#!/usr/bin/env bash
# Today's WhatsApp messages on the tablet ( wr whatsapp ):
#   wr whatsapp              one message after the other: the chat opens in WhatsApp Business with the message
#                            already typed, you press Send there, come back to Termux and say how it went
#   wr whatsapp list         only show what is waiting
#   wr whatsapp test NUMBER  a test message to one number (your own): checks the Sheet, Termux and WhatsApp Business
# Nothing is sent by a machine: WhatsApp's terms forbid automated and bulk messages, and it bans numbers that send
# them. The robot only fills the WhatsApp Queue tab (docs/WHATSAPP.md).
NAME=worldreach
DIR=/root/worldreach
W4B=com.whatsapp.w4b                                # WhatsApp Business (not the personal WhatsApp)
KEEP="$HOME/.worldreach"
UNSAVED="$KEEP/whatsapp-unsaved.tsv"                # results the Sheet did not take yet: row, key, number, result
RETRY="${WHATSAPP_RETRY_SECONDS:-15}"

inside() { proot-distro login "$NAME" -- bash "$DIR/android/inside.sh" "$@" </dev/null; }

# Open the chat in WhatsApp Business; if Android cannot aim at it, open the link as usual.
open_chat() {
  local out
  if command -v am >/dev/null 2>&1; then
    out="$(am start -a android.intent.action.VIEW -d "$1" -p "$W4B" 2>&1)"
    case "$out" in *rror*|*xception*|*"not started"*|*"Unable"*) ;; *) return 0 ;; esac
  fi
  echo "   (Opened with Android's app for WhatsApp links: check it is WhatsApp Business, not your personal WhatsApp.)"
  termux-open-url "$1" 2>/dev/null
}

# Ask the Sheet, a few tries: prints the answer, fails after three tries.
ask() {
  local out code n
  for n in 1 2 3; do
    out="$(inside whatsapp "$@" 2>&1)"; code=$?
    if [ "$code" != 5 ]; then printf '%s\n' "$out"; return "$code"; fi
    [ "$n" = 3 ] || sleep "$RETRY"
  done
  printf '%s\n' "$out"
  return 5
}

save() {            # save ROW KEY NUMBER RESULT: into the Sheet, or kept on the tablet until the Sheet answers
  if ! ask mark "$1" "$2" "$3" "$4" >/dev/null; then
    mkdir -p "$KEEP"
    printf '%s\t%s\t%s\t%s\n' "$1" "$2" "$3" "$4" >> "$UNSAVED"
    echo "   (The Sheet did not answer: the result is kept here and saved next time.)"
  fi
}

flush_unsaved() {
  [ -s "$UNSAVED" ] || return 0
  local left="" row key number result
  while IFS=$'\t' read -r row key number result; do
    [ -n "$row" ] || continue
    ask mark "$row" "$key" "$number" "$result" >/dev/null || left+="$row"$'\t'"$key"$'\t'"$number"$'\t'"$result"$'\n'
  done < "$UNSAVED"
  printf '%s' "$left" > "$UNSAVED"
}

case "${1:-}" in
  list) inside whatsapp list; exit $? ;;
  test)
    [ -n "$2" ] || { echo "usage: wr whatsapp test +15125550100"; exit 2; }
    out="$(ask test "$2")" || { echo "$out"; exit 1; }
    link="$(printf '%s\n' "$out" | tail -n 1 | awk -F'\t' '{print $NF}')"
    case "$link" in https://wa.me/*) ;; *) echo "$out"; exit 1 ;; esac
    open_chat "$link" || { echo "Could not open WhatsApp Business: is it installed on this tablet?"; exit 1; }
    echo "WhatsApp Business opened with a test message typed: press Send there. If it did, everything works."
    exit 0 ;;
esac

flush_unsaved
skip=()
sent=0
echo "For each message: WhatsApp Business opens with the text typed. Press Send there, come back here, then:"
echo "   Enter = sent    n = this number is not on WhatsApp    s = skip    q = stop for now"
while :; do
  args=(next)
  for n in "${skip[@]}"; do args+=(--skip "$n"); done
  line="$(ask "${args[@]}")" || { echo "$line"; break; }
  [ -n "$line" ] || { echo "Nothing more to send today. ($sent sent this time)"; break; }
  IFS=$'\t' read -r row key number lead business link <<< "$line"
  case "$link" in https://wa.me/*) ;; *) echo "$line"; break ;; esac
  echo
  echo "$lead  $business  ($number)"
  open_chat "$link" || { echo "Could not open WhatsApp Business: is it installed on this tablet?"; break; }
  while :; do
    read -r -p "   Sent? [Enter / n / s / q] " answer
    case "$answer" in
      "") save "$row" "$key" "$number" "Sent"; sent=$((sent + 1)); break ;;
      n|N) save "$row" "$key" "$number" "Not on WhatsApp"; break ;;
      s|S) save "$row" "$key" "$number" "Skip"; break ;;
      q|Q) echo "Stopped. ($sent sent this time; the rest stays waiting)"; exit 0 ;;
      *) echo "   Press Enter, n, s or q." ;;
    esac
  done
  skip+=("$number")
done
