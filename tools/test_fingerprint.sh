#!/bin/sh
# First hardware test of the cros_ec_usb fingerprint driver on Ruby: install
# it with DKMS (autoload stays blocked), load it, query the FPMCU with ectool,
# then unload it. Run as root via sudo. Everything is logged to
# ~/fingerprint-test.log (the invoking user's home) and synced after each
# step, so the log survives if the kernel hangs. A reboot undoes the test.
#
#   sudo tools/test_fingerprint.sh [path/to/ectool]
set -u
here=$(dirname "$(readlink -f "$0")")
[ "$(id -u)" = 0 ] || { echo 'Run with sudo' >&2; exit 1; }
[ "$(cat /sys/class/dmi/id/product_name)" = Ruby ] || { echo 'Not a Ruby board' >&2; exit 1; }
user=${SUDO_USER:-root}
home=$(getent passwd "$user" | cut -d: -f6)
ectool=${1:-$home/src/ec-r107/build/host/util/ectool}
log=$home/fingerprint-test.log
: >"$log"; chown "$user:" "$log"

say() { printf '\n==> %s\n' "$*" | tee -a "$log"; sync; }
step() { say "$*"; { "$@"; echo "(exit $?)"; } 2>&1 | tee -a "$log"; sync; }
stop() { say "STOPPED: $*"; echo "Log: $log"; exit 1; }
newlog() { dmesg | tail -n +"$((mark + 1))" | tee -a "$log"; mark=$(dmesg | wc -l); sync; }

say "$(date -Is) kernel $(uname -r)"
step cat /sys/bus/usb/devices/3-7/product /sys/bus/usb/devices/3-7:1.0/modalias
[ -x "$ectool" ] || stop "ectool not found at $ectool (build it per docs/hardware.md, Fingerprint)"

say 'Install dkms and the driver (autoload blocked)'
dnf install -y dkms "kernel-devel-$(uname -r)" 2>&1 | tee -a "$log"
"$here/install_fingerprint_driver.sh" 2>&1 | tee -a "$log"
modinfo -F filename cros_ec_usb >/dev/null 2>&1 || stop 'cros_ec_usb did not build or install'

mark=$(dmesg | wc -l)
say 'Load cros_ec_usb'
modprobe cros_ec_usb 2>&1 | tee -a "$log"
sleep 5
newlog
for i in 1 2 3 4 5; do [ -e /dev/cros_fp ] && break; sleep 1; done
if [ ! -e /dev/cros_fp ]; then
    say 'No /dev/cros_fp yet; loading cros_ec_dev and cros_ec_chardev'
    modprobe -a cros_ec_dev cros_ec_chardev 2>&1 | tee -a "$log"
    sleep 3
    newlog
fi
[ -e /dev/cros_fp ] || stop 'no /dev/cros_fp; driver left loaded for inspection'
step ls -l /dev/cros_fp
lsmod | grep -E '^cros' | tee -a "$log"

for cmd in version fpinfo fpencstatus; do
    step timeout 15 "$ectool" --name=cros_fp $cmd
done
newlog

say 'Unload cros_ec_usb (tests the unload path)'
modprobe -r cros_ec_usb 2>&1 | tee -a "$log"
sleep 2
newlog
if lsmod | grep -q '^cros_ec_usb '; then say 'cros_ec_usb still loaded'; else say 'cros_ec_usb unloaded'; fi
say 'Done'
echo "Log: $log"
