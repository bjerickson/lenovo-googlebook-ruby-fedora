"""Fedora installer, kernel updates and Ruby desktop services: logic that runs without hardware."""
import importlib.util
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from lapis.common import ROOT, read_json, write_all
from lapis.gpt import read_gpt
from tools import install_fedora_ruby as installer
from tools import kernel_update_fedora as ku


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def ruby_disk():
    size = read_json(ROOT / 'assets/ruby-512gb.json')['disk_bytes']
    primary, secondary = installer.new_gpt(size)
    with tempfile.TemporaryFile() as disk:   # sparse: only the two table regions hold data
        disk.truncate(size)
        disk.seek(0); disk.write(primary)
        disk.seek(size - len(secondary)); disk.write(secondary)
        disk.flush()
        return read_gpt(disk, size), size


class InstallerTests(unittest.TestCase):
    def test_new_gpt_keeps_firmware_partitions_at_factory_positions(self):
        gpt, size = ruby_disk()
        factory = {p['name']: p for p in read_json(ROOT / 'assets/ruby-512gb.json')['partitions']}
        parts = {p['name']: p for p in gpt.partitions()}
        self.assertEqual(set(parts), {'userdata', *installer.KEEP})
        for name in installer.KEEP:
            self.assertEqual((parts[name]['start_lba'], parts[name]['size'], parts[name]['type_guid']),
                             (factory[name]['start_lba'], factory[name]['size'], factory[name]['type_guid']), name)
        root = parts['userdata']
        self.assertEqual(root['start_lba'], factory['userdata']['start_lba'])
        self.assertEqual(root['end_lba'], size // 512 - 34)          # grows to the end of the disk

    def test_slot_a_is_the_only_bootable_slot(self):
        gpt, _ = ruby_disk()
        attrs = {p['name']: p['attributes'] for p in gpt.partitions()}
        self.assertEqual(attrs['vbmeta_a'] >> 48 & 15, 15)          # highest priority
        self.assertEqual(attrs['vbmeta_a'] >> 56 & 1, 1)            # marked successful
        self.assertEqual(attrs['vbmeta_b'], 0)

    def test_new_gpt_refuses_other_disk_sizes(self):
        with self.assertRaises(RuntimeError):
            installer.new_gpt(256 * 1024**3)


class KernelUpdateTests(unittest.TestCase):
    def test_hook_only_acts_on_add_of_the_newest_kernel_and_never_fails(self):
        text = ku.HOOK_TEXT
        self.assertIn('[ "$1" = add ] || exit 0', text)
        self.assertIn('[ "$2" = "$newest" ] || exit 0', text)
        self.assertTrue(text.rstrip().endswith('exit 0'))
        target = text.replace(str(ROOT), installer.KIT)
        self.assertIn('/opt/lapis-kit/tools/kernel_update_fedora.py update', target)
        self.assertNotIn(str(ROOT), target)

    def test_failed_write_restores_every_attempted_region(self):
        with tempfile.TemporaryDirectory() as tmp:
            disk = Path(tmp) / 'disk'
            original = bytes(range(256)) * 8
            disk.write_bytes(original)
            regions = [(0, b'A' * 512, original[:512]), (512, b'B' * 512, original[512:1024])]
            real, calls = write_all, []

            def fail_second(fd, offset, data):
                calls.append(offset)
                if len(calls) == 2:
                    os.pwrite(fd, data[:100], offset)
                    raise OSError('injected partial write')
                return real(fd, offset, data)
            with mock.patch.object(ku, 'write_all', side_effect=fail_second):
                with self.assertRaises(OSError):
                    ku.write_regions(str(disk), regions)
            self.assertEqual(disk.read_bytes(), original)


class DiskWriteTests(unittest.TestCase):
    def test_short_pwrites_are_completed(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'f'; path.write_bytes(bytes(32))
            real = os.pwrite
            fd = os.open(path, os.O_RDWR)
            try:
                with mock.patch('os.pwrite', side_effect=lambda f, d, o: real(f, bytes(d[:3]), o)):
                    write_all(fd, 4, b'abcdefghij')
            finally:
                os.close(fd)
            self.assertEqual(path.read_bytes()[4:14], b'abcdefghij')


class ServiceLogicTests(unittest.TestCase):
    def test_glowbar_reads_the_plasma_accent(self):
        glowbar = load('assets/installed/glowbar/ruby-glowbar.py', 'glowbar')
        self.assertEqual(glowbar.kde_accent('[General]\nAccentColor=61,174,233\n'), (61, 174, 233))
        self.assertIsNone(glowbar.kde_accent('[Colors:View]\nAccentColor=1,2,3\n'))
        self.assertEqual(glowbar.saturate((61, 174, 233)), (0, 168, 255))

    def test_autobrightness_follows_light_and_keeps_manual_changes(self):
        ab = load('assets/installed/autobrightness/ruby-autobrightness.py', 'autobrightness')
        ctl, cur, top = ab.Controller(), 500, 1000
        for _ in range(40):
            value = ctl.step(1, cur, top)
            if value is not None:
                self.assertLessEqual(abs(value - cur), ab.STEP * top + 1)   # gradual, never a jump
                cur = value
        self.assertAlmostEqual(cur / top, ab.curve(1), delta=ab.DEADBAND)
        cur = 600                                                        # user raises it
        self.assertIsNone(ctl.step(1, cur, top))
        for _ in range(10):
            self.assertIsNone(ctl.step(1, cur, top))                     # and it stays there

    def test_speaker_calibration_round_trips_through_the_saved_copy(self):
        cal = load('assets/installed/ruby-speaker-calibration.py', 'calibration')
        with tempfile.TemporaryDirectory() as tmp:
            live, saved = Path(tmp) / 'vpd', Path(tmp) / 'saved'
            live.mkdir()
            (live / 'dsm_calib_register_array').write_text('72' + '00' * 15 + '\n')
            for i in range(4):
                (live / f'dsm_calib_value_{i}').write_text((bytes([i]) + (4 << 27).to_bytes(4, 'big') + bytes(16)).hex())
            with mock.patch.object(cal, 'LIVE_VPD', live), mock.patch('builtins.print'):
                cal.save(saved)
            with mock.patch.object(cal, 'LIVE_VPD', Path(tmp) / 'absent'), mock.patch.object(cal, 'SAVED_VPD', saved), \
                 mock.patch('builtins.print'):
                self.assertEqual(cal.source(), saved)
                self.assertEqual(len(cal.payload(saved)), 1 + 16 + 21 * 4)


class DryRunAndBackupTests(unittest.TestCase):
    def factory_disk(self, tmp):
        """A sparse 512 GB disk file carrying the factory layout (all 30 partitions)."""
        import uuid as _uuid
        from lapis.gpt import ENTRY, tables
        profile = read_json(ROOT / 'assets/ruby-512gb.json')
        size = profile['disk_bytes']
        entries = bytearray(128 * 128)
        for part in profile['partitions']:
            i = part['index'] - 1
            end = part['start_lba'] + max(part['size'] // 512, 1) - 1
            entries[i * 128:(i + 1) * 128] = ENTRY.pack(_uuid.UUID(part['type_guid']).bytes_le, _uuid.uuid4().bytes_le,
                                                        part['start_lba'], end, 0, part['name'].encode('utf-16-le'))
        header = [b'EFI PART', 0x10000, 92, 0, 0, 1, size // 512 - 1, 34, size // 512 - 34, _uuid.uuid4().bytes_le, 2, 128, 128, 0]
        primary, secondary = tables(header, entries, bytes(510) + b'\x55\xaa')
        disk = Path(tmp) / 'disk.img'
        with disk.open('wb') as f:
            f.truncate(size); f.seek(0); f.write(primary); f.seek(size - len(secondary)); f.write(secondary)
            parts = {p['name']: p for p in profile['partitions']}
            f.seek(parts['boot_a']['start_lba'] * 512); f.write(b'FACTORY-BOOT-A')
        return disk, size

    def test_dry_run_shows_both_layouts_and_writes_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            disk, size = self.factory_disk(tmp)
            before = sha_of(disk)
            primary, secondary = installer.new_gpt(size)
            with mock.patch('builtins.print') as out:
                installer.dry_run(str(disk), size, primary, secondary, network=True)
            text = '\n'.join(' '.join(map(str, c.args)) for c in out.call_args_list)
            self.assertIn('Current partitions', text)
            self.assertIn('ota_recovery_a', text)          # a factory partition that will go
            self.assertIn('Dry run: nothing was written', text)
            self.assertEqual(sha_of(disk), before)

    def test_backup_saves_small_factory_partitions_and_verifies(self):
        with tempfile.TemporaryDirectory() as tmp:
            disk, size = self.factory_disk(tmp)
            backup = installer.Backup.__new__(installer.Backup)
            backup.dir = Path(tmp) / 'backup'; backup.dir.mkdir(); backup.records = {}
            with mock.patch('builtins.print'):
                backup.factory(str(disk), size)
                backup.finish()
            names = set(backup.records)
            self.assertIn('gpt-head.bin', names)
            self.assertIn('partitions/13-boot_a.img', names)
            self.assertFalse(any('userdata' in n or 'super' in n for n in names))
            self.assertTrue((backup.dir / 'partitions/13-boot_a.img').read_bytes().startswith(b'FACTORY-BOOT-A'))
            self.assertEqual(json_of(backup.dir / 'manifest.json'), backup.records)
            (backup.dir / 'gpt-head.bin').write_bytes(b'tampered')
            with self.assertRaises(RuntimeError), mock.patch('builtins.print'):
                backup.finish()

    def test_backup_refuses_ram_and_the_disk_being_erased(self):
        def fake(answers):
            def out(argv):
                key = (argv[0], argv[2]) if argv[0] == 'findmnt' else argv[0]
                return answers[key]
            return out
        with tempfile.TemporaryDirectory() as tmp:
            cases = {
                'tmpfs': {('findmnt', 'FSTYPE'): 'tmpfs', ('findmnt', 'SOURCE'): 'tmpfs', 'lsblk': ''},
                'same disk': {('findmnt', 'FSTYPE'): 'ext4', ('findmnt', 'SOURCE'): '/dev/nvme0n1p1',
                              'lsblk': '/dev/nvme0n1p1\n/dev/nvme0n1'},
            }
            for label, answers in cases.items():
                with self.subTest(label), mock.patch.object(installer, 'output', side_effect=fake(answers)):
                    with self.assertRaises(RuntimeError):
                        installer.Backup(tmp, '/dev/nvme0n1')
            ok = {('findmnt', 'FSTYPE'): 'ext4', ('findmnt', 'SOURCE'): '/dev/sdb1', 'lsblk': '/dev/sdb1\n/dev/sdb'}
            with mock.patch.object(installer, 'output', side_effect=fake(ok)), \
                 mock.patch.object(installer.shutil, 'disk_usage', return_value=mock.Mock(free=10 * 1024**3)):
                backup = installer.Backup(tmp, '/dev/nvme0n1')
            self.assertTrue(backup.dir.is_dir() and backup.dir.parent == Path(tmp).resolve())

    def test_installer_uses_the_fedora_image_on_the_usb(self):
        from tools import fedora
        from lapis.common import FEDORA_IMAGE_URL, FEDORA_CHECKSUM_URL, FEDORA_KEY
        with tempfile.TemporaryDirectory() as tmp:
            cache, work = Path(tmp) / 'cache', Path(tmp) / 'work'
            cache.mkdir(); work.mkdir()
            image = cache / FEDORA_IMAGE_URL.rsplit('/', 1)[1]
            image.write_bytes(b'pretend image')
            from lapis.common import sha256 as digest
            (cache / FEDORA_CHECKSUM_URL.rsplit('/', 1)[1]).write_text(f'SHA256 ({image.name}) = {digest(image)}\n')
            signed = mock.Mock(returncode=0, stdout=f'[GNUPG:] VALIDSIG {FEDORA_KEY} x')
            with mock.patch.object(fedora, 'FEDORA_CACHE', cache), \
                 mock.patch.object(fedora, 'FEDORA_IMAGE_SHA256', digest(image)), \
                 mock.patch.object(fedora, 'run'), \
                 mock.patch.object(fedora, 'output', return_value=f'fpr:::::::::{FEDORA_KEY}:'), \
                 mock.patch.object(fedora.subprocess, 'run', return_value=signed), \
                 mock.patch.object(fedora, 'fetch', side_effect=AssertionError('must not download')), \
                 mock.patch('builtins.print'):
                self.assertEqual(fedora.verified_image(work), image)
                image.write_bytes(b'corrupted')           # a bad copy falls back to downloading
                (work / 'again').mkdir()
                with self.assertRaises(AssertionError):     # reached fetch(): it would download
                    fedora.verified_image(work / 'again')


def sha_of(path):
    """Fingerprint of a sparse disk file: both table regions and the first MiB of every partition slot."""
    import hashlib
    size = Path(path).stat().st_size
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        h.update(f.read(34 * 512))
        f.seek(size - 33 * 512); h.update(f.read())
        for part in read_json(ROOT / 'assets/ruby-512gb.json')['partitions']:
            f.seek(part['start_lba'] * 512); h.update(f.read(1 << 20))
    return h.hexdigest()


def json_of(path):
    import json
    return json.loads(Path(path).read_text())


if __name__ == '__main__':
    unittest.main()
