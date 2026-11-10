#!/usr/bin/env bash
# android/wr.sh runs this inside the Ubuntu in Termux:  inside.sh COMMAND [options]
cd "$(dirname "$0")/.." || exit 1
cmd=$1
shift

field() { grep -o "\"$1\": *\"[^\"]*\"" "$2" 2>/dev/null | head -n 1 | cut -d'"' -f4; }
google_key() { [ -f "$1" ] && [ "$(field type "$1")" = service_account ]; }

case "$cmd" in
  getkey)
    # The Google key file you downloaded is in the tablet's Download folder (any name). The newest one is taken
    # (or the one whose name contains the word you give:  wr getkey review-leads ), and it replaces an older copy.
    mkdir -p secrets
    newest=""
    for f in "${DOWNLOAD_DIR:-/sdcard/Download}"/*.json; do
      google_key "$f" || continue
      case "$(basename "$f")" in *"${1:-}"*) ;; *) continue ;; esac
      if [ -z "$newest" ] || [ "$f" -nt "$newest" ]; then newest="$f"; fi
    done
    if [ -n "$newest" ]; then
      for f in secrets/*.json; do google_key "$f" && rm -f "$f"; done
      cp "$newest" secrets/ && chmod 600 secrets/*.json
      echo "Copied $(basename "$newest")."
      echo "Share your Google Sheet with this address as Editor:  $(field client_email "$newest")"
    else
      echo "No Google key file (.json) found in your Download folder."
      echo "Download it (docs/SETUP.md, step 3), and check that Termux may use storage: type"
      echo "termux-setup-storage  in Termux and tap ALLOW."
    fi
    ;;
  settings)
    [ -f settings.txt ] || cp settings-example.txt settings.txt
    chmod 600 settings.txt
    nano settings.txt
    ;;
  *)
    bash android/dns.sh
    exec bash scripts/run.sh "$cmd" "$@"
    ;;
esac
