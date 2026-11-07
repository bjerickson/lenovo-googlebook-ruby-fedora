# Fingerprint reader on Ruby (Google FPMCU over USB) — research

> Research log from the upstream CachyOS port (October 2026), kept for its sources and security analysis. The Fedora setup is in [hardware notes](../hardware.md#fingerprint).

Research date: 10 October 2026. Read-only; nothing was installed or loaded on the system.
Target: Lenovo Googlebook 15 "Ruby" (Fatcat family), CachyOS `linux-cachyos 7.2.9-2`.
Sensor: USB `18d1:5402` "Google FPMCU", bcdDevice 0404, interface ff/5a/00.

Legend: **[V]** verified from a primary source (code, binary, official repo, mailing list) ·
**[I]** inferred or not yet tested on hardware.

## Verdict

**This looks feasible, but nobody has tested it on this laptop yet.** I'd put it at 1–3 days of work.
The two main pieces already exist. Each needs a little adaptation:

1. **Kernel transport.** `cros_ec_usb.c` is GPL and Google posted it to LKML (v6, Sept 2025). It isn't in mainline as of v7.3-rc6. The v6 file builds out of tree against our 7.2.9 headers once you add a small (~20-line) fix for the new cros_ec core API. I test-built it in scratch and it compiled cleanly. Without that fix it would oops on 7.2. Once the module binds, mainline `cros_ec_dev` + `cros_ec_chardev` should create `/dev/cros_fp`, because the FPMCU reports `EC_FEATURE_FINGERPRINT`. **[V code / I runtime]**
2. **Userspace.** libfprint MR !512, the `crfpmoc` driver (open, still being updated in Sept 2026), talks to `/dev/cros_fp` using the classic "match-on-MCU" flow. Chromebook-on-Linux users report it working with fprintd. ChocolateLoverRaj's `rust-fp` is an alternative PAM/D-Bus route. **[V exists / I works on Ruby]**
3. **Firmware.** The factory firmware (board `srebrna`, Egis ET171 + EGIS660, Zephyr EC) still contains the upstream EC code for the **classic, unauthenticated flow**. The newer FingerGuard/ASCP authentication only applies once a host sets up a session in that FPMCU boot. That means Linux can use `FP_SEED` → `FP_CONTEXT` → `FP_MODE` without Google's trusted application. You can't flash custom FPMCU firmware (RO/RW signed, hardware write-protect), and you don't need to. **[V upstream source + firmware strings / I exact srebrna behaviour]**

**Recommended path:**
- DKMS-package the ported `cros_ec_usb` and confirm `/dev/cros_fp` with upstream `ectool --name=cros_fp version/fpinfo/fpencstatus`.
- Build libfprint with MR !512.
- Replace crfpmoc's random per-open seed with a stable seed sealed to the TPM, so stored templates survive reboots.

## Q1 — Where is the GPL source of `cros_ec_usb.c`?

- **LKML (primary).** "[PATCH] platform/chrome: Add ChromeOS EC USB driver", Dawid Niedzwiecki (Google), 24 Jun 2025: https://lkml.rescloud.iu.edu/2506.3/00557.html. Tzung-Bi Shih reviewed it: https://lkml.rescloud.iu.edu/2506.3/06528.html. v2 review: https://lkml.rescloud.iu.edu/2507.0/02805.html. v3, 4 Aug 2025: https://lkml.org/lkml/2025/8/4/1012. **[V]**
- **Latest posting: v6, 12 Sep 2025.** patchwork https://patchwork.kernel.org/patch/14228232/ (state "new"), lore `20250912065104.260344-1-dawidn@google.com`. **[V]**
- **ChromiumOS Gerrit (easiest place to download the file):**
  - CL 6939126, `chromeos-6.12`, "FROMLIST: platform/chrome: Add ChromeOS EC USB driver", patchset 3, revision `b1b109a0db328a1bccbe426f9a32c783528bec43`. Status NEW, not merged. BUG=b:392914842.
  - Raw file: `https://chromium-review.googlesource.com/changes/6939126/revisions/3/files/drivers%2Fplatform%2Fchrome%2Fcros_ec_usb.c/content` (base64). Size 586 lines, sha256 `c656d58f…80f8ed`.
  - Older CLs: 6606826 (6.12), 6495204 (6.6), and 3360094 "First draft" (5.15, 2022). **[V]**
- **Not present** in: Android common `android17-6.18` / `android16-6.12` / `android-mainline`, ChromiumOS `chromeos-6.6` / `chromeos-6.12` branch heads, or torvalds `master` (v7.3-rc6). I checked directory listings. **[V]** Google ships its DDK build in the Android `vendor_dlkm`. I found no public repo for that exact build (scmversion `ga70996de74a5`).
- **The factory module is a newer revision than v6.** It has a local helper `cros_ec_device_alloc_usb` (seen in `nm`), which matches the 6.18 core API change below. Its import list contains only standard mainline exports (`cros_ec_register/unregister/irq_thread/prepare_tx`, usb_*). **[V]**

**Dependencies:**
- **Exports:** no non-mainline exports.
- **Private header.** It includes the private header `drivers/platform/chrome/cros_ec.h`, which isn't in the installed `build/` tree. Copy it from v7.2 (30 lines): https://github.com/torvalds/linux/blob/v7.2/drivers/platform/chrome/cros_ec.h.
- **Core API change (breaking).** Mainline commits `918856986014` "Centralize cros_ec_device allocation", `e19ceeb1c0f6`, `7a79b0bfd8b3` "Separate initialization from cros_ec_register()" and `56cb557279d7` (all 28 Aug 2025) moved several things out of `cros_ec_register()` into `cros_ec_device_alloc()`: `din`/`dout` allocation, `mutex_init(&lock)`, notifier heads, `max_request`/`max_response`. v6 still `kzalloc`s `ec_dev` and relies on the old behaviour, so **on 7.2 it would dereference NULL `dout` in the first transfer (`cros_ec_rwsig_continue`)**. **[V from source]**

## Q2 — Building it out-of-tree (DKMS) on 7.2

- **Test build.** I test-built it in scratch with `make -C /usr/lib/modules/7.2.9-2-cachyos/build M=… LLVM=1`. It succeeded, giving vermagic `7.2.9-2-cachyos`, alias `usb:v18D1p*…icFFisc5Aip00in*`, depends `cros_ec,cros-ec-proto`. **[V]**
- **The port (29-line diff).** For first-time registration, do the following inside the existing `!is_registered` branch:
  - call `mutex_init(&ec_dev->lock)`;
  - call `BLOCKING_INIT_NOTIFIER_HEAD` on `event_notifier` and `panic_notifier`;
  - set `max_request`, `max_response` and `suspend_timeout_ms`;
  - add `EC_MAX_*_OVERHEAD` to `din_size` and `dout_size`.

  Then make the existing `devm_kzalloc(if_dev, din/dout)` block run on every probe. Don't use `cros_ec_device_alloc()` directly: it's `devm` on the USB interface, and that conflicts with the driver's design of keeping `ec_dev` across FPMCU re-enumeration. **[V compile / I runtime]**
- **Module loading.** CachyOS config has `MODULE_SIG_FORCE` unset and lockdown `none`. An unsigned DKMS module will load (with a taint). **[V]**
- **Known driver caveat.**
  - The driver has no cleanup for `registered_list`.
  - It never calls `cros_ec_unregister()`, because it deliberately keeps `/dev/cros_fp` alive across FPMCU reboots.
  - **Don't `rmmod` it.** If the module is unloaded, the `cros-ec-dev` platform devices are left holding a stale `pkt_xfer` pointer. Add a `module_exit` that unregisters, or blacklist unloading. **[I from code reading]**
- **`/dev/cros_fp` path:**
  1. `cros_ec_register()` registers a `cros-ec-dev` platform device.
  2. Mainline `drivers/mfd/cros_ec_dev.c` maps `EC_FEATURE_FINGERPRINT` → name `CROS_EC_DEV_FP_NAME` = `"cros_fp"` (the `cros_mcu_devices[]` table): https://github.com/torvalds/linux/blob/v7.2/drivers/mfd/cros_ec_dev.c.
  3. `cros_ec_chardev` (enabled, `=m`) then exposes `/dev/cros_fp` with `CROS_EC_DEV_IOCXCMD(_V2)` and the MKBP event read interface.

  Events: the FPMCU signals over the USB interrupt endpoint, and the driver calls `cros_ec_irq_thread()` from a workqueue, so MKBP fingerprint events reach the chardev. **[V code / I runtime]**
- **Firmware side of the transport.** The Zephyr EC `ec_host_cmd_usb` USB host-command backend is in `srebrna` (strings), and upstream at https://chromium.googlesource.com/chromiumos/platform/ec/+/HEAD/zephyr/subsys/usbd_service/. The FPMCU program is `zephyr/program/fpmcu/et171`. **[V]**

## Q3 — Userspace

- **libfprint**
  - **MR !493** "Add Chromium OS EC fingerprint Match-On-Chip driver (crfpmoc)" by fandango96, opened Jun 2024, closed Dec 2024 in favour of !512: https://gitlab.freedesktop.org/libfprint/libfprint/-/merge_requests/493 **[V]**
  - **MR !512** (same title), by Xelef2000, **open**, last updated 7 Sep 2026, head `56442591a5c302a906289f30988fb50fc3d82ed6`: https://gitlab.freedesktop.org/libfprint/libfprint/-/merge_requests/512. **[V]**
    - Uses udev misc device `cros_fp` and `CROS_EC_DEV_IOCXCMD_V2`.
    - Commands: `FP_INFO/MODE/STATS/ENC_STATUS/SEED/CONTEXT/FRAME/TEMPLATE`.
    - Stores the encrypted template blob as the fprintd print data and re-uploads it.
  - **Caveat [V code]:** `crfpmoc_init_keys()` generates a **random seed and user context on every open**. FP_SEED is write-once per FPMCU boot, so templates enrolled in one FPMCU boot shouldn't decrypt after a full power cycle. **[I — test]** For a laptop you reboot, plan to patch it to use a stable, TPM-sealed seed and user ID.
    - Update (10 Oct 2026, hardware): the context is random per open too, so prints would not even survive an fprintd restart. srebrna answers `FP_INFO` only in v3; MR !512 asks for v1 and gets `INVALID_VERSION`. Both are patched in `assets/packages/libfprint-crfpmoc` (seed: root-only file, not TPM-sealed yet). See the Fingerprint section of `docs/cachyos-ruby.md`. **[V code and fpinfo on hardware / I fprintd-restart effect]**
  - Issue #568 (HP x360 14c Chromebook fingerprint) is a user report only.
- **Community projects**
  - chrultrabook forum thread, Apr 2024–Sep 2026, covers ectool usage, `fpseed`, Fedora/NixOS/KDE successes and SELinux issues: https://forum.chrultrabook.com/t/in-search-of-contributors-to-a-linux-chromebook-fingerprint-pam-module/1819
  - Rust: https://github.com/ChocolateLoverRaj/rust-fp (PAM + D-Bus + CLI) and https://github.com/ChocolateLoverRaj/crosec-rs (Rust ectool)
  - Archived: https://github.com/chrultrabook/libfprint-cros
  - Xelef2000 fork: https://github.com/Xelef2000/libfprint
  - Those projects all use SPI-attached FPMCUs (bloonchipper etc.), which already have `/dev/cros_fp` via mainline `cros_ec_spi`. **Nobody has reported a USB FPMCU (Googlebook) yet.** **[V from thread / I nothing else exists]**
- **biod / protocol.** biod README: https://chromium.googlesource.com/chromiumos/platform2/+/HEAD/biod/README.md. Full command set in EC `include/ec_commands.h` (EC main `fc818f5ce0e4ce277017ff7a43a1351c448b36d0`). **[V]**
  - `EC_CMD_FP_MODE 0x402` with mode bits `FP_MODE_{DEEPSLEEP,FINGER_DOWN,FINGER_UP,CAPTURE,ENROLL_SESSION,ENROLL_IMAGE,MATCH,RESET_SENSOR,SENSOR_MAINTENANCE,ENCRYPT_TEMPLATE,DECRYPT_TEMPLATE,MATCH_NO_TEMPLATE_UPDATE}`.
  - `FP_INFO 0x403`, `FP_FRAME 0x404` (template download, `FP_FRAME_INDEX_TEMPLATE`), `FP_TEMPLATE 0x405` (upload, `FP_TEMPLATE_COMMIT`), `FP_CONTEXT 0x406` (user ID), `FP_STATS 0x407`, `FP_SEED 0x408`, `FP_ENC_STATUS 0x409`, `FP_READ_MATCH_SECRET 0x40A`.
  - FP-auth commands: `0x410–0x418` (pairing key keygen/wrap/load, `GENERATE_NONCE`, `ESTABLISH_SESSION` carrying an encrypted TPM seed, challenge, confirm template, sign match, unlock dev options).
  - ASCP commands: `0x420–0x421` (`FP_ASCP_CLAIM`/`ESTABLISH`).
  - Results arrive as MKBP `EC_MKBP_EVENT_FINGERPRINT` events (enroll %, match result + finger index). Matching runs on the MCU, and the host only stores encrypted blobs.
  - Mainline's `cros_ec_commands.h` only defines up to `0x409`, which is enough for the classic flow.
- **Factory HAL (for reference).** `com.android.hardware.fingerprint.crosfp.apex` → `android.hardware.biometrics.fingerprint-service.crosfp`.
  - Written in Rust (`system/desktop/ec/src/libec`).
  - Opens `/dev/cros_fp`, so it relies on the kernel transport, not libusb.
  - libusb is only used for the Egis/Elan/Focaltech IAP bootloader recovery flasher.
  - Talks to a `FingerGuard` trusted application (`android.desktop.security.finger_guard.IFingerGuard`). It tries ASCP first and falls back to the "Fingerprint Auth protocol".
  - Bundles FPMCU firmware for `srebrna`, `sanok`, `chobienia`, `chojnik`, `buccaneer`, `helipilot` and runs an updater.
  - Ruby's `fingerprint_*.xml` says `board=srebrna`, `STAND_ALONE`, `KEYBOARD_TOP_RIGHT`. **[V from extracted apex]**
  - The vendor `ectool` is an Android binary. On Linux, build upstream `util/ectool` from the EC repo or use crosec-rs. **[I]**
    - Correction (10 Oct 2026, build-tested): EC `main` (`fc818f5c`) `ectool` no longer builds standalone; it needs ChromiumOS `libchrome` and platform2 `libec`. Branch `release-R107-15117.B-main` (`24a1cee5`) builds with only libusb and has `--name=cros_fp`, `fpinfo` and `fpencstatus`. See the Fingerprint section of `docs/cachyos-ruby.md`. **[V]**

## Q4 — Security model

- **Design doc:** https://chromium.googlesource.com/chromiumos/platform/ec/+/HEAD/docs/fingerprint/fingerprint-authentication-design-doc.md **[V]**
- **How templates are protected:**
  - Templates are encrypted with AES-GCM under `HW_Key = HKDF(SBP_Src_Key, TPM_Seed, User_Salt, User_ID)`.
  - `SBP_Src_Key` is an FPMCU-internal secret mixed with rollback-block entropy, and it never leaves the MCU.
  - On ChromeOS, `TPM_Seed = HMAC-SHA256(Cros_Sys_Key, "biod")`, so a TPM clear invalidates every template.
  - The FPMCU keeps no templates across reboots. The host uploads them each boot.
- **Classic flow** (verified in EC `common/fpsensor/fpsensor_state.cc`): `FP_SEED` is accepted **once per FPMCU boot**, and later calls return `ACCESS_DENIED` with "Seed has already been set." The same string is in the srebrna binary.
- **What this means for Linux:**
  1. Linux must supply its own 32-byte seed. Seal it to the TPM, e.g. `systemd-creds encrypt --with-key=tpm2`, and feed it to the driver/daemon. If the seed or user ID changes, every stored template is useless.
  2. If Googlebook OS ran before a warm reboot, the seed or session may still be set. Reboot the FPMCU first (`ectool --name=cros_fp reboot_ec`). It re-enumerates on USB, and the driver keeps `/dev/cros_fp`.
  3. Linux templates and Googlebook OS templates are independent, because the seed differs. Expect to enroll separately.
  4. Without FingerGuard/ASCP, Linux gets **no cryptographic proof** that a match came from the genuine sensor. A root attacker could fake MKBP match events. That's the same trust level as every libfprint match-on-chip driver without SDCP, which is fine for screen unlock and sudo, but not for disk encryption. **[I]**
- **FP-auth / ASCP:**
  - `fingerprint_auth_enabled()` is just `fp_encryption_status & FP_CONTEXT_STATUS_SESSION_ESTABLISHED`.
  - `authenticate_fp_mode()` returns success immediately when it's false ("Allow for classic fingerprint flow").
  - The session only exists once the host runs `FP_GENERATE_NONCE` + `FP_ESTABLISH_SESSION`.
  - Implementing ASCP on Linux would mean emulating FingerGuard. That isn't required, and the model/device keys are signed by Google. **[V upstream; I srebrna build is the same]**

## Q5 — Firmware-level obstacles

- **No custom firmware.**
  - The HAL updater checks `HardwareWriteProtectEnabled`, `IncompatibleRwSignature` ("RW signature … not compatible with the RO public key") and a minimum rollback version.
  - The firmware logs "System is unlocked. Skip MPU configuration", meaning it's locked in production.
  - You can't flash your own FPMCU firmware; you can only run Google-signed RW. Not needed. **[V strings]**
- **RWSIG.** The FPMCU boots RO and jumps to RW after signature verification. Mainline `cros_ec_register()` already sends RWSIG continue (`5ffa0dbfdc9f`, "jump to RW before probing"). **[V]**
- **Firmware updates.** The FPMCU firmware only updates via the Googlebook OS HAL updater. Linux stays on whatever firmware is installed. That's fine, but **don't** port the updater (risk of rollback-block and write-protect changes).
- **Locked system.** Raw image readout (`FP_FRAME` raw index) is denied when locked (`get_frame`: `if (system_is_locked()) return EC_RES_ACCESS_DENIED`). Template download/upload and MCU matching are unaffected. **[V upstream]**
- **Not checked.** Whether the srebrna build disables `FP_SEED` through a Kconfig switch. Upstream has none, and the firmware strings show the classic handler is present. **[I]**

## Step plan

1. **Package the kernel module.** Create `tools/dkms/cros-ec-usb/` (or wherever the repo keeps packages), containing:
   - v6 `cros_ec_usb.c` from Gerrit CL 6939126 PS3;
   - `cros_ec.h` from torvalds v7.2;
   - the 7.2 port diff (appendix);
   - a `module_exit` that unregisters;
   - `dkms.conf`.

   Build against `linux-cachyos-headers`. Pin it like the kernel.
2. **First hardware test (needs sudo, owner's call).** Run `modprobe cros_ec_dev cros_ec_chardev` then `insmod cros_ec_usb.ko`, and watch dmesg for "Chrome EC device registered" and `cros-ec-dev … cros_fp`. Check for `/dev/cros_fp`.
3. **Check the protocol.** Run upstream `ectool --name=cros_fp version`, `fpinfo`, `fpencstatus`.
   - If the seed is already set, run `reboot_ec`.
   - Then `fpseed <32 chars>`, `fpcontext`, `fpmode enroll`, and watch events (crosec-rs `wait-event fingerprint --device fp`).
   - Expect `fpmode` to succeed **without** the auth error. That confirms the classic flow on srebrna.
4. **Install the userspace.** Build libfprint from MR !512 (`feature/crfpmoc` @ `56442591`) plus fprintd. Patch `crfpmoc_init_keys()` to read the seed and user ID from a TPM-sealed credential, and add a udev rule/permissions for `/dev/cros_fp`.
5. **Integrate.** Wire up PAM (sudo, hyprlock/greeter). Test across reboot, suspend/resume (the driver resubmits its interrupt URB on resume) and FPMCU reboot.
6. **Upstream.** Report results on MR !512 and to the cros_ec_usb thread. The USB FPMCU is a new case for both.

**Effort:**
- Steps 1–3: about 1 day.
- Steps 4–5: 1–2 days.

**Main risks:**
- An untested runtime corner of the ported driver (reprobe path).
- An undiscovered srebrna-specific restriction.
- crfpmoc maturity.

## Appendix — 7.2 port diff (applies to v6 from CL 6939126 PS3; compile-tested only)

```diff
--- a/cros_ec_usb.c
+++ b/cros_ec_usb.c
@@ -378,11 +378,23 @@
 		ec_dev->irq = 0;
 		ec_dev->cmd_xfer = NULL;
 		ec_dev->pkt_xfer = do_cros_ec_pkt_xfer_usb;
+		/* Linux >= 6.18: cros_ec_register() no longer initialises these
+		 * (see cros_ec_device_alloc()); do it here without devm so the
+		 * struct survives USB re-enumeration. */
+		mutex_init(&ec_dev->lock);
+		BLOCKING_INIT_NOTIFIER_HEAD(&ec_dev->event_notifier);
+		BLOCKING_INIT_NOTIFIER_HEAD(&ec_dev->panic_notifier);
+		ec_dev->max_response = sizeof(struct ec_response_get_protocol_info);
+		ec_dev->max_request = sizeof(struct ec_params_rwsig_action);
+		ec_dev->suspend_timeout_ms = EC_HOST_SLEEP_TIMEOUT_DEFAULT;
 		ec_dev->din_size = sizeof(struct ec_host_response) +
-				   sizeof(struct ec_response_get_protocol_info);
+				   sizeof(struct ec_response_get_protocol_info) +
+				   EC_MAX_RESPONSE_OVERHEAD;
 		ec_dev->dout_size = sizeof(struct ec_host_request) +
-				    sizeof(struct ec_params_rwsig_action);
-	} else {
+				    sizeof(struct ec_params_rwsig_action) +
+				    EC_MAX_REQUEST_OVERHEAD;
+	}
+	{
 		ec_dev = ec_usb->ec_dev;
 
 		/*
```
