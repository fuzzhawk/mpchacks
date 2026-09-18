# MPC1000 Custom OS — Reverse Engineering Handoff

> **Superseded in part.** This is the record of the first analysis session.
> A later session verified its findings against the binary and corrected
> several of them. **Read [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md),
> [`docs/BOOT.md`](docs/BOOT.md) and
> [`docs/IMAGE_FORMAT.md`](docs/IMAGE_FORMAT.md) first.**
>
> Corrections made below are marked **[CORRECTED]**. The two that matter most:
>
> - The load address is **`0xA0000000`**, not `0x8C000000`. Loading at the
>   wrong base makes every pointer in the image resolve to nothing.
> - The bootblock validates an OS image with `memcmp(hdr,"MPC1000",7)` plus a
>   **CRC-32**, not the `MPC1001 JJ OS2XL` string.

**Session date:** September 18, 2026  
**Binary analyzed:** `mpc1000_jv316.bin` (JJOS 3.16)  
**Goal:** Reverse-engineer JJOS to inform development of a custom MPC1000 OS

---

## 1. Architecture — Critical Finding

**The MPC1000 does NOT use a Motorola ColdFire processor.**  
It uses a **Renesas SH7727** — a SuperH SH3-DSP variant running at ~100 MHz.

| Property | Value |
|---|---|
| CPU family | Renesas SuperH (SH3-DSP) |
| Part | SH7727 |
| Instruction width | 16-bit fixed-width |
| Byte order | **Little-endian** (words stored LE) |
| Instruction set | SH3 (with DSP extensions) |

This changes everything about toolchain selection. Ignore any community info pointing at ColdFire/MCF5249.

---

## 2. Binary Overview

**File:** `mpc1000_jv316.bin`  
**Size:** 750,808 bytes (733.2 KB)

### Section Map

| Region | Offset | Size | Description |
|---|---|---|---|
| Header | `0x000000–0x0007FF` | 2 KB | Bootblock config, magic string `MPC1000BOOT`, load address hints |
| Bootblock code | `0x000800–0x00A2FF` | ~38 KB | Boot/flash-updater code; self-contained; **start here** |
| Padding | `0x00A300–0x00FFFF` | ~24 KB | Zeroed |
| OS image header | `0x010000–0x01002F` | 48 B | **[CORRECTED]** `"MPC1000"` magic, version, size, CRC-32, load address `0xA0010030`, build date. See `docs/IMAGE_FORMAT.md` |
| **Main OS code** | `0x010030–0x0A6000` | **~620 KB** | **[CORRECTED]** code starts at `0x010030`, immediately after the header — core JJOS: sequencer, sampler, UI, MIDI, effects |
| String/data tables | `0x0AD600–0x0AF2FF` | ~7 KB | UI strings, MIDI name tables, effect names |
| Additional data | `0x0AF400–0x0B74D8` | ~27 KB | Audio tables, patch data, more config |

### Key File Header Fields (offset 0x0)

```
Bytes 0–3:   01 D0 2B 40  — NOT a magic number: this is SH-3 code
                            d001  mov.l @(0x8,pc),r0
                            402b  jmp   @r0
Bytes 4–7:   09 00 00 00  — 0009 = nop (the jmp's delay slot)
Bytes 8–11:  00 08 00 A0  — the jump target: 0xA0000800
Bytes 0x20:  "MPC1000BOOT" — bootblock identifier string
```

**[CORRECTED]** The first 12 bytes are the SH-3 reset vector, not a header.
This is what proves the image is mapped at `0xA0000000`.

---

## 3. Confirmed Version String

```
Offset 0xA64F8:  "JJ OS Ver.3.16 "
```

Context bytes around it:
```
MPC1000 . BMP . JJ OS Ver.3.16  . (unused) . 0123456789
```

Also present in binary: `MPC1001 JJ OS2`, `MPC1001 JJ OS3`, `MPC1001 JJ OS2XL` — compatibility/identification strings for multiple JJOS generations.

---

## 4. Code Statistics

| Metric | Count |
|---|---|
| Function entry points (`STS.L PR,@-R15` prologue) | **1,822** (1,826 counting from offset 0) |
| RTS (return) instructions | **2,424** (2,452 counting from offset 0) |
| **[CORRECTED]** Functions found by recursive-descent disassembly | **2,267** in the main OS, **127** in the bootblock |
| Architecture confirmation method | SH LE prologue pattern `bytes 22 4F` |

First function: `0x1A64`  
Last function: `0xA61E8`  
All within the main OS section.

---

## 5. String Table — Feature Map

All strings are in the region `0xA6000–0xB4000`. Cross-referencing these back to the code that loads them is the fastest way to find feature implementations in Ghidra.

| Feature | String offset | Sample strings |
|---|---|---|
| Version/ID | `0xA64EC` | `MPC1000`, `JJ OS Ver.3.16` |
| Transport | `0x10DA8` | `TAP TEMPO`, `+Power on-->FREE OS` |
| Pads | `0xB3126` | `PAD BANK A/B/C/D` |
| Sequencer | `0xA7118` | `SEQUENCE MEMORY`, `Track01` |
| Programs/samples | `0xA7074` | `PROGRAM ONLY`, `WITH SAMPLE`, `Replace same sample` |
| Note functions | `0xAB77E` | `NOTE REPEAT`, `SHORT PHRASE` |
| MIDI | `0xA8138` | `MIDI`, `SYNC`, `NOTE`, `PITCH BEND`, `CONTROL CHANGE`, etc. |
| Effects — insert | `0xA87A4` | `BIT GRUNGER`, `4 BAND EQ`, `COMPRESSOR`, `PHASE SHIFTER`, `TREMOLO`, `FLYING PAN`, `REVERB` |
| Effects — send | `0xA892C` | `REVERB`, `CHORUS`, `FLANGER`, `DELAY` |
| Advanced playback | `0xB38E8` | `PATCHED PHRASE`, `SLICED SAMPLES` |
| GM drum names | `~0xA6BD0` | Full GM drum map: `Bass Drum 1` → `Open Triangle` |
| LFO waveforms | (nearby) | `SINE`, `TRIANGLE`, `PEAKY TRIANGLE` |
| Pad MIDI assign | (nearby) | `NOTE`, `PITCH BEND`, `CONTROL CHANGE`, `PROGRAM CHANGE`, etc. |
| File system | `~0x8DC0` | `Detected FAT12/16/32 volume`, `OS file searching....` |
| Error messages | (bootblock) | `Flash erasing`, `Flash writing`, `Completed`, `system halt` |

---

## 6. Bootblock Detail

The bootblock (`0x800–0xA300`) is a standalone flash update utility. It:
1. Checks for a CompactFlash card at boot
2. Searches for a valid OS file (FAT12/16/32)
3. **[CORRECTED]** Validates the OS file with `memcmp(hdr,"MPC1000",7)` and a CRC-32
4. Erases and re-flashes the main OS region
5. Falls back to emergency mode or SODIMM memory check mode if needed

Key bootblock strings:
```
"MPC1000 BootBlock Ver:%d.%02d"
"Boot on emergency mode"
"Boot on SODIMM memory check mode"
"A CompactFlash card isn't inserted."
"Flash erasing......  Flash writing......%d/%d"
"ERROR : Flash can't write.(boot)"
"current os start after 5sec."
```

The bootblock is the **recommended starting point** for your custom OS project — it's small, self-contained, and understanding it gives you the hardware initialization sequence and flash memory map.

---

## 7. Exception / Interrupt Vectors

The SH3 uses a VBR (Vector Base Register) based interrupt table. These exception handler strings are present, confirming SH3:

```
TLB miss/invalid (read)
TLB miss/invalid (write)
TLB miss/Address error in repeat loop
Initial page write
TLB protection violation (read/write)
CPU Address error (read/write)
Unconditional trap (TRAPA instruction)
Illegal general instruction exception
Illegal slot instruction exception
User breakpoint trap
DMA address error
```

**[CORRECTED — found]** VBR is set at `0xA000090C` (`ldc r2,vbr`, `r2 =
0xA0000000`), so the vector table is at the base of flash: `VBR+0x100`
(general exception), `VBR+0x400` (TLB miss), `VBR+0x600` (interrupt). All
three jump to one handler at `0xA00048A0`.

---

## 8. Recommended Toolchain

### Disassembly / Analysis
- **Ghidra** (free, NSA) — has SH3 support
  - Load `mpc1000_jv316.bin` as **raw binary**
  - Processor: `SH-3 LE` (little-endian)
  - Base address: **`0xA0000000`** **[CORRECTED]** — confirmed by the reset
    vector and by the OS header's load-address field (`0xA0010030`). Do not
    use `0x8C000000`; that is SDRAM, not flash.
  - Mark `0xA0000800` (bootblock) and `0xA0010030` (OS) as code entry points
  - Or just run `tools/ghidra_load_mpc1000.py`, which does all of this
  - Define the string table region as data

- **sh-elf-objdump** for quick CLI disassembly

### Cross-compilation
```bash
# Install SH3 cross-compiler
apt install gcc-sh-linux-gnu   # or build sh-elf-gcc from source
# Target: sh3-elf or sh-elf with -m3 flag
```

### Reference docs
- **SH7727 Hardware Manual** (Renesas) — peripheral register map, DMA, timers, LCD, I²S
- **SH-3 Software Manual** (Renesas) — instruction set reference
- Search: "SH7727 datasheet" or "HD6417727" (Hitachi part number)

---

## 9. Suggested Investigation Order

1. **Bootblock** (`0x800–0xA300`)  
   Understand hardware init, flash map, CF card interface. Smallest isolated chunk.

2. **Exception vector table**  
   Find VBR setup (`LDC` instruction), map all interrupt handlers.

3. **String cross-references**  
   In Ghidra: find `xrefs` to the version string at `0xA64F8` → traces back to the OS init/display function. Good anchor point.

4. **Sequencer engine**  
   Cross-ref `SEQUENCE MEMORY` string at `0xA7118`. The sequencer is the heart of the MPC; understanding its data structures unlocks everything.

5. **Sample playback**  
   Cross-ref `WITH SAMPLE` / `SLICED SAMPLES` / `PATCHED PHRASE`. The DSP extensions on the SH7727 are likely used here.

6. **UI/screen rendering**  
   Cross-ref `TAP TEMPO`, pad bank strings. The MPC1000 uses a 240×64 LCD; finding the framebuffer address gives you the display subsystem.

7. **MIDI engine**  
   Cross-ref MIDI string block at `0xA8138`.

---

## 10. Notes for Claude Code Session

- The binary is SH3 little-endian — confirm Ghidra is set to `SH-3 LE` before any analysis
- **[CORRECTED]** It is specifically an SH3-**DSP** part: the bootblock uses the
  on-chip X/Y data memories at `0xA5007000` and `0xA5017000`
- Function prologue to search: bytes `22 4F` (STS.L PR,@-R15) — 1,822 identified
- The "code" sections have entropy ~7.1 (not encrypted, just dense SH3 bytecode)
- Strings are NOT encrypted — entire UI string table is readable ASCII
- The file appears to be a flat binary dump, not ELF — no section headers, load as raw
- Two `MPC1000BOOT` strings: `0x20` (main header) and `0x8DBC` (inside bootblock code)
- **[CORRECTED]** `MPC1001 JJ OS2XL` is *not* what the bootblock validates.
  The bootblock checks `memcmp(header, "MPC1000", 7)` and a CRC-32 over the
  image, and nothing else. The `MPC1001 JJ OS*` strings are used by the main
  OS to identify JJOS variants. See `docs/IMAGE_FORMAT.md`.

---

*Handoff generated from Claude analysis session, September 18 2026*
