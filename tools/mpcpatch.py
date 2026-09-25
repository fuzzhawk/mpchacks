#!/usr/bin/env python3
"""
mpcpatch.py - apply verified byte patches to an MPC1000 flash image.

Every patch states the bytes it expects to find.  If the image does not match,
nothing is written.  That check is the whole point: a patch written against
JJOS 3.16 must not be applied blindly to a different OS version, because flash
offsets move between builds and a wrong write produces an image that passes
CRC and then crashes the machine.

The bootblock (flash 0x000000-0x00FFFF) is refused by default.  It is the only
thing that can reflash the machine, so a bad write there is unrecoverable -
there is no second bootloader and no JTAG header exposed.  Overriding the
guard needs --allow-bootblock and is almost never the right thing to do.

Patch file format (see patches/*.patch):

    # comment
    [patch-id]
    desc = one line describing the change
    @0a64f8
    - "JJ OS Ver.3.16 "              ; expected current bytes
    + "QFADER OS  0.01"              ; replacement, must be the same length
    @01131c
    - 00 00 00 00
    + 09 00 0b 00

Values are either a double-quoted ASCII string or whitespace-separated hex
bytes.  `-` and `+` must be the same length: this tool does not move code, so
it cannot change the size of anything.

Usage:
    mpcpatch.py check <image.bin> <patch...>
    mpcpatch.py apply <image.bin> <patch...> -o OUT.BIN
    mpcpatch.py revert <image.bin> <patch...> -o OUT.BIN
"""

import argparse
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mpcimg

BOOTBLOCK_END = 0x010000


class PatchError(Exception):
    pass


class Hunk:
    def __init__(self, off, old, new, lineno):
        self.off, self.old, self.new, self.lineno = off, old, new, lineno
        if len(old) != len(new):
            raise PatchError(
                f'line {lineno}: - is {len(old)} bytes but + is {len(new)}; '
                'mpcpatch cannot resize anything')


class Patch:
    def __init__(self, pid):
        self.id = pid
        self.desc = ''
        self.hunks = []


def _bytes(spec, lineno):
    spec = spec.split(';')[0].strip()
    m = re.fullmatch(r'"(.*)"', spec)
    if m:
        return m.group(1).encode('latin1')
    spec = spec.replace(',', ' ')
    try:
        return bytes(int(t, 16) for t in spec.split())
    except ValueError:
        raise PatchError(f'line {lineno}: cannot parse bytes from {spec!r}')


def parse(path):
    patches, cur, off, old = [], None, None, None
    for n, raw in enumerate(open(path), 1):
        line = raw.strip()
        if not line or line.startswith('#'):
            continue
        m = re.fullmatch(r'\[(.+)\]', line)
        if m:
            cur = Patch(m.group(1))
            patches.append(cur)
            off = old = None
            continue
        if cur is None:
            raise PatchError(f'line {n}: content before any [patch-id]')
        if line.startswith('desc'):
            cur.desc = line.split('=', 1)[1].strip()
        elif line.startswith('@'):
            off = int(line[1:].split(';')[0].strip(), 16)
            old = None
        elif line.startswith('-'):
            old = _bytes(line[1:], n)
        elif line.startswith('+'):
            if off is None or old is None:
                raise PatchError(f'line {n}: + without a preceding @ and -')
            cur.hunks.append(Hunk(off, old, _bytes(line[1:], n), n))
            old = None
        else:
            raise PatchError(f'line {n}: unrecognised line {line!r}')
    return patches


def status(data, h):
    cur = data[h.off:h.off + len(h.old)]
    if cur == h.old:
        return 'unapplied'
    if cur == h.new:
        return 'applied'
    return 'MISMATCH'


def run(data, patches, revert, allow_bb):
    out = bytearray(data)
    changed = 0
    for p in patches:
        print(f'[{p.id}]' + (f'  {p.desc}' if p.desc else ''))
        for h in p.hunks:
            want, put = (h.new, h.old) if revert else (h.old, h.new)
            st = status(data, h)
            if h.off < BOOTBLOCK_END and not allow_bb:
                raise PatchError(
                    f'  @{h.off:06x} is inside the bootblock. Refusing. '
                    'A bad bootblock write cannot be recovered on this machine. '
                    'Use --allow-bootblock only if you truly mean it.')
            if h.off + len(h.old) > len(out):
                raise PatchError(f'  @{h.off:06x} runs past the end of the image')
            if out[h.off:h.off + len(want)] != want:
                if st == ('applied' if not revert else 'unapplied'):
                    print(f'  @{h.off:06x} already {st}, skipping')
                    continue
                raise PatchError(
                    f'  @{h.off:06x} expected {want.hex(" ")}\n'
                    f'                 found    {bytes(out[h.off:h.off+len(want)]).hex(" ")}\n'
                    '  This patch was not written for this image. Nothing written.')
            out[h.off:h.off + len(put)] = put
            print(f'  @{h.off:06x} {len(put):4d} B  ok')
            changed += 1
    return bytes(out), changed


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('cmd', choices=['check', 'apply', 'revert'])
    ap.add_argument('image')
    ap.add_argument('patches', nargs='+')
    ap.add_argument('-o', '--out')
    ap.add_argument('--allow-bootblock', action='store_true')
    a = ap.parse_args()

    data = open(a.image, 'rb').read()
    try:
        patches = [p for f in a.patches for p in parse(f)]
    except PatchError as e:
        print(f'error: {e}', file=sys.stderr)
        return 2

    if a.cmd == 'check':
        bad = False
        for p in patches:
            print(f'[{p.id}]' + (f'  {p.desc}' if p.desc else ''))
            for h in p.hunks:
                st = status(data, h)
                bad |= st == 'MISMATCH'
                print(f'  @{h.off:06x} {len(h.old):4d} B  {st}')
        return 1 if bad else 0

    if not a.out:
        print('error: apply/revert need -o OUT.BIN', file=sys.stderr)
        return 2
    try:
        out, n = run(data, patches, a.cmd == 'revert', a.allow_bootblock)
    except PatchError as e:
        print(f'error:\n{e}', file=sys.stderr)
        return 2

    # the patched OS image needs its header size + CRC-32 recomputed or the
    # bootblock will reject it
    img = mpcimg.fix(out[mpcimg.OS_FLASH_OFF:])
    if len(img) > mpcimg.OS_MAX_LEN:
        print('error: image exceeds the 13 flash sectors the updater erases',
              file=sys.stderr)
        return 2
    open(a.out, 'wb').write(img)
    print(f'\n{n} hunk(s) written')
    print(f'wrote OS image: {a.out} ({len(img)} bytes)')
    mpcimg.Header(img).dump()
    print('\nFlash it by copying to a CF card as a *.BIN file and holding the '
          'OS-update keys at power-on.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
