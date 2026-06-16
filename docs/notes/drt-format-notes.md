# DaVinci Resolve Timeline (`.drt`) Format Notes

`.drt` is the file DaVinci Resolve writes from **Timelines → Export → Timeline
(.drt)**. The scripting API can import and export it (`MediaPool.ImportTimeline
FromFile` / `Timeline.Export`), but several things you may want — flattening
compounds without losing speed ramps, remapping subtitles to source record
timecode, reading a clip's real frame rate — are not reachable through the
scripting API and have to be done on the file itself.

These notes are reverse-engineered from real project files. They are **not**
an official spec; field names and layout can change between Resolve versions.
Treat a `.drt` as opaque unless you have verified the structure on the same
build you are editing, and always keep a copy of the original.

> Source-media safety still applies: editing a `.drt` rewrites *timeline*
> metadata only. Never use this as a path to alter or re-encode camera
> originals.

## Container Layout

A `.drt` is a **ZIP archive** (no compression header magic beyond the normal
ZIP one). Typical members:

```
project.xml                     # project-level wrapper
SeqContainer/<uuid>.xml         # one XML per sequence:
                                #   - the main timeline
                                #   - one per compound clip it contains
MediaPool/ ...                  # media-pool item references
```

- The **main timeline** is one `SeqContainer/<uuid>.xml`; every **compound
  clip** used in it is its own `SeqContainer/<uuid>.xml`.
- A clip entry that is itself a compound carries `<Sequence>UUID</Sequence>`;
  resolve that UUID to `SeqContainer/UUID.xml` to descend into the compound.
- Video clip entries are `Sm2TiVideoClip`, audio entries `Sm2TiAudioClip`,
  generated items (titles, subtitles) `Sm2TiGenerator`.

## Non-Standard XML — Do Not Feed To A Strict Parser

The XML uses Resolve-internal tag/label tokens containing `::`, e.g.
`ListMgt::...` and `Sm2Clip::dbid`. A `::` is illegal in an XML element name,
so `ElementTree` / `lxml` will **raise on parse**.

Work on the file as text, or escape the `::` tokens to a placeholder before
parsing and restore them on write. Binary/opaque fields are stored as hex
(often UTF-16 blobs) — **preserve them byte-for-byte**; do not decode-and-
re-encode, or you will corrupt the timeline.

## Key Fields

### `MediaFrameRate` — IEEE double, **little-endian**, hex-encoded

The clip's source frame rate is an 8-byte IEEE-754 double stored as a hex
string, in **little-endian** byte order (not big-endian as the leading zeros
suggest):

```python
import struct
def frame_rate(hexstr: str) -> float:
    return struct.unpack("<d", bytes.fromhex(hexstr))[0]

frame_rate("00000000000049400000000000000000")  # -> 50.0
frame_rate("00000000000039400000000000000000")  # -> 25.0
```

Decoding big-endian (`">d"`) yields garbage / `None`. (The block is 16 hex
bytes here because two doubles are concatenated; the first 8 are the rate.)

### `MediaTimemapBA` — variable-speed (retime) curve

- A **zstd-compressed binary blob** stored as hex. An identity (no retime)
  timemap is tiny (~18 bytes); a complex speed ramp is larger (~2 KB).
- The curve's domain is **source time in seconds, frame-rate-agnostic**, and is
  **independent of which media the entry references**. This is the key to
  lossless flattening (below).
- When decompressing, use **one-shot** `zstd.decompress(blob)`. The streaming/
  `.flush()` interface has an EOF edge case that silently yields an empty frame
  and breaks the downstream protobuf parse.

### `MediaStartTime` — source record timecode of frame 0

On the `Sm2TiAudioClip` of the dialogue track (`MediaTrackIdx=0`),
`MediaStartTime` is the **embedded camera record timecode of the source's
frame 0, in seconds** (absolute time-of-day). Combined with the timeline frame
fields it lets you map any timeline position back to the on-set record TC:

```
record_tc_seconds = MediaStartTime + (subtitle_frame - clip.Start + clip.In) / project_fps
```

where `Start` (timeline position), `In` (offset into the source), and
`Duration` are **timeline frames** at the project frame rate.

### Subtitles — `Sm2TiGenerator PrettyType=Subtitle`

Subtitle text and timing live in `Sm2TiGenerator` items with
`PrettyType=Subtitle`. When harvesting them, filter out: the empty
`Name=="Subtitle"` placeholder blocks, residual items outside the content
range, and exact `(Start, Duration, Name)` duplicates across tracks.

### `pLmVerTable` — color version history

Stores the grade version history for the entry (which CDL/DRX was applied).
Preserve it when rewriting an entry so the color-version audit trail survives.

## Recipe: Flatten Compounds Without Losing Speed Ramps

Resolve's API cannot set a clip's variable speed, and FCPXML import re-wraps
any `<timeMap>` clip back into a compound (see the `api_truth.py` entry
"MediaPoolItem variable speed / FCPXML timeMap import"). A GUI *Decompose*
also drops the speed curve. The file-level route preserves everything:

1. In the main sequence XML, find each compound clip entry (`<Sequence>` set).
2. Repoint it at the underlying source: change `<MediaRef>` from the compound's
   UUID to the source MediaPoolItem's UUID and add the source `<MediaFilePath>`.
3. **Leave `MediaTimemapBA` untouched** — because it is seconds-domain and
   media-independent, the ramp keeps working against the new source.
4. Preserve `pLmVerTable` so the grade version metadata is retained.
5. Re-zip and import.

This was used in production to flatten an 87-clip timeline with 33 curve-based
speed ramps to zero nested compounds with no visible drift.

Two caveats found the hard way:

- **Conform timing.** Right after import, a frame-diff against the original can
  falsely flag clips as wrong while Resolve is still conforming/caching the
  newly linked media asynchronously. Re-test after media settles (a settled
  60-frame MAD was ~1, i.e. visually identical).
- **Color inside a compound is unrecoverable.** Grades done on a clip *inside*
  a compound cannot be read back through any API or the file. Copy the grade
  out to the source clip (GUI CopyGrades) before flattening, or plan to re-grade.

## Cross-Process Cleanup Ordering (data-loss trap)

If you import a `.drt` and then, **in the same script/session**, run a
media-pool "junk cleanup" that deletes unused compounds, the freshly imported
timeline's compounds may not be in your protect-set yet (the timeline is not
fully indexed), so cleanup deletes clips still in use and corrupts the
timeline. Do import + edit + **SaveProject** first, then run cleanup as a
**separate** step after the timeline is indexed.
