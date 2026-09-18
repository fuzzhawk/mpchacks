#!/usr/bin/env python3
"""
List firmware strings together with the code that loads their address.

A string is "referenced" when its address appears in a PC-relative literal
pool, which is how SH-3 code materialises any 32-bit constant.  Printing the
referencing instruction's offset gives a direct jumping-off point for reading
the code that uses the string.

The address to look for is the string's *run-time* address: the OS copies its
static data out of flash into SDRAM (and the DSP overlay into on-chip X/Y RAM)
before running, so a flash address finds nothing.  sh3.runtime_addr() applies
that mapping.  The second column printed below is the run-time address.

An `xref[0]` does not mean the string is unused.  Many UI strings sit in
fixed-width tables that the code indexes as `base + i * width`, so only the
table base appears as a literal.  When a string shows no reference, look at
the addresses just before it.
"""
import re
import sys
import struct
import collections

sys.path.insert(0, __file__.rsplit('/', 1)[0])
import sh3


def string_table(data, min_len=4):
    out = []
    for m in re.finditer(rb'[\x20-\x7e]{%d,}' % min_len, data):
        out.append((m.start(), m.group().decode('ascii')))
    return out


def literal_sites(data, regions):
    """run-time address -> [offsets of instructions that load it]"""
    refs = collections.defaultdict(list)
    for start, end in regions:
        for off in range(start, min(end, len(data) - 1), 2):
            lit = sh3.pcrel(data, off)
            if lit:
                refs[lit[1]].append(off)
    return refs


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else 'mpc1000_jv316.bin'
    pat = sys.argv[2] if len(sys.argv) > 2 else None
    data = sh3.load(path)
    refs = literal_sites(data, [(0x0, 0xA300), (0x10000, 0xAD000)])
    for off, s in string_table(data):
        if pat and pat.lower() not in s.lower():
            continue
        # main-OS strings are relocated to SDRAM at start-up, so look up the
        # run-time address, not the flash address
        sites = refs.get(sh3.runtime_addr(off), [])
        tag = ' '.join(f'{x:06x}' for x in sites[:6]) if sites else '-'
        rt = sh3.runtime_addr(off)
        print(f'{off:06x} {rt:08x} xref[{len(sites)}]: {tag:<45s} {s!r}')


if __name__ == '__main__':
    main()
