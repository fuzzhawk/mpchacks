#!/usr/bin/env python3
"""
mpcimg.py - inspect, verify and build MPC1000 OS images.

The bootblock accepts an OS image only if it passes the check implemented at
0xA00019A8-0xA00019E4 in the JJOS 3.16 bootblock:

    memcmp(header, "MPC1000", 7) == 0
    crc = crc32_update(0xFFFFFFFF, header,        16)         # +0x00..+0x0F
    crc = crc32_update(crc,        "\0\0\0\0",     4)         # +0x10 field zeroed
    crc = crc32_update(crc,        header + 20, size - 20)    # +0x14..end
    header.crc32 == ~crc

`~crc` after a 0xFFFFFFFF-seeded run is exactly the standard CRC-32 final
value, so this is plain CRC-32 (poly 0x04C11DB7, reflected) over the whole
image with the checksum field zeroed.  Verified against mpc1000_jv316.bin.

Usage:
    mpcimg.py info    <image.bin>
    mpcimg.py verify  <image.bin>
    mpcimg.py fix     <image.bin> [-o out.bin]      # recompute size + crc
    mpcimg.py build   <payload.bin> -o out.bin [--version 3.16] [--load 0xa0010030]
    mpcimg.py extract <full_flash.bin> -o os.bin    # split a 0xB74D8-style dump
"""

import argparse
import datetime
import struct
import sys
import zlib

MAGIC = b'MPC1000\x00'
HDR_LEN = 0x30
CRC_OFF = 0x10

# Flash geometry, from the RAM-resident erase routine at 0xA0008884/0xA0008924:
# AMD/Spansion command set, 16-bit bus, uniform 64 KB sectors; the updater
# erases sectors 1..13 and leaves sector 0 (the bootblock) alone.
SECTOR = 0x10000
OS_FLASH_OFF = 0x10000          # sector 1
OS_SECTORS = 13
OS_MAX_LEN = OS_SECTORS * SECTOR   # 0xD0000 = 851968 bytes


class Header:
    """The 0x30-byte image header that lives at the start of the OS image."""

    def __init__(self, buf):
        self.magic = bytes(buf[0:8])
        self.major, self.minor = buf[8], buf[9]
        self.build = struct.unpack_from('<H', buf, 10)[0]
        self.size = struct.unpack_from('<I', buf, 12)[0]
        self.crc32 = struct.unpack_from('<I', buf, 16)[0]
        self.load = struct.unpack_from('<I', buf, 20)[0]
        self.year = struct.unpack_from('<H', buf, 32)[0]
        self.month, self.day = buf[34], buf[35]

    def version(self):
        v = f'{self.major}.{self.minor:02d}'
        return v + (f'.{self.build:04d}' if self.build else '')

    def date(self):
        try:
            return datetime.date(self.year, self.month, self.day).isoformat()
        except ValueError:
            return f'{self.year:04d}-{self.month:02d}-{self.day:02d} (invalid)'

    def dump(self):
        print(f'  +0x00 magic     {self.magic!r}'
              f'{"" if self.magic.startswith(b"MPC1000") else "   <-- BAD"}')
        print(f'  +0x08 version   {self.version()}  '
              f'(major={self.major} minor={self.minor} build={self.build})')
        print(f'  +0x0c size      0x{self.size:x} ({self.size} bytes)')
        print(f'  +0x10 crc32     0x{self.crc32:08x}')
        print(f'  +0x14 load addr 0x{self.load:08x}')
        print(f'  +0x20 date      {self.date()}')


def compute_crc(img, size=None):
    """CRC-32 over the image with the 4-byte checksum field zeroed."""
    size = size if size is not None else len(img)
    t = bytearray(img[:size])
    t[CRC_OFF:CRC_OFF + 4] = b'\0\0\0\0'
    return zlib.crc32(bytes(t)) & 0xFFFFFFFF


def verify(img, verbose=True):
    ok = True
    h = Header(img)
    if verbose:
        h.dump()
    if not h.magic.startswith(b'MPC1000'):
        print('  FAIL: magic is not "MPC1000"')
        ok = False
    if h.size != len(img):
        print(f'  WARN: size field 0x{h.size:x} != actual length 0x{len(img):x}')
        if h.size > len(img):
            print('  FAIL: size field runs past end of file')
            return False
        ok = False
    if h.size > OS_MAX_LEN:
        print(f'  FAIL: image is larger than the {OS_SECTORS} flash sectors '
              f'the updater erases (max 0x{OS_MAX_LEN:x})')
        ok = False
    got = compute_crc(img, h.size)
    if got == h.crc32:
        if verbose:
            print(f'  crc32 OK (0x{got:08x})')
    else:
        print(f'  FAIL: crc32 is 0x{got:08x}, header says 0x{h.crc32:08x}')
        ok = False
    return ok


def fix(img):
    out = bytearray(img)
    struct.pack_into('<I', out, 12, len(out))
    struct.pack_into('<I', out, CRC_OFF, 0)
    struct.pack_into('<I', out, CRC_OFF, compute_crc(out))
    return bytes(out)


def build(payload, version='1.00', load=0xA0010030, date=None):
    major, _, minor = version.partition('.')
    hdr = bytearray(HDR_LEN)
    hdr[0:8] = MAGIC
    hdr[8] = int(major) & 0xFF
    hdr[9] = int(minor or 0) & 0xFF
    struct.pack_into('<H', hdr, 10, 0)
    struct.pack_into('<I', hdr, 20, load)
    d = date or datetime.date.today()
    struct.pack_into('<H', hdr, 32, d.year)
    hdr[34], hdr[35] = d.month, d.day
    return fix(bytes(hdr) + payload)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('cmd', choices=['info', 'verify', 'fix', 'build', 'extract'])
    ap.add_argument('file')
    ap.add_argument('-o', '--out')
    ap.add_argument('--version', default='1.00')
    ap.add_argument('--load', default='0xa0010030')
    a = ap.parse_args()

    data = open(a.file, 'rb').read()

    if a.cmd == 'extract':
        img = data[OS_FLASH_OFF:]
        h = Header(img)
        img = img[:h.size] if 0 < h.size <= len(img) else img
        open(a.out or 'os.bin', 'wb').write(img)
        print(f'wrote {len(img)} bytes to {a.out or "os.bin"}')
        return 0

    if a.cmd == 'build':
        img = build(data, a.version, int(a.load, 0))
        open(a.out, 'wb').write(img)
        print(f'wrote {len(img)} bytes to {a.out}')
        Header(img).dump()
        return 0

    if a.cmd == 'fix':
        img = fix(data)
        open(a.out or a.file, 'wb').write(img)
        print(f'wrote {len(img)} bytes to {a.out or a.file}')
        Header(img).dump()
        return 0

    # info / verify -- accept either a bare OS image or a full flash dump
    img = data
    if data[:7] != b'MPC1000' and len(data) > OS_FLASH_OFF and \
            data[OS_FLASH_OFF:OS_FLASH_OFF + 7] == b'MPC1000':
        print(f'(full flash dump: bootblock at 0x0, OS image at 0x{OS_FLASH_OFF:x})')
        img = data[OS_FLASH_OFF:]
    ok = verify(img)
    print('\nRESULT:', 'valid' if ok else 'INVALID')
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
