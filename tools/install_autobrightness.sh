#!/bin/sh
# Install the Ruby ambient-light brightness service for KDE Plasma (user service).
# Run with sudo; needs the light sensor (cros-ec-light) from install_fedora_ruby /
# the cros_ec_ishtp DKMS module.
set -eu
here=$(dirname "$(readlink -f "$0")")
assets=$here/../assets/installed/autobrightness
[ "$(id -u)" = 0 ] || { echo 'Run with sudo' >&2; exit 1; }
grep -qx cros-ec-light /sys/bus/iio/devices/*/name 2>/dev/null || { echo 'No cros-ec-light sensor: load cros_ec_ishtp first' >&2; exit 1; }
install -Dm755 "$assets/ruby-autobrightness.py" /usr/local/libexec/ruby-autobrightness
install -Dm644 "$assets/ruby-autobrightness.service" /etc/systemd/user/ruby-autobrightness.service
echo 'Installed. As your user:'
echo '  systemctl --user daemon-reload && systemctl --user enable --now ruby-autobrightness'
