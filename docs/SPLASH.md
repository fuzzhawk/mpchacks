# Boot splash: MPC1000.BMP

**JJOS already loads a custom boot splash from the CompactFlash card.** No
firmware patching is needed to change the start-up image — it is a file.

## How it works

**[verified]** The start-up screen is drawn by one function at flash
`0x0186C8`, reached from the OS entry path at `0x0104D0`. It builds the
filename from the strings `"MPC1000"` (flash `0x0A64EC`) and `"BMP"`
(`0x0A64F4`) and looks for it on the card:

- **File found** → the bitmap is drawn full screen at (0,0) and held for
  about three seconds, then start-up continues.
- **File missing** → the usual text splash is drawn instead:
  `MPC1000` at (98,8), the RAM size, and the version banner at (115,28).

The two are mutually exclusive — the image replaces the text splash rather
than appearing alongside it. If you want the OS name visible at boot *and* a
picture, put the name in the picture. `tools/mksplash.py` does.

The file is rejected if it is 512 KB or larger (`0x80000`, checked at
`0x018828`).

## The format

**[verified]** from the parser at flash `0x0162BC`. It is a standard Windows
BMP, but only four header fields are read, and each as a **16-bit**
little-endian value — the upper halves of the 32-bit BMP fields are ignored:

| Byte offset | Field | Required value |
|---|---|---|
| 10 | `bfOffBits` | wherever the pixel data starts (62 for a 1-bpp BMP) |
| 18 | `biWidth` | 240 (clamped to 240 if larger) |
| 22 | `biHeight` | 64 (clamped to 64 if larger) |
| 34 | `biSizeImage` | 2048 |

Everything else — `biBitCount`, `biPlanes`, the palette — is **not read**.
The parser assumes 1 bit per pixel unconditionally.

- Row stride = `biSizeImage / biHeight`, with a floor of 32 bytes. For
  240×64 that gives the correct 32. A file with `biSizeImage = 0` still
  works by falling through to the floor, but set it properly.
- Pixels are most-significant-bit first.
- Rows are consumed from the bottom up, which is normal BMP order, so a
  standard bottom-up BMP displays the right way up.
- A **set** bit writes 0 to the framebuffer and a **clear** bit writes 15.
  The framebuffer takes values 0-15, so the panel is driven with 4 bits per
  pixel even though the source is 1 bpp.

With the usual 1-bpp palette (index 0 black, index 1 white), black artwork on
a white background should come out dark on the display. If it appears as a
negative on real hardware, use the inverted file the build also produces.

## The display itself

**[verified]** The LCD is a **Toshiba T6963C-compatible controller** mapped at
`0xB6000000` (area 5). The command write at flash `0x0049BA` is the textbook
T6963C handshake:

```
a00049be:  mov.l  #0xb6000004,r6   ; command / status port
a00049c0:  mov.b  @r6,r0           ; read status
a00049c2:  and    #3,r0
a00049c4:  cmp/eq #3,r0            ; spin until STA0 and STA1 are both set
a00049c6:  bf     0xa00049c0
a00049c8:  mov.b  r5,@r6           ; write the command byte
```

Requiring `status & 3 == 3` before a command is specific to the T6963C. That
also explains why no font table can be found in the firmware: the controller
has its own character generator ROM, and the OS uses the controller's text
mode for text and graphics mode for waveforms and bitmaps.

## Building one

```bash
python3 tools/mksplash.py -o MPC1000.BMP --text "morningcloak os"
python3 tools/simsplash.py MPC1000.BMP        # decode it the way JJOS will
```

`simsplash.py` reimplements the firmware parser field for field and prints
what the display would show. Run it on any splash before copying it to a
card — a BMP that other software opens happily can still be read as noise by
this parser, because it ignores the bit-depth field.

Copy the result to the **root of the CF card**, named exactly `MPC1000.BMP`.
