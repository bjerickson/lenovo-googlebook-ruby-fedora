# Attribution and source boundaries

The Python toolkit, configuration assembly and documentation are original project work, released under MIT. The live and installed graphics startup scripts were extracted from the implementation tested on the physical ASUS Googlebook.

This repository does not redistribute Omarchy, an OS image, ASUS firmware, Wi-Fi credentials, SSH host keys, AVB private keys, disk backups or LUKS headers.

The build downloads pinned **source code** from these projects. They retain their licenses:

| Component | Source | License |
|---|---|---|
| Android boot-image tools | [AOSP mkbootimg](https://android.googlesource.com/platform/system/tools/mkbootimg/) | Apache-2.0 |
| Android Verified Boot | [AOSP libavb / avbtool](https://android.googlesource.com/platform/external/avb/) | MIT/BSD and Apache-2.0 components; see upstream license files |
| Firmware loader validator | [ChromiumOS vboot_reference](https://chromium.googlesource.com/chromiumos/platform/vboot_reference/) | BSD-style and upstream component notices |
| OS and applications, obtained separately | [Omarchy](https://github.com/omacom/omarchy), [Arch Linux](https://archlinux.org/) | Each package's license |

`assets/installed/cros-ec-usb/` is Linux kernel code under GPL-2.0, not MIT: Google's `cros_ec_usb.c` as posted to LKML (v6, unmodified), `cros_ec.h` from Linux v7.2 (unmodified), a Kbuild `Makefile`, and two patches that DKMS applies at build time for the fingerprint reader. Provenance and checksums are in its `dkms.conf`.

`assets/installed/coreboot-fb/` is Linux kernel code under GPL-2.0, not MIT: `coreboot_table.[ch]`, `framebuffer-coreboot.c`, `vpd.c` and `vpd_decode.[ch]` from Linux v7.3.3 `drivers/firmware/google/`, unmodified, with a Kbuild `Makefile` and `dkms.conf`. They give kernels built without `CONFIG_GOOGLE_FIRMWARE` (Fedora) the coreboot framebuffer and VPD.

`assets/packages/libfprint-crfpmoc/` holds a PKGBUILD and patches to [libfprint](https://gitlab.freedesktop.org/libfprint/libfprint), which is LGPL-2.1-or-later. Patch `0001` is the unmodified diff of libfprint MR !512 (the `crfpmoc` driver); `0002`–`0005` are this project's changes and are offered under the same license as libfprint. The PKGBUILD is derived from the Arch Linux libfprint PKGBUILD.

The Ruby audio setup does not redistribute Lenovo or Google firmware. `tools/install_ruby_audio.sh` extracts the TAS2563 tuning, the Ruby SOF firmware with Dolby DAX, its topology and the DAX parameters from the laptop's own untouched factory `super` partition at install time. `tools/install_ruby_sensors.sh` likewise extracts Google's Intel Sensor Hub firmware for Ruby from the same partition.

`tools/loader_harness.c` is a modified ChromiumOS test utility, governed by `tools/LICENSE.chromium`. It is a host simulation of the Android loader in developer mode, not ASUS firmware or a replacement firmware image. Its disk-write callback deliberately does not write.

The audio diagnosis used the Linux Lapis board quirk and SOF topology sources. The [ExpertBook audio notes](https://github.com/burakgon/asus-expertbook-linux/tree/main/audio-fix) helped identify the matching `1043:15e4` speaker tuning. That project's patcher and firmware blobs are not incorporated. ExpertBook firmware must not be flashed onto a Googlebook.

Source revisions are fixed in `tools/fetch_sources.py`. Generated live images contain the source and licenses of those fetched build tools so native boot images can be assembled without another network download.

`assets/installed/cros-ec-ishtp/` is Linux kernel code under GPL-2.0, not MIT: `cros_ec_ishtp.c` and `cros_ec.h` from Linux v7.2.15 `drivers/platform/chrome/`, unmodified, with a Kbuild `Makefile` and `dkms.conf`, for kernels built without `CONFIG_CROS_EC_ISHTP` (Fedora).
