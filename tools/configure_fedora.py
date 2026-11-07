#!/usr/bin/env python3
"""Install Fedora and configure the mounted encrypted root of a Ruby Googlebook.

Runs as root from the console-only live USB after `native.py format --apply`.

  packages   verify and unpack Fedora's signed container image into /mnt, then
             let the target's own dnf5 install the system; create the user
  configure  fstab, locale, Ruby hardware settings, speaker calibration capture,
             the small encrypted-root initramfs, and an SELinux relabel

Next: native.py build / validate / commit, exactly as for CachyOS.
"""
import argparse
import getpass
import hashlib
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
                          FEDORA_KEY, FEDORA_KERNEL, FEDORA_INITRAMFS, board, output, read_json, require, run,
                          save_json, sha256)
from tools.native import STATE, TARGET, current, mounted, checked_backup
from tools.configure_target import put, mask, chroot

PACKAGES = [
    # Kernel, firmware, boot
    'kernel', 'kernel-modules-extra', 'kernel-devel', 'linux-firmware', 'intel-gpu-firmware',
    'iwlwifi-mld-firmware', 'iwlwifi-mvm-firmware', 'alsa-sof-firmware', 'intel-audio-firmware',
    'intel-vsc-firmware', 'microcode_ctl', 'dracut', 'cryptsetup', 'btrfs-progs',
    # Base system
    'systemd', 'systemd-resolved', 'passwd', 'sudo', 'kbd', 'glibc-langpack-en', 'policycoreutils',
    'selinux-policy-targeted', 'NetworkManager', 'NetworkManager-wifi', 'NetworkManager-tui', 'iwd',
    'iputils', 'python3', 'git', 'vim-enhanced', 'man-db', 'zram-generator-defaults', 'snapper',
    # Loader harness build (native.py validate) and later DKMS (fingerprint)
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


def fetch(url, dest):
    run(['curl', '--fail', '--location', '--proto', '=https', '--tlsv1.2', '--retry', '3', '-o', dest, url])


def verified_image(work):
    """Download the container image; check its pinned hash and the signed CHECKSUM file."""
    image, checksum = work / 'fedora.oci.tar.xz', work / 'CHECKSUM'
    fetch(FEDORA_CHECKSUM_URL, checksum)
    gnupg = work / 'gnupg'
    gnupg.mkdir(mode=0o700)
    gpg = ['gpg', '--homedir', gnupg, '--batch', '--no-autostart']
    run([*gpg, '--import', ROOT / 'assets/fedora/RPM-GPG-KEY-fedora-45-primary'])
    shown = output([*gpg, '--with-colons', '--fingerprint', FEDORA_KEY])
    require(f'fpr:::::::::{FEDORA_KEY}:' in shown, 'Bundled Fedora key fingerprint mismatch')
    status = subprocess.run([*gpg, '--status-fd', '1', '--verify', checksum], capture_output=True, text=True)
    require(status.returncode == 0 and f'VALIDSIG {FEDORA_KEY}' in status.stdout, 'CHECKSUM signature is not Fedora 45\'s')
    name = FEDORA_IMAGE_URL.rsplit('/', 1)[1]
    require(f'SHA256 ({name}) = {FEDORA_IMAGE_SHA256}' in checksum.read_text(), 'Signed CHECKSUM disagrees with pinned hash')
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


def packages(args):
    current(); mounted()
    require(board()[0] == 'Ruby', 'The Fedora target has only been prepared for Ruby')
    require(sys.stdin.isatty(), 'Package setup needs a local terminal for the private account-password prompt')
    require(not (STATE / 'packages-started').exists(), 'Packages already attempted; inspect failure before manual resumption')
    require(re.fullmatch('[a-z][a-z0-9_-]{0,30}', args.user) and args.user not in ('root', 'asuslive'), 'Invalid username')
    require('\n' not in args.name and '\r' not in args.name and ':' not in args.name, 'Invalid full name')
    require((Path('/usr/share/zoneinfo') / args.timezone).is_file() and '..' not in args.timezone.split('/'), 'Invalid timezone')
    require(re.fullmatch('[a-zA-Z0-9_-]+', args.keymap), 'Invalid console keymap')
    require(re.fullmatch('[a-z0-9][a-z0-9-]{0,62}', args.hostname), 'Invalid hostname')
    require(subprocess.run(['curl', '-sfI', '--max-time', '15', FEDORA_CHECKSUM_URL], capture_output=True).returncode == 0,
            'No network: connect Wi-Fi with iwctl first')
    save_json(STATE / 'account.json', dict(user=args.user, name=args.name, timezone=args.timezone, keymap=args.keymap,
                                           hostname=args.hostname, desktop=args.desktop))
    (STATE / 'packages-started').touch(mode=0o600)
    work = STATE / 'fedora-bootstrap'
    work.mkdir(mode=0o700)
    unpack_rootfs(verified_image(work), work)
    shutil.rmtree(work)
    # The image's own repo config and keys (fedora-repos) now drive every download, with GPG checks on.
    dnf('upgrade', '--refresh')
    # Reinstall what the container shipped without docs/locales, then the system itself.
    dnf('reinstall', '--skip-unavailable', '*')
    dnf('install', *PACKAGES, *DESKTOPS[args.desktop])
    modules = kernel_release()
    chroot('useradd', '-m', '-G', 'wheel', '-c', args.name, args.user)
    password = getpass.getpass('New login/sudo password (may differ from disk password): ')
    require(len(password) >= 12 and '\n' not in password and '\0' not in password, 'Use at least 12 characters')
    require(password == getpass.getpass('Repeat login password: '), 'Passwords differ')
    chroot('chpasswd', input=(args.user + ':' + password + '\n').encode())
    del password
    chroot('passwd', '-l', 'root')
    save_json(STATE / 'packages.json', dict(status='Fedora packages installed', kernel_release=modules.name,
                                            kernel_sha256=sha256(modules / 'vmlinuz')))
    print('Packages installed for kernel', modules.name, '- next: configure')


def capture_calibration(backup):
    """Fedora's kernel has no coreboot VPD driver; save the factory values while the live kernel can read them."""
    subprocess.run(['modprobe', '-a', 'coreboot_table', 'vpd_sysfs'], capture_output=True)
    script = ROOT / 'assets/installed/ruby-speaker-calibration.py'
    try:
        run([sys.executable, '-I', script, '--save', TARGET / CALIBRATION])
        run([sys.executable, '-I', script, '--save', backup / 'speaker-calibration'])
        return True
    except subprocess.CalledProcessError:
        print('WARNING: factory speaker calibration not captured. Speakers will use uncalibrated defaults until you\n'
              f'run: {script} --save /mnt/{CALIBRATION}  (from this live USB, with the root mounted)')
        return False


def configure(args):
    p, device, _ = current(); mounted(); backup = checked_backup(device)
    require(board()[0] == 'Ruby', 'The Fedora target has only been prepared for Ruby')
    installed = read_json(STATE / 'packages.json')
    require(not (STATE / 'configure-started').exists(), 'Configuration already attempted; inspect before resuming')
    account = read_json(STATE / 'account.json')
    user, release = account['user'], installed['kernel_release']
    modules = TARGET / 'usr/lib/modules' / release
    require(sha256(modules / 'vmlinuz') == installed['kernel_sha256'], 'Kernel changed since package stage')
    (STATE / 'configure-started').touch(mode=0o600)
    fs = read_json(STATE / 'format.json')['btrfs_uuid']
    put('/etc/fstab', ''.join(f'UUID={fs} {mount} btrfs noatime,compress=zstd:3,subvol={sub} 0 0\n' for mount, sub in
                              [('/', '@'), ('/home', '@home'), ('/var/log', '@log'), ('/var/cache/libdnf5', '@pkg')]))
    host = account['hostname']
    put('/etc/hostname', host + '\n')
    put('/etc/locale.conf', 'LANG=en_US.UTF-8\n')
    put('/etc/vconsole.conf', 'KEYMAP=' + account['keymap'] + '\n')
    localtime = TARGET / 'etc/localtime'
    localtime.unlink(missing_ok=True)
    localtime.symlink_to('../usr/share/zoneinfo/' + account['timezone'])
    chroot('systemd-machine-id-setup')
    # Graphics: firmware framebuffer (if any) through LUKS unlock, then one explicit Xe load.
    put('/etc/modprobe.d/ruby-xe.conf', 'blacklist xe\noptions xe ' + XE_OPTIONS + '\n')
    put('/etc/systemd/system/ruby-gpu.service', (ROOT / 'assets/installed/ruby-gpu.service').read_text())
    put('/etc/modprobe.d/ruby-audio.conf', (ROOT / 'assets/installed/ruby-audio.conf').read_text())
    put('/etc/systemd/logind.conf.d/ruby-power-key.conf', (ROOT / 'assets/installed/logind/ruby-power-key.conf').read_text())
    # The factory ESP and Android partitions must not be auto-mounted.
    mask('/etc/systemd/system-generators/systemd-gpt-auto-generator')
    chroot('systemctl', 'enable', 'ruby-gpu.service', 'NetworkManager.service', 'systemd-resolved.service')
    chroot('systemctl', 'mask', 'sshd.service', 'efi.mount', 'efi.automount')
    chroot('systemctl', 'set-default', 'graphical.target' if account['desktop'] != 'none' else 'multi-user.target')
    calibrated = capture_calibration(backup)
    # Record of the installation for kernel updates; the LUKS header backup stays root-only.
    save_json(TARGET / 'etc/asus-boot/install.json', p)
    (TARGET / 'etc/asus-boot/luks-header.bin').write_bytes((backup / 'luks-header.bin').read_bytes())
    (TARGET / 'etc/asus-boot/luks-header.bin').chmod(0o600)
    # The small encrypted-root initramfs for vendor_boot_a (29 MiB budget), with its own isolated dracut config.
    put('/etc/ruby-boot/dracut.conf', (ROOT / 'assets/fedora/dracut.conf').read_text())
    (TARGET / 'etc/ruby-boot/dracut.conf.d').mkdir(exist_ok=True)
    kernel = TARGET / FEDORA_KERNEL.lstrip('/')
    kernel.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(modules / 'vmlinuz', kernel)
    chroot('dracut', '--force', '--conf', '/etc/ruby-boot/dracut.conf', '--confdir', '/etc/ruby-boot/dracut.conf.d',
           '--kver', release, FEDORA_INITRAMFS)
    check_initramfs(TARGET / FEDORA_INITRAMFS.lstrip('/'))
    # SELinux: label everything now (the live kernel has no SELinux, so nothing was labelled on write).
    # First boot runs permissive; switch to enforcing once `ausearch -m avc -ts boot` is quiet.
    selinux = TARGET / 'etc/selinux/config'
    selinux.write_text(re.sub(r'(?m)^SELINUX=.*$', 'SELINUX=permissive', selinux.read_text()))
    relabel = subprocess.run(['arch-chroot', TARGET, 'setfiles', '-F', '-e', '/proc', '-e', '/sys', '-e', '/dev',
                              '-e', '/run', '/etc/selinux/targeted/contexts/files/file_contexts', '/'])
    if relabel.returncode != 0:
        (TARGET / '.autorelabel').touch()
        print('setfiles failed; the first boot will relabel the filesystem and reboot once.')
    chroot('chown', '-R', user + ':' + user, '/home/' + user)
    save_json(STATE / 'configured.json', dict(status='Configured; boot partitions not yet committed', distro='fedora',
                                              kernel=FEDORA_KERNEL, initramfs=FEDORA_INITRAMFS, kernel_release=release,
                                              kernel_sha256=installed['kernel_sha256'], speaker_calibration=calibrated,
                                              selinux_relabelled=relabel.returncode == 0))
    print('Configuration complete. Next: native.py build, validate, commit.')


def check_initramfs(path):
    listing = output(['arch-chroot', TARGET, 'lsinitrd', '/' + str(path.relative_to(TARGET))])
    for private in ('avb-private', 'luks-header', '.nmconnection', 'authorized_keys', 'speaker-calibration'):
        require(private not in listing, 'Private file in initramfs: ' + private)
    for needed in ('systemd-cryptsetup', 'nvme', 'dm-crypt', 'btrfs'):
        require(needed in listing, 'Initramfs lacks ' + needed)
    require('/xe.ko' not in listing and '/i915.ko' not in listing, 'Initramfs must not carry the GPU driver')
    size = path.stat().st_size
    require(size < 29 * 1024**2, f'Initramfs is {size / 2**20:.1f} MiB; the vendor_boot budget is 29 MiB')
    print(f'Initramfs OK: {size / 2**20:.1f} MiB')


def main():
    os.umask(0o022)
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    subs = p.add_subparsers(required=True)
    q = subs.add_parser('packages'); q.add_argument('--user', required=True); q.add_argument('--name', required=True)
    q.add_argument('--timezone', required=True); q.add_argument('--keymap', default='us')
    q.add_argument('--hostname', default='googlebook')
    q.add_argument('--desktop', choices=sorted(DESKTOPS), default='none',
                   help='none (text first boot, recommended), gnome or kde')
    q.set_defaults(fn=packages)
    q = subs.add_parser('configure'); q.set_defaults(fn=configure)
    a = p.parse_args(); a.fn(a)


if __name__ == '__main__':
    main()
