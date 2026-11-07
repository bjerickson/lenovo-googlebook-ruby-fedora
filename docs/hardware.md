# Ruby hardware notes

Lenovo Googlebook 15, DMI `Google / Ruby` (`Google_Fatcat` family), firmware `Google_Ruby.16650.143.0`, Core Ultra 5 325 (Panther Lake), 512 GB NVMe.

Most of these notes were measured on the laptop in October 2026 under CachyOS (kernel 7.2.9) by the upstream project, [lenovo-googlebook-ruby-cachyos](https://github.com/nbarrios/lenovo-googlebook-ruby-cachyos). They describe the hardware and kernel drivers, not the distribution. What has been re-checked on Fedora 45 is listed in [validation.md](validation.md); the Fedora-specific pieces (installer, kernel updates, DKMS modules) are in [architecture.md](architecture.md).

## Audio

`dspcfg` auto-detection picks legacy HDA (HDMI only), the TAS2563 tuning firmware is not in linux-firmware, and alsa-ucm-conf has no `sof-rt5682` profile. `tools/install_fedora_ruby.py` sets all of this up during installation; `sudo tools/install_ruby_audio.sh` redoes it on an installed system.

The script reads Lenovo's `tas2563RCA4.bin` and `tas2563_coef.bin` from the factory `vendor_a` image (in the kept `super` partition, or from Google's Ruby recovery image via `tools/fetch_ruby_vendor.py` when the local copy is left inconsistent by an unmerged Android update) into `/usr/lib/firmware/updates`, forces SOF (`ruby-audio.conf`), loads SOF after Xe (`ruby-gpu.service`), and installs a UCM profile converted from the factory CRAS config. The UCM Speaker sequence selects TAS2563 DSP configuration 0; the driver otherwise starts with configuration -1 and the amplifiers stay silent.

Factory per-speaker calibration lives in coreboot VPD (`dsm_calib_register_array`, `dsm_calib_value_0..3`), not on the erased disk. Fedora's kernel has no `CONFIG_GOOGLE_VPD`, so the installer saves the values from the live USB to `/etc/ruby/speaker-calibration` and also builds `vpd-sysfs` with DKMS; `ruby-speaker-calibration.service` writes them to the driver's write-only `Speaker Calibrated Data` control at boot.

Dolby DAX: Lenovo ships a Ruby-specific SOF firmware with a built-in Dolby module (`intel/sof-ipc4/ptl/ruby/sof-ptl.ri`, 2.14.1008.1) and a topology with `dolby-dax` pipelines. `ruby-dax.conf` points `snd_sof_pci` at them, as Googlebook OS's `mod_options --sof-fw` does, and a conditional UCM BootSequence block loads `dax_param.bin` and the factory switch/profile values. Remove `/etc/modprobe.d/ruby-dax.conf` to return to the stock sof-firmware files; the UCM block then skips itself. Toggle live with `amixer -c sofrt5682 cset name='DAX Speaker Switch' on|off`.

Microphones: there is no NHLT table, so `ruby-audio.conf` sets `dmic_num=4`. The DMICs are rated -26 dBFS at 94 dB SPL and SOF capture gain tops out at 0 dB, so speech arrives near -60 dBFS. Googlebook OS added gain in software; `/etc/pipewire/pipewire.conf.d/ruby-mic.conf` does the same with a filter-chain source ("Internal Microphone", `ruby_mic`): an 80 Hz high-pass and +36 dB in two `linear` stages (the builtin clamps `Mult` to 10). It outranks the raw mic and yields to a plugged-in headset mic.

## Suspend and power key

`s2idle` (the default in `/sys/power/mem_sleep`) works: on 10 October 2026 a 30 s RTC-woken suspend spent 30.06 s in S0ix (`slp_s0_residency_usec`), resumed with no Xe, SOF, Wi-Fi or `cros_ec_usb` errors, Wi-Fi reassociated within about 4 s, and audio, input and `fprintd-verify` worked afterwards. `tools/test_suspend.sh` repeats the check. `ruby-power-key.conf` in `/etc/systemd/logind.conf.d/` makes a short power-key press suspend and a long press shut down (logind's default is to power off on a short press); power key and lid suspend verified. Overnight on battery (lid closed, 11 h 18 min in one uninterrupted s2idle sleep) the battery went from 100% to 96% (182 of 4525 mAh), about 0.35 %/h or 16 mA. After one resume the kernel logged `cros_ec_ucsi GOOG0021:00: failed to re-enable notifications (-110)`, but it did not recur, and on 11 October 2026 a USB-C external display worked before suspend and after resume, including unplugging and replugging it twice.

## Camera

The integrated camera is USB UVC (`30c9:013f`, `uvcvideo`, no setup): `/dev/video0` offers MJPG up to 2592×1944 and 1920×1080 at 30 fps, and YUYV up to 640×480 at 30 fps; `/dev/video1` is its metadata node. Verified in Chrome, 11 October 2026.

## Thunderbolt

The Thunderbolt/USB4 controller runs at security level `user` with IOMMU DMA protection, so a dock does nothing until `boltd` authorizes it. The installer includes `bolt`. Enroll a dock once with `boltctl enroll --policy auto <uuid>` (the UUID is in `boltctl list`); bolt records the policy as `iommu` and then authorizes the dock on every plug-in. Verified 11 October 2026 with a Belkin Thunderbolt 3 Dock Plus (40 Gb/s, USB Power Delivery charging, USB and its Realtek Ethernet adapter enumerated, a USB mouse working), including after resume and after unplugging and replugging. Plugging in a dock logs `cros_ec_ucsi ... UCSI_GET_PDOS failed (-5)`, and a resume with a dock attached logged `failed to re-enable notifications (-110)` again; neither affected charging or hotplug. Displays through the dock are untested.

## Bluetooth

Intel CNVi Bluetooth (`hci0`, bluez 5.87) works without setup; pair from Plasma's Bluetooth settings or `bluetoothctl`. The kernel logs `Failed to send Intel_Write_DDC (-95)` at startup; it is harmless. Verified 11 October 2026 with earbuds: playback uses A2DP with AAC, and opening the headset microphone makes WirePlumber switch to HFP with mSBC (16 kHz), then back to A2DP when recording stops. The first second or so of a recording is lost during that switch. The internal-microphone boost does not apply to Bluetooth microphones.

## Keyboard backlight

`cros_kbd_led_backlight` exposes `chromeos::kbd_backlight` (0–100). `brightnessctl -d chromeos::kbd_backlight set 40%` works without root through logind, and `systemd-backlight` restores the level at boot. The ChromeOS convention is Alt plus the screen-brightness keys.

## Top-row keys

The top row reports, left to right: `KEY_BACK`, `KEY_HOMEPAGE`, `KEY_SCALE` (overview, XKB `XF86LaunchA`), `KEY_FULL_SCREEN`, `KEY_SYSRQ` (screenshot, `Print`), brightness down and up, `KEY_KBDILLUMTOGGLE`, `KEY_MICMUTE`, `KEY_MUTE` and the volume keys; two further keys send `KEY_ACCESSIBILITY` and `KEY_DICTATE` (XKB `XF86Accessibility`, `XF86Dictate`, xkeyboard-config 2.48). All arrive on the `AT Translated Set 2 keyboard` device and need no remapping; bind them in the compositor.

## Ambient light sensor

The Intel Sensor Hub (ISH) needs Google's board firmware. linux-firmware only has Intel's generic `ish_ptl.bin`, with which the ISH exposes HID sensors (accelerometer, gyroscope, magnetometer, light) that all read 0. The factory `vendor_a` image carries `firmware/intel/ish/ish_ptl_62b0f067_6c687233.bin`, the name the kernel's ISH loader tries first on this board (CRC32 of the DMI vendor "Google" and product "Ruby"). The installer (or `sudo tools/install_ruby_sensors.sh`) extracts it into `/usr/lib/firmware/updates`; the ISH driver loads after the initramfs, so a reboot is enough. The ISH then reports `CrOS Integrated Sensor Hub MCU detected`, `cros_ec_ishtp` registers it, and `cros-ec-light` (IIO, `in_illuminance_input`) gives the ambient light level; the placeholder HID sensors disappear. Verified 11 October 2026: about 10 lux in a dim room, 1 when covered and up to about 5600 under a phone flashlight. The firmware also declares an ACPI ambient light sensor (`acpi-als`) that always reads 0. It registers first and is the only one with `in_illuminance_raw`, so tools that take the first light sensor read it and see a dark room; the installer blacklists `acpi_als` in `/etc/modprobe.d/ruby-sensors.conf`. `cros-ec-sensorhub ... unknown type 8` at boot is a sensor type the kernel does not support yet and is harmless. The firmware is loaded into the ISH at every boot, never flashed; deleting the file and rebooting returns to the generic firmware. For automatic screen brightness under KDE Plasma, `sudo tools/install_autobrightness.sh` installs `ruby-autobrightness`, a user service that maps the sensor to the panel through Plasma's own `org.kde.ScreenBrightness` D-Bus API (so the slider and keys stay in sync) and keeps manual changes as an offset.

## Fan and thermals

The EC drives the single fan on its own (`cros_ec` hwmon, `pwm1_enable=2` automatic) from its CPU sensor; `acpi_fan` reports the same speed. Idle on 11 October 2026: about 2,740 rpm (PWM 84/255), package 43 °C. With all 8 cores of the Core Ultra 5 325 busy for two minutes, the CPU ran at about 3.3 GHz for the first ~15 s (package up to 91 °C, PL2 35 W), then held about 1.8 GHz at 66–68 °C under the 15 W long-term limit (PL1, 28 s window). The fan rose to about 4,250 rpm (PWM 153, 60%) and fell back over a minute of cooldown. No thermal throttling or critical-temperature messages were logged; sustained performance is set by the firmware's 15 W limit, not by temperature.

The 15 W long-term limit (PL1) is not locked: root can raise it to the reported 25 W maximum through `/sys/class/powercap`, on both `intel-rapl:0` (MSR) and `intel-rapl-mmio:0` (the lower of the two applies). The SoC power slider is `platform_profile` (`low-power`, `balanced`, `performance`), managed by power-profiles-daemon (`tuned-ppd` on Fedora). Two minutes of all-core load per setting on AC, performance profile:

| PL1 | Sustained clock | Package | Fan |
| --- | --- | --- | --- |
| 15 W (stock, balanced) | ~1.8 GHz | 67 °C | ~4,100 rpm |
| 20 W | ~2.24 GHz | 78 °C | ~4,330 rpm |
| 22 W | ~2.39 GHz | 83 °C | ~4,390 rpm |
| 24 W | ~2.55 GHz | 87–89 °C, still rising | ~4,400 rpm |
| 25 W | 2.6–2.9 GHz, falling | 90–91 °C, held at the thermal target | ~4,500 rpm |

Each run starts with about 30 s at the 35 W short-term limit. The EC's fan curve stops at about 63% whatever the CPU temperature, because it follows the EC's own sensor; above about 24 W the package reaches its 91 °C target and clocks fall. The optional `sudo tools/install_power_mode.sh` sets 22 W and the performance profile on AC and restores 15 W and balanced on battery: a service applies it at boot, a udev rule when AC changes, and a `system-sleep` hook after resume (verified 12 October 2026: AC unplug and replug, and suspend). Change `AC_WATTS` in `assets/installed/power/ruby-power-mode` for another limit.

## Glowbar

The glowbar is the EC's lightbar (`cros_ec_lightbar`, protocol version 3, four segments numbered 0–3 from the left), under `/sys/class/chromeos/cros_ec/lightbar/`. Direct colour writes work (`echo "LED R G B" > led_rgb`, LED 4 for all segments; `brightness` 0–255), but the EC rejects the built-in sequences, programs and parameters (`INVALID_PARAM`), so any animation has to come from the host. The kernel's own suspend and resume sequences fail for the same reason, so nothing switches the bar off for sleep unless the host does.

`sudo tools/install_glowbar.sh` installs `ruby-glowbar`, a user service with this priority: pulsing red while hyprwhspr is recording; on AC while charging, green segments up to the charge level with the segment being filled breathing from yellow to green as it nears completion, and solid green when not charging (full or held at the charge limit); on battery, amber at 20% or below and pulsing red at 10% or below; otherwise the desktop accent colour (KDE Plasma's `AccentColor`) at full saturation (pastel theme colours look white on the LEDs). The bar is off while the session is locked, the panel is off or the lid is closed. The installer also adds a udev rule that lets the `video` group write `led_rgb` and `brightness`, a `system-sleep` hook that switches the bar off before suspend, and the invoking user to `video`. Reboot afterwards: the systemd user manager keeps its old groups across a logout. Verified 11 October 2026.

## Battery charge limit

The EC's charge control (`cros_charge_control`) exposes `charge_control_start_threshold` and `charge_control_end_threshold` on `BAT0`; they reset at boot. The optional `assets/installed/udev/90-ruby-charge-limit.rules` holds the battery between 75 and 80% on AC:

```sh
sudo install -Dm644 assets/installed/udev/90-ruby-charge-limit.rules /etc/udev/rules.d/
sudo udevadm control --reload
sudo udevadm trigger --action=add /sys/class/power_supply/BAT0
```

Edit the two numbers in the rule for other limits.

## Display

The Samsung ATNA53JB03 OLED runs at 2880x1800@120 (KDE Display Configuration). Xe feature switches live only in `/etc/modprobe.d/ruby-xe.conf`, not the kernel command line, so changing them needs a reboot but no boot-set rebuild. All Xe display power features run at driver defaults (10 October 2026: stable at 120 Hz, DC3→DC5→DC6 entered, driver selects Panel Replay with selective update, which disables FBC). On a still screen `i915_edp_psr_status` shows `ctl: enabled` and status `SLEEP`, and DC5→DC6 entries keep rising (28 in 10 s). External displays work on USB-C DisplayPort and on the built-in HDMI port (11 October 2026; HDMI tested with a 1920x1080@60 monitor; the desktop extends automatically). A 4K OLED monitor on USB-C offered 3840x2160 at 60, 120, 180 and 240 Hz and ran cleanly at 240 Hz; Compositors pick the monitor's preferred mode (60 Hz here); choose a higher rate in the display settings. With an external monitor attached, map the touchscreen to the built-in panel (`eDP-1`) in the desktop's touchscreen settings so touches land on it. To fall back, add `enable_panel_replay=0 enable_psr=0` (then `enable_fbc=0 enable_dsb=0 enable_sagv=0 enable_dc=0`) to the `options xe` line and reboot.

## Fingerprint

The reader is a Google fingerprint MCU on internal USB (`18d1:5402`, interface `ff/5a/00`). Linux 7.2 has no driver for that transport. Google's `cros_ec_usb` driver was posted to LKML (v6, September 2025) but is not merged. Research and the security model: [research/fingerprint.md](research/fingerprint.md).

On Fedora, `sudo tools/install_fingerprint_fedora.sh` sets up both halves (verified on the laptop, 7 November 2026: `fprintd-enroll` and `fprintd-verify`):

- **Kernel:** `assets/installed/cros-ec-usb/`, DKMS package `cros-ec-usb/6.1`: Google's unmodified v6 `cros_ec_usb.c`, the private `cros_ec.h` from Linux v7.2 (absent from distribution kernel headers), and two patches DKMS applies at build time. `0001` ports the driver to the 6.18+ cros_ec core, which no longer allocates buffers or initialises the lock in `cros_ec_register()`; `0002` unregisters the EC on module unload so `rmmod` is safe. DKMS rebuilds it for each new kernel. Fedora does not enforce module signatures without Secure Boot, so it loads (and taints the kernel).
- **Userspace:** Fedora's libfprint 1.94.100 spec (`assets/packages/libfprint-crfpmoc/libfprint.spec`, release `100.crfpmoc4`) plus six patches. It replaces Fedora's `libfprint` under the same name and soname, so `fprintd` works unchanged. The installer adds `excludepkgs=libfprint` to `/etc/dnf/dnf.conf`; when Fedora ships a newer libfprint, rebase the spec and rerun the installer. The full libfprint test suite passes (133 tests, including the `crfpmoc` and `crfpmoc-v3` replays and unit tests for the v3 parser and the seed file).

The patches:

- `0001`: libfprint [MR !512](https://gitlab.freedesktop.org/libfprint/libfprint/-/merge_requests/512) (driver `crfpmoc`), pinned to head `56442591`. This is the unmodified MR diff; it applies to 1.94.100 with offsets only.
- `0002`: `FP_INFO` v2/v3. The MR asks for v1, which srebrna rejects with `INVALID_VERSION`. At open the driver queries `GET_CMD_VERSIONS` and uses the highest of v3/v2/v1, falling back to v1 if the query fails, so older Chromebooks keep working. A v3 response is the header plus 10 frame entries (236 bytes); the EC refuses a smaller buffer. The driver reads only the template fields. Frame sizes are logged, never used.
- `0003`: a persistent seed. The MR picks a random `FP_SEED` and user id on every open, so prints would stop matching after fprintd restarts or a reboot. The patched driver:
  - reads 32 bytes from `/var/lib/fprint/crfpmoc-seed`, creating the file on first use with `getrandom(2)`;
  - refuses the file unless it is root-owned with mode 0600 or stricter, in a root-owned directory that is not group or world writable;
  - derives the `FP_CONTEXT` user id as SHA-256(`crfpmoc-userid-v1` ‖ seed), one id for the whole machine;
  - sets the seed only when `fpencstatus` reports it unset, and treats `ACCESS_DENIED` as "already set".
- `0004`: reply sizes. `FP_MODE` always returns its 4-byte mode, but the MR sent the sensor reset (end of enroll/verify) and the clear-storage `FP_MODE` commands with `insize` 0. The EC transports reject a reply larger than `insize`: over USB the ioctl fails with `ENOSPC` and the kernel logs `Incorrect number of expected bytes: 12`. Every `FP_MODE` now passes `insize` 4. All other commands already used the `ec_commands.h` response sizes; `FP_SEED`, `FP_CONTEXT` v1 and `FP_TEMPLATE` return no data. The replay traces already recorded `insize` 4 (umockdev does not compare `insize`), so they are unchanged.
- `0005`: event callback. `g_pollable_input_stream_create_source()` calls its callback as `GPollableSourceFunc (stream, user_data)`, but the MR's `crfpmoc_read_bytes()` took only `user_data`, so it treated the stream as its state machine and crashed fprintd on the first MKBP event (`FP_IS_DEVICE` and `G_IS_POLLABLE_INPUT_STREAM` assertions). The replay tests never deliver an MKBP event, so they could not catch it.
- `0006`: suspend. The MR's suspend handler resets the sensor (`FP_MODE` 0) but completed without an error, which tells libfprint that the running action continues after resume; there is no resume handler, so a verify left running when the lid closed never matched, and the lock screen's retry after resume got `AlreadyInUse` until a password was typed. It now returns `FP_DEVICE_ERROR_NOT_SUPPORTED`, so libfprint cancels the action and the lock screen starts a new verify after resume. Verified 16 October 2026 with `1.94.100-4`: locked, suspended without touching the sensor, and unlocked by fingerprint after resume (fprintd logs `Cannot run while suspended` for the cancelled verify).

For sudo, login and the lock screen: `sudo authselect enable-feature with-fingerprint`.

**Security trade-off.** ChromeOS derives the seed from the TPM. Here it is a plaintext root-only file. Templates are still encrypted with a key that never leaves the FPMCU, so they are useless on other hardware. Anyone who can read both the seed and `/var/lib/fprint` (root, or offline access to an unencrypted disk) can load them back into this FPMCU. Root can already fake a match on this reader, because there is no authenticated session (see the research notes). Sealing the seed with `systemd-creds --with-key=tpm2` would only add protection against offline disk access. Deleting the seed file invalidates every enrolled print, so re-enroll afterwards. If another OS set a different seed before a warm reboot, verify fails until the FPMCU is reset (`ectool --name=cros_fp reboot_ec`) or the machine is powered off.

### Debugging

The Googlebook OS `ectool` is an Android binary and won't run here. EC `main`'s `ectool` no longer builds outside ChromiumOS: at `fc818f5c` it needs `libchrome` and `libec`. The R107 branch builds with only libusb:

```sh
sudo dnf install -y gcc make libusb1-devel
mkdir -p ~/src/ec-r107 && cd ~/src/ec-r107
curl -L https://chromium.googlesource.com/chromiumos/platform/ec/+archive/24a1cee59942b595f459d69c2aa2f97d37b268df.tar.gz | bsdtar -xf -
make BOARD=host LIBFTDIUSB_CFLAGS=-I/usr/include/libusb-1.0 LIBFTDIUSB_LDLIBS=-lusb-1.0 build/host/util/ectool
sudo ./build/host/util/ectool --name=cros_fp version
sudo ./build/host/util/ectool --name=cros_fp fpinfo
sudo ./build/host/util/ectool --name=cros_fp fpencstatus
```

`version` should print the RO and RW firmware versions, which should be `srebrna` builds. `fpinfo` should report the Egis sensor. `fpencstatus` shows whether a seed is already set. If Googlebook OS ran before a warm reboot, reset the MCU with `ectool --name=cros_fp reboot_ec`.

For driver debug output: `sudo systemctl stop fprintd`, then `sudo env G_MESSAGES_DEBUG=all /usr/libexec/fprintd --no-timeout` in one terminal and `fprintd-enroll`/`fprintd-verify` in another. fprintd finds `/dev/cros_fp` only if it exists when fprintd starts.

Unload with `sudo modprobe -r cros_ec_usb`. First close everything that holds `/dev/cros_fp` open, such as fprintd or ectool. Unloading while it is open is a use-after-free in `cros_ec_chardev`, and the same applies to every cros_ec transport.

