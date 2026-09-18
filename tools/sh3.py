"""
sh3.py - SuperH SH-3 / SH3-DSP analysis primitives for the MPC1000 firmware.

The firmware is a flat little-endian SH-3 image that the CPU executes in place
from P2 (uncached) space: the reset vector at file offset 0 jumps to 0xA0000800,
so file offset N corresponds to virtual address 0xA0000000 + N.

Everything here works off that single mapping.
"""

import struct
from dataclasses import dataclass, field

BASE = 0xA0000000          # P2 (uncached) view of the flash
BASE_P1 = 0x80000000       # P1 (cached) view of the same flash

try:
    import capstone as _cs
    _MD = _cs.Cs(_cs.CS_ARCH_SH, _cs.CS_MODE_SH4A | _cs.CS_MODE_LITTLE_ENDIAN)
    _MD.detail = False
except Exception:          # capstone is optional; the rest still works
    _MD = None


def load(path):
    with open(path, 'rb') as f:
        return f.read()


def va(off):
    return BASE + off


def off_of(addr):
    """Virtual address -> file offset, accepting either the P1 or P2 view."""
    return addr & 0x0FFFFFFF


def in_image(data, addr):
    return (addr & 0xF0000000) in (0xA0000000, 0x80000000) and off_of(addr) < len(data)


def u16(data, off):
    return struct.unpack_from('<H', data, off)[0]


def u32(data, off):
    return struct.unpack_from('<I', data, off)[0]


# ---------------------------------------------------------------------------
# instruction decoding
# ---------------------------------------------------------------------------

def text(data, off):
    """Capstone mnemonic for the instruction at a file offset."""
    if _MD is None:
        return f".word 0x{u16(data, off):04x}"
    ins = list(_MD.disasm(data[off:off + 2], va(off)))
    if not ins:
        return f".word 0x{u16(data, off):04x}"
    return (ins[0].mnemonic + ' ' + ins[0].op_str).strip()


def pcrel(data, off):
    """
    Resolve a PC-relative load.

    Returns (pool_offset, value, width) for `mov.l @(d,pc),Rn` and
    `mov.w @(d,pc),Rn`, else None.  mov.w sign-extends, which matters a lot:
    most on-chip register addresses in this firmware are written as negative
    16-bit constants (0xFE90 -> 0xFFFFFE90).
    """
    w = u16(data, off)
    if (w & 0xF000) == 0xD000:                       # mov.l @(disp,pc),Rn
        a = ((off + 4) & ~3) + (w & 0xFF) * 4
        if a + 4 <= len(data):
            return a, u32(data, a), 4
    elif (w & 0xF000) == 0x9000:                     # mov.w @(disp,pc),Rn
        a = (off + 4) + (w & 0xFF) * 2
        if a + 2 <= len(data):
            v = struct.unpack_from('<h', data, a)[0]  # sign-extended
            return a, v & 0xFFFFFFFF, 2
    return None


def branch_target(data, off):
    """Target file offset of a pc-relative branch, or None."""
    w = u16(data, off)
    op = w & 0xF000
    if op in (0xA000, 0xB000):                       # bra / bsr
        d = w & 0xFFF
        if d >= 0x800:
            d -= 0x1000
        return off + 4 + d * 2
    if (w & 0xFF00) in (0x8900, 0x8B00, 0x8D00, 0x8F00):   # bt/bf/bt.s/bf.s
        d = w & 0xFF
        if d >= 0x80:
            d -= 0x100
        return off + 4 + d * 2
    return None


def is_call(w):
    return (w & 0xF000) == 0xB000 or (w & 0xF0FF) == 0x400B or (w & 0xF0FF) == 0x0003


def is_flow_end(w):
    """Unconditional transfer: bra, jmp, rts, rte, braf."""
    return ((w & 0xF000) == 0xA000 or (w & 0xF0FF) == 0x402B
            or w == 0x000B or w == 0x002B or (w & 0xF0FF) == 0x0023)


def is_prologue(data, off):
    """sts.l pr,@-r15 -- the standard non-leaf function entry in this image."""
    return u16(data, off) == 0x4F22


# ---------------------------------------------------------------------------
# on-chip register names (SH-3 / SH3-DSP)
# ---------------------------------------------------------------------------
# P4 area (0xFFFFFExx-0xFFFFFFxx) names are from the SH-3 core; the A4/A5
# names are the SH7727-class on-chip peripheral area.  Names marked with a
# trailing '?' are inferred from how this firmware uses them, not confirmed
# against the hardware manual.

SH3_REGS = {
    # Timer unit (TMU)
    0xFFFFFE90: 'TOCR',   0xFFFFFE92: 'TSTR',
    0xFFFFFE94: 'TCOR0',  0xFFFFFE98: 'TCNT0',  0xFFFFFE9C: 'TCR0',
    0xFFFFFEA0: 'TCOR1',  0xFFFFFEA4: 'TCNT1',  0xFFFFFEA8: 'TCR1',
    0xFFFFFEAC: 'TCOR2',  0xFFFFFEB0: 'TCNT2',  0xFFFFFEB4: 'TCR2',
    0xFFFFFEB8: 'TCPR2',
    # Real-time clock
    0xFFFFFEC0: 'R64CNT', 0xFFFFFEC2: 'RSECCNT', 0xFFFFFEC4: 'RMINCNT',
    0xFFFFFEC6: 'RHRCNT', 0xFFFFFEC8: 'RWKCNT',  0xFFFFFECA: 'RDAYCNT',
    0xFFFFFECC: 'RMONCNT', 0xFFFFFECE: 'RYRCNT', 0xFFFFFEDC: 'RCR1',
    0xFFFFFEDE: 'RCR2',
    # Interrupt controller
    0xFFFFFEE0: 'ICR0', 0xFFFFFEE2: 'IPRA', 0xFFFFFEE4: 'IPRB',
    # Bus state controller
    0xFFFFFF60: 'BCR1', 0xFFFFFF62: 'BCR2', 0xFFFFFF64: 'WCR1',
    0xFFFFFF66: 'WCR2', 0xFFFFFF68: 'MCR',  0xFFFFFF6A: 'DCR',
    0xFFFFFF6C: 'PCR',  0xFFFFFF6E: 'RTCSR', 0xFFFFFF70: 'RTCNT',
    0xFFFFFF72: 'RTCOR', 0xFFFFFF74: 'RFCR',
    # Cache / MMU
    0xFFFFFFE0: 'PTEH', 0xFFFFFFE4: 'PTEL', 0xFFFFFFE8: 'TTB',
    0xFFFFFFF0: 'TEA',  0xFFFFFFF4: 'MMUCR', 0xFFFFFFEC: 'CCR',
    # Clock pulse generator / watchdog / power
    0xFFFFFF80: 'FRQCR', 0xFFFFFF84: 'WTCNT', 0xFFFFFF86: 'WTCSR',
    0xFFFFFF88: 'STBCR', 0xFFFFFF90: 'STBCR2',
}

# On-chip peripheral block bases in the 0xA4xxxxxx area.
A4_BLOCKS = [
    (0xA4000000, 0x20, 'IRDA/SCI0?'),
    (0xA4000020, 0x20, 'SCI?'),
    (0xA4000060, 0x20, 'unknown-A4_0060'),
    (0xA4000080, 0x20, 'ADC'),
    (0xA40000A0, 0x20, 'DAC'),
    (0xA40000C0, 0x40, 'unknown-A4_00C0'),
    (0xA4000100, 0x40, 'PFC (port control)'),
    (0xA4000140, 0x10, 'PFC (port data)'),
    (0xA4000150, 0x20, 'SCIF0?'),
    (0xA4000160, 0x20, 'unknown-A4_0160'),
    (0xA4000220, 0x20, 'unknown-A4_0220'),
    (0xA4000240, 0x20, 'unknown-A4_0240'),
]

# SH3-DSP on-chip X/Y data memory (this is where the bootblock lives at run time)
XRAM = (0xA5007000, 0xA5009000)
YRAM = (0xA5017000, 0xA5019000)

PFC_REGS = {
    0xA4000100: 'PACR', 0xA4000102: 'PBCR', 0xA4000104: 'PCCR',
    0xA4000106: 'PDCR', 0xA4000108: 'PECR', 0xA400010A: 'PFCR',
    0xA400010C: 'PGCR', 0xA400010E: 'PHCR', 0xA4000110: 'PJCR',
    0xA4000112: 'PKCR', 0xA4000114: 'PLCR', 0xA4000116: 'SCPCR',
    0xA4000120: 'PADR', 0xA4000122: 'PBDR', 0xA4000124: 'PCDR',
    0xA4000126: 'PDDR', 0xA4000128: 'PEDR', 0xA400012A: 'PFDR',
    0xA400012C: 'PGDR', 0xA400012E: 'PHDR', 0xA4000130: 'PJDR',
    0xA4000132: 'PKDR', 0xA4000134: 'PLDR', 0xA4000136: 'SCPDR',
}


def describe_addr(addr):
    """Human-readable label for an absolute address constant."""
    if addr in SH3_REGS:
        return SH3_REGS[addr]
    if addr in PFC_REGS:
        return PFC_REGS[addr]
    if 0xFFFFFE00 <= addr <= 0xFFFFFFFF:
        return 'P4 on-chip reg'
    if XRAM[0] <= addr < XRAM[1]:
        return f'XRAM+0x{addr - XRAM[0]:04x}'
    if YRAM[0] <= addr < YRAM[1]:
        return f'YRAM+0x{addr - YRAM[0]:04x}'
    if 0xA4000000 <= addr < 0xA5000000:
        for b, sz, name in A4_BLOCKS:
            if b <= addr < b + sz:
                return f'{name}+0x{addr - b:02x}'
        return 'on-chip peripheral'
    if 0x88000000 <= addr < 0x8C000000:
        return f'SDRAM+0x{addr - 0x88000000:07x}'
    if 0xA8000000 <= addr < 0xAC000000:
        return f'SDRAM(uncached)+0x{addr - 0xA8000000:07x}'
    if (addr & 0xF0000000) in (0xA0000000, 0x80000000) and (addr & 0x0FFFFFFF) < 0x100000:
        return 'flash'
    return None


# ---------------------------------------------------------------------------
# recursive-descent code discovery
# ---------------------------------------------------------------------------

@dataclass
class Analysis:
    data: bytes
    code: set = field(default_factory=set)        # file offsets known to be code
    funcs: set = field(default_factory=set)       # file offsets of function entries
    calls: dict = field(default_factory=dict)     # callee off -> set of caller offs
    pools: set = field(default_factory=set)       # file offsets of literal-pool words
    consts: dict = field(default_factory=dict)    # value -> list of (site, pool)


def analyze(data, entries, limit=None):
    """
    Walk code from a set of entry offsets, following branches and direct calls.
    Literal pool words that a mov.l/mov.w reaches are recorded (and excluded
    from the code set) so the disassembly does not try to decode them.
    """
    a = Analysis(data=data)
    limit = limit or len(data)
    todo = list(entries)
    a.funcs.update(entries)
    while todo:
        off = todo.pop()
        while 0 <= off < limit - 1:
            if off in a.code or off in a.pools:
                break
            a.code.add(off)
            w = u16(data, off)

            lit = pcrel(data, off)
            if lit:
                pool, val, width = lit
                a.pools.add(pool)
                if width == 4:
                    a.pools.add(pool + 2)
                a.consts.setdefault(val, []).append((off, pool))

            # direct call: bsr
            if (w & 0xF000) == 0xB000:
                t = branch_target(data, off)
                if t is not None and 0 <= t < limit:
                    a.calls.setdefault(t, set()).add(off)
                    if t not in a.funcs:
                        a.funcs.add(t)
                        todo.append(t)

            # conditional branch: queue target, keep falling through
            if (w & 0xFF00) in (0x8900, 0x8B00, 0x8D00, 0x8F00):
                t = branch_target(data, off)
                if t is not None and 0 <= t < limit and t not in a.code:
                    todo.append(t)

            # unconditional bra: follow target, stop falling through
            if (w & 0xF000) == 0xA000:
                t = branch_target(data, off)
                # the delay slot still executes
                a.code.add(off + 2)
                if t is not None and 0 <= t < limit and t not in a.code:
                    todo.append(t)
                break

            if is_flow_end(w):
                a.code.add(off + 2)     # delay slot
                break

            off += 2
    return a


def find_prologues(data, start=0, end=None):
    end = end or len(data)
    return [i for i in range(start, end - 1, 2) if u16(data, i) == 0x4F22]


# registers the SH ABI makes callee-saved: r8-r14 (plus pr).  A function
# entry is the first `mov.l rN,@-r15` of such a run, or a bare `sts.l pr,@-r15`.
_SAVE = {0x2F86, 0x2F96, 0x2FA6, 0x2FB6, 0x2FC6, 0x2FD6, 0x2FE6}


def find_entries(data, start=0, end=None):
    """
    Heuristic function-entry scan.

    Catches both `sts.l pr,@-r15` (non-leaf) and the callee-saved-register
    push runs that C++ methods open with, which the bare prologue scan misses.
    """
    end = end or len(data)
    out = []
    for i in range(start, end - 1, 2):
        w = u16(data, i)
        if w not in _SAVE and w != 0x4F22:
            continue
        prev = u16(data, i - 2) if i >= 2 else 0
        if prev in _SAVE or (w == 0x4F22 and prev in _SAVE):
            continue                      # middle of a push run
        if w == 0x4F22 and prev == 0x4F22:
            continue
        out.append(i)
    return out


# ---------------------------------------------------------------------------
# main-OS data relocation
# ---------------------------------------------------------------------------
# The OS does not run from flash.  The bootblock jumps to 0xA0010030, and the
# start-up code copies the image into SDRAM (and the DSP overlay into the
# on-chip X/Y memories) and continues there.  Every pointer the OS code holds
# is therefore a *run-time* address, which is why searching the image for
# flash addresses finds almost no cross-references.
#
# (flash_start, flash_end, runtime_destination); the segments tile the image
# from 0x010000 to its end at 0x0B74D8 with no gaps.
RELOC = [
    # OS text, static data and the UI string table: one constant delta,
    # 0x8842B644.  Validated by mapping every indirect call target back:
    # 99.7 % land inside the OS code region and 84.3 % land exactly on a
    # function prologue.
    (0x010000, 0x0AC40C, 0x8843B644),
    # a second static data area
    (0x0AC40C, 0x0B3DFC, 0x881C0000),
    # the DSP overlay: ~11.6 KB of code and tables that run from the
    # SH3-DSP's on-chip X and Y memories
    (0x0B3DFC, 0x0B4400, 0xA50089BC),   # -> YRAM tail via XRAM window
    (0x0B4400, 0x0B4768, 0xA50183B4),   # -> YRAM
    (0x0B4768, 0x0B6124, 0xA5007000),   # -> XRAM
    (0x0B6124, 0x0B74D8, 0xA5017000),   # -> YRAM
]


def runtime_addr(off):
    """File offset -> the address the running OS uses for it."""
    for lo, hi, dst in RELOC:
        if lo <= off < hi:
            return dst + (off - lo)
    return va(off)


def flash_off(addr):
    """Run-time address -> file offset, undoing the start-up relocation."""
    for lo, hi, dst in RELOC:
        if dst <= addr < dst + (hi - lo):
            return lo + (addr - dst)
    if (addr & 0xF0000000) in (0xA0000000, 0x80000000):
        o = off_of(addr)
        return o if o < 0x010000 else None      # bootblock runs in place
    return None


# BSS / global variables: heavily referenced, but no initialiser in the image.
BSS = (0x881C79F0, 0x8843B644)
