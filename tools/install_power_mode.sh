#!/bin/sh
# Optional: raise Ruby's sustained CPU power limit and use the performance
# profile on AC, back to 15 W and balanced on battery. Edit AC_WATTS in
# assets/installed/power/ruby-power-mode first if you want another limit.
set -eu
here=$(dirname "$(readlink -f "$0")")
assets=$here/../assets/installed/power
[ "$(id -u)" = 0 ] || { echo 'Run with sudo' >&2; exit 1; }
[ "$(cat /sys/class/dmi/id/product_name)" = Ruby ] || { echo 'Not a Ruby board' >&2; exit 1; }
command -v powerprofilesctl >/dev/null || { echo 'Missing powerprofilesctl: dnf install tuned-ppd' >&2; exit 1; }

install -Dm755 "$assets/ruby-power-mode" /usr/local/libexec/ruby-power-mode
install -Dm644 "$assets/ruby-power-mode.service" /etc/systemd/system/ruby-power-mode.service
install -Dm644 "$assets/90-ruby-power-mode.rules" /etc/udev/rules.d/90-ruby-power-mode.rules
install -Dm755 "$assets/ruby-power-mode.sleep" /usr/lib/systemd/system-sleep/ruby-power-mode
udevadm control --reload
systemctl daemon-reload
systemctl enable --now ruby-power-mode.service
journalctl -u ruby-power-mode -b -o cat --no-pager | grep "^ruby-power-mode:" | tail -n 1
