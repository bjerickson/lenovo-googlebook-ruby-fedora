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
    command -v $tool >/dev/null || { echo "Missing $tool: install android-tools and erofs-utils (dnf or pacman)" >&2; exit 1; }
done

super=$(lsblk -rno PATH,PARTLABEL | awk '$2 == "super" {print $1}')
[ -b "$super" ] || { echo 'Factory super partition not found' >&2; exit 1; }
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
lpunpack -p vendor_a "$super" "$work"
mkdir "$work/vendor"
fsck.erofs --extract="$work/vendor" --no-preserve "$work/vendor_a.img" >/dev/null
for f in tas2563RCA4.bin tas2563_coef.bin; do
    [ -s "$work/vendor/firmware/$f" ] || { echo "Factory image lacks $f" >&2; exit 1; }
    install -Dm644 "$work/vendor/firmware/$f" "/usr/lib/firmware/updates/$f"
done
# Factory Ruby SOF firmware with Dolby DAX, its topology, and the DAX tuning.
for f in intel/sof-ipc4/ptl/ruby/sof-ptl.ri intel/sof-ipc4/ptl/ruby/sof-ptl-openmodules.ri \
         intel/sof-ipc4-tplg/ruby/sof-ptl-tas2563-rt5682.tplg; do
    [ -s "$work/vendor/firmware/$f" ] || { echo "Factory image lacks $f" >&2; exit 1; }
    install -Dm644 "$work/vendor/firmware/$f" "/usr/lib/firmware/updates/$f"
done
install -Dm644 "$work/vendor/etc/audio/dax/ruby/dax_param.bin" /usr/lib/firmware/updates/intel/sof-ipc4-tplg/ruby/dax_param.bin

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
