#!/usr/bin/env python3
"""One-shot Fedora install on a Ruby Googlebook. ERASES THE WHOLE INTERNAL DISK.

    python3 tools/install_fedora_ruby.py --user YOU --name 'Your Name' --timezone America/Chicago

Run as root from the live USB, on AC, with Wi-Fi connected. No backups, no stages.
Asks once for confirmation and the two passwords, then:

  1. writes a new partition table: one Fedora root partition plus only what the
     stock firmware boots from (boot/init_boot/vendor_boot/vbmeta a+b, misc) and
     `super` (source of Lenovo's speaker firmware); everything else is dropped
  2. LUKS2 + Btrfs on the root partition, installs Fedora 45
  3. speaker firmware + calibration, light sensor firmware
  4. builds and signs the boot images, checks them with ChromiumOS's Android
     loader, writes them to slot A

Safe to rerun from the top if it fails partway.
"""
import argparse
import getpass
import os
from pathlib import Path
import re
import shutil
import struct
import subprocess
import sys
import uuid
import zlib
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lapis.boot import build_set
from lapis.common import (ROOT, FEDORA_CHECKSUM_URL, FEDORA_KERNEL, FEDORA_INITRAMFS, board, output, read_json, require,
                          run, save_json, sha256)
from lapis.gpt import ENTRY, read_gpt, tables
from tools.configure_target import put, mask, chroot
from tools.configure_fedora import (PACKAGES, DESKTOPS, XE_OPTIONS, CALIBRATION, verified_image, unpack_rootfs, dnf,
                                    kernel_release, check_initramfs)
from tools.native import write_all

TARGET = Path('/mnt')
MAPPER = 'fedora-root'
KIT = '/opt/lapis-kit'
LINUX = '0fc63daf-8483-4772-8e79-3d69d8477de4'
VBMETA = '88434509-d9d1-487d-b82c-15ef964cbd4b'
# Factory positions (assets/lapis-512gb.json); the firmware finds these by name.
KEEP = ('super', 'boot_a', 'boot_b', 'vbmeta_a', 'vbmeta_b', 'init_boot_a', 'init_boot_b',
        'vendor_boot_a', 'vendor_boot_b', 'misc')
SLOT_A = ('boot_a', 'init_boot_a', 'vendor_boot_a', 'vbmeta_a')
COREBOOT_DKMS = 'ruby-coreboot-7.3.3'


def new_gpt(disk_bytes):
    """Fedora root at the old userdata start, running to the end of the disk."""
    profile = read_json(ROOT / 'assets/lapis-512gb.json')
    require(disk_bytes == profile['disk_bytes'], f'Expected the 512 GB Ruby disk, found {disk_bytes} bytes')
    sectors = disk_bytes // 512
    first, last = 34, sectors - 34
    entries = bytearray(128 * 128)
    by_name = {p['name']: p for p in profile['partitions']}
    layout = [(1, 'userdata', by_name['userdata']['start_lba'], last, LINUX, 0)]
    for name in KEEP:
        p = by_name[name]
        attrs = 0
        if name == 'vbmeta_a':
            attrs = (15 << 48) | (1 << 56)   # highest priority, marked successful
        layout.append((p['index'], name, p['start_lba'], p['start_lba'] + p['size'] // 512 - 1, p['type_guid'], attrs))
    for index, name, start, end, typ, attrs in layout:
        entries[(index - 1) * 128:index * 128] = ENTRY.pack(uuid.UUID(typ).bytes_le, uuid.uuid4().bytes_le, start, end,
                                                             attrs, name.encode('utf-16-le'))
    header = [b'EFI PART', 0x10000, 92, 0, 0, 1, sectors - 1, first, last, uuid.uuid4().bytes_le, 2, 128, 128, 0]
    mbr = bytearray(512)
    mbr[450] = 0xee
    struct.pack_into('<II', mbr, 454, 1, min(sectors - 1, 0xffffffff))
    mbr[510:512] = b'\x55\xaa'
    return tables(header, entries, bytes(mbr))


def release_disk(disk):
    if subprocess.run(['mountpoint', '-q', TARGET]).returncode == 0:
        run(['umount', '-R', TARGET])
    if Path('/dev/mapper', MAPPER).exists():
        run(['cryptsetup', 'close', MAPPER])
    for line in output(['lsblk', '-nrpo', 'PATH,MOUNTPOINTS', disk]).splitlines():
        parts = line.split(' ', 1)
        require(len(parts) == 1 or not parts[1].strip(), f'{parts[0]} is mounted at {parts[-1]}; unmount it first')
    subprocess.run(['swapoff', '-a'], check=False)


def write_table(disk, primary, secondary, disk_bytes):
    fd = os.open(disk, os.O_RDWR | os.O_SYNC)
    try:
        write_all(fd, 0, primary)
        write_all(fd, disk_bytes - len(secondary), secondary)
    finally:
        os.close(fd)
    if subprocess.run(['blockdev', '--rereadpt', disk]).returncode != 0:
        subprocess.run(['partx', '-d', disk])   # drop stale entries, then add the new ones
        run(['partx', '-a', disk])
    run(['udevadm', 'settle'])
    with open(disk, 'rb') as f:
        gpt = read_gpt(f, disk_bytes)
    names = {p['name'] for p in gpt.partitions()}
    require(names == {'userdata', *KEEP}, 'Partition table did not read back as written')
    return gpt


def part(disk, gpt, name):
    p = next(p for p in gpt.partitions() if p['name'] == name)
    return Path(f"{disk}p{p['index']}"), p


def format_root(block, disk_password):
    luks_uuid = str(uuid.uuid4())
    secret = disk_password.encode()
    run(['wipefs', '-a', block])
    run(['cryptsetup', 'luksFormat', '--type', 'luks2', '--batch-mode', '--uuid', luks_uuid, '--label', 'FEDORA',
         '--cipher', 'aes-xts-plain64', '--key-size', '512', '--pbkdf', 'argon2id', '--pbkdf-memory', '1048576',
         '--iter-time', '2000', '--key-file', '-', block], input=secret)
    run(['cryptsetup', 'open', '--key-file', '-', block, MAPPER], input=secret)
    mapper = f'/dev/mapper/{MAPPER}'
    run(['mkfs.btrfs', '-f', '-L', 'Fedora', mapper])
    TARGET.mkdir(exist_ok=True)
    run(['mount', mapper, TARGET])
    for name in ('@', '@home', '@log', '@pkg'):
        run(['btrfs', 'subvolume', 'create', TARGET / name])
    run(['umount', TARGET])
    mounts = [('@', '/'), ('@home', '/home'), ('@log', '/var/log'), ('@pkg', '/var/cache/libdnf5')]
    for subvol, rel in mounts:
        folder = TARGET / rel.lstrip('/')
        folder.mkdir(parents=True, exist_ok=True)
        run(['mount', '-o', 'noatime,compress=zstd:3,subvol=' + subvol, mapper, folder])
    fs = output(['blkid', '-s', 'UUID', '-o', 'value', mapper])
    return luks_uuid, ''.join(f'UUID={fs} {m} btrfs noatime,compress=zstd:3,subvol={s} 0 0\n' for s, m in mounts)


def install_fedora(args, login_password):
    work = TARGET / 'var/tmp/ruby-bootstrap'
    work.mkdir(parents=True, mode=0o700)
    unpack_rootfs(verified_image(work), work)
    shutil.rmtree(work)
    dnf('upgrade', '--refresh')
    dnf('reinstall', '--skip-unavailable', '*')
    dnf('install', *PACKAGES, *DESKTOPS[args.desktop])
    chroot('useradd', '-m', '-G', 'wheel', '-c', args.name, args.user)
    chroot('chpasswd', input=(args.user + ':' + login_password + '\n').encode())
    chroot('passwd', '-l', 'root')
    return kernel_release()


def configure(args, fstab):
    put('/etc/fstab', fstab)
    put('/etc/hostname', args.hostname + '\n')
    put('/etc/locale.conf', 'LANG=en_US.UTF-8\n')
    put('/etc/vconsole.conf', 'KEYMAP=' + args.keymap + '\n')
    localtime = TARGET / 'etc/localtime'
    localtime.unlink(missing_ok=True)
    localtime.symlink_to('../usr/share/zoneinfo/' + args.timezone)
    chroot('systemd-machine-id-setup')
    put('/etc/modprobe.d/ruby-xe.conf', 'blacklist xe\noptions xe ' + XE_OPTIONS + '\n')
    put('/etc/systemd/system/ruby-gpu.service', (ROOT / 'assets/installed/ruby-gpu.service').read_text())
    put('/etc/modprobe.d/ruby-audio.conf', (ROOT / 'assets/installed/ruby-audio.conf').read_text())
    put('/etc/systemd/logind.conf.d/ruby-power-key.conf', (ROOT / 'assets/installed/logind/ruby-power-key.conf').read_text())
    mask('/etc/systemd/system-generators/systemd-gpt-auto-generator')
    chroot('systemctl', 'enable', 'ruby-gpu.service', 'NetworkManager.service', 'systemd-resolved.service')
    chroot('systemctl', 'mask', 'sshd.service', 'efi.mount', 'efi.automount')
    chroot('systemctl', 'set-default', 'graphical.target' if args.desktop != 'none' else 'multi-user.target')
    # Kit copy: loader harness build, audio/sensor installers, later kernel updates.
    kit = TARGET / KIT.lstrip('/')
    if kit.exists():
        shutil.rmtree(kit)
    shutil.copytree(ROOT, kit, ignore=shutil.ignore_patterns('build', '__pycache__', '*.img'))


def optional(label, fn):
    """Hardware extras must not stop the install; report and carry on."""
    try:
        fn()
        return True
    except (subprocess.CalledProcessError, RuntimeError, OSError) as error:
        print(f'WARNING: {label} failed ({error}); the system will still boot. Retry later from {KIT}/tools.')
        return False


def coreboot_modules(release):
    """Build coreboot_table/framebuffer-coreboot/vpd-sysfs for Fedora's kernel (DKMS rebuilds them on updates).

    Fedora lacks CONFIG_GOOGLE_FIRMWARE; with these in the initramfs the firmware framebuffer becomes a
    simple-framebuffer that the built-in simpledrm drives, so the disk password prompt is visible.
    """
    src = TARGET / f'usr/src/{COREBOOT_DKMS}'
    if src.exists():
        shutil.rmtree(src)
    shutil.copytree(ROOT / 'assets/installed/coreboot-fb', src)
    chroot('dkms', 'install', '--force', COREBOOT_DKMS.replace('-7', '/7', 1), '-k', release)
    put('/etc/ruby-boot/dracut.conf.d/coreboot-fb.conf', 'force_drivers+=" coreboot_table framebuffer_coreboot "\n')
    put('/etc/modules-load.d/ruby-coreboot.conf', 'coreboot_table\nframebuffer_coreboot\nvpd_sysfs\n')


def extras():
    subprocess.run(['modprobe', '-a', 'coreboot_table', 'vpd_sysfs'], capture_output=True)
    calibration = optional('speaker calibration capture', lambda: run(
        [sys.executable, '-I', ROOT / 'assets/installed/ruby-speaker-calibration.py', '--save', TARGET / CALIBRATION]))
    audio = optional('speaker firmware from super', lambda: chroot('sh', f'{KIT}/tools/install_ruby_audio.sh'))
    sensors = optional('light sensor firmware from super', lambda: chroot('sh', f'{KIT}/tools/install_ruby_sensors.sh'))
    return dict(calibration=calibration, audio=audio, sensors=sensors)


def build_initramfs(release, framebuffer):
    put('/etc/ruby-boot/dracut.conf', (ROOT / 'assets/fedora/dracut.conf').read_text())
    (TARGET / 'etc/ruby-boot/dracut.conf.d').mkdir(exist_ok=True)
    kernel = TARGET / FEDORA_KERNEL.lstrip('/')
    kernel.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(TARGET / 'usr/lib/modules' / release / 'vmlinuz', kernel)
    chroot('dracut', '--force', '--conf', '/etc/ruby-boot/dracut.conf', '--confdir', '/etc/ruby-boot/dracut.conf.d',
           '--kver', release, FEDORA_INITRAMFS)
    check_initramfs(TARGET / FEDORA_INITRAMFS.lstrip('/'), framebuffer=framebuffer)
    return kernel, TARGET / FEDORA_INITRAMFS.lstrip('/')


def build_and_check_boot(gpt, luks_uuid, kernel, initramfs):
    cmdline = (f'rd.luks.name={luks_uuid}={MAPPER} rd.driver.blacklist=xe root=/dev/mapper/{MAPPER} rootfstype=btrfs '
               'rootflags=subvol=@ rw zswap.enabled=0 modprobe.blacklist=xe initramfs_async=0 console=tty0 loglevel=3 '
               'log_buf_len=4M printk.time=1 panic=30 fbcon=nodefer plymouth.enable=0 rd.plymouth=0 '
               'xe.gsc_firmware_path=')
    state = TARGET / 'var/lib/asus-boot/installation'
    if state.exists():
        shutil.rmtree(state)
    state.parent.mkdir(parents=True, exist_ok=True)
    cand = state / 'candidate'
    sizes = {p['name']: p['size'] for p in gpt.partitions()}
    build_set(kernel, initramfs, cmdline, cand, ROOT / 'vendor', sizes=sizes, installed=True,
              kernel_sha256=sha256(kernel))
    # Sparse copy of the disk as it will be, booted through ChromiumOS's Android loader.
    chroot('python3', f'{KIT}/tools/build_loader.py')
    image = state / 'loader-test.img'
    with image.open('wb') as f:
        f.truncate(gpt.disk_bytes)
        f.seek(0); f.write(gpt.primary)
        f.seek(gpt.disk_bytes - len(gpt.secondary)); f.write(gpt.secondary)
        for p in gpt.partitions():
            if p['name'] in SLOT_A:
                f.seek(p['start_lba'] * 512); f.write((cand / (p['name'] + '.img')).read_bytes())
    rel = '/' + str(state.relative_to(TARGET))
    result = subprocess.run(['arch-chroot', TARGET, 'sh', '-c', f'cd {rel} && {KIT}/build/load_android_test -b 1 loader-test.img'],
                            capture_output=True, text=True)
    (state / 'loader-validation.log').write_text(result.stdout + result.stderr)
    image.unlink()
    (state / 'loaded-ramdisk.img').unlink(missing_ok=True)
    require(result.returncode == 0 and 'vb2api_load_kernel() returned 0' in result.stdout,
            f'Android loader rejected the boot set; nothing written to slot A. Log: {state}/loader-validation.log')
    put('/etc/kernel/cmdline', cmdline + '\n')
    shutil.copy2(cand / 'avb-private.pem', TARGET / 'etc/asus-boot/avb-private.pem')
    return cand


def write_slot_a(disk, gpt, cand):
    fd = os.open(disk, os.O_RDWR | os.O_SYNC)
    try:
        for p in gpt.partitions():
            if p['name'] in SLOT_A:
                data = (cand / (p['name'] + '.img')).read_bytes()
                require(len(data) == p['size'], f"{p['name']} image does not fit its partition")
                write_all(fd, p['start_lba'] * 512, data)
                require(os.pread(fd, len(data), p['start_lba'] * 512) == data, f"{p['name']} read-back failed")
                print('Wrote', p['name'])
            elif p['name'] == 'misc':  # clear any pending Android recovery/boot command
                write_all(fd, p['start_lba'] * 512, bytes(p['size']))
    finally:
        os.close(fd)


def relabel():
    selinux = TARGET / 'etc/selinux/config'
    selinux.write_text(re.sub(r'(?m)^SELINUX=.*$', 'SELINUX=permissive', selinux.read_text()))
    if subprocess.run(['arch-chroot', TARGET, 'setfiles', '-F', '-e', '/proc', '-e', '/sys', '-e', '/dev', '-e', '/run',
                       '/etc/selinux/targeted/contexts/files/file_contexts', '/']).returncode != 0:
        (TARGET / '.autorelabel').touch()


def ask_password(label, minimum):
    while True:
        first = getpass.getpass(f'{label}: ')
        if len(first) < minimum:
            print(f'Use at least {minimum} characters.'); continue
        if first == getpass.getpass(f'Repeat {label.lower()}: '):
            return first
        print('They differ; try again.')


def main():
    os.umask(0o022)
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--disk', default='/dev/nvme0n1')
    p.add_argument('--user', required=True); p.add_argument('--name', required=True)
    p.add_argument('--timezone', required=True); p.add_argument('--keymap', default='us')
    p.add_argument('--hostname', default='googlebook')
    p.add_argument('--desktop', choices=sorted(DESKTOPS), default='none')
    args = p.parse_args()
    require(os.geteuid() == 0, 'Run as root')
    require(board()[0] == 'Ruby', 'This script is for the Lenovo Googlebook 15 (Ruby)')
    require(re.fullmatch('[a-z][a-z0-9_-]{0,30}', args.user) and args.user != 'root', 'Invalid username')
    require((Path('/usr/share/zoneinfo') / args.timezone).is_file(), 'Unknown timezone')
    require(subprocess.run(['curl', '-sfI', '--max-time', '15', FEDORA_CHECKSUM_URL], capture_output=True).returncode == 0,
            'No network: connect Wi-Fi with iwctl first')
    disk = args.disk
    disk_bytes = int(output(['blockdev', '--getsize64', disk]))
    primary, secondary = new_gpt(disk_bytes)

    print(f'\nThis ERASES {disk} ({disk_bytes / 1e9:.0f} GB) and installs Fedora.')
    require(input('Type ERASE to continue: ') == 'ERASE', 'Cancelled')
    disk_password = ask_password('Disk encryption password', 8)
    login_password = ask_password(f'Login/sudo password for {args.user}', 8)

    release_disk(disk)
    gpt = write_table(disk, primary, secondary, disk_bytes)
    root_block, _ = part(disk, gpt, 'userdata')
    luks_uuid, fstab = format_root(root_block, disk_password)
    del disk_password
    release = install_fedora(args, login_password).name
    del login_password
    configure(args, fstab)
    framebuffer = optional('coreboot framebuffer modules (visible password prompt)', lambda: coreboot_modules(release))
    found = dict(extras(), framebuffer=framebuffer)
    kernel, initramfs = build_initramfs(release, framebuffer)
    cand = build_and_check_boot(gpt, luks_uuid, kernel, initramfs)
    save_json(TARGET / 'etc/asus-boot/install.json', dict(device=disk, disk_guid=gpt.guid, luks_uuid=luks_uuid,
                                                          disk_bytes=disk_bytes, partitions=gpt.partitions(),
                                                          kernel_release=release, **found))
    relabel()
    chroot('chown', '-R', f'{args.user}:{args.user}', f'/home/{args.user}')
    write_slot_a(disk, gpt, cand)
    os.sync()
    run(['umount', '-R', TARGET])
    run(['cryptsetup', 'close', MAPPER])
    print('\nDone. Power off, remove the USB, choose "Boot from internal disk".')
    if framebuffer:
        print('Type the disk password at the prompt.')
    else:
        print('The screen stays black at the disk password: wait ~15 s, type it, press Enter.')
    missing = [k for k, ok in found.items() if not ok]
    if missing:
        print('Not set up (see warnings above):', ', '.join(missing))


if __name__ == '__main__':
    main()
