# Bootblock walkthrough

The bootblock occupies flash sector 0 (`0x000000`–`0x00FFFF`, code through
`0x008CC4`). It is self-contained: it brings the board up, can reflash the OS
from a CompactFlash card, and then jumps to the OS. It is the best place to
start reading, and everything a custom OS needs to do at reset is in here.

A machine-generated listing of the reset path is in
[`boot_listing.txt`](boot_listing.txt); regenerate it with:

```bash
python3 tools/disasm.py mpc1000_jv316.bin 0x800 244
```

## Reset path, step by step

All addresses are virtual (`0xA0000000` + file offset).

### `0xA0000000` — reset vector

```
mov.l @(0x8,pc),r0     ; 0xA0000800
jmp   @r0
nop
```

The SH-3 starts at `0xA0000000` with VBR = 0, so this is the first instruction
the chip executes. Three instructions, then straight into the bootblock.

### `0xA0000800` — early bring-up

1. **Stack into on-chip YRAM.** `r15 = 0xA5019000 + (int16)0xFEE4 =
   0xA5018EE4`. No external memory is needed or trusted yet.

2. **Clock.** `0xA101` then `0x8102` written to FRQCR (`0xFFFFFF80`).

3. **Bus controller** (`r12 = 0xFFFFFF60`):

   | Register | Value |
   |---|---|
   | BCR1 | `0x180F` |
   | BCR2 | `0x26F0` |
   | WCR1 | `0x8000` |
   | WCR2 | `0xDA55` |
   | PCR | `0x0445` |
   | RTCSR | `0xA508` |
   | RTCOR | `0xA5D5` |

   `RTCSR`/`RTCOR` need `0xA5` in the high byte as a write key — those two
   values are what make the SH-3 identification airtight.

4. **Timers** (`r6 = 0xFFFFFE90`): `TCOR0..2 = 0xFFFFFFFF`, `TCR0 = 1`,
   `TCR1 = 2`, `TCR2 = 2`, then `TSTR = 7` — all three TMU channels free-run
   with different prescalers.

5. **ADC / DAC**: `ADCSR = 0x3B`, `ADCR = 0x20`, `DADR0 = 0x64`,
   `DADR1 = 0x80`, `DACR = 0xC0` (both D/A outputs on).

6. **Pin function controller** (`r14` walked to `0xA4000100`): `PCCR = 0x5555`,
   `PDCR = 0x4465`, `PECR = 0x5555`, `PFCR = 0xAAAA`, `PGCR = 0xAAAA`,
   `PHCR = 0x7AAA`, `PJCR = 0x5544`, `PKCR = 0x0115`, plus initial values in
   the matching port data registers.

7. **`0xA000090C`: `ldc r2,vbr` with `r2 = 0xA0000000`** — exception vectors
   now point at the base of flash (`VBR+0x100`, `+0x400`, `+0x600`).

8. **Stage the flash driver into on-chip RAM.** The long-copy helper at
   `0xA00000A4` runs twice:

   | Source | Length | Destination |
   |---|---|---|
   | `0xA000882C`–`0xA00089E0` | `0x1B4` | `0xA5007008` (XRAM) |
   | `0xA000A260`–`0xA000A2E4` | `0x84` | `0xA50071BC` (XRAM) |

   NOR flash cannot be read while it is being erased, so the erase/program
   routines must not execute from it. Entry points after the copy:
   `0xA5007030` (erase the OS region), `0xA5007060` (unlock bypass),
   `0xA5007100` (erase one sector).

9. **Size the SDRAM from the SODIMM SPD EEPROM.** Reads SPD bytes 3, 4, 5 and
   17, picks `MCR` from byte 4 (`8 -> 0x4024`, `9 -> 0x402C`, `10 -> 0x4034`,
   fallback `0x4024`), then sets the SDRAM mode registers with dummy writes to
   `0xFFFFD880` (area 2) and `0xFFFFE880` (area 3).

10. **Validate the installed OS** at `0xA0010000` and jump to `0xA0010030`,
    unless a button combination selected one of the alternate modes. The OS
    then relocates itself into SDRAM and continues there — see
    [`ARCHITECTURE.md` §3](ARCHITECTURE.md).

## Boot modes

From the strings and the mode variable the bootblock switches on:

| Mode | Message |
|---|---|
| normal | (jump to OS) |
| emergency | `Boot on emergency mode` |
| memory check | `Boot on SODIMM memory check mode` |
| OS update | `Boot on OS update mode` |
| OS update from EX-MEM | `Boot on OS update mode from EX-MEM` |
| OS + boot update from EX-MEM | `Boot on OS/BOOT update mode from EX-MEM` |

The memory-check mode runs four passes with patterns `0xAA55AA55`,
`0x84848484`, `0xEEEEEEEE` and reports `pass %d : passed` /
`pass %d : failed(%08x)`.

The main OS also advertises `+Power on-->FREE OS`, so key combinations at
power-on select these.

## OS validation and update

`0xA0001998` onward:

```
memcmp(header, "MPC1000", 7)            ; fail -> "System halt......"
crc32 over the image, checksum field zeroed
compare against header+0x10             ; fail -> "System halt......"
```

See [`IMAGE_FORMAT.md`](IMAGE_FORMAT.md) for the full format and for
`tools/mpcimg.py`, which reproduces this exactly.

The CF update path mounts FAT12/16/32, looks for `*.bin`, compares versions,
prompts `OK(REC) , CANCEL(PLAY or STOP)`, then erases sectors 1–13 and writes.

## The panic handler is worth keeping

All three exception vectors jump to `0xA00048A0`, which prints:

```
----------------------------------------
<exception name>
PC(%08x) SR(%08x) TEA(%08x)
--------stack dump (sp=%08x) -------
%08x %08x %08x %08x
```

with a table of SH-3 exception names (`TLB miss/invalid (read)`,
`Illegal slot instruction exception`, `Unconditional trap (TRAPA instruction)`,
and so on). If you are bringing up your own OS on this hardware, reproducing
this handler early will save you a great deal of guessing — it is the only
debug output the machine has before you have a working display driver.

## Reading order for the rest of the OS

The bootblock is done; what follows is the map for the main OS at
`0xA0010030`. Use `tools/strings_xref.py` to jump in — it prints, for each
string, the offsets of the instructions that load its address.

| Subsystem | Suggested anchor |
|---|---|
| OS entry / RAM size splash | `0x010030`, string `MPC1000 (   MB installed)` at `0x010D8C` |
| OS variant checks | `MPC1001 JJ OS2` / `OS3` at `0x010D6C`, used at `0x010050` / `0x010078` |
| Display | trace the GPIO routine at `0xA00026D4` and the bootblock's `print_line` at `0xA00022D0` |
| CompactFlash | the `AFat12Volume` / `AFat16Volume` / `AFat32Volume` classes; `0xB6000004` is the only external-bus constant in the bootblock |
| Sequencer | `SEQUENCE MEMORY`, `Track01` |
| Sampler | `WITH SAMPLE`, `SLICED SAMPLES`, `PATCHED PHRASE` |
| Effects | `BIT GRUNGER`, `4 BAND EQ`, `COMPRESSOR`, `FLYING PAN` |
| MIDI | the MIDI string block (`SYNC`, `PITCH BEND`, `CONTROL CHANGE`) |
