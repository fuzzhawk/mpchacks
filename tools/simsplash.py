#!/usr/bin/env python3
"""
simsplash.py - decode a splash BMP exactly the way JJOS does, and print it.

This mirrors the parser at flash 0x0162BC in JJOS 3.16 instruction for
instruction, so a file that renders correctly here is one the firmware will
render correctly too.  It is the only check available without the hardware,
and it has caught more than one plausible-looking BMP that the firmware would
have drawn as noise.

Usage:
    simsplash.py MPC1000.BMP
"""
import sys

LCD_W, LCD_H = 240, 64


def decode(buf):
    # the firmware reads each of these as a 16-bit little-endian value and
    # ignores the upper half of the 32-bit BMP fields
    u16 = lambda o: buf[o] | (buf[o + 1] << 8)
    offbits = u16(10)
    width = u16(18)
    height = u16(22)
    size_image = u16(34)

    stride = size_image // height if height else 0     # signed divide helper
    stride = max(stride, 32)                           # floor of 32 bytes
    width = min(width, LCD_W)
    height = min(height, LCD_H)

    info = dict(offbits=offbits, width=width, height=height,
                size_image=size_image, stride=stride)

    # the destination walks from the bottom row upward, which consumes a
    # normal bottom-up BMP in the right order
    fb = [[0] * width for _ in range(height)]
    src = offbits
    for row in range(height - 1, -1, -1):
        x = 0
        for b in range(stride):
            if src >= len(buf):
                break
            byte = buf[src]
            src += 1
            for bit in range(8):
                if x >= width:
                    break
                set_ = (byte >> (7 - bit)) & 1
                fb[row][x] = 0 if set_ else 15    # set bit -> 0, clear -> 15
                x += 1
    return info, fb


def main():
    buf = open(sys.argv[1], 'rb').read()
    info, fb = decode(buf)
    print(f'as the firmware sees it: {info}')
    bad = []
    if info['width'] != LCD_W:
        bad.append(f"width {info['width']} != {LCD_W}")
    if info['height'] != LCD_H:
        bad.append(f"height {info['height']} != {LCD_H}")
    if info['stride'] * 8 < info['width']:
        bad.append(f"stride {info['stride']} too small for width {info['width']}")
    need = info['offbits'] + info['stride'] * info['height']
    if len(buf) < need:
        bad.append(f'file is {len(buf)} bytes, parser will read {need}')
    print('+' + '-' * info['width'] + '+')
    for row in fb:
        print('|' + ''.join('#' if v else ' ' for v in row) + '|')
    print('+' + '-' * info['width'] + '+')
    if bad:
        print('PROBLEMS: ' + '; '.join(bad))
        return 1
    print('OK: the firmware parser will read this as a full 240x64 image')
    return 0


if __name__ == '__main__':
    sys.exit(main())
