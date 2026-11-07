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


if __name__ == '__main__':
    unittest.main()
