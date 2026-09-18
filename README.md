# MPC1000 Custom OS

Reverse engineering and custom OS development for the Akai MPC1000.

## Start here

Read [`HANDOFF.md`](HANDOFF.md) — full findings from initial binary analysis session.

## Quick facts

- **CPU:** Renesas SH7727 (SH3-DSP), little-endian, 16-bit instructions
- **Binary analyzed:** JJOS 3.16 (`mpc1000_jv316.bin`)
- **Functions identified:** 1,822
- **Ghidra load address:** `0x8C000000`, processor `SH-3 LE`

## Files

| File | Description |
|---|---|
| `HANDOFF.md` | Full analysis findings — read first |
| `mpc1000_jv316.bin` | JJOS 3.16 firmware binary |
| `analyze.py` | Python analysis utilities (section map, disassembler, string finder) |

## Usage

```bash
python3 analyze.py mpc1000_jv316.bin
```

## References

- SH7727 Hardware Manual (Renesas / Hitachi HD6417727)
- SH-3 Software Manual (instruction set)
- [Ghidra](https://ghidra-sre.org/) — load binary as Raw, SH-3 LE, base `0x8C000000`
