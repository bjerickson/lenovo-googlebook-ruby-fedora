#!/bin/sh
# Enable speakers, headset and microphones on an installed Ruby system.
# Run as root on the Googlebook. Reads (never writes) the factory `super`
# partition to obtain Lenovo's TAS2563 amplifier firmware from vendor_a;
# the proprietary files are not shipped in this repository.
set -eu
here=$(dirname "$(readlink -f "$0")")
assets=$here/../assets/installed
[ "$(id -u)" = 0 ] || { echo 'Run as root' >&2; exit 1; }
[ "$(cat /sys/class/dmi/id/product_name)" = Ruby ] || { echo 'Not a Ruby board' >&2; exit 1; }
for tool in lpunpack fsck.erofs; do
    command -v $tool >/dev/null || { echo "Missing $tool: dnf install android-tools erofs-utils" >&2; exit 1; }
done

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
    if ! fsck.erofs --extract="$work/vendor" --no-preserve "$work/vendor_a.img" >/dev/null 2>&1; then
        # A super left mid-way through a virtual A/B merge holds an inconsistent vendor_a.
        echo "This laptop's vendor_a is unusable (unmerged Android update); fetching it from Google's recovery image (~5.5 GB download)."
        rm -rf "$work/vendor" "$work/vendor_a.img"
        mkdir "$work/vendor"
        python3 -I "$here/fetch_ruby_vendor.py" --output "$work/vendor_a.img"
        fsck.erofs --extract="$work/vendor" --no-preserve "$work/vendor_a.img" >/dev/null
    fi
    vendor=$work/vendor
fi
for f in tas2563RCA4.bin tas2563_coef.bin; do
    [ -s "$vendor/firmware/$f" ] || { echo "Factory image lacks $f" >&2; exit 1; }
    install -Dm644 "$vendor/firmware/$f" "/usr/lib/firmware/updates/$f"
done
# Factory Ruby SOF firmware with Dolby DAX, its topology, and the DAX tuning.
for f in intel/sof-ipc4/ptl/ruby/sof-ptl.ri intel/sof-ipc4/ptl/ruby/sof-ptl-openmodules.ri \
         intel/sof-ipc4-tplg/ruby/sof-ptl-tas2563-rt5682.tplg; do
    [ -s "$vendor/firmware/$f" ] || { echo "Factory image lacks $f" >&2; exit 1; }
    install -Dm644 "$vendor/firmware/$f" "/usr/lib/firmware/updates/$f"
done
install -Dm644 "$vendor/etc/audio/dax/ruby/dax_param.bin" /usr/lib/firmware/updates/intel/sof-ipc4-tplg/ruby/dax_param.bin

install -Dm644 "$assets/ruby-audio.conf" /etc/modprobe.d/ruby-audio.conf
install -Dm644 "$assets/ruby-dax.conf" /etc/modprobe.d/ruby-dax.conf
install -Dm644 "$assets/ruby-gpu.service" /etc/systemd/system/ruby-gpu.service
install -Dm644 "$assets/ucm2/sof-rt5682/sof-rt5682.conf" /usr/share/alsa/ucm2/conf.d/sof-rt5682/sof-rt5682.conf
install -Dm644 "$assets/ucm2/sof-rt5682/HiFi.conf" /usr/share/alsa/ucm2/conf.d/sof-rt5682/HiFi.conf
install -Dm755 "$assets/ruby-speaker-calibration.py" /usr/local/libexec/ruby-speaker-calibration
install -Dm644 "$assets/ruby-speaker-calibration.service" /etc/systemd/system/ruby-speaker-calibration.service
install -Dm644 "$assets/pipewire/ruby-mic.conf" /etc/pipewire/pipewire.conf.d/ruby-mic.conf
systemctl daemon-reload
systemctl enable ruby-speaker-calibration.service
echo 'Ruby audio installed; reboot to load SOF with the amplifier firmware.'
