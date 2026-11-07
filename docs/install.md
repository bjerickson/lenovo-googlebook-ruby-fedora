# Installing Fedora on Ruby

**This erases the whole internal disk and replaces Googlebook OS.** Unlocking the bootloader erases it too. Copy off anything you need first.

## 1. Build the installer USB

You build the USB on another computer: Linux, macOS or Windows (through WSL 2). Allow about 20 GB of free space. The tools need Python 3.10+, git, curl, OpenSSL, zstd, bsdtar (libarchive), make and a C compiler.

| Build machine | Install the tools |
| --- | --- |
| Fedora | `sudo dnf install python3 git curl openssl zstd bsdtar make gcc` |
| Debian / Ubuntu | `sudo apt install python3 git curl openssl zstd libarchive-tools build-essential` |
| Arch | `sudo pacman -S --needed python git curl openssl zstd libarchive base-devel` |
| macOS | `xcode-select --install`, then with [Homebrew](https://brew.sh) `brew install python zstd` (macOS already has bsdtar, curl and an OpenSSL-compatible `openssl`) |
| Windows | Install [WSL 2](https://learn.microsoft.com/windows/wsl/install) with Ubuntu, then follow the Debian/Ubuntu row inside it. USB access needs [usbipd-win](https://github.com/dorssel/usbipd-win), below |

Then, in a terminal (on Windows, the WSL terminal):

```sh
git clone https://github.com/bjerickson/lenovo-googlebook-ruby-fedora.git
cd lenovo-googlebook-ruby-fedora
python3 tools/build_usb.py
```

`build_usb.py` does everything and can be rerun (downloads are kept in `downloads/` and resume if interrupted):

1. downloads the Omarchy 4.0.4 ISO (about 6 GB) and checks its pinned SHA-256. The ISO is only the live environment: a pinned Arch kernel and userland known to boot on Ruby's firmware;
2. downloads Fedora 45's container image (73 MB) and signed CHECKSUM, checks the pinned hash and, if `gpg` is installed, Fedora's signature. The image goes onto the USB so the laptop does not download it; `--no-fedora-image` leaves it out;
3. fetches the pinned mkbootimg, AVB and vboot sources and builds the loader check;
4. builds `build/ruby-fedora-live.img` and checks it with ChromiumOS's Android loader (a packaging check, not a boot test).

Use `--force` to rebuild an existing image. The individual steps are `tools/fetch_sources.py`, `tools/build_loader.py` and `tools/build_live.py`.

Write it to a USB stick of 16 GB or more that you can erase. Unplug other removable drives, and identify the **whole** stick, never a partition or an internal disk. `write_usb.py` checks first, then on `--apply` asks you to type `ERASE <device>`, writes, reads the whole image back and moves the backup partition table to the end of the stick. Use it rather than `dd`, Etcher or Rufus, which skip that last step.

**Linux:**
```sh
lsblk -d -o PATH,SIZE,MODEL,TRAN                     # the stick shows TRAN usb, e.g. /dev/sdb
sudo python3 tools/write_usb.py --image build/ruby-fedora-live.img --device /dev/sdX
sudo python3 tools/write_usb.py --image build/ruby-fedora-live.img --device /dev/sdX --apply
```

**macOS:**
```sh
diskutil list external physical                      # e.g. /dev/disk4
sudo python3 tools/write_usb.py --image build/ruby-fedora-live.img --device /dev/diskN
sudo python3 tools/write_usb.py --image build/ruby-fedora-live.img --device /dev/diskN --apply
```
Dismiss the "disk not readable" prompt macOS shows afterwards; do not initialize the stick.

**Windows (WSL 2):** WSL does not see USB drives until you attach them. In an administrator PowerShell:
```powershell
winget install usbipd
usbipd list                          # note the stick's BUSID, e.g. 2-3
usbipd bind --busid 2-3
usbipd attach --wsl --busid 2-3
```
Then follow the Linux steps in the WSL terminal. Afterwards, `usbipd detach --busid 2-3` before unplugging.

## 2. Unlock the bootloader

Follow Google's [bootloader-unlock instructions](https://support.google.com/googlebook/answer/17389679): in Googlebook OS, tap Build number seven times (About device), enable OEM unlocking (System → Advanced → Developer options), then with peripherals disconnected hold Esc + F2, tap Power, release the keys when the screen lights, and choose Advanced options → Unlock bootloader. This erases the device.

Leave developer mode enabled for as long as you run Fedora. If you may ever want Googlebook OS back, you can make a recovery USB at any time from another computer ([recovery](recovery.md)).

## 3. Install

Connect AC and the USB stick, start the laptop and choose **Boot from external drive** on the developer screen. You get a root console.

```sh
iwctl                                   # station wlan0 connect YOUR_SSID, then exit
cd /opt/ruby-fedora
python3 tools/install_fedora_ruby.py --user YOU --name 'Your Name' --timezone America/Chicago
```

Options: `--desktop kde` (tested), `--desktop gnome` or `--desktop none` (text login; the default); `--keymap`, `--hostname`.

- `--dry-run` shows the current partitions, the layout after installation, whether the Fedora image is on the USB and whether the network works, then stops without writing anything.
- `--backup DIR` first saves, to a mounted external drive (not the installer USB, not RAM), the raw partition table, every factory partition except `userdata` and `super` (about 0.8 GB), and the speaker calibration, and verifies them before anything is erased; the LUKS header is added after formatting. It is off by default: Google's recovery USB restores Googlebook OS completely, and the firmware can always be downloaded again. The backup contains private material (the LUKS header can unlock the disk with a password valid when it was taken); keep it offline.

The script asks once for `ERASE`, the disk encryption password and your login password, then runs unattended:

1. writes a new partition table: one Fedora root partition (about 465 GB), the boot partitions the firmware needs (`boot`, `init_boot`, `vendor_boot`, `vbmeta` for slots A and B, `misc`) at their factory positions, and the factory `super` partition, from which the speaker and sensor firmware is read; everything else is dropped;
2. creates LUKS2 (Argon2id) with Btrfs subvolumes `@`, `@home`, `@log`, `@pkg`;
3. takes Fedora's container image from the USB, or downloads it (either way the hash is pinned and the CHECKSUM signature is checked against the Fedora 45 key), unpacks it and installs `@core` and the system with the target's own `dnf5`, GPG checks on;
4. builds the out-of-tree modules with DKMS: the coreboot framebuffer (visible password prompt) and `cros_ec_ishtp` (light sensor);
5. saves the factory speaker calibration from VPD, and installs Lenovo's speaker and sensor firmware from `vendor_a`;
6. builds the small boot initramfs, signs the boot images with a new device key, validates them with the Android loader, relabels for SELinux and writes slot A.

Step 5 first tries the laptop's own `vendor_a`. If Googlebook OS had an update in flight, that copy is inconsistent and you will see `erofs: Failed to extract filesystem`; the installer then streams `vendor_a` from Google's Ruby recovery image instead (about 5.5 GB of download). That is expected.

If anything fails, the script stops with the error before writing the boot partitions. Fix the cause and run the same command again; it starts from the top. Firmware or module steps that fail only print a `WARNING` and the install continues.

When it prints `Done`, power off, remove the USB, start the laptop and choose **Boot from internal disk**. Type the disk password at the prompt.

## After the first boot

Connect Wi-Fi from the desktop (or `nmtui`), then clone this repository and run what you want:

```sh
sudo dnf install -y git
git clone https://github.com/bjerickson/lenovo-googlebook-ruby-fedora.git ~/googlebook && cd ~/googlebook

# Fingerprint reader (builds libfprint with the crfpmoc driver, a few minutes)
sudo sh tools/install_fingerprint_fedora.sh
fprintd-enroll && fprintd-verify
sudo authselect enable-feature with-fingerprint      # optional: sudo, login, lock screen

# Automatic screen brightness (KDE Plasma)
sudo sh tools/install_autobrightness.sh
systemctl --user daemon-reload && systemctl --user enable --now ruby-autobrightness

# Glowbar (adds you to the video group; reboot before enabling)
sudo sh tools/install_glowbar.sh
systemctl --user daemon-reload && systemctl --user enable --now ruby-glowbar
```

Also optional: `sudo sh tools/install_power_mode.sh` (22 W sustained on AC) and the 75–80 % charge limit rule; see [hardware notes](hardware.md).

Then read [maintenance](maintenance.md): kernel updates, rollback and SELinux.
