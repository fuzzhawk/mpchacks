# Roadmap to a custom MPC1000 OS

The order here is chosen so that each step is testable on real hardware before
the next one depends on it.

## Phase 0 — recoverability (do this first)

The bootblock in sector 0 is the only thing that can flash the machine. If it
survives, any bad OS image is recoverable by putting a good `*.bin` on a CF
card. So:

- **Never write sector 0.** Avoid the `OS/BOOT update ... from EX-MEM` path
  entirely.
- Keep a known-good JJOS `.bin` on a CF card at all times.
- Confirm you can re-flash stock JJOS from CF *before* flashing anything of
  your own.

Also worth doing: dump your own machine's flash and compare against
`mpc1000_jv316.bin`, so you know your bootblock version.

## Phase 1 — get arbitrary code running

Everything needed for this is already known.

1. Build an `sh-elf` toolchain (`--target=sh-elf`, `-m3` — or `-m3e`/DSP if you
   want the X/Y memory). Plain SH-3 is enough to start.
2. Link a flat binary at **`0xA0010030`**. No relocation, no ELF — the
   bootblock copies the image straight into flash and jumps to the load
   address.
3. Wrap it: `python3 tools/mpcimg.py build payload.bin -o MYOS.BIN`.
4. Put `MYOS.BIN` on a FAT-formatted CF card, hold the OS-update key
   combination at power-on, and accept the prompt.

**First target:** reimplement the panic handler. Set VBR, install stubs at
`+0x100/+0x400/+0x600`, and print `PC/SR/TEA` plus a stack dump. That is the
debug channel for everything after this, and JJOS's own version at
`0xA00048A0` shows exactly what to produce.

Bring-up order inside your startup code should mirror `docs/BOOT.md`: stack
into YRAM, FRQCR, BSC, TMU, PFC, VBR, then SDRAM.

Note that the bootblock has already initialised all of that before it jumps to
you. A first image can therefore be almost trivial — it inherits a working
bus, running timers and configured pins. Do the full init yourself only once
you know the rest works.

## Phase 2 — see something

Nothing is output-capable yet, so this is the real unblocking step.

- **Display.** 240×64 graphic LCD. Trace the bootblock's `print_line` at
  `0xA00022D0` down to the hardware; also look at the GPIO routine at
  `0xA00026D4`, which toggles `0xA4000162` and port E bits and is a candidate
  for backlight/reset control. Find the framebuffer and the font table.
- **Keys and pads.** The ADC is enabled at boot (`ADCSR = 0x3B`), so at least
  the analog controls (slider, pad velocity) go through it. Scan matrices will
  be on the port pins configured by `PCCR`/`PDCR`/`PECR`/`PFCR`/`PGCR`.

## Phase 3 — storage

- CompactFlash. JJOS mounts FAT12/16/32 with C++ classes whose RTTI names
  survive in the image (`AFileSystem`, `AFat12Volume`, `AFat16Volume`,
  `AFat32Volume`), so those are good anchors. `0xB6000004` is the only
  external-bus address the bootblock references and is the leading candidate
  for the CF task-file window — confirm it.

## Phase 4 — audio

The hard part, and the reason the machine exists.

- **Start with the DSP overlay.** Flash `0x0B3DFC`–`0x0B74D8` — the last
  11.6 KB of the image — is copied into the SH3-DSP's on-chip X and Y
  memories at start-up. Nothing else in the system is placed there, and the
  X/Y memories exist precisely to feed the DSP unit, so this is the audio
  engine. It is small, self-contained, and disassembles as
  `tools/disasm.py mpc1000_jv316.bin 0xb4768 ...`.
- Find the codec/DAC path and the sample clock. The SH7727's on-chip D/A is
  enabled at boot but is far too slow for audio; expect an external codec on a
  serial audio interface, fed by DMA.
- Identify the DMA channels and the audio interrupt.
- Then: voice mixing, pitch shifting, envelopes.

## Phase 5 — MIDI, sequencer, UI

Anchor each with `tools/strings_xref.py`, which resolves through the
run-time relocation so the offsets it prints are real call sites:

| Subsystem | Strings to cross-reference |
|---|---|
| MIDI | `SYNC`, `PITCH BEND`, `CONTROL CHANGE`, `PROGRAM CHANGE` |
| Sequencer | `SEQUENCE MEMORY`, `Track01` |
| Sampler | `WITH SAMPLE`, `SLICED SAMPLES`, `PATCHED PHRASE` |
| Effects | `BIT GRUNGER`, `4 BAND EQ`, `COMPRESSOR`, `FLYING PAN` |
| Pads | `PAD BANK A/B/C/D`, `NOTE REPEAT` |

MIDI is 31250 baud on one of the SH-3's serial channels; finding the SCI/SCIF
block that gets that bit rate will identify it quickly.

## Compatibility worth preserving

Even a from-scratch OS is much more useful if it reads existing files. The
MPC1000's on-disk formats (`.PGM`, `.SEQ`, `.ALL`, `.WAV`) are documented by
the community and are also described by the string tables around `0xAA000`
(`MPC1000 SEQ 1.00`, `MPC1000 ALL 1.00`, `MPC1000 PGM 1.00`).
