# NewEra AI Agent — Intro Film Creative Brief

Duration target: **1:50 – 2:20**. Cut frame-accurately to *Life Force*
(ptasinski / RJ Pasin). Style: minimalist motion graphics, high-contrast
typography, geometric shapes, fluid eased motion. **No cinematic footage.**

---

## 1. Why this film exists

NewEra is an autonomous AI agent IDE. The founder is the audience's proxy: he
loves the Manus 2.0 intro because it says *"we are serious, we are fast, we are
engineered"* without ever shouting. The film must do the same for NewEra:

- Signal **engineering seriousness**, not startup whimsy.
- Signal **speed** — cuts land on the beat, never late.
- Signal **autonomy** — the agent acts, the human directs.
- End with one memorable line and the real domain.

Non-goals: no stock footage, no fake UI screenshots, no celebrity voice, no
3D renders, no drop-shadow "tech" cliches, no emoji.

---

## 2. Typography

| Role | Face | Treatment |
| --- | --- | --- |
| Display | Inter / Archivo, weight 700-800 | Tracking -2% to -4%, all caps for slams |
| Body / captions | Inter, weight 400-500 | Tracking 0, sentence case |
| Mono accents | JetBrains Mono, weight 500 | File paths, version strings, counters |

Rules:
- **One idea per screen.** Never more than 9 words of display type visible.
- Kerning is manual: display words get letter-spacing tightened as they scale up.
- Text never fades in *and* moves; pick one. Motion is the entry, opacity is the exit.
- Type is set on a 12-column grid, optical baseline aligned to the safe area.

---

## 3. Colour

```
--ink        #08090C   near-black base (not pure #000)
--paper      #F4F5F7   primary type
--muted      #6B7280   secondary type, rules
--accent     #4D7CFE   single accent, used sparingly
--accent-2   #A9C1FF   accent tint for trails only
```

Discipline:
- Roughly 85% of frames are **ink + paper only**.
- Accent appears in exactly four moments: the turn, the wordmark sweep, the
deploy confirmation, and the final dot.
- No gradients except a single vertical ink vignette at 6% opacity.

---

## 4. Motion grammar

| Property | Rule |
| --- | --- |
| Easing | `cubic-bezier(0.22,1,0.36,1)` (out-expo) for entries; `(0.65,0,0.35,1)` for moves |
| Duration | 8-14 frames for slams, 20-30 frames for reveals |
| Linear motion | Forbidden, except intentional mechanical scans |
| Overshoot | Max 4% scale, only on beat-locked hits |
| Cut type | Hard cut on transient. Crossfade only under sustained pads, max 6 frames |
| Camera | Simulated by 1-3% scale drift on long holds; never a real 3D move |

Every cut is triggered by a **measured onset**, not by a round number. Where the
music has a gap, the film breathes; where it machine-guns, the film machine-guns.

---

## 5. Recurring visual devices

1. **The hairline** — 1px horizontal rule that draws left-to-right. Introduces
   every section. Its speed tracks the local energy of the track.
2. **The grid** — 6x4 dot matrix that assembles from noise on transitions.
3. **The ring** — expanding circle used for impacts; radius maps to bass energy.
4. **The mask wipe** — type revealed by a moving rectangular mask, never a fade.
5. **The counter** — mono digits ticking, used for stats and the end card.
6. **The cursor block** — 12x24px accent block that blinks on the beat.

---

## 6. Scene architecture (proportional)

Exact times come from the measured beat grid. Sections are defined as fractions
so the film auto-retimes if analysis changes.

| # | Section | Share | Content |
| --- | --- | --- | --- |
| 1 | Cold open | 0-9% | Black. Hairline draws. "Every era has a tool." "Then it has a partner." |
| 2 | The friction | 9-22% | Beat-slammed words: TABS / CONTEXT / COPY PASTE / WAITING / ALT-TAB. Grid jitters. |
| 3 | The turn | 22-34% | Dots assemble into a grid. "What if the machine understood the intent?" Accent enters. |
| 4 | Wordmark | 34-50% | N-E-W-E-R-A builds letter by letter on hits. Accent sweep. "AI AGENT IDE". |
| 5 | Capability run | 50-74% | Four beat-locked cards: PLAN / BUILD / VERIFY / DEPLOY, each with a stroke icon. |
| 6 | Proof | 74-86% | Counters: repos shipped, tests run, time to live. "One prompt. One repo. One URL." |
| 7 | Outro | 86-100% | Logo lockup, domain, accent dot lands on the final downbeat, cut to black. |

---

## 7. Sound design

BGM is the spine and is never ducked below -3dB relative to its own level.
Layered on top, all synthesised in-repo (no licensed samples):

- **Impacts** — short sine sweep 180Hz->40Hz, 120ms, on section boundaries.
- **Swooshes** — filtered noise sweep, 200ms, on type mask wipes.
- **Ticks** — 2kHz blip, 15ms, on counters.
- **Riser** — 2s noise + pitch ramp into the wordmark reveal.
- **Sub hit** — 45Hz sine, 300ms, on the final accent dot.

Mix target: -14 LUFS integrated, true peak -1.0 dBTP.

---

## 8. Acceptance criteria

1. `ffprobe` reports 1920x1080, 30fps, H.264+AAC, duration 110-140s.
2. At least 90% of hard cuts land within +/-2 frames of a measured onset.
3. No frame contains more than 9 words of display type.
4. Accent colour appears in no more than 8% of total frames.
5. A contact sheet of 40 sampled frames shows a coherent, non-repeating film.
6. The player page loads, plays, and shows the analysis summary.
