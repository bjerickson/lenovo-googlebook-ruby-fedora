# Validation record

## Physical tests

One laptop: Lenovo Googlebook 15 (DMI `Google / Ruby`), 512 GB NVMe, firmware `Google_Ruby.16650.143.0`. Fedora 45, kernel `7.2.15-300.fc45`, KDE Plasma. 7 November 2026.

| Area | Result |
| --- | --- |
| Installer USB | Boots via **Boot from external drive** |
| `install_fedora_ruby.py` | Completed; the laptop's own `vendor_a` was inconsistent (unmerged virtual A/B update), so firmware came from Google's recovery image |
| Boot | Disk password prompt visible (coreboot framebuffer → simpledrm), unlock, KDE Plasma |
| Wi-Fi | Connected, `dnf` updates |
| Speakers | Playback works and sounds right; Lenovo tuning, Dolby DAX and calibration were installed but not individually measured |
| Ambient light sensor | `cros-ec-light` reads lux (about 20 indoors) |
| Automatic brightness | Dims when the sensor is covered |
| Glowbar | Manual colour writes; `ruby-glowbar` service on AC and battery, follows the Plasma accent colour |
| Fingerprint | `fprintd-enroll` and `fprintd-verify` |
| Kernel-update hook | Installed; `status` consistent. **A real kernel update has not happened yet.** |
| Display | 2880×1800 at 120 Hz |
| Bluetooth | Working |
| Camera | Working |
| Microphone | Working |
| Thunderbolt | Working |
| HDMI | External display on the built-in HDMI port |

Not yet checked on Fedora: suspend and resume, headphones, USB-C DisplayPort displays, the power-mode and charge-limit options, fingerprint for sudo and the lock screen, SELinux enforcing, a cold boot after a kernel update, GNOME. These worked under CachyOS on the same hardware ([hardware notes](hardware.md)).

## Host-side tests

These run without the laptop and are not physical results.

- `python3 -m unittest discover -s tests` (also with `-O`): GPT, cpio and USB writer guards; the installer's partition table (factory offsets, slot priorities); kernel-update write rollback; glowbar, auto-brightness and speaker-calibration logic.
- A Fedora 45 tree installed from the same container image and package list, run in an unprivileged user namespace: dracut builds the initramfs at 20.1 MiB with the required contents; DKMS builds all three module packages for `7.2.15-300.fc45`; the installer's tail (loader build, Android loader check, key, SELinux relabel, slot-A write with read-back) against a sparse 512 GB disk image; the kernel-update hook, `update`, `status` and `rollback` against the same image; the libfprint RPM builds and passes its 133 tests; Google's `vendor_a` passes `fsck.erofs` and both firmware installers run from it.
- `tools/update_installed.py` against the same tree with drifted state (stale kit file, changed DKMS source, deleted UCM file): first run restores everything, including the fingerprint driver via its installer; a second run changes nothing.
- `tools/build_usb.py` builds the image with the Fedora image inside and it passes the Android loader check (`vb2api_load_kernel() returned 0`). `--dry-run` and `--backup` are covered by unit tests against a sparse disk file with the factory layout; neither has been run on the laptop yet.
