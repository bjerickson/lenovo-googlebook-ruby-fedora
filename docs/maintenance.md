# Maintenance

## Updating

### Fedora updates

```sh
sudo dnf upgrade
sudo reboot
```

Nothing else is needed. When a new kernel arrives, DKMS rebuilds this project's drivers for it and the kernel-update hook writes it to the boot partitions during the same transaction (see [kernel updates](#kernel-updates)). If that step fails, dnf still completes and prints a retry command; `sudo python3 /opt/lapis-kit/tools/kernel_update_fedora.py status` shows whether slot A holds the newest kernel.

### Updates to this project

The installed system does not run code from your git checkout: the kernel-update hook runs from `/opt/lapis-kit`, a copy made at install time, and the optional services are installed under `/usr/local/libexec`. After pulling changes, bring them across:

```sh
cd ~/googlebook && git pull
sudo python3 tools/update_installed.py
```

`update_installed.py` only touches what this project installed, and only where it differs from the checkout, so it is safe to run at any time:

- refreshes `/opt/lapis-kit` (code and assets; the built loader and pinned tool sources are kept unless their pins changed);
- reinstalls the kernel-update hook;
- rebuilds a DKMS driver (coreboot framebuffer, light sensor, fingerprint) for every installed kernel if its source changed;
- restores configuration files that are missing or differ: graphics and audio services, modprobe options, the UCM profile, the microphone boost, the speaker-calibration service. Firmware is never touched;
- reinstalls the glowbar, auto-brightness and power-mode services if you installed them.

It never writes the boot partitions. If the boot initramfs configuration changed, it says so; apply it with `kernel_update_fedora.py update`. It also tells you when to restart your user services and when the fingerprint library needs rebuilding.

### When something else needs attention

- **The fingerprint library is held back.** `/etc/dnf/dnf.conf` has `excludepkgs=libfprint`, so dnf skips Fedora's libfprint updates and the reader keeps working with this project's build. When the project moves to a newer libfprint, `update_installed.py` says so; rebuild with `sudo sh tools/install_fingerprint_fedora.sh`.
- **The audio profile can be overwritten.** The UCM profile lives under `/usr/share/alsa/ucm2/conf.d/sof-rt5682/`, which Fedora's `alsa-ucm` package could one day claim. If the speakers go silent after an update, run `sudo python3 tools/update_installed.py`, which puts it back.
- **Fedora release upgrades** (for example 45 to 46 with `dnf system-upgrade`) have not been tested. The kernel hook runs in that transaction too, but the libfprint hold can stop dependency resolution; if it does, run the upgrade with `--setopt=excludepkgs=` and rebuild the fingerprint library afterwards. Keep the installer USB at hand for [rollback](#if-a-new-kernel-does-not-boot).

## Kernel updates

The firmware boots the kernel in the Android boot partitions (slot A), not `/boot`. The installer adds a kernel-install plugin, `/etc/kernel/install.d/95-ruby-android.install`, so an ordinary `sudo dnf upgrade` that brings a new kernel also:

1. rebuilds the DKMS modules for it (Fedora's `40-dkms` plugin runs first);
2. builds the small Ruby initramfs with `/etc/ruby-boot/dracut.conf` (29 MiB budget);
3. signs the four boot images with the device key `/etc/asus-boot/avb-private.pem`;
4. validates them with ChromiumOS's Android loader;
5. backs up the current slot A to `/var/lib/asus-boot/kernel-update/slots/` (the last two are kept), writes the new set and reads it back.

Reboot to use the new kernel. If any step fails, nothing is written, the dnf transaction still succeeds, and the message says how to retry:

```sh
sudo python3 /opt/lapis-kit/tools/kernel_update_fedora.py status    # running, slot A, newest installed
sudo python3 /opt/lapis-kit/tools/kernel_update_fedora.py update    # build and write the newest kernel now
```

Fedora keeps three kernels installed and never removes the running one, so the slot-A kernel's modules are always present. Do not lower `installonly_limit`.

### If a new kernel does not boot

Boot the installer USB, then:

```sh
cryptsetup open /dev/nvme0n1p1 fedora-root
mount -o subvol=@ /dev/mapper/fedora-root /mnt
arch-chroot /mnt python3 /opt/lapis-kit/tools/kernel_update_fedora.py rollback
umount /mnt; cryptsetup close fedora-root
```

`rollback` restores the slot-A backup taken before the last update. From a working system the same command works directly.

### Changing the boot command line or initramfs

The command line is `/etc/kernel/cmdline`; the initramfs configuration is `/etc/ruby-boot/dracut.conf` and `/etc/ruby-boot/dracut.conf.d/`. After editing either, run `kernel_update_fedora.py update` to rebuild and write slot A. Xe options belong in `/etc/modprobe.d/ruby-xe.conf` instead and need only a reboot.

## libfprint

The fingerprint reader needs this repository's libfprint build, so `/etc/dnf/dnf.conf` has `excludepkgs=libfprint`. When Fedora ships a newer libfprint, update `assets/packages/libfprint-crfpmoc/libfprint.spec` to it (check the patches still apply) and rerun `sudo sh tools/install_fingerprint_fedora.sh`. Enrolled prints survive: they are tied to `/var/lib/fprint/crfpmoc-seed`, not to the library.

## SELinux

The install relabels the filesystem but leaves SELinux **permissive**. After a few normal boots and the optional extras:

```sh
sudo ausearch -m avc -ts boot
```

If it reports nothing, switch to enforcing and reboot:

```sh
sudo sed -i 's/^SELINUX=permissive/SELINUX=enforcing/' /etc/selinux/config
sudo reboot
```

Report any denials that involve this project's services in an issue.

## Snapshots

The root is Btrfs (`@`, `@home`, `@log`, `@pkg`) and `snapper` is installed. A root snapshot does not include the Android boot partitions; kernel changes are rolled back with `kernel_update_fedora.py rollback`.

## Things not to do

- Do not relock the bootloader or leave developer mode: the firmware would refuse the self-signed boot images.
- Do not install GRUB, shim or systemd-boot, and do not repartition the disk: the firmware boots only the named Android partitions.
- Do not delete the `super` partition until you no longer need to rerun `install_ruby_audio.sh` or `install_ruby_sensors.sh` (without it they fall back to downloading `vendor_a` from Google's recovery image, about 5.5 GB).
