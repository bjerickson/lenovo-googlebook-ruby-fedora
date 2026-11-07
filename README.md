# Fedora on Lenovo Googlebook 15

Native **Fedora 45 on the Lenovo Googlebook 15 (Google "Ruby")**, using the factory firmware, an encrypted internal disk and no firmware replacement. Fedora replaces Googlebook OS entirely.

**Early release, tested on one laptop.** Everything below was verified on a single Ruby (512 GB, firmware `Google_Ruby.16650.143.0`) in November 2026 with Fedora 45 and KDE Plasma. Other capacities, SKUs or firmware versions are untested, and the installer refuses a disk that is not the 512 GB model. This is a community project, unaffiliated with Lenovo, Google, Fedora or the upstream projects below.

> **Built with AI assistance.** The Fedora port (code, patches and documentation) was developed with substantial help from an AI assistant, Anthropic's Claude, under the direction of the maintainer, and tested on that one laptop. Read the scripts before running them as root.

## Where this comes from

This is a fork of **[lenovo-googlebook-ruby-cachyos](https://github.com/nbarrios/lenovo-googlebook-ruby-cachyos)** by Nick Barrios, which ported the Googlebook boot path to Ruby and did the hardware work (audio, sensors, fingerprint, glowbar). That is itself a fork of **[asus-googlebook-omarchy](https://github.com/jmklex/asus-googlebook-omarchy)** by Jonathan Kleiman, whose Android-boot toolkit (`lapis/`), loader validation and live USB this project still uses. Please credit both.

## What works

| Area | Status on Fedora |
| --- | --- |
| Install and boot | LUKS2 + Btrfs on the internal NVMe; disk password prompt visible at boot |
| Desktop | KDE Plasma (`--desktop kde`); GNOME (`--desktop gnome`) or a text login are also available, only KDE has been tested. See [choosing a desktop](docs/install.md#choosing-a-desktop) |
| Wi-Fi | Intel CNVi |
| Speakers | SOF + 4× TAS2563 with Lenovo's tuning, Dolby DAX and factory per-speaker calibration (loaded at boot) |
| Ambient light sensor | `cros-ec-light`; optional automatic screen brightness for Plasma |
| Glowbar | Battery, charging and accent colour |
| Fingerprint reader | Enroll, verify, sudo and the KDE lock screen (patched libfprint, `cros_ec_usb`) |
| Kernel updates | `dnf upgrade` writes new kernels to the boot partitions automatically |
| Display | 2880×1800 OLED at 120 Hz; external displays over HDMI and USB-C DisplayPort |
| Input | Keyboard, keyboard backlight, touchpad, touchscreen |
| Suspend | Suspend and resume |
| Bluetooth, camera, microphone, headphones, Thunderbolt | Working |
| Not yet tested on Fedora | A kernel update through the hook, GNOME, the charge limit |

SELinux starts permissive after installation; switching to enforcing has been tested ([maintenance](docs/maintenance.md#selinux)).

## Start here

1. Back up anything you need from the laptop. **Unlocking the bootloader erases it**, and the install replaces Googlebook OS.
2. [Build the installer USB and install](docs/install.md): one script partitions, installs Fedora, sets up the hardware and writes the boot partitions.
3. Optional, after first boot: fingerprint, automatic brightness, glowbar ([install.md](docs/install.md#after-the-first-boot)).

You need a second computer to build the USB (Linux, macOS, or Windows with WSL 2), a USB stick of 16 GB or more, Wi-Fi, and AC power during the install.

## How it boots

```text
Factory Depthcharge firmware, developer mode
  → AVB-signed Android v4 boot / init_boot / vendor_boot / vbmeta, slot A (signed with a key generated on your laptop)
  → Fedora kernel + small dracut initramfs + coreboot framebuffer → LUKS password
  → encrypted Btrfs root → Xe graphics, then SOF audio → desktop
```

The firmware never boots `/boot`; it boots the Android partitions, which the installer and the kernel-update hook write after validating them with ChromiumOS's own Android loader. Details: [architecture](docs/architecture.md).

## Repository

| Path | Purpose |
| --- | --- |
| `tools/build_usb.py` | One command: download and verify everything, build the installer USB image |
| `tools/build_live.py`, `tools/write_usb.py` | Build and write the installer USB (console only, from a pinned Omarchy 4.0.4 ISO, with the Fedora image) |
| `tools/install_fedora_ruby.py`, `tools/fedora.py` | One-shot installer, run from the USB (`--dry-run`, `--backup DIR`) |
| `tools/kernel_update_fedora.py` | kernel-install hook: build, sign, validate and write new kernels; `rollback`, `status` |
| `tools/update_installed.py` | After `git pull`: bring the installed system up to date with the checkout |
| `tools/fetch_ruby_vendor.py` | Stream Lenovo's `vendor_a` (speaker and sensor firmware) from Google's Ruby recovery image |
| `tools/install_ruby_audio.sh`, `tools/install_ruby_sensors.sh` | Firmware from `vendor_a`; UCM, DAX, calibration |
| `tools/install_fingerprint_fedora.sh` | `cros_ec_usb` (DKMS) and libfprint with the `crfpmoc` driver |
| `tools/install_autobrightness.sh`, `tools/install_glowbar.sh` | Optional desktop services |
| `tools/install_power_mode.sh`, `assets/installed/udev/90-ruby-charge-limit.rules` | Optional power limit and charge limit |
| `assets/installed/coreboot-fb`, `cros-ec-ishtp`, `cros-ec-usb` | Out-of-tree kernel modules (DKMS) for drivers Fedora does not build |
| `lapis/` | Android boot-image, GPT and cpio toolkit (upstream) |

## What is not shipped

No OS image, Lenovo/Google firmware, disk passwords, Wi-Fi profiles, SSH keys, AVB private keys or device backups. Each installation generates its own AVB signing key; firmware is extracted from the laptop or downloaded from Google at install time. See [NOTICE.md](NOTICE.md).

## Contributing

Reports from other Ruby units are welcome: exact SKU, firmware version, storage capacity, the step you reached and what you saw. Keep serial numbers, network details, disk UUIDs and passwords out of issues. See [CONTRIBUTING.md](CONTRIBUTING.md) and the [validation record](docs/validation.md).

## License

MIT, as upstream ([LICENSE](LICENSE)). The kernel modules under `assets/installed/` are GPL-2.0 and the libfprint patches LGPL-2.1-or-later; see [NOTICE.md](NOTICE.md).
