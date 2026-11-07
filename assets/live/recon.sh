#!/bin/sh
# Read-only hardware survey for porting to another fatcat board (e.g. Lenovo "Ruby").
# Writes only to the RAM overlay; never opens the internal disk for writing.
# Usage (root, live USB): sh /opt/ruby-fedora/assets/live/recon.sh [/dev/nvme0n1]
set -u
disk=${1:-/dev/nvme0n1}
out=/root/recon-$(cat /sys/class/dmi/id/product_name 2>/dev/null || echo unknown)
mkdir -p "$out"
cd "$out" || exit 1

save() { name=$1; shift; "$@" > "$name" 2>&1; }

# Board and firmware (serial numbers and UUIDs deliberately skipped).
for f in sys_vendor product_name product_version product_family board_name board_vendor bios_vendor bios_version bios_date; do
    printf '%s: %s\n' "$f" "$(cat /sys/class/dmi/id/$f 2>/dev/null)"
done > dmi.txt
save uname.txt uname -a
save cmdline.txt cat /proc/cmdline
save cpuinfo.txt cat /proc/cpuinfo
save meminfo.txt cat /proc/meminfo

# Devices.
save lspci.txt lspci -nnk
save lspci-vv.txt lspci -vvnn
save lsusb.txt lsusb
save lsmod.txt lsmod
save input-devices.txt cat /proc/bus/input/devices
save gpu-id.txt cat /sys/bus/pci/devices/0000:00:02.0/device

# Storage layout (read-only).
save lsblk.txt lsblk -b -o NAME,SIZE,TYPE,FSTYPE,LABEL,PARTLABEL,PARTTYPE,MODEL,TRAN,MOUNTPOINTS
save blkid.txt blkid
save sgdisk.txt sgdisk -p "$disk"
save sgdisk-parts.txt sh -c "for i in \$(seq 1 64); do sgdisk -i \$i '$disk' 2>/dev/null | grep -q 'Partition GUID' && { echo \"== \$i\"; sgdisk -i \$i '$disk'; }; done"
save disk-bytes.txt blockdev --getsize64 "$disk"
# Primary and backup GPT regions, for building a layout profile.
dd if="$disk" of=gpt-primary.bin bs=512 count=34 status=none
sectors=$(blockdev --getsz "$disk")
dd if="$disk" of=gpt-backup.bin bs=512 skip=$((sectors - 33)) count=33 status=none

# Display.
for e in /sys/class/drm/*/edid; do
    [ -s "$e" ] && cp "$e" "edid-$(basename "$(dirname "$e")").bin"
done
save drm-status.txt sh -c 'for c in /sys/class/drm/card*-*; do echo "$c $(cat $c/status) $(cat $c/modes 2>/dev/null | tr "\n" " ")"; done'
save xe-params.txt sh -c 'for p in /sys/module/xe/parameters/*; do echo "$(basename $p)=$(cat $p)"; done'

# Audio.
save asound-cards.txt cat /proc/asound/cards
save audio-subsystem.txt sh -c 'cat /sys/bus/pci/devices/0000:00:1f.3/subsystem_vendor /sys/bus/pci/devices/0000:00:1f.3/subsystem_device'
save soundwire.txt sh -c 'ls -l /sys/bus/soundwire/devices/ 2>&1; for d in /sys/bus/soundwire/devices/*; do echo "== $d"; cat $d/modalias 2>/dev/null; done'

# ACPI tables (audio/SoundWire/touchpad descriptions live here).
mkdir -p acpi
cp /sys/firmware/acpi/tables/DSDT acpi/ 2>/dev/null
cp /sys/firmware/acpi/tables/SSDT* acpi/ 2>/dev/null
cp /sys/firmware/acpi/tables/NHLT* acpi/ 2>/dev/null

# Logs.
save dmesg.txt dmesg
save journal-boot.txt journalctl -b --no-pager
save failed-units.txt systemctl --failed --no-pager

cd /root && tar czf "$out.tar.gz" "$(basename "$out")"
echo "Saved $out.tar.gz"
echo "Copy it to a spare FAT/exFAT USB stick (not the live USB), e.g.:"
echo "  mount /dev/sdX1 /mnt && cp $out.tar.gz /mnt/ && umount /mnt"
