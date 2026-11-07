#!/bin/sh
# Build and install the ChromeOS EC USB driver (cros_ec_usb) for the Ruby
# fingerprint MCU with DKMS, so it is rebuilt for every new kernel. Run as root
# on the Googlebook; tools/install_fingerprint_fedora.sh calls it with --autoload.
# Without --autoload the module is blacklisted until loaded by hand (a first,
# manual test; docs/hardware.md, Fingerprint).
set -eu
here=$(dirname "$(readlink -f "$0")")
assets=$here/../assets/installed
src=$assets/cros-ec-usb
name=cros-ec-usb
autoload=no
case "${1-}" in
    '') ;;
    --autoload) autoload=yes ;;
    *) echo "Usage: $0 [--autoload]" >&2; exit 2 ;;
esac
[ "$(id -u)" = 0 ] || { echo 'Run as root' >&2; exit 1; }
[ "$(cat /sys/class/dmi/id/product_name)" = Ruby ] || { echo 'Not a Ruby board' >&2; exit 1; }
command -v dkms >/dev/null || { echo 'Missing dkms: dnf install dkms kernel-devel' >&2; exit 1; }
running=$(uname -r)
[ -d "/usr/lib/modules/$running/build/include" ] || {
    echo "No headers for the running kernel $running: dnf install kernel-devel-$running" >&2
    exit 1
}
ver=$(sed -n 's/^PACKAGE_VERSION="\(.*\)"$/\1/p' "$src/dkms.conf")
[ -n "$ver" ] || { echo 'PACKAGE_VERSION missing from dkms.conf' >&2; exit 1; }

# Replace any earlier copy (this or another version) so DKMS builds exactly this source.
for old in /usr/src/$name-*; do
    [ -d "$old" ] || continue
    dkms remove "$name/${old#/usr/src/$name-}" --all >/dev/null 2>&1 || true
    rm -rf "$old"
done
dest=/usr/src/$name-$ver
for f in dkms.conf Makefile cros_ec_usb.c cros_ec.h \
         patches/0001-port-to-linux-6.18-cros-ec-core.patch \
         patches/0002-unregister-ec-on-module-unload.patch; do
    install -Dm644 "$src/$f" "$dest/$f"
done

if [ $autoload = yes ]; then
    rm -f /etc/modprobe.d/ruby-fingerprint.conf
else
    install -Dm644 "$assets/ruby-fingerprint.conf" /etc/modprobe.d/ruby-fingerprint.conf
fi

dkms add "$name/$ver"
# Every installed kernel that has headers.
for build in /usr/lib/modules/*/build/include; do
    kver=${build#/usr/lib/modules/}; kver=${kver%/build/include}
    [ -d "/usr/lib/modules/$kver/kernel" ] || continue
    dkms install "$name/$ver" -k "$kver"
done
dkms status "$name"
if [ $autoload = yes ]; then
    echo 'cros_ec_usb installed; udev loads it at boot. Load it now: modprobe cros_ec_usb'
else
    echo 'cros_ec_usb installed, autoload blocked. First test: modprobe cros_ec_usb'
fi
