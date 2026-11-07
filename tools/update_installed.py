#!/usr/bin/env python3
"""Bring an installed Fedora system up to date with this checkout. Run after `git pull`:

    cd ~/googlebook && git pull && sudo python3 tools/update_installed.py

It only updates what this project installed and leaves everything else alone:
  - /opt/lapis-kit, the copy the kernel-update hook runs from (code and assets;
    the built loader and pinned tool sources are kept unless the pins changed)
  - the kernel-install hook
  - DKMS driver sources that changed (coreboot framebuffer, light sensor,
    fingerprint), rebuilt for every installed kernel with headers
  - configuration files that are missing or differ (graphics/audio services,
    modprobe options, UCM profile, mic boost, calibration service)
  - the glowbar, auto-brightness and power-mode services, if installed
It never writes the boot partitions: when the boot initramfs configuration
changed it says so, and `kernel_update_fedora.py update` applies it.
"""
import filecmp
import os
from pathlib import Path
import shutil
import subprocess
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lapis.common import ROOT, require, run
from tools.fetch_sources import SOURCES

KIT = Path('/opt/lapis-kit')
KIT_CONTENT = ('lapis', 'tools', 'assets', 'docs', 'LICENSE', 'NOTICE.md', 'README.md')
A = ROOT / 'assets/installed'
# (source, destination, mode); installed by install_fedora_ruby.py on every system
BASE = [
    (A / 'ruby-gpu.service', '/etc/systemd/system/ruby-gpu.service', 0o644),
    (A / 'ruby-audio.conf', '/etc/modprobe.d/ruby-audio.conf', 0o644),
    (A / 'logind/ruby-power-key.conf', '/etc/systemd/logind.conf.d/ruby-power-key.conf', 0o644),
]
# installed by tools/install_ruby_audio.sh (the firmware itself is never touched here)
AUDIO = [
    (A / 'ruby-dax.conf', '/etc/modprobe.d/ruby-dax.conf', 0o644),
    (A / 'ucm2/sof-rt5682/sof-rt5682.conf', '/usr/share/alsa/ucm2/conf.d/sof-rt5682/sof-rt5682.conf', 0o644),
    (A / 'ucm2/sof-rt5682/HiFi.conf', '/usr/share/alsa/ucm2/conf.d/sof-rt5682/HiFi.conf', 0o644),
    (A / 'ruby-speaker-calibration.py', '/usr/local/libexec/ruby-speaker-calibration', 0o755),
    (A / 'ruby-speaker-calibration.service', '/etc/systemd/system/ruby-speaker-calibration.service', 0o644),
    (A / 'pipewire/ruby-mic.conf', '/etc/pipewire/pipewire.conf.d/ruby-mic.conf', 0o644),
]
SENSORS = [(A / 'ruby-sensors.conf', '/etc/modprobe.d/ruby-sensors.conf', 0o644)]
BOOT = [
    (ROOT / 'assets/fedora/dracut.conf', '/etc/ruby-boot/dracut.conf', 0o644),
    (ROOT / 'assets/fedora/99-ruby-size.conf', '/etc/ruby-boot/dracut.conf.d/99-ruby-size.conf', 0o644),
]
# DKMS package -> source in this repository (installed only if /usr/src has it)
DKMS = {
    'ruby-coreboot/7.3.3': A / 'coreboot-fb',
    'ruby-cros-ec-ishtp/7.2.15': A / 'cros-ec-ishtp',
}
SERVICES = [  # (installed marker, installer)
    ('/usr/local/libexec/ruby-glowbar', 'tools/install_glowbar.sh'),
    ('/usr/local/libexec/ruby-autobrightness', 'tools/install_autobrightness.sh'),
    ('/usr/local/libexec/ruby-power-mode', 'tools/install_power_mode.sh'),
]


def same_tree(a, b):
    """True if both directories hold the same files with the same contents."""
    a, b = Path(a), Path(b)
    if not b.is_dir():
        return False
    files = lambda d: sorted(str(p.relative_to(d)) for p in d.rglob('*') if p.is_file() and '__pycache__' not in p.parts)
    names = files(a)
    return names == files(b) and all(filecmp.cmp(a / n, b / n, shallow=False) for n in names)


def install_file(src, dest, mode):
    """Copy src to dest if missing or different; return True if it changed."""
    dest = Path(dest)
    if dest.is_file() and filecmp.cmp(src, dest, shallow=False) and (dest.stat().st_mode & 0o777) == mode:
        return False
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(src, dest)
    dest.chmod(mode)
    print('  updated', dest)
    return True


def kernels_with_headers():
    found = []
    for build in sorted(Path('/usr/lib/modules').glob('*/build/include')):
        kver = build.parent.parent.name
        if (build.parent.parent / 'kernel').is_dir() or (build.parent.parent / 'vmlinuz').is_file():
            found.append(kver)
    return found


def refresh_kit():
    """Code and assets from the checkout; keep the built loader and vendored sources if still pinned."""
    if ROOT.resolve() == KIT.resolve():
        print('Running from /opt/lapis-kit itself; run this from your git checkout to update it.')
        return
    KIT.mkdir(parents=True, exist_ok=True)
    for name in KIT_CONTENT:
        src, dest = ROOT / name, KIT / name
        if dest.is_dir():
            shutil.rmtree(dest)
        elif dest.exists():
            dest.unlink()
        if src.is_dir():
            shutil.copytree(src, dest, ignore=shutil.ignore_patterns('__pycache__'))
        else:
            shutil.copy2(src, dest)
    stale = []
    for name, (_, revision) in SOURCES.items():
        marker = KIT / 'vendor' / name / '.source-revision'
        git = subprocess.run(['git', '-C', str(KIT / 'vendor' / name), 'rev-parse', 'HEAD'], capture_output=True, text=True)
        have = marker.read_text().strip() if marker.is_file() else git.stdout.strip()
        if have != revision:
            stale.append(name)
    if stale or not (KIT / 'build/load_android_test').exists():
        print(f"  refetching pinned sources ({', '.join(stale) or 'loader missing'}) and rebuilding the loader")
        shutil.rmtree(KIT / 'vendor', ignore_errors=True)
        shutil.rmtree(KIT / 'build', ignore_errors=True)
        run([sys.executable, '-I', KIT / 'tools/fetch_sources.py', '--destination', KIT / 'vendor'])
        for name, (_, revision) in SOURCES.items():           # later runs need no git
            (KIT / 'vendor' / name / '.source-revision').write_text(revision + '\n')
        run([sys.executable, '-I', KIT / 'tools/build_loader.py'])
    print(f'  {KIT} matches this checkout')


def refresh_dkms():
    kernels = kernels_with_headers()
    for package, src in DKMS.items():
        name, version = package.split('/')
        dest = Path('/usr/src') / f'{name}-{version}'
        if not dest.exists():
            continue                                  # not installed on this system
        if same_tree(src, dest):
            continue
        print(f'  {package}: source changed, rebuilding for {", ".join(kernels)}')
        subprocess.run(['dkms', 'remove', package, '--all'], capture_output=True)
        shutil.rmtree(dest)
        shutil.copytree(src, dest, ignore=shutil.ignore_patterns('__pycache__'))
        for kver in kernels:
            run(['dkms', 'install', '--force', package, '-k', kver])
    # The fingerprint driver has its own installer (patches, blacklist handling).
    usb = A / 'cros-ec-usb'
    version = next(l.split('"')[1] for l in (usb / 'dkms.conf').read_text().splitlines() if l.startswith('PACKAGE_VERSION='))
    installed = sorted(Path('/usr/src').glob('cros-ec-usb-*'))
    if installed and not same_tree(usb, Path('/usr/src') / f'cros-ec-usb-{version}'):
        autoload = not Path('/etc/modprobe.d/ruby-fingerprint.conf').exists()
        print('  cros-ec-usb: source changed, reinstalling')
        run(['sh', KIT / 'tools/install_fingerprint_driver.sh', *(['--autoload'] if autoload else [])])


def libfprint_note():
    spec = (ROOT / 'assets/packages/libfprint-crfpmoc/libfprint.spec').read_text()
    wanted = next(l.split()[1] for l in spec.splitlines() if l.startswith('Release:')).replace('%{?dist}', '')
    have = subprocess.run(['rpm', '-q', '--qf', '%{RELEASE}', 'libfprint'], capture_output=True, text=True).stdout
    if 'crfpmoc' in have and not have.startswith(wanted):
        return f'The fingerprint library changed ({have} -> {wanted}): sudo sh tools/install_fingerprint_fedora.sh'
    return None


def step(failures, title, fn):
    """Run one part; a failure is reported at the end instead of stopping the others."""
    print('==> ' + title, flush=True)
    try:
        return fn()
    except (RuntimeError, OSError, subprocess.CalledProcessError) as e:
        print(f'  FAILED: {e}', flush=True)
        failures.append(f'{title}: {e}')
        return None


def main():
    require(os.geteuid() == 0, 'Run with sudo')
    require(Path('/etc/asus-boot/install.json').is_file(), 'This is not a Ruby Fedora installation (no /etc/asus-boot/install.json)')
    notes, failures = [], []
    if step(failures, 'Kit used by the kernel-update hook', refresh_kit) is None and failures:
        sys.exit(f'Error: {failures[0]}')                  # everything below runs from the kit
    step(failures, 'Kernel-update hook',
         lambda: run([sys.executable, '-I', KIT / 'tools/kernel_update_fedora.py', 'install-hook']))
    step(failures, 'Drivers (DKMS)', refresh_dkms)
    step(failures, 'Configuration', lambda: configuration(notes))
    step(failures, 'Optional services', lambda: services(notes))
    note = libfprint_note()
    if note:
        notes.append(note)
    step(failures, 'Kernel status', lambda: run([sys.executable, '-I', KIT / 'tools/kernel_update_fedora.py', 'status']))
    print('\n' + ('Up to date.' if not failures else 'Finished with errors:') + ''.join('\n- ' + n for n in failures + notes))
    if failures:
        sys.exit(1)


def configuration(notes):
    units = any([install_file(*f) for f in BASE])
    if Path('/usr/local/libexec/ruby-speaker-calibration').exists():
        units = any([install_file(*f) for f in AUDIO]) or units
    if Path('/etc/modprobe.d/ruby-sensors.conf').exists():
        [install_file(*f) for f in SENSORS]
    if any([install_file(*f) for f in BOOT]):
        notes.append('The boot initramfs configuration changed; apply it with:\n'
                     f'    sudo python3 {KIT}/tools/kernel_update_fedora.py update')
    if units:
        run(['systemctl', 'daemon-reload'])


def services(notes):
    user_services = []
    for marker, installer in SERVICES:
        if Path(marker).exists():
            run(['sh', KIT / installer])
            user_services += [n for n in ('ruby-glowbar', 'ruby-autobrightness') if n in marker]
    if user_services:
        notes.append(f"Restart your session services: systemctl --user daemon-reload && systemctl --user restart {' '.join(user_services)}")


if __name__ == '__main__':
    try:
        main()
    except (RuntimeError, subprocess.CalledProcessError) as e:
        sys.exit(f'Error: {e}')
