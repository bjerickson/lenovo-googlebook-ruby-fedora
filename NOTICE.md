# Attribution and source boundaries

This is a fork of [lenovo-googlebook-ruby-cachyos](https://github.com/nbarrios/lenovo-googlebook-ruby-cachyos) (Nick Barrios), itself a fork of [asus-googlebook-omarchy](https://github.com/jmklex/asus-googlebook-omarchy) (Jonathan Kleiman). The Python toolkit, installers and documentation of all three are released under MIT.

This repository does not redistribute Fedora, Omarchy, any OS image, Lenovo or Google firmware, Wi-Fi credentials, SSH host keys, AVB private keys, disk backups or LUKS headers.

The build downloads pinned **source code** from these projects. They retain their licenses:

| Component | Source | License |
|---|---|---|
| Android boot-image tools | [AOSP mkbootimg](https://android.googlesource.com/platform/system/tools/mkbootimg/) | Apache-2.0 |
| Android Verified Boot | [AOSP libavb / avbtool](https://android.googlesource.com/platform/external/avb/) | MIT/BSD and Apache-2.0 components; see upstream license files |
| Firmware loader validator | [ChromiumOS vboot_reference](https://chromium.googlesource.com/chromiumos/platform/vboot_reference/) | BSD-style and upstream component notices |
| Installer USB base, downloaded by the user | [Omarchy](https://github.com/omacom/omarchy) 4.0.4 ISO ([Arch Linux](https://archlinux.org/)) | Each package's license |
| Installed OS, downloaded at install time | [Fedora](https://fedoraproject.org/) 45 container image and repositories | Each package's license |

`assets/installed/cros-ec-usb/` is Linux kernel code under GPL-2.0, not MIT: Google's `cros_ec_usb.c` as posted to LKML (v6, unmodified), `cros_ec.h` from Linux v7.2 (unmodified), a Kbuild `Makefile`, and two patches that DKMS applies at build time for the fingerprint reader. Provenance and checksums are in its `dkms.conf`.

`assets/installed/coreboot-fb/` is Linux kernel code under GPL-2.0, not MIT: `coreboot_table.[ch]`, `framebuffer-coreboot.c`, `vpd.c` and `vpd_decode.[ch]` from Linux v7.3.3 `drivers/firmware/google/`, unmodified, with a Kbuild `Makefile` and `dkms.conf`. They give kernels built without `CONFIG_GOOGLE_FIRMWARE` (Fedora) the coreboot framebuffer and VPD.

`assets/packages/libfprint-crfpmoc/` holds an RPM spec and patches to [libfprint](https://gitlab.freedesktop.org/libfprint/libfprint), which is LGPL-2.1-or-later. Patch `0001` is the unmodified diff of libfprint MR !512 (the `crfpmoc` driver); `0002`–`0006` are the upstream Ruby port's changes, offered under the same license as libfprint. `libfprint.spec` is Fedora's libfprint 1.94.100 spec with those patches added.

The Ruby audio setup does not redistribute Lenovo or Google firmware. `tools/install_ruby_audio.sh` extracts the TAS2563 tuning, the Ruby SOF firmware with Dolby DAX, its topology and the DAX parameters from the laptop's own factory `vendor_a` image at install time, and `tools/install_ruby_sensors.sh` extracts Google's Intel Sensor Hub firmware for Ruby from the same image. When the laptop's copy is unusable, `tools/fetch_ruby_vendor.py` downloads `vendor_a` from Google's official Ruby recovery image for the user.

`tools/loader_harness.c` is a modified ChromiumOS test utility, governed by `tools/LICENSE.chromium`. It is a host simulation of the Android loader in developer mode, not Googlebook firmware or a replacement firmware image. Its disk-write callback deliberately does not write.

Source revisions are fixed in `tools/fetch_sources.py`. Generated live images contain the source and licenses of those fetched build tools so native boot images can be assembled without another network download.

`assets/installed/cros-ec-ishtp/` is Linux kernel code under GPL-2.0, not MIT: `cros_ec_ishtp.c` and `cros_ec.h` from Linux v7.2.15 `drivers/platform/chrome/`, unmodified, with a Kbuild `Makefile` and `dkms.conf`, for kernels built without `CONFIG_CROS_EC_ISHTP` (Fedora).
