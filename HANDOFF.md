# MPC1000 Custom OS — Reverse Engineering Handoff
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
| Section 2 | `0x010000–0x0113FF` | ~5 KB | Unknown — possibly init stubs or interrupt dispatch |
| **Main OS code** | `0x011500–0x0AC5FF` | **~620 KB** | Core JJOS — sequencer, sampler, UI, MIDI, effects |
| String/data tables | `0x0AD600–0x0AF2FF` | ~7 KB | UI strings, MIDI name tables, effect names |
| Additional data | `0x0AF400–0x0B74D8` | ~27 KB | Audio tables, patch data, more config |

### Key File Header Fields (offset 0x0)

```
Bytes 0–3:   01 D0 2B 40  — magic / version marker
Bytes 4–7:   09 00 00 00
Bytes 8–11:  00 08 00 A0  — load address hint: 0xA0000800
Bytes 0x20:  "MPC1000BOOT" — bootblock identifier string
```

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
| Function entry points (`STS.L PR,@-R15` prologue) | **1,822** |
| RTS (return) instructions | **2,424** |
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
3. Validates the OS file against magic strings (`MPC1001 JJ OS2XL`, etc.)
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

The VBR is set early in the boot sequence. Finding where it gets set (`LDC Rn, VBR` instruction) will give you the interrupt table base address.

---

## 8. Recommended Toolchain

### Disassembly / Analysis
- **Ghidra** (free, NSA) — has SH3 support
  - Load `mpc1000_jv316.bin` as **raw binary**
  - Processor: `SH-3 LE` (little-endian)
  - Base address: `0x8C000000` (SH3 cached P1 RAM, standard for SH7727)
  - Or try `0xA0000000` (uncached P2) — check which matches the header hint `0xA0000800`
  - Mark `0x8C000800` (after header) as code entry point
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
- Function prologue to search: bytes `22 4F` (STS.L PR,@-R15) — 1,822 identified
- The "code" sections have entropy ~7.1 (not encrypted, just dense SH3 bytecode)
- Strings are NOT encrypted — entire UI string table is readable ASCII
- The file appears to be a flat binary dump, not ELF — no section headers, load as raw
- Two `MPC1000BOOT` strings: `0x20` (main header) and `0x8DBC` (inside bootblock code)
- JJOS stores its own identifier string `MPC1001 JJ OS2XL` — this is what the bootblock validates on CF card before flashing

---

*Handoff generated from Claude analysis session, September 18 2026*
