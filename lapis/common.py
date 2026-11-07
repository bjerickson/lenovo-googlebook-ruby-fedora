"""Small, explicit helpers shared by the image builder and target tools."""
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess

ROOT = Path(__file__).resolve().parents[1]
KERNEL_RELEASE = '7.2.4-arch1-Watanare-T2-3-t2'
ISO_SHA256 = 'ddeded2758c48318d201dfdac905ecb28f570441883f0c052ea3cd5d05acf92d'
KERNEL_SHA256 = 'df69967d55b74263fcd78bbfc0e0e6c86d0e27b9cebb873f6f86b5d072602bb6'
KERNEL_PACKAGES = {
    'linux-t2-7.2.4.arch1-3-x86_64.pkg.tar.zst': 'cc5a5ff74f5c04ea1bb79b6e58400a3b3eb69d1cda9093226921d4a2ebb1b17d',
    'linux-t2-headers-7.2.4.arch1-3-x86_64.pkg.tar.zst': '9892cea1ee6ba091ec7f9e053bb5fb1cc42f94c359ab2a4ab158ddc1d2001eae',
}
XE_PARAMETERS = {
    'gsc_firmware_path': '', 'enable_panel_replay': '0', 'enable_psr': '0',
    'enable_fbc': '0', 'enable_dsb': '0', 'enable_sagv': '0', 'enable_dc': '0',
}
# Physically surveyed fatcat boards. Ruby (Lenovo Googlebook 15) has a GPT
# byte-identical to the Lapis 512 GB profile; one plain Xe load drives its panel.
BOARDS = {
    'Lapis': dict(gpu='0xb090', audio_subsystem='0x15e4', profile='lapis-512gb.json', xe_reload=True,
                  mapper='omarchy_root', label='Omarchy'),
    'Ruby': dict(gpu='0xb090', audio_subsystem='0x0000', profile='lapis-512gb.json', xe_reload=False,
                 mapper='fedora-root', label='Fedora', pkg_cache='var/cache/libdnf5'),
}
# Root mappers the installed-system tools accept (Fedora fork first; CachyOS and
# pre-rename Omarchy names kept so upstream tools still recognise their installs).
ROOT_MAPPERS = ('fedora-root', 'cachyos-root', 'omarchy_root')
# CachyOS target (Ruby). The kernel is pinned by the installed system; its hash
# is recorded at install time rather than shipped, because CachyOS repos only
# carry the current build.
CACHYOS_KEY = '882DCFE48E2051D48E2562ABF3B607488DB35A47'
CACHYOS_KERNEL = '/boot/vmlinuz-linux-cachyos'
CACHYOS_INITRAMFS = '/boot/initramfs-linux-cachyos-android.img'
# Fedora target (Ruby). Bootstrapped from Fedora's signed OCI container image,
# then completed by the target's own dnf5. The image hash is pinned and the
# CHECKSUM file's signature is checked against Fedora 45's primary key, whose
# fingerprint is published at https://fedoraproject.org/security/.
FEDORA_RELEASE = '45'
FEDORA_IMAGE_URL = ('https://dl.fedoraproject.org/pub/fedora/linux/releases/45/Container/x86_64/images/'
                    'Fedora-Container-Base-Generic-45-1.4.x86_64.oci.tar.xz')
FEDORA_CHECKSUM_URL = ('https://dl.fedoraproject.org/pub/fedora/linux/releases/45/Container/x86_64/images/'
                       'Fedora-Container-45-1.4-x86_64-CHECKSUM')
FEDORA_IMAGE_SHA256 = 'cfd51bdc8a26bc6f23c6993145e19e9a2be4c7af2aefa1f309c5e05e5beac197'
FEDORA_KEY = '4F50A6114CD5C6976A7F1179655A4B02F577861E'
# Outside kernel-install's /boot/vmlinuz-<release> names, so dnf never touches them.
FEDORA_KERNEL = '/boot/ruby-android/vmlinuz'
FEDORA_INITRAMFS = '/boot/ruby-android/initramfs.img'


def require(condition, message):
    # Never use assert for a guard: Python -O must not disable it.
    if not condition:
        raise RuntimeError(message)


def board():
    """Return (name, facts) for the running board, refusing unsurveyed hardware."""
    name = Path('/sys/class/dmi/id/product_name').read_text().strip()
    require(Path('/sys/class/dmi/id/sys_vendor').read_text().strip() == 'Google', 'Wrong DMI vendor')
    require(name in BOARDS, 'Unsupported board: ' + name)
    facts = BOARDS[name]
    require(Path('/sys/bus/pci/devices/0000:00:02.0/device').read_text().strip() == facts['gpu'], 'Wrong graphics device')
    require(Path('/sys/bus/pci/devices/0000:00:1f.3/subsystem_device').read_text().strip() == facts['audio_subsystem'], 'Wrong audio subsystem')
    return name, facts


def sha256(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def run(argv, **kwargs):
    # Passwords are passed on stdin, never in argv or this log.
    print('+', ' '.join(map(str, argv)), flush=True)
    return subprocess.run(list(map(str, argv)), check=True, **kwargs)


def output(argv):
    return subprocess.check_output(list(map(str, argv)), text=True).strip()


def save_json(path, value, mode=0o600):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + '.new')
    fd = os.open(tmp, os.O_CREAT | os.O_EXCL | os.O_WRONLY, mode)
    with os.fdopen(fd, 'w') as f:
        json.dump(value, f, indent=2)
        f.write('\n')
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def new_regular_output(path):
    path = Path(path)
    require(not path.exists() and not path.is_symlink(), f'Output already exists: {path}')
    require(not str(path.resolve()).startswith('/dev/'), 'Image tools never write device nodes')
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def require_regular(path):
    path = Path(path)
    require(not path.is_symlink() and stat.S_ISREG(path.stat().st_mode), f'Not a regular file: {path}')


def read_json(path):
    return json.loads(Path(path).read_text())
