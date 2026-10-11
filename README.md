# NewEra AI Agent — Beat-Synced Intro Film

A 1.5–3 minute minimalist motion-graphics intro film for **NewEra AI Agent**
([newera.namansoni.in](https://newera.namansoni.in)), cut frame-accurately to
*Life Force* by ptasinski / RJ Pasin.

## Creative direction

Clean motion graphics, not cinematic footage:

| Axis | Decision |
| --- | --- |
| Typography | Single sans-serif family (Inter), tight tracking, optical kerning |
| Palette | Near-black `#08090C` base, paper `#F4F5F7` type, one accent `#4D7CFE` |
| Motion | Cubic/quint ease-in-out only. Nothing linear, nothing bouncing |
| Cuts | Beat-locked, hard cut on transient, no crossfades longer than 6 frames |
| Shapes | Lines, frames, grids, dots, expanding rings, type masks |

## Why this repo is shaped the way it is

The browser sandbox has **no working FFmpeg** (vendored wasm core is absent) and
**no shell**, so nothing can be decoded, measured or encoded locally. All media
work therefore runs on a remote Linux VM (GitHub Actions runner) that has real
`ffmpeg`, `python3`, `numpy` and `librosa`.



audio/bgm.mp3          the supplied soundtrack (source of truth for timing)
tools/analyze_audio.py runs on VM -> analysis/*.json + analysis/AUDIO.md
tools/analyze_ref.py   runs on VM -> analysis/REFERENCE.md + contact sheets
tools/render_film.py   runs on VM -> frames/ -> media/newera-intro.mp4
tools/mix_sound.py     runs on VM -> synthesised impacts/risers mixed under BGM
scenes/scenes.json     authored scene sheet, times taken from measured beat grid
site/                  static player page deployed to Cloudflare Pages



## Timing contract

The film is **data-driven**: `tools/render_film.py` reads
`analysis/beat_map.json` (measured) and `scenes/scenes.json` (authored) and
renders every frame deterministically. No timing is hardcoded in the renderer,
so a re-analysis automatically re-times the whole film.

## Deliverables

1. `media/newera-intro.mp4` — 1920x1080, 30 fps, H.264 + AAC, BGM mixed with
   synthesised sound design.
2. `media/newera-intro.webm` — VP9 web fallback.
3. A static player page with poster, captions and the full audio analysis.

## Verify


bash
python3 tools/analyze_audio.py --audio audio/bgm.mp3
python3 tools/render_film.py --scenes scenes/scenes.json --out frames
ffmpeg -i media/newera-intro.mp4 -f null -   # probe the finished master


