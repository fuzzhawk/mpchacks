# MPC1000 Custom OS

Reverse engineering the Akai MPC1000 firmware (via JJOS 3.16) with the goal of
building a custom OS for the machine.

## Where things stand

The hardware and the firmware container are understood well enough to build
and flash a custom image. The application layer — sequencer, sampler, UI,
audio path — is mapped but not yet reverse engineered.

**Solved:**

- CPU, endianness and load address, proven from the binary
- Full memory map, including the on-chip X/Y RAM the bootblock runs from
- The reset-to-OS boot sequence, register by register
- SDRAM auto-sizing from the SODIMM SPD
- NOR flash command set, sector size and partition layout
- **The OS image format and its CRC-32** — `tools/mpcimg.py` rebuilds the
  stock image byte-for-byte, so we can produce images the stock bootblock
  will accept
- **The OS's run-time relocation** — the OS copies itself into SDRAM and runs
  there, which is why string cross-references appeared to be missing. With the
  mapping applied, they work, and the code is navigable
- The audio DSP overlay is located: the last 11.6 KB of the image is copied
  into the SH3-DSP's on-chip X/Y memories

**Not yet solved:** display driver, CompactFlash driver, audio codec path,
MIDI UART, pad/key scanning, and the whole application layer.

## Read these first

| Document | Contents |
|---|---|
| [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) | CPU, memory map, peripherals, flash — with the evidence for each claim |
| [`docs/BOOT.md`](docs/BOOT.md) | The bootblock, step by step, from reset to OS entry |
| [`docs/IMAGE_FORMAT.md`](docs/IMAGE_FORMAT.md) | The OS image header and CRC-32, and how to build a valid image |
| [`docs/QLINK_FADERS.md`](docs/QLINK_FADERS.md) | Q-link faders -> sample start/end: hook points, patch space, and what reverse actually costs |
| [`docs/ROADMAP.md`](docs/ROADMAP.md) | What to do next, in order |
| [`HANDOFF.md`](HANDOFF.md) | First-session notes. Partly superseded — corrections are marked inline |

## Quick facts

| | |
|---|---|
| CPU | Renesas SuperH **SH3-DSP**, little-endian, 16-bit instructions (SH7727, inferred) |
| **Load address** | **`0xA0000000`** (P2, uncached). File offset N = `0xA0000000 + N` |
| Bootblock entry | `0xA0000800` |
| OS entry | `0xA0010030` |
| VBR | `0xA0000000` |
| SDRAM | `0x88000000` (area 2) and `0x8C000000` (area 3) |
| On-chip XRAM / YRAM | `0xA5007000` / `0xA5017000`, 8 KB each |
| Flash | AMD command set, 16-bit, 64 KB sectors. Sector 0 = bootblock, sectors 1–13 = OS |
| Max OS image | `0xD0000` = 851,968 bytes |
| OS run-time base | flash offset + `0x8842B644` (OS text starts at `0x8843B644`) |
| DSP overlay | flash `0x0B3DFC`–`0x0B74D8` -> on-chip X/Y RAM |
| Analyzed binary | JJOS 3.16, built 2015-02-13 |

## Tools

```bash
# check / build / split OS images
python3 tools/mpcimg.py verify  mpc1000_jv316.bin
python3 tools/mpcimg.py extract mpc1000_jv316.bin -o os.bin
python3 tools/mpcimg.py build   payload.bin -o MYOS.BIN --version 1.00

# annotated disassembly (resolves literals, names SH-3 registers, inlines strings)
python3 tools/disasm.py mpc1000_jv316.bin 0x800 60
python3 tools/disasm.py mpc1000_jv316.bin 0xa0008924 --func

# strings with the offsets of the code that loads them
python3 tools/strings_xref.py mpc1000_jv316.bin REVERB

# patch the OS: verify expected bytes, apply, recompute size + CRC
python3 tools/mpcpatch.py check mpc1000_jv316.bin patches/00-boot-proof.patch
python3 tools/mpcpatch.py apply mpc1000_jv316.bin patches/00-boot-proof.patch -o QFADER.BIN
```

Patches refuse to apply unless the bytes they expect are actually present, and
writes into the bootblock (flash `0x000000`-`0x00FFFF`) are refused outright —
a bad bootblock write cannot be recovered on this machine.

| File | Purpose |
|---|---|
| `tools/sh3.py` | SH-3 decoding, literal resolution, register names, recursive-descent code discovery |
| `tools/disasm.py` | Annotated disassembler CLI |
| `tools/strings_xref.py` | Strings plus the instructions that reference them |
| `tools/mpcimg.py` | OS image verify / build / fix / extract |
| `tools/mpcpatch.py` | Apply verified byte patches, fix the CRC, emit a flashable image |
| `tools/ghidra_load_mpc1000.py` | Ghidra setup: memory blocks, labels, entry points |
| `analyze.py` | Original first-session script (kept for reference) |

`tools/disasm.py` needs `pip install capstone` (Capstone 5+, which has
`CS_ARCH_SH`). The rest is pure Python.

## Ghidra

Import `mpc1000_jv316.bin` as **Raw Binary**, language **SH-3 / 16 / little**,
base address **`a0000000`**, then run `tools/ghidra_load_mpc1000.py` from the
Script Manager. It creates the SDRAM / XRAM / YRAM / peripheral blocks, labels
the vectors and the known routines, and disassembles the entry points.

## Legal note

`mpc1000_jv316.bin` is third-party firmware (JJOS, by Japanese developer "JJ"),
included here as the analysis subject. The goal of this project is an
independent, clean OS for hardware people own — not redistribution of, or a
derivative of, JJOS. Anything written here should be an original
implementation informed by hardware facts (register addresses, bus timings,
the image container), not copied JJOS code.
