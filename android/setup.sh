#!/data/data/com.termux/files/usr/bin/bash
# One-time setup on an Android tablet or phone, inside the Termux app (docs/SETUP.md).
# Paste this into Termux:
#   curl -fsSL https://raw.githubusercontent.com/__REPO__/main/android/setup.sh | bash
# It installs a small Ubuntu Linux inside Termux (its own, named worldreach: the ones of your other robots are left
# alone), Python and WorldReach, and adds ONE command to Termux:  wr   (type  wr  alone for the list).
# If it stops halfway (a network hiccup), paste the line again: it carries on from where it stopped.
set -e
REPO=https://github.com/__REPO__
RAW=https://raw.githubusercontent.com/__REPO__/main
NAME=worldreach                         # the Ubuntu inside Termux
DIR=/root/worldreach                    # the robot's folder in it
UBUNTU=https://cdimage.ubuntu.com/ubuntu-base/releases/24.04/release
APT=(apt-get -y -o Acquire::Retries=5 -o Dpkg::Options::=--force-confold)
UBUNTU_PACKAGES="python3 python3-venv git nano ca-certificates"

# pkg downloads from a volunteer mirror picked at random, and some break off halfway. Termux's own server
# (behind Cloudflare) is used instead, written into the package lists the way pkg itself writes them.
use_termux_server() {
  local mirror="$PREFIX/etc/termux/mirrors/default" MAIN="" X11="" ROOT="" WEIGHT=""
  [ -f "$mirror" ] || return 0
  . "$mirror"
  point main "$MAIN" "stable main"
  point x11 "$X11" "x11 main"
  point root "$ROOT" "root stable"
}
point() {           # point REPO URL SUITE: one package list at URL, if that list is in use
  local lists="$PREFIX/etc/apt/sources.list.d"
  [ -n "$2" ] || return 0
  if [ -f "$lists/$1.sources" ]; then
    sed -i "s|^URIs:.*|URIs: $2|" "$lists/$1.sources"
  elif [ "$1" = main ]; then
    echo "deb $2 $3" > "$PREFIX/etc/apt/sources.list"
  elif [ -f "$lists/$1.list" ]; then
    echo "deb $2 $3" > "$lists/$1.list"
  fi
}

# Ubuntu 24.04 straight from Ubuntu (about 30 MB), checked against Ubuntu's own checksum list.
install_ubuntu() {
  local arch sums file want tarball
  case "$(dpkg --print-architecture)" in
    aarch64|arm64) arch=arm64 ;;
    arm|armhf) arch=armhf ;;
    x86_64|amd64) arch=amd64 ;;
    *) echo "Sorry, this device ($(dpkg --print-architecture)) is not supported."; exit 1 ;;
  esac
  sums=$(curl -fsSL --retry 5 "$UBUNTU/SHA256SUMS")
  file=$(grep -o "ubuntu-base-[0-9.]*-base-$arch\.tar\.gz" <<<"$sums" | sort -V | tail -n 1)
  want=$(awk -v f="*$file" '$2 == f { print $1 }' <<<"$sums")
  if [ -z "$file" ] || [ -z "$want" ]; then echo "Could not find Ubuntu for this device ($arch)."; exit 1; fi
  tarball="${TMPDIR:-$PREFIX/tmp}/$file"
  if [ "$(sha256sum "$tarball" 2>/dev/null | cut -d' ' -f1)" != "$want" ]; then
    curl -fL --retry 5 -C - -o "$tarball" "$UBUNTU/$file" ||
      { rm -f "$tarball"; curl -fL --retry 5 -o "$tarball" "$UBUNTU/$file"; }
  fi
  if [ "$(sha256sum "$tarball" | cut -d' ' -f1)" != "$want" ]; then
    rm -f "$tarball"
    echo "The Ubuntu download was damaged. Paste the line again."
    exit 1
  fi
  if ! proot-distro install --name "$NAME" "$tarball"; then
    echo "(This proot-distro is too old for that: getting the newest one...)"
    termux_packages
    proot-distro install --name "$NAME" "$tarball"
  fi
  rm -f "$tarball"
}

# proot-distro from Termux's own server, upgrading all of Termux only if it does not start otherwise.
termux_packages() {
  use_termux_server
  dpkg --configure -a || true
  "${APT[@]}" update || echo "(Some package lists could not be loaded. Carrying on.)"
  "${APT[@]}" install proot-distro
  if ! proot-distro list >/dev/null 2>&1; then
    echo "(proot-distro needs newer Termux parts: updating all of Termux, this can take a while...)"
    "${APT[@]}" dist-upgrade
    proot-distro list >/dev/null
  fi
}

ubuntu() { proot-distro login "$NAME" -- "$@"; }

main() {
  echo "== 1/5 Access to your Download folder (tap ALLOW if Android asks)..."
  [ -d "$HOME/storage" ] || termux-setup-storage || true

  echo "== 2/5 Termux: the tool that runs Ubuntu..."
  # Shared with your other robots: when it works it stays exactly as it is.
  proot-distro list >/dev/null 2>&1 || termux_packages

  echo "== 3/5 Ubuntu inside Termux (its own, named $NAME)..."
  proot-distro login "$NAME" -- true >/dev/null 2>&1 || install_ubuntu

  echo "== 4/5 Python and WorldReach inside Ubuntu (5-10 minutes)..."
  curl -fsSL --retry 5 "$RAW/android/dns.sh" | proot-distro login "$NAME" -- bash -s
  if ! ubuntu dpkg -s $UBUNTU_PACKAGES >/dev/null 2>&1; then
    ubuntu env DEBIAN_FRONTEND=noninteractive apt-get -o Acquire::Retries=5 update
    ubuntu env DEBIAN_FRONTEND=noninteractive apt-get -y -o Acquire::Retries=5 install \
      --no-install-recommends $UBUNTU_PACKAGES
  fi
  if ubuntu test -d "$DIR/.git"; then
    ubuntu git -C "$DIR" pull --ff-only
  else
    ubuntu git clone "$REPO" "$DIR"
  fi

  echo "== 5/5 The  wr  command..."
  # wr is a tiny script in Termux that runs android/wr.sh from inside Ubuntu's folder, so an update of WorldReach
  # also updates the command itself.
  rootfs=$(proot-distro login "$NAME" --get-proot-cmd 2>/dev/null | grep -o -- '--rootfs=[^ \\]*' | head -n 1 | cut -d= -f2)
  if [ -n "$rootfs" ] && [ -f "$rootfs$DIR/android/wr.sh" ]; then
    printf '#!%s/bin/bash\nexec bash "%s" "$@"\n' "$PREFIX" "$rootfs$DIR/android/wr.sh" > "$PREFIX/bin/.wr.new"
    chmod +x "$PREFIX/bin/.wr.new"
    mv -f "$PREFIX/bin/.wr.new" "$PREFIX/bin/wr"
  else
    echo "(The wr command could not be set up: Ubuntu's folder was not found. Paste the setup line again.)"
    exit 1
  fi

  echo
  if [ "${1:-}" = update ]; then
    echo "Updated."
  else
    echo "Done. Next:   wr getkey   then   wr settings   then   wr check     (docs/SETUP.md)"
  fi
}

# This script arrives through a pipe (curl ... | bash). Everything above is only definitions, so nothing runs
# unless the whole script arrived, and questions are answered on the screen rather than by the rest of the script.
if (exec </dev/tty) 2>/dev/null; then main "$@" </dev/tty; else main "$@" </dev/null; fi
