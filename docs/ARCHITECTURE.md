# MPC1000 hardware, as proven by the JJOS 3.16 binary

Everything here is derived from `mpc1000_jv316.bin` and can be re-checked with
the tools in `tools/`. Claims are tagged:

- **[verified]** — follows directly from instructions in the image.
- **[inferred]** — consistent with the image and with the SH-3 manuals, but not
  proven by the image alone. Check against the SH7727 hardware manual before
  relying on it.

---

## 1. CPU

**[verified] Renesas SuperH SH-3, little-endian, with the DSP extension.**

Three independent proofs:

1. **Instruction density.** Decoding the image as SH little-endian yields
   97–99 % valid instructions across the code regions; big-endian yields
   66–75 %. (`tools/sh3.py`, capstone `CS_ARCH_SH`.)

2. **The reset stub is SH-3 code.** File offset 0 decodes as:

   ```
   a0000000: d001   mov.l  @(0x8,pc),r0     ; r0 = 0xA0000800
   a0000002: 402b   jmp    @r0
   a0000004: 0009   nop                     ; delay slot
   a0000008: .long  0xa0000800
   ```

   An SH-3 comes out of reset at `0xA0000000` with VBR = 0, so this is the
   reset vector, and it fixes the load address (§2).

3. **The bring-up sequence matches SH-3 registers exactly**, including two
   registers that need a magic `0xA5` key byte — `RTCSR` is written `0xA508`
   and `RTCOR` is written `0xA5D5`. Guessing those by accident is not
   plausible. See `docs/BOOT.md`.

**[verified] It is a DSP part (SH3-DSP), not a plain SH7709.** The bootblock
copies code into `0xA5007008` and calls it at `0xA5007030`, and sets its stack
pointer to `0xA5018EE4`. Those are the SH3-DSP on-chip X and Y data memories:

| Block | Range | Use in JJOS |
|---|---|---|
| XRAM | `0xA5007000`–`0xA5008FFF` | bootblock globals; RAM-resident flash driver |
| YRAM | `0xA5017000`–`0xA5018FFF` | bootblock stack (top `0xA5018EE4`) and buffers |

Running the flash driver out of on-chip RAM is required — you cannot execute
from a NOR flash while erasing it.

**[inferred] The specific part is the SH7727 (HD6417727).** The X/Y memory
placement, the on-chip peripheral block at `0xA4000000`, and the on-chip
ADC/DAC all fit the SH7727. The image contains no part-number string, so this
is not proven from the binary.

---

## 2. Address space

The image is executed in place from **P2, the uncached window**:

```
file offset N   <->   virtual address 0xA0000000 + N
```

**[verified]** by the reset stub (entry `0xA0000800` = file offset `0x800`) and
by the OS image header, whose load-address field reads `0xA0010030` — exactly
file offset `0x10030`, where the OS code starts.

> The earlier handoff note suggested loading at `0x8C000000`. That is wrong;
> use `0xA0000000`. `0x80000000` is the same flash through the cached P1
> window, and a handful of constants use it.

### Memory map

| Virtual (P2) | Physical | What | Evidence |
|---|---|---|---|
| `0xA0000000`– | `0x00000000` area 0 | NOR flash: bootblock + OS | **[verified]** reset vector, all code |
| `0xA1000000`– | `0x01000000` area 0 | "EX-MEM" update window: bootblock image at `+0x20`, OS image at `+0x10000` | **[verified]** read by the update path at `0xA00012D6`; what device backs it is **unconfirmed** |
| `0xA4000000`– | `0x04000000` area 1 | on-chip peripheral registers | **[verified]** PFC/ADC/DAC writes in boot |
| `0xA5007000`– | `0x05007000` area 1 | XRAM (8 KB) | **[verified]** code copied there and called |
| `0xA5017000`– | `0x05017000` area 1 | YRAM (8 KB) | **[verified]** boot stack |
| `0x88000000`– | `0x08000000` area 2 | main SDRAM, 32-bit | **[verified]** dominant data region; SDRAM mode-register write to `0xFFFFD880` |
| `0x8C000000`– | `0x0C000000` area 3 | second SDRAM bank | **[verified]** mode-register write to `0xFFFFE880` |
| `0xB6000000`– | `0x16000000` area 5 | external device | **[verified]** one reference (`0xB6000004`); function **unidentified** |
| `0xFFFFFE00`– | — | SH-3 core registers (P4) | **[verified]** BSC/TMU/INTC/CPG writes |

The OS's own data lives in SDRAM at roughly `0x88100000`–`0x884FFFFF`: of the
31,044 PC-relative constants the code loads, 27,631 are in `0x88xxxxxx`, and
`0x88400000`–`0x884FFFFF` alone accounts for 17,248 of them.

### Exception vectors

**[verified]** `ldc r2,vbr` at `0xA000090C` with `r2 = 0xA0000000` sets
**VBR = 0xA0000000**, so the vectors sit at the very start of the flash:

| Offset | SH-3 meaning | Contents |
|---|---|---|
| `VBR+0x100` | general exception | `stc spc,r4` / `stc ssr,r5` / `jmp 0xA00048A0` |
| `VBR+0x400` | TLB miss | same stub |
| `VBR+0x600` | interrupt | same stub |

All three funnel into one handler at `0xA00048A0`, which prints
`PC(%08x) SR(%08x) TEA(%08x)` plus a stack dump — a ready-made panic screen
that a custom OS can reuse for bring-up debugging.

---

## 3. The OS does not run from flash

**[verified] The main OS relocates itself into SDRAM at start-up and runs
there.** This matters more than it sounds: it is why searching the image for
pointers to its own strings finds nothing, and why the OS looked much harder
to navigate than it is.

The bootblock jumps to `0xA0010030` in flash, and the start-up code copies the
image out before continuing. The mapping is a single constant for the whole
text-and-data region:

```
run-time address = flash offset + 0x8842B644
```

so flash `0x010000` becomes `0x8843B644`.

**How this was confirmed:** resolve every indirect call target the OS
materialises in a literal pool, and map each one back through the delta.
1,841 of 1,846 distinct targets (99.7 %) land inside the OS code region, and
1,557 (84.3 %) land exactly on a function prologue. The rest are leaf
functions that do not open with a register save.

### Full relocation map

| Flash | Run-time | Size | Contents |
|---|---|---|---|
| `0x000000`–`0x00FFFF` | `0xA0000000` (in place) | 64 KB | bootblock — runs from flash |
| `0x010000`–`0x0AC40C` | `0x8843B644`–`0x884D7A50` | 623 KB | OS text, static data, UI strings |
| `0x0AC40C`–`0x0B3DFC` | `0x881C0000`–`0x881C79F0` | 31 KB | second static data area |
| `0x0B3DFC`–`0x0B4400` | `0xA50089BC` | 1.5 KB | DSP overlay |
| `0x0B4400`–`0x0B4768` | `0xA50183B4` | 872 B | DSP overlay (YRAM) |
| `0x0B4768`–`0x0B6124` | `0xA5007000` | 6.4 KB | DSP overlay (XRAM) |
| `0x0B6124`–`0x0B74D8` | `0xA5017000` | 4.9 KB | DSP overlay (YRAM) |
| — | `0x881C79F0`–`0x8843B644` | 2.2 MB | BSS / globals (no initialiser in the image) |

Reference counts from the literal pools back this up: 16,531 into the text and
data image, 2,611 into the `0x881C0000` area, 8,452 into BSS, 179 into X/Y RAM.

**The last 11.6 KB of the image is a DSP overlay.** Four segments totalling
`0x36DC` bytes are copied into the SH3-DSP's on-chip X and Y memories — the
only code in the system placed there deliberately at run time, in the memories
the DSP unit can access in a single cycle. That is where the audio engine
lives, and it is the natural starting point for anyone working on the sample
playback path.

`tools/sh3.py` implements this as `runtime_addr()` / `flash_off()`, and both
`disasm.py` and `strings_xref.py` resolve through it. That is what makes
string cross-references work:

```
$ python3 tools/strings_xref.py mpc1000_jv316.bin "SEQUENCE MEMORY"
0a7118 884d275c xref[1]: 03d292   'SEQUENCE MEMORY'

$ python3 tools/disasm.py mpc1000_jv316.bin 0x3d290 4
a003d290 03d290:  d474  mov.l ...,r4   ; = 0x882168b0  bss
a003d292 03d292:  d577  mov.l ...,r5   ; = 0x884d275c  [flash 0x0a7118]  "SEQUENCE MEMORY"
a003d294 03d294:  d277  mov.l ...,r2   ; = 0x884410d2  [flash 0x015a8e]
a003d296 03d296:  420b  jsr @r2
```

---

## 4. SDRAM

**[verified]** The bootblock reads a SODIMM's SPD EEPROM and picks the bus
controller's `MCR` value from SPD byte 4 (number of column address bits):

| SPD byte 4 | MCR written to `0xFFFFFF68` |
|---|---|
| 8 | `0x4024` |
| 9 | `0x402C` |
| 10 | `0x4034` |
| SPD unreadable | `0x4024` (fallback) |

It also reads SPD bytes 3 (row bits), 5 (ranks) and 17 (banks per device) and
multiplies them out to get the total size, which the OS prints as
`MPC1000 (   MB installed)`.

**[verified]** SDRAM mode registers are then programmed by dummy writes to
`0xFFFFD880` (area 2) and `0xFFFFE880` (area 3) — the SH-3's
write-to-a-magic-address MRS mechanism.

**[inferred]** `0x880` in those addresses encodes MRS value `0x220`:
burst length 1, sequential, **CAS latency 2**, single-location write.

---

## 5. NOR flash

**[verified]** AMD/Spansion command set, 16-bit bus, uniform 64 KB sectors.
From the RAM-resident driver at `0xA0008884` / `0xA0008924`:

```
; unlock bypass entry
w16(base + 0xAAA, 0xAA); w16(base + 0x554, 0x55); w16(base + 0xAAA, 0x20)

; sector erase  (sector index in r5)
w16(base + 0xAAA, 0xAA); w16(base + 0x554, 0x55); w16(base + 0xAAA, 0x80)
w16(base + 0xAAA, 0xAA); w16(base + 0x554, 0x55)
w16(base + (sector << 16), 0x30)          ; <-- 64 KB sectors
poll  DQ7 / DQ5 at base + (sector << 16), timeout 3000
```

`shll16` on the sector index is what proves the 64 KB sector size.

### Flash layout

| Sectors | Offsets | Contents |
|---|---|---|
| 0 | `0x000000`–`0x00FFFF` | bootblock (written in 128 × 512-byte chunks) |
| 1–13 | `0x010000`–`0x0DFFFF` | OS image, **832 KB max** |

**[verified]** the OS updater erases sectors 1 through 13 in a loop
(`0xA0008854`, `r13 = 13`), so a custom OS image must fit in `0xD0000` bytes.
JJOS 3.16 uses `0xA74D8` (685,272), leaving about 166 KB of headroom.

---

## 6. On-chip peripherals in use

**[verified]** addresses the boot code writes; names are **[inferred]** from
the SH-3/SH7727 register map.

| Address | Name | Boot value | Notes |
|---|---|---|---|
| `0xFFFFFF80` | FRQCR | `0xA101` then `0x8102` | clock/PLL setup |
| `0xFFFFFF60` | BCR1 | `0x180F` | bus config |
| `0xFFFFFF62` | BCR2 | `0x26F0` | per-area bus widths |
| `0xFFFFFF64` | WCR1 | `0x8000` | wait states |
| `0xFFFFFF66` | WCR2 | `0xDA55` | wait states |
| `0xFFFFFF68` | MCR | see §4 | SDRAM control |
| `0xFFFFFF6C` | PCR | `0x0445` | |
| `0xFFFFFF6E` | RTCSR | `0xA508` | refresh control (key `0xA5`) |
| `0xFFFFFF72` | RTCOR | `0xA5D5` | refresh interval (key `0xA5`) |
| `0xFFFFFE90` | TOCR/TSTR/TCOR/TCNT/TCR | TCOR0-2 = `0xFFFFFFFF`, TCR0 = 1, TCR1 = 2, TCR2 = 2, **TSTR = 7** | all three timers running |
| `0xA4000090` | ADCSR | `0x3B` | A/D converter enabled |
| `0xA4000092` | ADCR | `0x20` | |
| `0xA40000A0` | DADR0 | `0x64` | D/A channel 0 |
| `0xA40000A2` | DADR1 | `0x80` | D/A channel 1 |
| `0xA40000A4` | DACR | `0xC0` | both D/A outputs enabled |
| `0xA4000104` | PCCR | `0x5555` | pin function config |
| `0xA4000106` | PDCR | `0x4465` | |
| `0xA4000108` | PECR | `0x5555` | |
| `0xA400010A` | PFCR | `0xAAAA` | |
| `0xA400010C` | PGCR | `0xAAAA` | |
| `0xA400010E` | PHCR | `0x7AAA` | |
| `0xA4000110` | PJCR | `0x5544` | |
| `0xA4000112` | PKCR | `0x0115` | |

Port data registers `PCDR`/`PDDR`/`PEDR`/`PHDR` are also initialised, and
`0xA4000160`–`0xA4000162` plus `PEDR` bits are toggled by a routine at
`0xA00026D4` that takes a boolean — a GPIO-controlled rail, most likely LCD
backlight/reset or CF power. **Unconfirmed.**

---

## 7. What the code is built from

**[verified]** The bootblock is **C++ with RTTI**: the image contains
`std::type_info`, `AFileSystem`, `AFat12Volume`, `AFat16Volume`,
`AFat32Volume`. Most calls in the main OS go through vtables, which is why
following call targets from literal pools only reaches part of the code and
why prologue scanning is the practical way to enumerate functions.

Code size, measured by recursive-descent disassembly from detected entries:

| Region | Offsets | Entries found | Code bytes | Coverage |
|---|---|---|---|---|
| Bootblock | `0x000000`–`0x008CC4` | 127 functions | 28,706 | complete |
| Main OS | `0x010030`–`0x0A8000` | 1,869 entries / 2,267 functions | 520,126 | 94.1 % |

The remainder is literal pools, jump tables and data. Strings start around
`0x0A6000` and run to the end of the image.
