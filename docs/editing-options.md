# Fonts, looks and master exports

The campaign work made three things obvious: the type has to be chosen per
platform, a hook is a designed card rather than a line of text, and a clip is
only finished once it is encoded to a delivery spec. Those are now part of the
library, the Studio and the web pipeline.

## Fonts

Three Open Font License faces ship in `clipsai/fonts` (Montserrat ExtraBold,
Archivo Black, Noto Serif Bold), plus the common system faces (Arial, Arial
Black, Impact, Georgia).

```python
from clipsai.typography import available_fonts, font_family, load_font, resolve_font

available_fonts()            # menu entries: key, label, family, bundled
resolve_font("archivo-black")  # path for Pillow
font_family("archivo-black")   # family name for libass
load_font(72, "noto-serif")    # PIL font
```

Bundled faces are passed to libass with `fontsdir`, so a preview and a burn use
the same file instead of silently falling back to DejaVu. A preset may also name
any family installed on the host (`"Helvetica Neue"`); the caption renderer
passes the name through unchanged.

## Caption presets and per-render overrides

| preset | look |
| --- | --- |
| `bold` | white caps, yellow active word (default) |
| `kinetic` | Montserrat ExtraBold 52 px, yellow active word that pops, 5-word lines |
| `shorts` | larger kinetic type for fast cuts |
| `clean` | sentence case, thin outline, no highlight |
| `lime` | lime active word |
| `pill` | purple box |
| `boxed` | black type in a yellow box |
| `impact` | Archivo Black caps on a thick outline |
| `editorial` | Noto Serif Bold, sentence case, documentary feel |
| `oneword` | one giant word at a time |

Any preset can be overridden for one render without defining a new class:

```python
from clipsai import build_cues, burn_captions

cues = build_cues(transcription, 12.0, 42.0, preset="kinetic")
burn_captions(
    "clip.mp4", cues, "clip_captioned.mp4",
    preset="kinetic",
    font="archivo-black",
    font_size=58,
    position="center",   # bottom | center | top
    pop=True,            # scale the spoken word
)
```

`position` selects the ASS anchor and its default margin: bottom (2, 110 px),
center (5), top (8, 120 px) for a 1080×1920 frame. Sizes and margins scale with
the target height.

## Hook cards

`render_hook_png` now takes a kicker (a smaller question above the hook), a font,
and the campaign `card` style: a dark plate, a yellow rule across the top, the
kicker in white and the payoff in yellow.

```python
from clipsai.ai.hooks import burn_hook, render_hook_png

image = render_hook_png(
    "Coolest white boy since Mac Miller",
    width=1080,
    style="card",
    kicker="Who knew Ad-Rock's son could rap?",
    font="montserrat-extrabold",
)
image.save("hook.png")
burn_hook("clip.mp4", "Coolest white boy since Mac Miller", "out.mp4",
          style="card", position="upper", font="montserrat-extrabold",
          kicker="Who knew Ad-Rock's son could rap?",
          start=0.0, end=4.0, fade=0.2)
```

`position` is one of `top`, `upper`, `center`, `lower`, `bottom`; `upper` is the
17% band used on the campaign clips. `start`/`end` keep the hook an opening
card instead of covering the whole clip, and `fade` softens the edges.

## Master export profiles

A profile is size, frame rate, bitrate, audio and loudness. `shorts` is the
campaign master: 1080×1920, 60 fps, H.264 ~12 Mbps CBR, AAC 48 kHz 192 kbps,
−14 LUFS, true peak −1.5 dBTP.

| key | target |
| --- | --- |
| `shorts` | 1080×1920 · 60 fps · 12 Mbps |
| `reels` | 1080×1920 · 30 fps · 10 Mbps · ≤ 90 s |
| `tiktok` | 1080×1920 · 30 fps · 10 Mbps |
| `youtube` | 1920×1080 · 30 fps · 12 Mbps |
| `square` | 1080×1080 · 30 fps · 8 Mbps |

```python
from clipsai.render import export_clip, finish_clip, verify_output

export_clip("clip.mp4", "master.mp4", "shorts", pad="blur", grade="warm")
report = verify_output("master.mp4", "shorts")
report["ok"]           # every check passed
report["checks"]       # resolution, fps, codecs, duration, LUFS, true peak
```

`pad` controls what happens when the source aspect does not match:

* `blur` (default) fills the frame with a blurred copy of the picture — no black
  bars, and the same trick the 4:5 masters needed;
* `crop` fills the frame and crops the edges;
* `black` fits the picture inside a black frame.

`finish_clip` is the one-pass master: grade → punch-ins → hook → captions, then
the platform encode. Burning the hook and captions in the same encode as the
grade avoids stacking two or three lossy generations.

```python
finish_clip(
    "clip_vertical.mp4", "clip_final.mp4", "shorts",
    pad="blur", grade="punchy",
    punch_ins=[1.0, 3.5],              # 102% → 108% cadence
    cues=cues, caption_preset="kinetic",
    hook_png="clip_hook.png", hook_seconds=4.0,
)
```

## Colour, punch-ins and crop

`GRADES` provides `none`, `warm`, `cool`, `punchy`, `film` and `mono`.
`build_punch_in_filter` turns a list of seconds into the campaign cadence.
`CropWindow(top, bottom, left, right)` (or the string `"0,0.28,0,0"`) removes a
fraction of each edge before reframing — the fix for sources with burned-in app
captions or a padded 4:5 band.

```python
from clipsai.render import CropWindow, finish_clip

finish_clip("reel.mp4", "master.mp4", "reels",
            crop=CropWindow(bottom=0.28), pad="blur")
```

## Effect types

The AI edit planner (and `build_filter_string`) now understands `warm`, `cool`,
`grain` and `shake` in addition to `zoom_in`, `punch_in`, `zoom_out`,
`zoom_pulse`, `color_pop`, `bw_moment`, `flash` and `vignette`. Zoom is still
refused when captions are already burned, because the zoom would crop them;
in the pipeline, use the master export stage so zooms and captions are composed
in the right order instead.

## In the Studio

* **Output & captions**: caption font, position, size (0 = preset), pop toggle.
* **Master & look**: export profile, colour grade, punch-in cadence, source crop.
* **Packaging & publishing**: hook style, position, font, on-screen seconds and
  an optional kicker.

The `Master export` stage runs after packaging and writes `clip_<n>_final.mp4`;
publishing prefers that file. The web pipeline exposes the same fields through
`GET /api/pipeline/options` and `PUT /api/pipeline/jobs/<id>/config`.
