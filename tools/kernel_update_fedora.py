#!/usr/bin/env python3
"""Put Fedora kernel updates into the Ruby's Android boot partitions (slot A).

The firmware boots the kernel in boot_a/vendor_boot_a, not /boot, so a new
`kernel` package does nothing until its boot set is built, signed and written.

  update [--kver V]  build + sign + loader-check V (default: newest installed),
                     back up slot A, write V, read it back
  rollback           restore the slot-A backup taken before the last update
  status             running kernel, slot-A kernel, newest installed kernel
  install-hook       install the kernel-install plugin so dnf runs `update`

Run as root. Also works from the live USB against a mounted install:
  arch-chroot /mnt python3 /opt/lapis-kit/tools/kernel_update_fedora.py rollback
"""
import argparse
from datetime import datetime
import os
from pathlib import Path
import shutil
import subprocess
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lapis.boot import build_set
from lapis.common import ROOT, FEDORA_KERNEL, FEDORA_INITRAMFS, output, read_json, require, run, save_json, sha256, write_all
from lapis.gpt import read_gpt

SLOT_A = ('boot_a', 'init_boot_a', 'vendor_boot_a', 'vbmeta_a')
STATE = Path('/var/lib/asus-boot/kernel-update')
INSTALL = Path('/etc/asus-boot/install.json')
KEY = Path('/etc/asus-boot/avb-private.pem')
DRACUT_CONF = '/etc/ruby-boot/dracut.conf'
DRACUT_DIR = Path('/etc/ruby-boot/dracut.conf.d')
COREBOOT_CONF = 'coreboot-fb.conf'
HOOK = Path('/etc/kernel/install.d/95-ruby-android.install')
KEEP_BACKUPS = 2
HOOK_TEXT = f"""#!/bin/sh
# Ruby Googlebook: the firmware boots slot A, not /boot. Build, check and write the
# new kernel there. Never fails the package transaction; nothing is written on error.
[ "$1" = add ] || exit 0
newest=$(ls -1v /usr/lib/modules | while read -r k; do [ -f "/usr/lib/modules/$k/vmlinuz" ] && echo "$k"; done | tail -n1)
[ "$2" = "$newest" ] || exit 0
if ! /usr/bin/python3 -I {ROOT}/tools/kernel_update_fedora.py update --kver "$2"; then
    echo "==> Ruby: kernel $2 is installed but NOT in the boot partitions; still booting the previous kernel." >&2
    echo "==> Retry: sudo python3 {ROOT}/tools/kernel_update_fedora.py update --kver $2" >&2
fi
exit 0
"""


def disk_and_gpt():
    plan = read_json(INSTALL)
    disk = plan['device']
    size = os.stat(disk).st_size if Path(disk).is_file() else int(output(['blockdev', '--getsize64', disk]))
    with open(disk, 'rb') as f:
        gpt = read_gpt(f, size)
    require(gpt.guid == plan['disk_guid'], 'Disk GUID differs from /etc/asus-boot/install.json')
    return disk, gpt


def slot_parts(gpt):
    parts = {p['name']: p for p in gpt.partitions()}
    require(all(n in parts for n in SLOT_A), 'Slot-A partitions missing')
    return [parts[n] for n in SLOT_A]


def newest_kernel():
    kernels = [d.name for d in Path('/usr/lib/modules').iterdir() if (d / 'vmlinuz').is_file()]
    require(kernels, 'No installed kernel')
    return subprocess.run(['sort', '-V'], input='\n'.join(kernels), capture_output=True, text=True,
                          check=True).stdout.split()[-1]


def build_initramfs(kver, dest):
    """The installer's dracut setup; without the coreboot pair if DKMS did not build it for kver."""
    confdir = DRACUT_DIR
    wanted = (DRACUT_DIR / COREBOOT_CONF).exists()   # the installer writes it only if DKMS worked
    have_fb = any((Path('/usr/lib/modules') / kver).rglob('framebuffer-coreboot.ko*'))
    if wanted and not have_fb:
        subprocess.run(['dkms', 'autoinstall', '-k', kver], check=False)
        have_fb = any((Path('/usr/lib/modules') / kver).rglob('framebuffer-coreboot.ko*'))
    if wanted and not have_fb:
        print(f'WARNING: coreboot framebuffer modules not built for {kver}; the disk password prompt will be blank.')
        confdir = dest.parent / 'dracut.conf.d'
        shutil.rmtree(confdir, ignore_errors=True)
        shutil.copytree(DRACUT_DIR, confdir)
        (confdir / COREBOOT_CONF).unlink()
    run(['dracut', '--force', '-q', '--conf', DRACUT_CONF, '--confdir', confdir, '--kver', kver, dest])
    listing = output(['lsinitrd', dest])
    for private in ('avb-private', 'luks-header', '.nmconnection', 'authorized_keys'):
        require(private not in listing, 'Private file in initramfs: ' + private)
    for needed in ('systemd-cryptsetup', 'nvme', 'dm-crypt', 'btrfs'):
        require(needed in listing, 'Initramfs lacks ' + needed)
    if wanted and have_fb:
        require('framebuffer-coreboot' in listing, 'Initramfs lacks the coreboot framebuffer')
    size = dest.stat().st_size
    require(size < 29 * 1024**2, f'Initramfs is {size / 2**20:.1f} MiB; the vendor_boot budget is 29 MiB')
    print(f'Initramfs {size / 2**20:.1f} MiB')


def loader():
    path = ROOT / 'build/load_android_test'
    if not path.exists():
        run([sys.executable, '-I', ROOT / 'tools/build_loader.py'])
    return path


def validate(gpt, cand, work):
    image = work / 'loader-test.img'
    image.unlink(missing_ok=True)
    with image.open('wb') as f:
        f.truncate(gpt.disk_bytes)
        f.seek(0); f.write(gpt.primary)
        f.seek(gpt.disk_bytes - len(gpt.secondary)); f.write(gpt.secondary)
        for p in slot_parts(gpt):
            data = (cand / (p['name'] + '.img')).read_bytes()
            require(len(data) == p['size'], f"{p['name']} image does not fit its partition")
            f.seek(p['start_lba'] * 512); f.write(data)
    result = subprocess.run([str(loader()), '-b', '1', str(image)], cwd=work, capture_output=True, text=True)
    (work / 'loader-validation.log').write_text(result.stdout + result.stderr)
    image.unlink()
    (work / 'loaded-ramdisk.img').unlink(missing_ok=True)
    require(result.returncode == 0 and 'vb2api_load_kernel() returned 0' in result.stdout,
            f'Android loader rejected the boot set; see {work}/loader-validation.log')


def write_regions(disk, regions):
    fd = os.open(disk, os.O_RDWR | os.O_SYNC)
    done = []
    try:
        for offset, new, old in regions:
            done.append((offset, old))
            write_all(fd, offset, new)
            require(os.pread(fd, len(new), offset) == new, 'Read-back failed')
    except BaseException:
        for offset, old in reversed(done):
            write_all(fd, offset, old)
        print('Write failed; the previous slot-A contents were restored.')
        raise
    finally:
        os.close(fd)


def update(args):
    require(os.geteuid() == 0, 'Run as root')
    kver = args.kver or newest_kernel()
    vmlinuz = Path('/usr/lib/modules') / kver / 'vmlinuz'
    require(vmlinuz.is_file(), f'No kernel {kver}')
    disk, gpt = disk_and_gpt()
    STATE.mkdir(parents=True, exist_ok=True, mode=0o700)
    work = STATE / 'candidate'
    shutil.rmtree(work, ignore_errors=True); work.mkdir(mode=0o700)
    initramfs = work / 'initramfs.img'
    build_initramfs(kver, initramfs)
    cmdline = Path('/etc/kernel/cmdline').read_text().strip()
    sizes = {p['name']: p['size'] for p in gpt.partitions()}
    cand = work / 'boot'
    build_set(vmlinuz, initramfs, cmdline, cand, ROOT / 'vendor', sizes=sizes, installed=True,
              kernel_sha256=sha256(vmlinuz), key=KEY)
    validate(gpt, cand, work)
    # Back up what slot A holds now, then write the new set.
    state = read_json(STATE / 'state.json') if (STATE / 'state.json').exists() else {}
    previous = state.get('slot_kernel', os.uname().release)
    backup = STATE / 'slots' / f"{datetime.now().strftime('%Y%m%d-%H%M%S')}-{previous}"
    backup.mkdir(parents=True, mode=0o700)
    regions = []
    with open(disk, 'rb') as f:
        for p in slot_parts(gpt):
            f.seek(p['start_lba'] * 512); old = f.read(p['size'])
            (backup / (p['name'] + '.img')).write_bytes(old)
            regions.append((p['start_lba'] * 512, (cand / (p['name'] + '.img')).read_bytes(), old))
    save_json(backup / 'manifest.json', dict(kernel=previous, disk_guid=gpt.guid))
    os.sync()
    write_regions(disk, regions)
    for src, dst in ((vmlinuz, FEDORA_KERNEL), (initramfs, FEDORA_INITRAMFS)):
        Path(dst).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, dst)
    save_json(STATE / 'state.json', dict(slot_kernel=kver, previous=previous, backup=str(backup),
                                         updated=datetime.now().isoformat(timespec='seconds')))
    for old in sorted((STATE / 'slots').iterdir())[:-KEEP_BACKUPS]:
        shutil.rmtree(old)
    shutil.rmtree(work)
    os.sync()
    print(f'==> Ruby: slot A now boots kernel {kver} (was {previous}). Reboot to use it.')
    print(f'==> If it does not boot: live USB, unlock and mount, then arch-chroot /mnt python3 {ROOT}/tools/kernel_update_fedora.py rollback')


def rollback(args):
    require(os.geteuid() == 0, 'Run as root')
    disk, gpt = disk_and_gpt()
    backups = sorted((STATE / 'slots').iterdir()) if (STATE / 'slots').exists() else []
    require(backups, 'No slot-A backup to roll back to')
    backup = backups[-1]
    manifest = read_json(backup / 'manifest.json')
    require(manifest['disk_guid'] == gpt.guid, 'Backup belongs to another disk')
    regions = []
    with open(disk, 'rb') as f:
        for p in slot_parts(gpt):
            f.seek(p['start_lba'] * 512); now = f.read(p['size'])
            data = (backup / (p['name'] + '.img')).read_bytes()
            require(len(data) == p['size'], 'Backup image size differs from the partition')
            regions.append((p['start_lba'] * 512, data, now))
    write_regions(disk, regions)
    save_json(STATE / 'state.json', dict(slot_kernel=manifest['kernel'], rolled_back_from=str(backup),
                                         updated=datetime.now().isoformat(timespec='seconds')))
    shutil.rmtree(backup)
    os.sync()
    print(f"==> Ruby: slot A restored to kernel {manifest['kernel']}. Reboot.")


def status(args):
    state = read_json(STATE / 'state.json') if (STATE / 'state.json').exists() else {}
    install = read_json(INSTALL) if INSTALL.exists() else {}
    print('running  :', os.uname().release)
    print('slot A   :', state.get('slot_kernel', install.get('kernel_release', 'unknown (install-time kernel)')))
    print('newest   :', newest_kernel())
    print('hook     :', 'installed' if HOOK.exists() else 'missing (run install-hook)')


def install_hook(args):
    require(os.geteuid() == 0, 'Run as root')
    HOOK.parent.mkdir(parents=True, exist_ok=True)
    HOOK.write_text(HOOK_TEXT)
    HOOK.chmod(0o755)
    print(f'Installed {HOOK}; dnf kernel updates now go to slot A automatically.')


def main():
    os.umask(0o022)
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    subs = p.add_subparsers(required=True)
    q = subs.add_parser('update'); q.add_argument('--kver'); q.set_defaults(fn=update)
    subs.add_parser('rollback').set_defaults(fn=rollback)
    subs.add_parser('status').set_defaults(fn=status)
    subs.add_parser('install-hook').set_defaults(fn=install_hook)
    a = p.parse_args(); a.fn(a)


if __name__ == '__main__':
    main()
