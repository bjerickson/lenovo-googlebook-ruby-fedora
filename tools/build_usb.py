#!/usr/bin/env python3
"""Download everything and build the Fedora installer USB image, in one command.

Works on Linux, macOS and Windows (WSL 2). Steps:
  1. download the pinned Omarchy 4.0.4 ISO (the live environment) and check its hash
  2. download Fedora 45's container image and signed CHECKSUM, check the pinned hash
     and, when gpg is installed, the Fedora 45 signature
  3. fetch the pinned mkbootimg/avb/vboot sources and build the loader check
  4. build the image with the Fedora image inside, and check it with the Android loader

Downloads are kept in downloads/ and reused (interrupted downloads resume).

    python3 tools/build_usb.py
    python3 tools/build_usb.py --force          # rebuild an existing image
    python3 tools/build_usb.py --no-fedora-image   # smaller USB; the laptop downloads it instead
"""
import argparse
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tempfile
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lapis.common import (ROOT, ISO_SHA256, FEDORA_IMAGE_URL, FEDORA_CHECKSUM_URL, FEDORA_IMAGE_SHA256, FEDORA_KEY,
                          require, run, sha256)

ISO_URL = 'https://iso.omarchy.org/omarchy-4.0.4.iso'
TOOLS = ('git', 'curl', 'openssl', 'zstd', 'bsdtar', 'make', 'cc')
HINTS = {
    'fedora': 'sudo dnf install python3 git curl openssl zstd bsdtar make gcc',
    'debian': 'sudo apt install python3 git curl openssl zstd libarchive-tools build-essential',
    'arch': 'sudo pacman -S --needed python git curl openssl zstd libarchive base-devel',
    'macos': 'xcode-select --install; brew install python zstd',
}


def platform_hint():
    if platform.system() == 'Darwin':
        return HINTS['macos']
    try:
        ids = Path('/etc/os-release').read_text()
    except OSError:
        ids = ''
    for key in ('fedora', 'arch'):
        if f'ID={key}' in ids or f'ID_LIKE={key}' in ids or f'ID_LIKE="{key}' in ids:
            return HINTS[key]
    return HINTS['debian']


def check_tools():
    missing = [t for t in TOOLS if shutil.which(t) is None]
    require(not missing, f"Missing {', '.join(missing)}. Install with:\n  {platform_hint()}")


def download(url, dest):
    """Resumable download into dest (partial file kept as dest.part)."""
    if dest.exists():
        return
    part = dest.with_name(dest.name + '.part')
    dest.parent.mkdir(parents=True, exist_ok=True)
    run(['curl', '--fail', '--location', '--proto', '=https', '--retry', '5', '--continue-at', '-',
         '--output', part, url])
    part.rename(dest)


def verified(path, expected, what):
    got = sha256(path)
    if got != expected:
        path.rename(path.with_name(path.name + '.bad'))
        raise RuntimeError(f'{what} hash mismatch (got {got}); moved aside as {path.name}.bad, rerun to download again')


def fedora_signature(checksum):
    """Optional on the build machine; the installer always checks it on the laptop."""
    if shutil.which('gpg') is None:
        print('gpg not installed: Fedora CHECKSUM signature not checked here (the pinned image hash still is, '
              'and the installer checks the signature on the laptop)')
        return
    with tempfile.TemporaryDirectory() as home:
        gpg = ['gpg', '--homedir', home, '--batch', '--no-autostart']
        run([*gpg, '--import', ROOT / 'assets/fedora/RPM-GPG-KEY-fedora-45-primary'])
        status = subprocess.run([*gpg, '--status-fd', '1', '--verify', str(checksum)], capture_output=True, text=True)
        require(status.returncode == 0 and f'VALIDSIG {FEDORA_KEY}' in status.stdout,
                'Fedora CHECKSUM signature does not verify with the Fedora 45 key')
    print('Fedora CHECKSUM signature verified')


def write_instructions(image):
    rel = os.path.relpath(image, Path.cwd())
    print(f'''
Image ready: {rel}

Write it to a USB stick of 16 GB or more (everything on the stick is erased):
  Linux:  lsblk -d -o PATH,SIZE,MODEL,TRAN          # find the stick, e.g. /dev/sdb
          sudo python3 tools/write_usb.py --image {rel} --device /dev/sdX --apply
  macOS:  diskutil list external physical           # e.g. /dev/disk4
          sudo python3 tools/write_usb.py --image {rel} --device /dev/diskN --apply
  WSL:    attach the stick first (PowerShell as admin: usbipd attach --wsl --busid <id>),
          then use the Linux commands.
Then follow docs/install.md from step 2.''')


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--output', type=Path, default=ROOT / 'build/ruby-fedora-live.img')
    p.add_argument('--downloads', type=Path, default=ROOT / 'downloads')
    p.add_argument('--no-fedora-image', action='store_true', help='do not carry the Fedora image on the USB')
    p.add_argument('--force', action='store_true', help='replace an existing output image')
    args = p.parse_args()
    check_tools()
    output = args.output.resolve()
    products = [output, output.with_suffix('.build'), output.with_suffix('.manifest.json'), output.with_suffix('.sha256')]
    if any(x.exists() for x in products):
        require(args.force, f'{output.name} already exists; use --force to rebuild it')
        for x in products:
            shutil.rmtree(x) if x.is_dir() else x.unlink(missing_ok=True)

    print('==> Live environment (Omarchy 4.0.4 ISO, about 6 GB)')
    iso = args.downloads / 'omarchy-4.0.4.iso'
    download(ISO_URL, iso)
    verified(iso, ISO_SHA256, 'ISO')

    cache = None
    if not args.no_fedora_image:
        print('==> Fedora 45 container image')
        cache = args.downloads / 'fedora'
        checksum = cache / FEDORA_CHECKSUM_URL.rsplit('/', 1)[1]
        image = cache / FEDORA_IMAGE_URL.rsplit('/', 1)[1]
        download(FEDORA_CHECKSUM_URL, checksum)
        fedora_signature(checksum)
        require(f'= {FEDORA_IMAGE_SHA256}' in checksum.read_text(), 'Fedora CHECKSUM does not list the pinned image')
        download(FEDORA_IMAGE_URL, image)
        verified(image, FEDORA_IMAGE_SHA256, 'Fedora image')

    print('==> Build tools (pinned sources)')
    run([sys.executable, ROOT / 'tools/fetch_sources.py'])
    run([sys.executable, ROOT / 'tools/build_loader.py'])

    print('==> Installer image')
    cmd = [sys.executable, ROOT / 'tools/build_live.py', '--iso', iso, '--output', output]
    if cache:
        cmd += ['--fedora-cache', cache]
    run(cmd)
    check = subprocess.run([str(ROOT / 'build/load_android_test'), '-b', '1', str(output)], cwd=output.parent,
                           capture_output=True, text=True)
    (output.parent / 'loaded-ramdisk.img').unlink(missing_ok=True)
    require(check.returncode == 0 and 'vb2api_load_kernel() returned 0' in check.stdout,
            'The Android loader rejected the image')
    print('Android loader check passed (packaging only, not a boot test)')
    write_instructions(output)


if __name__ == '__main__':
    try:
        main()
    except RuntimeError as e:
        sys.exit(f'Error: {e}')
