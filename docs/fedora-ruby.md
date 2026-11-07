# Fedora 45 on Lenovo Googlebook 15 (Ruby)

**Work in progress, not yet physically tested.** This fork replaces CachyOS with Fedora 45 in the Ruby procedure. Everything outside the distribution, including the live USB, backup, format, boot-image build, loader validation and commit, is the upstream code described in [cachyos-ruby.md](cachyos-ruby.md), [install.md](install.md) and [recovery.md](recovery.md). Read those first.

This **replaces Googlebook OS entirely**: `userdata` (~464 GB) becomes the encrypted Fedora root. The small Android boot partitions stay because the firmware boots from them. The 12 GB `super` partition stays because the audio and sensor installers extract Lenovo's firmware from it.

## What differs from CachyOS

| Area | CachyOS | Fedora |
| --- | --- | --- |
| Bootstrap | `pacstrap` from the live USB | Fedora's signed container image (hash pinned, CHECKSUM signature checked against the Fedora 45 key), unpacked into `/mnt`; the target's own `dnf5` installs the rest with GPG checks |
| Root mapper / labels | `cachyos-root`, `CACHYOS` | `fedora-root`, `FEDORA` |
| Boot initramfs | `mkinitcpio` + `encrypt` | `dracut` with `assets/fedora/dracut.conf` (systemd initrd, `rd.luks.name=`), isolated from `/etc/dracut.conf.d` |
| Kernel location | `/boot/vmlinuz-linux-cachyos` | `/boot/ruby-android/vmlinuz` (outside kernel-install's names) |
| SELinux | none | relabelled with `setfiles` at install; first boot **permissive** |
| Package cache subvolume | `/var/cache/pacman/pkg` | `/var/cache/libdnf5` |
| Speaker calibration | read from VPD at every boot | captured from VPD **once, at install**, into `/etc/ruby/speaker-calibration` (Fedora's kernel lacks `CONFIG_GOOGLE_FIRMWARE`) |

## RAM-only backup

`backup --in-ram` keeps the backup in `/run/lapis-install/ram-backup` (tmpfs) instead of on an external drive. The install still needs it: `format` stores the LUKS header there, and `commit` uses the original bytes to restore the boot regions if a write fails. It disappears at power-off, so nothing outside the laptop can undo the installation; a factory recovery USB is then the only way back to Googlebook OS. A successful commit still archives the install state, including that backup, on the encrypted root under `/var/lib/asus-boot/installation`. It needs about 2 GB free in `/run`; if `backup` says otherwise, run `mount -o remount,size=8G /run`. Do not reboot the live session between `backup` and `commit`.

## Known gaps

- **Blank screen at the disk password.** Fedora's kernel has no coreboot framebuffer driver. If Depthcharge does not hand over a framebuffer that `simpledrm` can use, the LUKS prompt is invisible: type the password blind and press Enter. Xe takes over the display after root is mounted. Check on the live USB first: `dmesg | grep -i -e simpledrm -e simple-framebuffer`.
- **No ambient light sensor** (`CONFIG_CROS_EC_ISHTP` is off in Fedora).
- **Kernel updates are not yet automated.** `dnf upgrade` installs new kernels alongside the old one (Fedora keeps 3 and never removes the running one), but slot A keeps booting the kernel from installation until a Fedora version of `kernel_update.py` exists. Do not lower `installonly_limit`.
- Fingerprint (libfprint RPM) and the other optional installers are not ported yet.

## Procedure (root, console-only live session)

```sh
cd /opt/asus-googlebook-omarchy
iwctl                                    # station wlan0 connect YOUR_SSID
curl -I https://dl.fedoraproject.org

# 1. Inspect and back up
python3 tools/native.py plan --device /dev/nvme0n1
python3 tools/native.py backup --in-ram   # or --destination /run/media/backup/ruby-original on an ext4 drive

# 2. Format userdata only (unchanged)
python3 tools/native.py format
python3 tools/native.py format --apply

# 3. Install and configure Fedora
python3 tools/configure_fedora.py packages --user YOU --name 'Your Name' --timezone America/Chicago --keymap us
python3 tools/configure_fedora.py configure     # also saves speaker calibration to /mnt (and the backup)

# 4. Build and validate the boot set (unchanged)
mkdir -p /mnt/opt/lapis-kit && cp -a . /mnt/opt/lapis-kit/
arch-chroot /mnt python3 /opt/lapis-kit/tools/build_loader.py
python3 tools/native.py build
python3 tools/native.py validate --loader /mnt/opt/lapis-kit/build/load_android_test

# 5. Commit (unchanged)
python3 tools/native.py commit
python3 tools/native.py commit --apply
sync; umount -R /mnt; cryptsetup close fedora-root; poweroff
```

`--desktop gnome` or `--desktop kde` installs a desktop in step 3. The default `none` gives a text first boot, which is easier to debug; install a desktop afterwards with `sudo dnf install @workstation-product-environment` and `sudo systemctl set-default graphical.target`.

## First boot

Choose **Boot from internal disk** and type the disk password (blind, if the screen is blank). Then:

```sh
findmnt /                          # btrfs on /dev/mapper/fedora-root
uname -r
systemctl status ruby-gpu.service
systemctl --failed
getenforce                         # Permissive
sudo ausearch -m avc -ts boot      # SELinux denials; when quiet, set SELINUX=enforcing in /etc/selinux/config
nmtui
```

Audio: `sudo /opt/lapis-kit/tools/install_ruby_audio.sh`, then reboot. The calibration service finds `/etc/ruby/speaker-calibration` and prints `Calibration source:` in `journalctl -u ruby-speaker-calibration`.
