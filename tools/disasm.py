#!/usr/bin/env python3
"""
disasm.py - annotated SH-3 disassembly of the MPC1000 firmware.

Annotations resolve PC-relative literals, name SH-3 on-chip registers, and
inline any string a constant points at, which is what makes this readable
without a full RE database.

Usage:
    disasm.py <image.bin> <offset> [count]
    disasm.py <image.bin> --func <offset>      # stop at the function's rts
"""
import argparse
import sys

sys.path.insert(0, __file__.rsplit('/', 1)[0])
import sh3


def cstr(data, off, maxlen=40):
    out = []
    for b in data[off:off + maxlen]:
        if b == 0:
            break
        if not 0x20 <= b <= 0x7E:
            return None
        out.append(chr(b))
    return ''.join(out) if len(out) >= 3 else None


def annotate(data, off):
    lit = sh3.pcrel(data, off)
    if not lit:
        return ''
    pool, val, width = lit
    note = f'   ; = 0x{val:08x}'
    name = sh3.describe_addr(val)
    if name:
        note += f'  {name}'
    fo = sh3.flash_off(val)
    if fo is not None:
        if not sh3.in_image(data, val):
            note += f'  [flash 0x{fo:06x}]'
        s = cstr(data, fo)
        if s:
            note += f'  "{s}"'
    elif sh3.BSS[0] <= val < sh3.BSS[1]:
        note += '  bss'
    return note


def line(data, off):
    w = sh3.u16(data, off)
    return (f'{sh3.va(off):08x} {off:06x}:  {w:04x}  '
            f'{sh3.text(data, off):<30s}{annotate(data, off)}')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('image')
    ap.add_argument('offset')
    ap.add_argument('count', nargs='?', default='40')
    ap.add_argument('--func', action='store_true',
                    help='disassemble until the function returns')
    a = ap.parse_args()

    data = sh3.load(a.image)
    off = int(a.offset, 0)
    if off >= sh3.BASE_P1:              # accept a virtual address too
        off = sh3.off_of(off)
    off &= ~1                           # instructions are 2-byte aligned

    if a.func:
        n = 0
        while off < len(data) - 1 and n < 4096:
            print(line(data, off))
            w = sh3.u16(data, off)
            off += 2
            n += 1
            if w in (0x000B, 0x002B):    # rts / rte -- one delay slot follows
                print(line(data, off))
                break
        return

    for i in range(int(a.count, 0)):
        if off + 2 > len(data):
            break
        print(line(data, off))
        off += 2


if __name__ == '__main__':
    main()
