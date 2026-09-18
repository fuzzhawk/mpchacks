# Ghidra script: set up an MPC1000 / JJOS flash dump for analysis.
#
# In Ghidra, import mpc1000_jv316.bin as:
#     Format    : Raw Binary
#     Language  : SuperH / SH-3 / 16 / little  (SH-3:LE:32:default)
#     Base addr : a0000000
# then run this script (Script Manager -> pick the folder holding this file).
#
# It creates the RAM/peripheral memory blocks the firmware talks to, labels the
# reset and exception vectors, and marks the two known entry points.
#
# @category MPC1000

from ghidra.program.model.address import AddressSet  # noqa: F401
from ghidra.program.model.symbol import SourceType

FLASH_BASE = 0xA0000000

# name, address, length, read, write, execute, is_overlay/uninitialized
BLOCKS = [
    ('XRAM',      0xA5007000, 0x2000, True, True, True),    # SH3-DSP X data memory
    ('YRAM',      0xA5017000, 0x2000, True, True, True),    # SH3-DSP Y data memory
    ('SDRAM',     0x88000000, 0x1000000, True, True, True),  # area 2, 16 MB stock
    ('PERIPH_A4', 0xA4000000, 0x1000, True, True, False),   # on-chip peripherals
    ('FLASH_EXT', 0xA1000000, 0x400000, True, True, False),  # update window
    ('P4_REGS',   0xFFFFFE00, 0x200, True, True, False),    # BSC/TMU/INTC/CPG
]

LABELS = {
    0xA0000000: 'reset_vector',
    0xA0000100: 'vec_general_exception',
    0xA0000400: 'vec_tlb_miss',
    0xA0000600: 'vec_interrupt',
    0xA00000A4: 'copy_longs',            # memcpy used to stage code into XRAM
    0xA0000800: 'bootblock_entry',
    0xA0004874: 'crc32_update',          # (seed, buf, len) -> crc
    0xA00048A0: 'exception_handler',
    0xA0005080: 'memcmp',
    0xA00022D0: 'print_line',
    0xA0008854: 'flash_erase_os_region',  # runs from XRAM at 0xA5007030
    0xA0008884: 'flash_unlock_bypass',    # runs from XRAM at 0xA5007060
    0xA0008924: 'flash_erase_sector',     # runs from XRAM at 0xA5007100
    0xA0010000: 'os_image_header',
    0xA0010030: 'os_entry',
}

REGS = {
    0xFFFFFE90: 'TOCR', 0xFFFFFE92: 'TSTR', 0xFFFFFE94: 'TCOR0',
    0xFFFFFE98: 'TCNT0', 0xFFFFFE9C: 'TCR0', 0xFFFFFEA0: 'TCOR1',
    0xFFFFFEA4: 'TCNT1', 0xFFFFFEA8: 'TCR1', 0xFFFFFEAC: 'TCOR2',
    0xFFFFFEB0: 'TCNT2', 0xFFFFFEB4: 'TCR2',
    0xFFFFFEE0: 'ICR0', 0xFFFFFEE2: 'IPRA', 0xFFFFFEE4: 'IPRB',
    0xFFFFFF60: 'BCR1', 0xFFFFFF62: 'BCR2', 0xFFFFFF64: 'WCR1',
    0xFFFFFF66: 'WCR2', 0xFFFFFF68: 'MCR', 0xFFFFFF6A: 'DCR',
    0xFFFFFF6C: 'PCR', 0xFFFFFF6E: 'RTCSR', 0xFFFFFF70: 'RTCNT',
    0xFFFFFF72: 'RTCOR', 0xFFFFFF74: 'RFCR',
    0xFFFFFF80: 'FRQCR', 0xFFFFFF84: 'WTCNT', 0xFFFFFF86: 'WTCSR',
    0xFFFFFF88: 'STBCR', 0xFFFFFFEC: 'CCR',
    0xA4000080: 'ADDRA', 0xA4000090: 'ADCSR', 0xA4000092: 'ADCR',
    0xA40000A0: 'DADR0', 0xA40000A2: 'DADR1', 0xA40000A4: 'DACR',
    0xA4000100: 'PACR', 0xA4000102: 'PBCR', 0xA4000104: 'PCCR',
    0xA4000106: 'PDCR', 0xA4000108: 'PECR', 0xA400010A: 'PFCR',
    0xA400010C: 'PGCR', 0xA400010E: 'PHCR', 0xA4000110: 'PJCR',
    0xA4000112: 'PKCR', 0xA4000114: 'PLCR', 0xA4000116: 'SCPCR',
    0xA4000120: 'PADR', 0xA4000122: 'PBDR', 0xA4000124: 'PCDR',
    0xA4000126: 'PDDR', 0xA4000128: 'PEDR', 0xA400012A: 'PFDR',
    0xA400012C: 'PGDR', 0xA400012E: 'PHDR', 0xA4000136: 'SCPDR',
}


def addr(x):
    return currentProgram.getAddressFactory().getDefaultAddressSpace().getAddress(x)


def make_blocks():
    mem = currentProgram.getMemory()
    for name, start, length, r, w, x in BLOCKS:
        a = addr(start)
        if mem.getBlock(a) is not None:
            print('  block at %08x already exists, skipping %s' % (start, name))
            continue
        b = mem.createUninitializedBlock(name, a, length, False)
        b.setRead(r)
        b.setWrite(w)
        b.setExecute(x)
        b.setVolatile(not x)
        print('  created %-10s %08x +%06x' % (name, start, length))


def label_all():
    st = currentProgram.getSymbolTable()
    for a, n in sorted(list(LABELS.items()) + list(REGS.items())):
        try:
            st.createLabel(addr(a), n, SourceType.USER_DEFINED)
        except Exception as e:
            print('  label %08x %s failed: %s' % (a, n, e))


def mark_entries():
    for a in (0xA0000000, 0xA0000800, 0xA0010030,
              0xA0000100, 0xA0000400, 0xA0000600):
        try:
            disassemble(addr(a))
            createFunction(addr(a), None)
        except Exception as e:
            print('  entry %08x: %s' % (a, e))


print('MPC1000 loader: creating memory blocks')
make_blocks()
print('MPC1000 loader: applying labels')
label_all()
print('MPC1000 loader: disassembling entry points')
mark_entries()
print('MPC1000 loader: done')
