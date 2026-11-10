#!/usr/bin/env bash
# Internet names (DNS) for the Ubuntu inside Termux. proot-distro gives it Google's DNS at 8.8.8.8, which needs
# IPv4. Some networks in India (Jio, for example) have only IPv6: there Google's DNS64 is used instead, which also
# lets an IPv6-only tablet reach the many websites that only have IPv4. Checked before each run, because the
# tablet can move between networks.
v4=$'nameserver 8.8.8.8\nnameserver 8.8.4.4'
v6=$'nameserver 2001:4860:4860::6464\nnameserver 2001:4860:4860::64'
reach() { timeout 4 bash -c ": </dev/tcp/$1/$2" 2>/dev/null; }
if reach 1.1.1.1 443 || reach 8.8.8.8 53; then
  want=$v4                            # the network has IPv4
elif reach 2001:4860:4860::6464 53; then
  want=$v6                            # IPv6 only
else
  exit 0                              # no internet just now: leave it as it is
fi
[ "$(cat /etc/resolv.conf 2>/dev/null)" = "$want" ] || printf '%s\n' "$want" > /etc/resolv.conf
