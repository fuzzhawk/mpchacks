# Q-Link faders -> sample start/end

Target: make the two Q-link faders set the start and end point of the current
pad's sample, for reverse and granular-loop effects.

Status: **hook points located, engine support for reverse not yet established.**
Read §5 before planning the work — one part of the request needs more than
fader re-routing.

---

## 1. The faders

**[verified]** The OS keeps both fader positions as two 32-bit words in BSS:

| Address | Meaning |
|---|---|
| `0x882102B8` | Q1 current value |
| `0x882102BC` | Q2 current value |

Found via the hardware test screen (`Q1`, `Q2`, `DATA WHEEL`, `F1`-`F6` at
flash `0x0AB880`), which reads them at flash `0x09F728` as `@r12` and
`@(4,r12)` and prints them scaled to 9999.

Ten code sites reference that pair:

| Flash | Role |
|---|---|
| `0x011904` | start-up init |
| `0x023946`, `0x023B76` | ? |
| `0x04FC24`, `0x04FD50` | ? |
| `0x0588AE`, `0x058C8E`, `0x058D68`, `0x058EAC` | **the apply cluster** |
| `0x09F728` | hardware test screen |

The handler at `0x058C80` is the clearest one. It reads Q2, compares against a
cached previous value at `0x8843B7D0`, and only acts on a change — the
classic "fader moved" path, and the natural place to hook:

```
a0058c8e:  mov.l  #0x882102b8,r2      ; fader pair
a0058c90:  mov.l  #0x8843b7d0,r5      ; cached last Q2
a0058c92:  mov.l  @(4,r2),r6          ; r6 = Q2 now
a0058c94:  mov.l  @r5,r2
a0058c96:  cmp/eq r6,r2
a0058c98:  bt     0xa0058d42          ; unchanged -> skip
a0058c9a:  mov.l  #0x66666667,r2      ; divide-by-5 magic
a0058ca2:  dmuls.l r6,r2              ; scale the raw value
a0058ca4:  mov.l  r6,@r5              ; update the cache
```

## 2. There is already a Q-Link assignment framework

**[verified]** JJOS has a Q-Link page with per-pad assignment, a parameter
selector, a Change mode (`NOTE ON` / `REAL TIME`) and `High range:` /
`Low range:` scaling. The UI strings are at flash `0x0A85E4` onward:

```
Q1  Q2  ALL R  RESET  FILTER
Assign Pad:   -   IN    Change:   NOTE ON    REAL TIME
Parameter:   High range:    Low range:
```

That framework is the thing to extend — the scaling, the per-pad assignment
and the real-time/note-on choice already exist.

### The parameter list

**[verified]** 12 entries, 10 bytes each (9 characters plus NUL), at flash
`0x0B2D18` (run-time `0x881C690C`):

| # | Name | | # | Name |
|---|---|---|---|---|
| 0 | `TUNE` | | 6 | `CUTOFF1` |
| 1 | `CUTOFF1+2` | | 7 | `CUTOFF2` |
| 2 | `LAYER` | | 8 | `RESO1+2` |
| 3 | `ATTACK` | | 9 | `RESO1` |
| 4 | `DECAY` | | 10 | `RESO2` |
| 5 | `LEVEL` | | 11 | `PAN` |

The index-to-name lookup is at flash `0x05E132`, and confirms the stride:

```
a005e132:  mov   r6,r2
a005e134:  shll2 r6            ; r6 = index*4
a005e136:  add   r2,r6         ; r6 = index*5
a005e138:  mov.l #0x881c690c,r2
a005e13a:  shll  r6            ; r6 = index*10
a005e13e:  add   r2,r6         ; -> name pointer
```

A second, 9-byte-wide list at `0x0B3579` (`VELOCITY`, `TUNE`, `FILTER`,
`LAYER`, `ATTACK`, `DECAY`) belongs to a different screen.

Because `CUTOFF1  ` and `CUTOFF2  ` are both exactly 9 characters, they can be
relabelled to `START    ` and `END      ` **in place**, with no need to move
or grow anything. Relabelling alone changes nothing functional, though — the
apply path still has to be redirected.

## 3. Sample start and end

**[inferred, needs confirming]** The Trim page's `St:` / `End:` handlers
(flash `0x04E754` and `0x04EB78`) write 32-bit values to **`+0x24`** and
**`+0x28`** of a struct, alongside 16-bit mirrors at `+0x160A`/`+0x160C`/
`+0x160E` of a much larger base:

```
; St:  handler
a004e756:  mov.l r6,@(36,r5)     ; +0x24
; End: handler
a004eb7a:  mov.l r6,@(40,r5)     ; +0x28
```

Still to do: confirm that `r5` is the sample struct, and find where the
playback engine reads those two fields.

## 4. Where new code can go

**[verified]** Three runs of unused zero filler inside the OS text image,
which relocates into SDRAM and is executable. Checked for references: none of
the three has a single literal pointing inside it.

| Flash | Size | Run-time | Refs inside | Refs within 64 B |
|---|---|---|---|---|
| `0x01131C` | 728 B | `0x8843C960` | 0 | **0** |
| `0x01161C` | 472 B | `0x8843CC60` | 0 | 1 |
| `0x01121C` | 216 B | `0x8843C860` | 0 | 1 |

`0x01131C` is the best of them — 728 bytes with nothing referencing anywhere
near it. That is a few hundred SH-3 instructions, far more than a fader hook
needs.

Do **not** use the large zero runs at `0x0B4768` or `0x0B6124`. They look
inviting (6.4 KB and 4.9 KB) but they are zero-initialised working storage
copied into the on-chip X/Y memories — they are variables, not spare room.

The 101,160 bytes of erased flash after the image (`0x0B74D8`-`0x0D0000`) are
**not** free either, in the simple sense: the OS start-up copies itself to
SDRAM using lengths baked into its own code, so growing the image means
patching those bounds too.

## 5. Feasibility: the three parts are not equally hard

The request splits into three pieces with very different costs.

**Faders set start/end for the next hit — achievable.** Everything needed is
located: fader values, the changed-value handler, the parameter framework, the
struct fields, and space for code. This is the part to build.

**Granular by retriggering — comes free with the above.** Hold NOTE REPEAT and
sweep the faders and you get the moving-window stutter that people mean by
granular on an MPC. Each new voice picks up the current window.

**True reverse — needs more than fader routing, and probably new engine code.**
The evidence is against the playback engine supporting it:

- JJOS implements reverse as a **destructive sample edit** (`Edit:REVERSE`,
  flash `0x07873C`, with a `Pressing DO IT will execute the selected edit.`
  confirmation). A playback engine that could run a voice backwards would not
  need to rewrite the sample buffer to offer reverse.

So setting end < start will most likely not play backwards. It will either be
clamped, produce silence, or run the voice pointer off the end of the sample
buffer — the last of which is how you crash the machine. **Do not ship a patch
that lets end go below start until the engine has been read.**

Two ways round it, once the engine is understood:
- *Engine route:* give the voice a signed increment and let the pointer walk
  down. Cleanest result, most work, and the riskiest code to get wrong.
- *Buffer route:* keep a pre-reversed copy of the sample and switch the voice
  to it when the fader crosses over. No engine change, costs RAM, and the
  switch is only clean at a zero crossing or a retrigger.

**Live modulation of a sustaining note also needs the engine.** If the voice
latches start/end at note-on — which is the usual design — moving a fader will
not affect a note already playing. Granular-by-retrigger works regardless;
granular-on-a-held-note does not.

## 6. Next steps, in order

1. **Flash `patches/00-boot-proof.patch`** and confirm the banner changed on
   the machine. This proves build, CRC, CF delivery and boot before any real
   patch is attempted. Keep stock JJOS on a card the whole time.
2. **Read the playback engine.** Find where a note-on builds a voice and which
   fields it latches. That single answer decides whether reverse and held-note
   granular are in scope or need new code.
3. **Confirm the sample struct** — that `r5+0x24`/`r5+0x28` really are start
   and end, and what units they are in (frames, or bytes).
4. **Then** wire the faders, initially clamped so end > start, so a wrong
   guess cannot send a voice pointer out of bounds.
