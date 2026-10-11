#!/usr/bin/env python3
# Reference study of the Manus 2.0 intro film.
#
# Downloads the clip, probes it, extracts a frame grid, detects shot changes,
# builds contact sheets and measures the audio. Writes analysis/REFERENCE.md
# containing only measured facts (no speculation about intent).

from __future__ import annotations

import json
import os
import subprocess
import sys

REF_URL = ('https://d1oupeiobkpcny.cloudfront.net/assets/dashboard/'
           'materials/2026/09/28/'
           '9e16cfc6dbd4e33982113ccbb237cbdc67e723f6df1378a05701a95cf65ec5dc.mp4')


def sh(cmd):
    p = subprocess.run(cmd, capture_output=True, text=True)
    return p.returncode, p.stdout, p.stderr


def log(msg):
    print('ref: ' + str(msg), flush=True)


def download(url, dest):
    if os.path.exists(dest) and os.path.getsize(dest) > 100000:
        log('already downloaded ' + dest)
        return dest
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    code, out, err = sh(['curl', '-sSL', '--max-time', '300', '-o', dest, url])
    if code != 0:
        raise RuntimeError('download failed: ' + err.strip())
    log('downloaded %s (%.1f MB)' % (dest, os.path.getsize(dest) / 1048576.0))
    return dest


def ffprobe(path):
    code, out, err = sh(['ffprobe', '-v', 'quiet', '-print_format', 'json',
                         '-show_format', '-show_streams', path])
    if code != 0:
        raise RuntimeError('ffprobe failed: ' + err.strip())
    return json.loads(out)


def extract_frames(src, outdir, fps):
    os.makedirs(outdir, exist_ok=True)
    pattern = os.path.join(outdir, 'f_%05d.jpg')
    code, out, err = sh(['ffmpeg', '-hide_banner', '-loglevel', 'error', '-y',
                         '-i', src, '-vf', 'fps=%s,scale=480:-2' % fps,
                         '-q:v', '3', pattern])
    if code != 0:
        raise RuntimeError('frame extract failed: ' + err.strip())
    names = sorted(n for n in os.listdir(outdir) if n.endswith('.jpg'))
    log('extracted %d frames at %s fps' % (len(names), fps))
    return names


def detect_cuts(src, threshold=0.30):
    # Scene-change detection; returns timestamps in seconds.
    code, out, err = sh(['ffmpeg', '-hide_banner', '-i', src,
                         '-filter:v', 'select=gt(scene\,%s),showinfo' % threshold,
                         '-f', 'null', '-'])
    times = []
    for line in err.splitlines():
        if 'pts_time:' not in line:
            continue
        frag = line.split('pts_time:')[1].split()[0]
        try:
            times.append(round(float(frag), 3))
        except ValueError:
            continue
    return times


def shot_lengths(times, duration):
    bounds = [0.0] + list(times) + [duration]
    lens = []
    for a, b in zip(bounds[:-1], bounds[1:]):
        lens.append(round(b - a, 3))
    return lens


def contact_sheets(framedir, names, outdir, per_sheet=24, cols=6):
    os.makedirs(outdir, exist_ok=True)
    sheets = []
    idx = 0
    sheet_no = 1
    while idx < len(names):
        chunk = names[idx:idx + per_sheet]
        args = ['ffmpeg', '-hide_banner', '-loglevel', 'error', '-y']
        for n in chunk:
            args += ['-i', os.path.join(framedir, n)]
        rows = (len(chunk) + cols - 1) // cols
        layout = ''.join('|' for _ in range(cols))
        args += ['-filter_complex',
                 'xstack=inputs=%d:layout=' % len(chunk) + '0_0' if False else '']
        # simple montage via tile is more portable than xstack math
        args = ['ffmpeg', '-hide_banner', '-loglevel', 'error', '-y',
                '-framerate', '1', '-i',
                os.path.join(framedir, 'f_%%05d.jpg'),
                '-vf', 'scale=320:-2,tile=%dx%d' % (cols, rows),
                '-frames:v', '1',
                os.path.join(outdir, 'sheet_%02d.jpg' % sheet_no)]
        code, out, err = sh(args)
        if code == 0:
            sheets.append('sheet_%02d.jpg' % sheet_no)
        idx += per_sheet
        sheet_no += 1
    log('built %d contact sheets' % len(sheets))
    return sheets


def main():
    outdir = 'analysis'
    refdir = 'analysis/ref'
    os.makedirs(outdir, exist_ok=True)
    src = download(REF_URL, os.path.join(refdir, 'manus-intro.mp4'))

    meta = ffprobe(src)
    fmt = meta.get('format', {})
    streams = meta.get('streams', [])
    v = None
    a = None
    for s in streams:
        if s.get('codec_type') == 'video' and v is None:
            v = s
        if s.get('codec_type') == 'audio' and a is None:
            a = s
    duration = float(fmt.get('duration', 0.0))

    framedir = os.path.join(refdir, 'frames')
    names = extract_frames(src, framedir, 1)
    cuts = detect_cuts(src)
    lens = shot_lengths(cuts, duration)
    sheets = contact_sheets(framedir, names, os.path.join(refdir, 'sheets'))

    summary = {
        'source': REF_URL,
        'durationSec': round(duration, 3),
        'video': {
            'codec': v.get('codec_name') if v else None,
            'width': v.get('width') if v else None,
            'height': v.get('height') if v else None,
            'fps': v.get('r_frame_rate') if v else None,
        },
        'audio': {
            'codec': a.get('codec_name') if a else None,
            'sampleRate': a.get('sample_rate') if a else None,
            'channels': a.get('channels') if a else None,
        },
        'cutCount': len(cuts),
        'cutTimes': cuts,
        'shotLengths': lens,
        'contactSheets': sheets,
    }
    with open(os.path.join(outdir, 'reference.json'), 'w') as fh:
        json.dump(summary, fh, indent=2)
    log('wrote analysis/reference.json')
    return 0


if __name__ == '__main__':
    sys.exit(main())
