# VM Work Order — Render the NewEra intro film

You are working in the NewEra AI Agent intro-film repository. Everything you
need is already in the tree; your job is to measure the audio, render the film,
verify it, and commit the artifacts back.

## Goal

Produce `media/newera-intro.mp4` (plus `.webm`, `media/poster.jpg`,
`media/contact-sheet.jpg`, `analysis/beat_map.json`, `analysis/AUDIO.md`) from
`audio/bgm.mp3`, using the authored scene sheet and the renderer in this repo.

## Files you own

- `analysis/**` (generated)
- `media/**` (generated)
- `assets/fonts/**` (downloaded by the renderer)

## Files you must NOT change

- `tools/render_film.py`
- `tools/analyze_audio.py`
- `scenes/scenes.json`
- `index.html`
- `docs/CREATIVE_BRIEF.md`

If one of those files has a genuine bug that blocks the render, fix the minimum
lines required and record exactly what you changed and why.

## Environment setup


bash
python3 -m pip install --quiet --upgrade pip
python3 -m pip install --quiet numpy pillow
sudo apt-get update -qq
sudo apt-get install -y -qq ffmpeg fonts-dejavu-core curl
ffmpeg -version | head -n 1
python3 -c "import numpy, PIL; print('numpy', numpy.__version__, 'pillow', PIL.__version__)"



## Acquire the audio first (mandatory)

The 1.7 MB MP3 cannot live in the repo (platform hard limit ~500 KB per file),
so the clone will NOT contain a usable `audio/bgm.mp3`. Run this before anything
else; it tries both mirrors, validates with ffprobe, and exits non-zero if both
fail:

```bash
chmod +x tools/fetch_bgm.sh
tools/fetch_bgm.sh audio/bgm.mp3
ls -l audio/bgm.mp3
ffprobe -v error -show_entries format=duration -of default=nw=1:nk=1 audio/bgm.mp3
```

Mirrors, in order of preference:

1. `https://files.catbox.moe/8wi7fw.mp3`
2. `https://tmpfiles.org/dl/wFAk6KtKsGFz/ptasinskirjpasin-lifeforce.mp3`

Track: *Life Force* (ptasinski / RJ Pasin). If **both** mirrors fail, do NOT
substitute a synthesized score and do NOT invent a duration — stop, report the
fetch failure in `analysis/AUDIO.md`, and commit that report so the failure is
visible.

## Steps

1. **Measure the audio.**
   
bash
   python3 tools/analyze_audio.py --audio audio/bgm.mp3 --out analysis
   

   Confirm `analysis/beat_map.json` exists and `totalFrames` is greater than
   3000. Print the tempo, onset count and section count.

2. **Render the film.**
   
bash
   python3 tools/render_film.py --audio audio/bgm.mp3 --beats analysis/beat_map.json \
     --scenes scenes/scenes.json --out frames --media media
   

   This renders every frame at 1920x1080, synthesises the sound design, mixes
   it under the track, encodes H.264 plus VP9, and writes the contact sheet.
   Expect this to take 10-25 minutes. Print progress is on stdout.

3. **Verify with ffprobe.**
   
bash
   ffprobe -v error -show_entries format=duration,size,bit_rate \
     -show_entries stream=codec_name,width,height,r_frame_rate,channels \
     -of default=noprint_wrappers=1 media/newera-intro.mp4
   

   Required: 1920x1080, ~30 fps, h264 video, aac audio, duration between
   110 and 140 seconds. If duration is outside that window, report it as a
   failure with the measured number.

4. **Cut alignment check.**
   Write and run a small script that:
   - loads `analysis/beat_map.json`
   - takes the section boundaries from `scenes/scenes.json` (fractions x totalFrames)
   - checks each boundary frame is within 2 frames of a measured onset
   Print `PASS` or `FAIL` per boundary with the frame delta. This is the core
   claim of the film: cuts land on the music.

5. **Poster frame.**
   
bash
   ffmpeg -y -ss 00:00:58 -i media/newera-intro.mp4 -frames:v 1 -q:v 3 media/poster.jpg
   

   Pick a timestamp inside the wordmark section and confirm the JPEG is
   1920x1080.

6. **Contact sheet sanity.**
   Confirm `media/contact-sheet.jpg` exists and is at least 1500px wide, and
   that its 40 sampled frames are not near-identical (check that the standard
   deviation of pixel means across cells is non-trivial).

7. **Commit.**
   
bash
   git add -A
   git commit -m "Render NewEra intro film: measured beat grid, 1080p master, webm, poster, contact sheet"
   git push
   

   If the repository is large, that is expected: the master MP4 is the point.
   Use `git lfs` only if the push is rejected for size; otherwise plain push.

## Acceptance criteria

| # | Criterion | Evidence required |
| --- | --- | --- |
| 1 | `media/newera-intro.mp4` exists | `ls -l` size |
| 2 | 1920x1080, ~30 fps, h264+aac | ffprobe output |
| 3 | Duration 110-140 s | ffprobe duration |
| 4 | Section boundaries within 2 frames of an onset | alignment script output |
| 5 | `analysis/AUDIO.md` written with tempo and sections | file contents |
| 6 | `media/poster.jpg` at 1920x1080 | ffprobe/identify |
| 7 | `media/contact-sheet.jpg` present | file size + dimensions |
| 8 | All artifacts committed and pushed | `git log -1 --stat` |

## Reporting

Write `work/vm-report.md` containing:
- The exact ffprobe output for the master.
- The tempo, onset count and section count from the analysis.
- The alignment table (boundary, nearest onset frame, delta, PASS/FAIL).
- File sizes for every artifact.
- Any deviation from this brief and why.

Do not claim success for any criterion you did not directly measure.
