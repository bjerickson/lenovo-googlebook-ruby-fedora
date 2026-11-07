# How it works

## Boot path

Ruby keeps Google's Depthcharge firmware. In developer mode, its Android boot path picks the highest-priority successful `vbmeta` slot from the GPT, verifies the AVB metadata and loads Android v4 boot images. It never looks at `/boot` or an EFI system partition.

| Partition (slot A) | Size | Contents |
| --- | --- | --- |
| `boot_a` | 64 MiB | Fedora kernel and command line |
| `vendor_boot_a` | 32 MiB | the small encrypted-root initramfs (budget 29 MiB), padded to 4 bytes |
| `init_boot_a` | 8 MiB | an empty cpio |
| `vbmeta_a` | 4 MiB | descriptors for the three, signed with the device's own RSA-2048 AVB key |

The images are built by `lapis/boot.py` (AOSP `mkbootimg` and `avbtool`, pinned in `tools/fetch_sources.py`). Before anything is written, a sparse copy of the disk as it will be is booted through ChromiumOS's Android loader (`tools/loader_harness.c` + vboot_reference): the same code path as the firmware, run on the host. The loader concatenates vendor and generic ramdisks without padding, so the vendor ramdisk is padded to a multiple of four bytes.

AVB here checks image integrity; with a user key in developer mode it does not restore the locked-boot security model. The disk is encrypted, but the boot partitions are writable outside that encryption.

## Partition table

`tools/install_fedora_ruby.py` writes a new GPT with only:

- `userdata` (index 1): the LUKS2 root, from the factory userdata start to the end of the disk;
- `boot`, `init_boot`, `vendor_boot`, `vbmeta` for slots A and B, and `misc`, at their factory offsets (`assets/ruby-512gb.json`), because the firmware finds them by name; `vbmeta_a` is marked priority 15 and successful, `vbmeta_b` priority 0; `misc` is zeroed so no Android recovery command is pending;
- `super`: kept only as the source of Lenovo's firmware.

The other factory partitions (ChromeOS kernels, recovery, pvmfw, metadata, ESP) are dropped. Without a `pvmfw` partition the loader does not try to start protected-VM firmware.

## Root and initramfs

LUKS2 (aes-xts-plain64, 512-bit key, Argon2id) holds Btrfs with subvolumes `@` (/), `@home`, `@log` (/var/log) and `@pkg` (/var/cache/libdnf5). The command line uses `rd.luks.name=<uuid>=fedora-root`, so Fedora's systemd initrd asks for the password.

The initramfs is built with dracut from `/etc/ruby-boot/dracut.conf` and `/etc/ruby-boot/dracut.conf.d/`, never from `/etc/dracut.conf.d`, so it is unaffected by the normal Fedora initramfs that kernel-install also builds in `/boot`. `99-ruby-size.conf` overrides Fedora's `01-dist.conf` (all keymaps and fonts, rescue tools), omits FIPS, TPM2, FIDO2 and PCR modules and fsck tools, and lists the only modules needed: `nvme`, `vmd`, `dm_crypt`. Fedora builds the keyboard, USB HID, simpledrm, fbcon, Btrfs and AES-NI/XTS into the kernel. The result is about 20 MiB.

## Graphics

Fedora's kernel has no `CONFIG_GOOGLE_FIRMWARE`, so it cannot see the coreboot framebuffer and the password prompt would be blank. `assets/installed/coreboot-fb/` builds `coreboot_table`, `framebuffer-coreboot` and `vpd-sysfs` (unmodified Linux v7.3.3 sources) with DKMS. Without `CONFIG_DRM_COREBOOTDRM`, `framebuffer-coreboot` registers a `simple-framebuffer` device, which Fedora's built-in simpledrm drives; dracut force-loads both modules.

Xe is blacklisted during early boot (`modprobe.blacklist=xe`, `rd.driver.blacklist=xe`). `ruby-gpu.service` loads it once from the real root, taking the panel over from simpledrm, then loads SOF audio, which needs Xe's HDMI audio component first. Xe display power features run at driver defaults; options go in `/etc/modprobe.d/ruby-xe.conf`.

## Fedora bootstrap

The live USB is Arch (a pinned Omarchy ISO), so Fedora is not installed with Anaconda. The installer downloads Fedora's OCI container base image, checks its pinned SHA-256 and that the signed CHECKSUM file verifies with the Fedora 45 primary key (fingerprint `4F50 A611 4CD5 C697 6A7F 1179 655A 4B02 F577 861E`), unpacks its single layer into the new root, removes the container-only dnf and RPM settings that strip documentation and locales, and lets the target's own `dnf5` install `@core` and the rest, with repository GPG checks on. Container images never apply systemd presets, so the installer runs `systemctl preset-all --preset-mode=enable-only`, then uses `getty` rather than Fedora 45's default `kmscon` on the virtual consoles: the kernel console is what survives the simpledrm-to-Xe handover. SELinux labels are applied with `setfiles`; the first boot is permissive.

## Out-of-tree modules

Fedora does not build these drivers, so they are DKMS packages, rebuilt for every new kernel:

| Package | Modules | For |
| --- | --- | --- |
| `ruby-coreboot` | `coreboot_table`, `framebuffer-coreboot`, `vpd-sysfs` | visible password prompt; VPD (speaker calibration) |
| `ruby-cros-ec-ishtp` | `cros_ec_ishtp` | the sensor hub's EC: ambient light sensor |
| `cros-ec-usb` | `cros_ec_usb` | the fingerprint MCU (LKML v6 plus two patches) |

Fedora does not enforce module signatures without Secure Boot, so they load (and taint the kernel).

## Factory firmware

Lenovo's TAS2563 speaker tuning, the Ruby SOF firmware with Dolby DAX, its topology and DAX parameters, and Google's sensor-hub firmware live in the `vendor_a` EROFS image inside the factory `super` partition. The installer extracts them with `lpunpack` and `fsck.erofs`. A Googlebook that was mid-way through a virtual A/B update when it was wiped has an inconsistent `vendor_a` (an unmerged `vendor_a-cow`); then `tools/fetch_ruby_vendor.py` streams Google's official Ruby recovery image over HTTPS, reads its GPT and dynamic-partition (LP) metadata, and keeps only `vendor_a`, stopping the download once it is complete (about 5.5 GB of 7.8 GB). Nothing proprietary is stored in this repository.

## Kernel updates

See [maintenance](maintenance.md#kernel-updates). The kernel-install plugin reuses the installer's build, signing and loader validation, keeps a backup of the previous slot A and writes with read-back, restoring the old contents if a write fails.
