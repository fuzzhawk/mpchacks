# MPC1000 OS image format

This is the format the stock bootblock accepts. Getting it right is the whole
gate between "my code" and "my code running on the machine" — the bootblock
will refuse to flash anything that fails these checks.

Fully reverse-engineered and **verified**: `tools/mpcimg.py` rebuilds
`mpc1000_jv316.bin`'s OS image byte-for-byte from its payload.

## Header

32 bytes at the start of the image (flash offset `0x010000`, virtual
`0xA0010000`). All fields little-endian.

| Offset | Size | Field | JJOS 3.16 value |
|---|---|---|---|
| `0x00` | 8 | magic, `"MPC1000\0"` | `MPC1000\0` |
| `0x08` | 1 | version major | `0x03` |
| `0x09` | 1 | version minor | `0x10` (printed as `%02d` -> "16") |
| `0x0A` | 2 | version build | `0x0000` |
| `0x0C` | 4 | image size, **including this header** | `0x000A74D8` |
| `0x10` | 4 | CRC-32 | `0x40705C18` |
| `0x14` | 4 | load / entry address | `0xA0010030` |
| `0x18` | 8 | zero | |
| `0x20` | 2 | build year | `0x07DF` = 2015 |
| `0x22` | 1 | build month | `0x02` |
| `0x23` | 1 | build day | `0x0D` = 13 |
| `0x24` | 12 | zero | |

So JJOS 3.16 was built 2015-02-13, and the OS proper begins right after the
header at `0xA0010030`.

The version fields feed the bootblock's `%s OS version : %d.%02d` and
`%s OS version : %d.%02d.%04d` messages, which is how it shows you "current"
vs "new" before asking `Do you want to write this OS ?`.

## Checksum

**Plain CRC-32** — the standard reflected one, polynomial `0x04C11DB7` /
`0xEDB88320` — taken over the entire image with the 4 checksum bytes treated
as zero.

```python
import zlib
img = bytearray(open('os.bin','rb').read())
img[0x10:0x14] = b'\0\0\0\0'
crc = zlib.crc32(bytes(img[:size_field])) & 0xFFFFFFFF
```

The bootblock does it in three calls at `0xA00019A8`–`0xA00019E4`: bytes
`0x00..0x0F`, then four literal zero bytes standing in for the checksum field,
then `0x14..size`, seeded with `0xFFFFFFFF`, and finally compares the stored
value against `~crc`. Inverting a `0xFFFFFFFF`-seeded running CRC is exactly
the standard CRC-32 final step, hence plain CRC-32. The constant `0xEDB88320`
appears in the bootblock's literal pool, confirming it independently.

## What the bootblock actually checks

From the validator at `0xA0001998` onward:

1. `memcmp(header, "MPC1000", 7)` — note **7 bytes**, so the 8th byte is not
   compared.
2. The CRC-32 above.

That is all. It does **not** verify the load address, refuse a lower version
number, or sign anything. Any image with the right magic and a correct CRC
will be flashed.

Two size limits apply, both from the flash geometry:

- The image must fit in the 13 sectors the updater erases: **`0xD0000` =
  851,968 bytes max**.
- The `size` field must cover the real payload, since it bounds the CRC.

## Delivering an image

**[verified]** from the bootblock's strings and code: it mounts the
CompactFlash card (FAT12, FAT16 and FAT32 are all supported — `AFat12Volume`,
`AFat16Volume`, `AFat32Volume`), searches the root for **`*.bin`**, prints
`'%s' was found.`, shows the current and new version numbers, and prompts:

```
Do you want to write this OS ?
OK(REC) , CANCEL(PLAY or STOP)
```

Pressing REC erases sectors 1–13 and writes the image, reporting
`Flash erasing......` and `Flash writing......%d/%d`, then `Completed`.

There is a separate `Boot on OS/BOOT update mode from EX-MEM` path that takes
the new bootblock from `0xA1000000` and the new OS from `0xA1010000`, and can
rewrite sector 0 itself (`Flash erasing(boot area)......`, 128 × 512-byte
writes). Rewriting sector 0 is the one genuinely unrecoverable operation on
this machine — a bad bootblock leaves nothing to flash a fix from. A custom OS
has no reason to touch it.

## Tooling

```bash
# inspect / check an image or a full flash dump
python3 tools/mpcimg.py verify mpc1000_jv316.bin

# split the OS image out of a full dump
python3 tools/mpcimg.py extract mpc1000_jv316.bin -o os.bin

# wrap your own payload so the bootblock will accept it
python3 tools/mpcimg.py build payload.bin -o MYOS.BIN --version 1.00

# recompute size + CRC after patching an existing image
python3 tools/mpcimg.py fix patched.bin
```

`payload.bin` is raw code linked to run at `0xA0010030`.
