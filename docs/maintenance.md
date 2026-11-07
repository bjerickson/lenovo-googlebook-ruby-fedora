# Maintenance

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
- Do not delete the `super` partition until you no longer need to rerun `install_ruby_audio.sh` or `install_ruby_sensors.sh` (they can also use Google's recovery image instead: `tools/fetch_ruby_vendor.py`).
