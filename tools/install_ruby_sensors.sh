#!/bin/sh
# Install Ruby's Intel Sensor Hub firmware on an installed system. Reads (never
# writes) the factory `super` partition to obtain Google's ISH firmware from
# vendor_a; the proprietary file is not shipped in this repository.
#
# linux-firmware only has Intel's generic ish_ptl.bin, which exposes placeholder
# HID sensors that always read 0. With Google's board file the ISH runs ChromeOS
# EC firmware: cros_ec_ishtp registers it and cros-ec-light exposes the ambient
# light sensor. The kernel picks the file by name (CRC32 of "Google" and "Ruby").
# Also blacklists acpi_als, the firmware's ACPI light sensor, which always reads 0.
set -eu
assets=$(dirname "$0")/../assets/installed
[ "$(id -u)" = 0 ] || { echo 'Run as root' >&2; exit 1; }
[ "$(cat /sys/class/dmi/id/product_name)" = Ruby ] || { echo 'Not a Ruby board' >&2; exit 1; }
for tool in lpunpack fsck.erofs; do
    command -v $tool >/dev/null || { echo "Missing $tool: pacman -S android-tools erofs-utils" >&2; exit 1; }
done

fw=intel/ish/ish_ptl_62b0f067_6c687233.bin
# VENDOR_DIR: an already-extracted vendor_a tree (e.g. from Google's recovery image via
# tools/fetch_ruby_vendor.py, when this laptop's own super holds an unmerged update).
if [ -n "${VENDOR_DIR:-}" ]; then
    vendor=$VENDOR_DIR
else
    super=$(lsblk -rno PATH,PARTLABEL | awk '$2 == "super" {print $1}')
    [ -b "$super" ] || { echo 'Factory super partition not found' >&2; exit 1; }
    work=$(mktemp -d -p /var/tmp)
    trap 'rm -rf "$work"' EXIT
    lpunpack -p vendor_a "$super" "$work"
    mkdir "$work/vendor"
    fsck.erofs --extract="$work/vendor" --no-preserve "$work/vendor_a.img" >/dev/null
    vendor=$work/vendor
fi
[ -s "$vendor/firmware/$fw" ] || { echo "Factory image lacks $fw" >&2; exit 1; }
install -Dm644 "$vendor/firmware/$fw" "/usr/lib/firmware/updates/$fw"
install -Dm644 "$assets/ruby-sensors.conf" /etc/modprobe.d/ruby-sensors.conf
echo 'Ruby sensor hub firmware installed and acpi_als blacklisted; reboot to load them.'
