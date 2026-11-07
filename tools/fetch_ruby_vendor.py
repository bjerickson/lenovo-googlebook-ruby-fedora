#!/usr/bin/env python3
"""Stream vendor_a.img out of Google's Ruby factory recovery image.

The recovery zip holds one deflated disk image (~19 GB). This streams it over
HTTPS, decompresses on the fly, reads the image's GPT and the Android dynamic
partition (LP) metadata in `super`, keeps only vendor_a's extents and stops
downloading once they are complete. Needs only Python.

    python3 tools/fetch_ruby_vendor.py --output /var/tmp/vendor_a.img

Then: fsck.erofs --extract=DIR vendor_a.img (tools/install_ruby_firmware.sh does this).
"""
import argparse
from pathlib import Path
import struct
import sys
import urllib.request
import uuid
import zlib

URL = 'https://dl.google.com/device/recovery/ruby-user/16693588/recovery.zip'
MEMBER = 'android-desktop_signed_recovery_image.bin'
SECTOR = 512
LP_GEOMETRY_MAGIC = 0x616c4467
LP_HEADER_MAGIC = 0x414C5030


class Stream:
    """Sequential reader over the decompressed image."""

    def __init__(self, url):
        self.resp = urllib.request.urlopen(url)
        head = self.resp.read(30)
        sig, _, flags, method, _, _, _, _, _, nlen, elen = struct.unpack('<IHHHHHIIIHH', head)
        if sig != 0x04034b50 or method != 8:
            raise SystemExit('Unexpected recovery zip layout')
        name = self.resp.read(nlen).decode()
        self.resp.read(elen)
        if name != MEMBER:
            raise SystemExit(f'Unexpected member {name}')
        self.z = zlib.decompressobj(-15)
        self.buf = bytearray()
        self.pos = 0          # image offset of buf[0]
        self.downloaded = 0

    def _fill(self, need):
        while len(self.buf) < need:
            chunk = self.resp.read(4 << 20)
            if not chunk:
                raise SystemExit('Download ended early')
            self.downloaded += len(chunk)
            self.buf += self.z.decompress(chunk)

    def read_at(self, offset, size):
        if offset < self.pos:
            raise RuntimeError('Stream cannot seek backwards')
        self._fill(offset - self.pos + size)
        start = offset - self.pos
        data = bytes(self.buf[start:start + size])
        del self.buf[:start]          # drop everything before offset
        self.pos = offset
        return data


def gpt_super(s):
    h = s.read_at(SECTOR, 92)
    if h[:8] != b'EFI PART':
        raise SystemExit('No GPT in recovery image')
    entries_lba, count, esize = struct.unpack_from('<QII', h, 72)
    table = s.read_at(entries_lba * SECTOR, count * esize)
    for i in range(count):
        e = table[i * esize:(i + 1) * esize]
        if e[:16] == bytes(16):
            continue
        start, end = struct.unpack_from('<QQ', e, 32)
        name = e[56:128].decode('utf-16-le').rstrip('\0')
        if name == 'super':
            return start * SECTOR, (end - start + 1) * SECTOR
    raise SystemExit('No super partition in recovery image')


def lp_extents(s, base, partition):
    geo = s.read_at(base + 4096, 4096)
    magic, = struct.unpack_from('<I', geo, 0)
    if magic != LP_GEOMETRY_MAGIC:
        raise SystemExit('No LP geometry in super')
    hdr_off = base + 4096 + 2 * 4096   # primary metadata follows the two geometry copies
    hdr = s.read_at(hdr_off, 256)
    magic, major, minor, header_size = struct.unpack_from('<IHHI', hdr, 0)
    if magic != LP_HEADER_MAGIC:
        raise SystemExit('No LP metadata header in super')
    tables_size, = struct.unpack_from('<I', hdr, 44)
    desc = struct.unpack_from('<12I', hdr, 80)
    parts, extents = desc[0:3], desc[3:6]
    tables = s.read_at(hdr_off + header_size, tables_size)
    found, names = None, []
    for i in range(parts[1]):
        e = tables[parts[0] + i * parts[2]:parts[0] + (i + 1) * parts[2]]
        name = e[:36].split(b'\0')[0].decode()
        first, num = struct.unpack_from('<II', e, 40)
        names.append(name)
        if name == partition:
            found = (first, num)
    if not found:
        raise SystemExit(f'{partition} not in super metadata; found {names}')
    result = []
    for j in range(found[0], found[0] + found[1]):
        x = tables[extents[0] + j * extents[2]:extents[0] + (j + 1) * extents[2]]
        nsec, ttype, tdata, tsrc = struct.unpack_from('<QIQI', x, 0)
        if ttype != 0 or tsrc != 0:
            raise SystemExit('Unsupported extent type in super')
        result.append((tdata * SECTOR, nsec * SECTOR))
    return result


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--output', required=True, type=Path)
    p.add_argument('--partition', default='vendor_a')
    p.add_argument('--url', default=URL)
    a = p.parse_args()
    s = Stream(a.url)
    base, size = gpt_super(s)
    print(f'super at {base} ({size >> 20} MiB)', flush=True)
    ext = lp_extents(s, base, a.partition)
    total = sum(n for _, n in ext)
    print(f'{a.partition}: {len(ext)} extents, {total >> 20} MiB', flush=True)
    # Extents must be read in disk order; write each at its logical position.
    logical, off = [], 0
    for phys, n in ext:
        logical.append((phys, n, off)); off += n
    with a.output.open('wb') as f:
        f.truncate(total)
        for phys, n, lo in sorted(logical):
            done = 0
            while done < n:
                step = min(64 << 20, n - done)
                f.seek(lo + done); f.write(s.read_at(base + phys + done, step))
                done += step
                print(f'\r  {a.partition}: {(lo + done) >> 20} MiB written, {s.downloaded >> 20} MiB downloaded',
                      end='', flush=True)
    print(f'\nWrote {a.output}; downloaded {s.downloaded >> 20} MiB of the 7.8 GB zip')


if __name__ == '__main__':
    main()
