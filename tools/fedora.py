#!/usr/bin/env python3
"""Shared Fedora target helpers for the Ruby installer: bootstrap, dnf, files in /mnt.

Everything here acts on the target root mounted at /mnt (TARGET) from the live USB.
"""
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tarfile
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lapis.common import (ROOT, FEDORA_RELEASE, FEDORA_IMAGE_URL, FEDORA_CHECKSUM_URL, FEDORA_IMAGE_SHA256,
                          FEDORA_KEY, FEDORA_CACHE, output, require, run, sha256)

TARGET = Path('/mnt')

PACKAGES = [
    # Kernel, firmware, boot
    'kernel', 'kernel-modules-extra', 'kernel-devel', 'linux-firmware', 'intel-gpu-firmware',
    'iwlwifi-mld-firmware', 'iwlwifi-mvm-firmware', 'alsa-sof-firmware', 'intel-audio-firmware',
    'intel-vsc-firmware', 'microcode_ctl', 'dracut', 'cryptsetup', 'btrfs-progs',
    # Base system
    'systemd', 'systemd-resolved', 'passwd', 'sudo', 'kbd', 'glibc-langpack-en', 'policycoreutils',
    'selinux-policy-targeted', 'NetworkManager', 'NetworkManager-wifi', 'NetworkManager-tui', 'iwd',
    'iputils', 'python3', 'git', 'vim-enhanced', 'man-db', 'zram-generator-defaults', 'snapper',
    # Loader harness build (boot-set validation) and DKMS (coreboot framebuffer, light sensor, fingerprint)
    'gcc', 'make', 'dkms',
    # Audio, graphics, Ruby helpers
    'pipewire', 'pipewire-pulseaudio', 'pipewire-alsa', 'wireplumber', 'alsa-ucm', 'alsa-utils',
    'mesa-dri-drivers', 'mesa-vulkan-drivers', 'libva-intel-media-driver', 'bolt', 'brightnessctl',
    'android-tools', 'erofs-utils',
]

DESKTOPS = {'none': [], 'gnome': ['@workstation-product-environment'], 'kde': ['@kde-desktop-environment']}

# Container images trim docs and locales for size; a laptop wants both.
CONTAINER_TRIMS = ('etc/rpm/macros.image-language-conf',)

XE_OPTIONS = 'gsc_firmware_path='

CALIBRATION = 'etc/ruby/speaker-calibration'


def put(name, content, mode=0o644):
    path = TARGET / name.lstrip('/')
    path.parent.mkdir(parents=True, exist_ok=True)
    require(not path.is_symlink(), 'Refuse writing through target symlink: ' + name)
    path.write_text(content)
    path.chmod(mode)


def mask(name):
    path = TARGET / name.lstrip('/')
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() or path.is_symlink():
        require(path.is_symlink() and os.readlink(path) == '/dev/null', 'Unexpected file at ' + name)
    else:
        path.symlink_to('/dev/null')


def chroot(*argv, **kw):
    return run(['arch-chroot', TARGET, *argv], **kw)


def fetch(url, dest):
    run(['curl', '--fail', '--location', '--proto', '=https', '--tlsv1.2', '--retry', '3', '-o', dest, url])


def verified_image(work):
    """The container image from the USB (tools/build_usb.py) or the network.

    Either way its hash must match the pinned one and the CHECKSUM file must carry a
    valid Fedora 45 signature.
    """
    image, checksum = work / 'fedora.oci.tar.xz', work / 'CHECKSUM'
    name = FEDORA_IMAGE_URL.rsplit('/', 1)[1]
    cached_image = FEDORA_CACHE / name
    cached_checksum = FEDORA_CACHE / FEDORA_CHECKSUM_URL.rsplit('/', 1)[1]
    if cached_checksum.is_file():
        shutil.copyfile(cached_checksum, checksum)
    else:
        fetch(FEDORA_CHECKSUM_URL, checksum)
    gnupg = work / 'gnupg'
    gnupg.mkdir(mode=0o700)
    gpg = ['gpg', '--homedir', gnupg, '--batch', '--no-autostart']
    run([*gpg, '--import', ROOT / 'assets/fedora/RPM-GPG-KEY-fedora-45-primary'])
    shown = output([*gpg, '--with-colons', '--fingerprint', FEDORA_KEY])
    require(f'fpr:::::::::{FEDORA_KEY}:' in shown, 'Bundled Fedora key fingerprint mismatch')
    status = subprocess.run([*gpg, '--status-fd', '1', '--verify', checksum], capture_output=True, text=True)
    require(status.returncode == 0 and f'VALIDSIG {FEDORA_KEY}' in status.stdout, 'CHECKSUM signature is not Fedora 45\'s')
    require(f'SHA256 ({name}) = {FEDORA_IMAGE_SHA256}' in checksum.read_text(), 'Signed CHECKSUM disagrees with pinned hash')
    if cached_image.is_file() and sha256(cached_image) == FEDORA_IMAGE_SHA256:
        print('Using the Fedora image from the USB (hash and signature verified)')
        return cached_image
    fetch(FEDORA_IMAGE_URL, image)
    require(sha256(image) == FEDORA_IMAGE_SHA256, 'Fedora container image checksum mismatch')
    return image


def unpack_rootfs(image, work):
    """Extract the single OCI layer into /mnt, checking every digest on the way."""
    oci = work / 'oci'
    oci.mkdir()
    run(['tar', '-C', oci, '-xJf', image])

    def blob(digest):
        algo, _, hexd = digest.partition(':')
        require(algo == 'sha256' and re.fullmatch('[0-9a-f]{64}', hexd), 'Unexpected OCI digest')
        path = oci / 'blobs/sha256' / hexd
        require(sha256(path) == hexd, 'OCI blob digest mismatch')
        return path

    index = json.loads((oci / 'index.json').read_text())
    require(len(index['manifests']) == 1, 'Expected one image manifest')
    manifest = json.loads(blob(index['manifests'][0]['digest']).read_text())
    layers = manifest['layers']
    require(len(layers) == 1 and 'tar' in layers[0]['mediaType'], 'Expected a single-layer Fedora image')
    layer = blob(layers[0]['digest'])
    with tarfile.open(layer) as t:  # refuse anything that could escape /mnt
        for m in t.getmembers():
            require(not m.name.startswith('/') and '..' not in Path(m.name).parts, 'Unsafe path in layer: ' + m.name)
            require('.wh.' not in m.name, 'Unexpected OCI whiteout in a base layer')
    require(not any(p for p in TARGET.iterdir() if p.name not in ('home', 'var', 'lost+found')),
            '/mnt has unexpected content; this stage expects the freshly formatted root')
    run(['tar', '-C', TARGET, '--numeric-owner', '--xattrs', "--xattrs-include=*", '-xpf', layer])
    for rel in CONTAINER_TRIMS:
        (TARGET / rel).unlink(missing_ok=True)
    # Undo container-only dnf settings (docs and weak dependencies off).
    conf = TARGET / 'etc/dnf/dnf.conf'
    if conf.exists():
        kept = [l for l in conf.read_text().splitlines()
                if not re.match(r'\s*(tsflags|install_weak_deps)\s*=', l)]
        conf.write_text('\n'.join(kept) + '\n')
    shutil.rmtree(oci)


def dnf(*argv):
    chroot('dnf5', '-y', f'--releasever={FEDORA_RELEASE}', '--setopt=install_weak_deps=True', *argv)


def kernel_release():
    found = []
    for d in (TARGET / 'usr/lib/modules').iterdir():
        if (d / 'vmlinuz').is_file() and subprocess.run(['arch-chroot', TARGET, 'rpm', '-qf', f'/usr/lib/modules/{d.name}/vmlinuz'],
                                                       capture_output=True).returncode == 0:
            found.append(d)
    require(len(found) == 1, f'Expected exactly one Fedora kernel, found {[d.name for d in found]}')
    return found[0]


def check_initramfs(path, framebuffer=False):
    listing = output(['arch-chroot', TARGET, 'lsinitrd', '/' + str(path.relative_to(TARGET))])
    for private in ('avb-private', 'luks-header', '.nmconnection', 'authorized_keys', 'speaker-calibration'):
        require(private not in listing, 'Private file in initramfs: ' + private)
    for needed in ('systemd-cryptsetup', 'nvme', 'dm-crypt', 'btrfs'):
        require(needed in listing, 'Initramfs lacks ' + needed)
    if framebuffer:
        require('framebuffer-coreboot' in listing and 'coreboot_table' in listing, 'Initramfs lacks the coreboot framebuffer')
    require('/xe.ko' not in listing and '/i915.ko' not in listing, 'Initramfs must not carry the GPU driver')
    size = path.stat().st_size
    require(size < 29 * 1024**2, f'Initramfs is {size / 2**20:.1f} MiB; the vendor_boot budget is 29 MiB')
    print(f'Initramfs OK: {size / 2**20:.1f} MiB')

