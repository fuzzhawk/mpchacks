#!/usr/bin/env python3
"""
MPC1000 JJOS binary analysis utilities.
Architecture: Renesas SH7727 (SH3-DSP), little-endian, 16-bit instructions.
Run: python3 analyze.py mpc1000_jv316.bin
"""

import sys
import re
from collections import Counter
import math

def load(path):
    with open(path, 'rb') as f:
        return f.read()

def entropy(block):
    if not block: return 0.0
    c = Counter(block)
    return -sum((v/len(block))*math.log2(v/len(block)) for v in c.values())

def find_functions(data, start=0x800, end=None):
    """Find SH3 LE function entry points (STS.L PR,@-R15 = bytes 22 4F)."""
    if end is None: end = len(data)
    return [i for i in range(start, end, 2) if data[i] == 0x22 and data[i+1] == 0x4f]

def find_strings(data, min_len=6):
    """Extract printable ASCII strings with their offsets."""
    results = []
    for m in re.finditer(rb'[\x20-\x7e]{' + str(min_len).encode() + rb',}', data):
        results.append((m.start(), m.group().decode('ascii')))
    return results

def sh_disasm_le(w):
    """Basic SH3 little-endian disassembler."""
    n = (w >> 8) & 0xf
    m = (w >> 4) & 0xf
    d8 = w & 0xff
    imm8 = d8 if d8 < 128 else d8 - 256

    if (w & 0xf000) == 0xe000: return f"MOV #{imm8},R{n}"
    if (w & 0xf000) == 0xd000: return f"MOV.L @(PC+{(d8*4)+4}),R{n}"
    if (w & 0xf000) == 0x9000: return f"MOV.W @(PC+{(d8*2)+4}),R{n}"
    if (w & 0xf000) == 0xa000:
        d = w & 0xfff
        if d >= 0x800: d -= 0x1000
        return f"BRA {d*2+4}"
    if (w & 0xf000) == 0xb000:
        d = w & 0xfff
        if d >= 0x800: d -= 0x1000
        return f"BSR {d*2+4}"
    if (w & 0xff00) == 0x8900: return f"BT {(imm8*2)+4}"
    if (w & 0xff00) == 0x8b00: return f"BF {(imm8*2)+4}"
    if (w & 0xf00f) == 0x6003: return f"MOV R{m},R{n}"
    if (w & 0xf00f) == 0x6000: return f"MOV.B @R{m},R{n}"
    if (w & 0xf00f) == 0x6001: return f"MOV.W @R{m},R{n}"
    if (w & 0xf00f) == 0x6002: return f"MOV.L @R{m},R{n}"
    if (w & 0xf00f) == 0x2006: return f"MOV.L R{m},@R{n}"
    if (w & 0xf00f) == 0x2002: return f"MOV.L R{m},@-R{n}"
    if (w & 0xf0ff) == 0x4022: return f"STS.L PR,@-R{n}"
    if (w & 0xf0ff) == 0x4026: return f"LDS.L @R{n}+,PR"
    if (w & 0xf0ff) == 0x400b: return f"JSR @R{n}"
    if (w & 0xf0ff) == 0x402b: return f"JMP @R{n}"
    if w == 0x000b: return "RTS"
    if w == 0x0009: return "NOP"
    if w == 0x002b: return "RTE"
    if w == 0x0008: return "CLRT"
    if w == 0x0018: return "SETT"
    if w == 0x0028: return "CLRMAC"
    if w == 0x0038: return "LDTLB"
    if w == 0x0048: return "CLRS"
    return f"?? ({w:04x})"

def disassemble(data, offset, count=32, base=0x8c000000):
    """Disassemble count SH3 LE instructions starting at offset."""
    lines = []
    for i in range(offset, offset + count*2, 2):
        if i + 2 > len(data): break
        w = data[i] | (data[i+1] << 8)
        vaddr = base + i
        lines.append(f"  {vaddr:08x} ({i:06x}): {w:04x}  {sh_disasm_le(w)}")
    return '\n'.join(lines)

def section_map(data):
    """Print non-zero regions of the binary."""
    print("=== Section Map ===")
    in_sec = False
    start = 0
    for i in range(0, len(data), 256):
        nz = any(b != 0 for b in data[i:i+256])
        if nz and not in_sec:
            in_sec = True; start = i
        elif not nz and in_sec:
            in_sec = False
            print(f"  {start:06x} – {i:06x}  ({(i-start)//1024} KB)  entropy={entropy(data[start:i]):.2f}")
    if in_sec:
        print(f"  {start:06x} – {len(data):06x}  ({(len(data)-start)//1024} KB)  entropy={entropy(data[start:]):.2f}")

def find_string_xrefs(data, string_offset, base=0x8c000000):
    """Find code that references a given string offset (by its virtual address)."""
    vaddr = base + string_offset
    results = []
    # Search for the address as a 32-bit LE value in MOV.L literal pools
    target = vaddr.to_bytes(4, 'little')
    for m in re.finditer(re.escape(target), data):
        results.append(m.start())
    return results

# ── Known offsets ────────────────────────────────────────────────────────────
KNOWN = {
    'version_string':    0xa64f8,   # "JJ OS Ver.3.16 "
    'bootblock_start':   0x000800,
    'bootblock_end':     0x00a300,
    'main_os_start':     0x011500,
    'main_os_end':       0x0ac600,
    'string_table_start':0x0a6000,
    'string_table_end':  0x0b4000,
    'tap_tempo_str':     0x010da8,
    'sequence_str':      0x0a7118,
    'midi_str':          0x0a8138,
    'reverb_str':        0x0a892c,
    'patched_phrase_str':0x0b38e8,
    'pad_bank_str':      0x0b3126,
}

if __name__ == '__main__':
    path = sys.argv[1] if len(sys.argv) > 1 else 'mpc1000_jv316.bin'
    data = load(path)
    print(f"Loaded: {path} ({len(data):,} bytes)\n")

    section_map(data)
    print()

    funcs = find_functions(data)
    print(f"Function entry points: {len(funcs)}")
    print(f"  First: {hex(funcs[0])}  Last: {hex(funcs[-1])}\n")

    print("Sample disassembly at bootblock entry (0x800):")
    print(disassemble(data, 0x800, count=16))
    print()

    print("Known offsets:")
    for k, v in KNOWN.items():
        if v < len(data):
            snip = data[v:v+32]
            printable = ''.join(chr(b) if 0x20<=b<=0x7e else '.' for b in snip)
            print(f"  {k:30s} {v:06x}  {printable}")
