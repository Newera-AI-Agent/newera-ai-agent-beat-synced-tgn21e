#!/usr/bin/env python3
# Precise audio analysis for the NewEra intro film.
#
# Measures the soundtrack so the renderer can cut on real musical events
# instead of guessed round numbers. Nothing in this file is aesthetic.
#
# Outputs:
#   analysis/beat_map.json   one value per film frame at 30 fps
#   analysis/AUDIO.md        human readable report

from __future__ import annotations

import argparse
import json
import math
import os
import subprocess
import sys
import tempfile
import wave

import numpy as np

FPS = 30
SR = 22050
HOP = int(round(SR / FPS))

BANDS = {
    'sub': (20.0, 60.0),
    'bass': (60.0, 250.0),
    'lowmid': (250.0, 500.0),
    'mid': (500.0, 2000.0),
    'high': (2000.0, 8000.0),
    'air': (8000.0, 16000.0),
}


def log(msg):
    print('analyze: ' + str(msg), flush=True)


def decode_to_wav(path, sr=SR):
    # Decode any input to mono float32 via ffmpeg. Returns samples and rate.
    with tempfile.TemporaryDirectory() as tmp:
        out = os.path.join(tmp, 'decoded.wav')
        cmd = ['ffmpeg', '-hide_banner', '-loglevel', 'error', '-y',
               '-i', path, '-ac', '1', '-ar', str(sr), '-f', 'wav', out]
        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode != 0:
            raise RuntimeError('ffmpeg decode failed: ' + proc.stderr.strip())
        with wave.open(out, 'rb') as wf:
            n = wf.getnframes()
            raw = wf.readframes(n)
            width = wf.getsampwidth()
            chans = wf.getnchannels()
            rate = wf.getframerate()
    dtype = {1: np.int8, 2: np.int16, 4: np.int32}.get(width, np.int16)
    data = np.frombuffer(raw, dtype=dtype).astype(np.float32)
    if chans > 1:
        data = data.reshape(-1, chans).mean(axis=1)
    scale = {1: 128.0, 2: 32768.0, 4: 2147483648.0}.get(width, 32768.0)
    return (data / scale).astype(np.float32), rate


def stft_mag(y, n_fft=2048):
    # Magnitude spectrogram plus its frequency axis.
    window = np.hanning(n_fft).astype(np.float32)
    span = max(0, len(y) - n_fft)
    frames = 1 + int(span / HOP)
    nbins = int(n_fft / 2) + 1
    mag = np.zeros((nbins, frames), dtype=np.float32)
    for i in range(frames):
        seg = y[i * HOP: i * HOP + n_fft]
        if len(seg) < n_fft:
            seg = np.pad(seg, (0, n_fft - len(seg)))
        spec = np.fft.rfft(seg * window)
        mag[:, i] = np.abs(spec)
    freqs = np.fft.rfftfreq(n_fft, d=1.0 / SR)
    return mag, freqs


def to_frames(series, n_frames):
    # Resample a per-spectrogram series onto exactly n_frames film frames.
    if len(series) == 0:
        return np.zeros(n_frames, dtype=np.float32)
    x_old = np.linspace(0.0, 1.0, len(series))
    x_new = np.linspace(0.0, 1.0, n_frames)
    return np.interp(x_new, x_old, series).astype(np.float32)


def normalize(a):
    lo = float(np.min(a))
    hi = float(np.max(a))
    if hi - lo < 1e-9:
        return np.zeros_like(a, dtype=np.float32)
    return ((a - lo) / (hi - lo)).astype(np.float32)


def smooth(a, k=5):
    if k <= 1:
        return a
    kern = np.ones(k, dtype=np.float32) / float(k)
    return np.convolve(a, kern, mode='same').astype(np.float32)


# ------------------------------------------------------------------ events ---

def pick_onsets(env, min_gap_frames=4, delta_ratio=0.18):
    # Peak-pick the onset envelope. Returns film frame indices.
    n = len(env)
    if n == 0:
        return []
    thresh = float(np.max(env)) * float(delta_ratio)
    onsets = []
    last = -100000
    for i in range(1, n - 1):
        if env[i] < thresh:
            continue
        if env[i] >= env[i - 1] and env[i] > env[i + 1]:
            if i - last >= min_gap_frames:
                onsets.append(int(i))
                last = i
    return onsets


def estimate_tempo(onset_env, fps):
    # Autocorrelation tempo estimate in BPM plus a phase-aligned beat grid.
    x = onset_env - float(np.mean(onset_env))
    ac = np.correlate(x, x, mode='full')
    ac = ac[len(x) - 1:]
    ac = ac / (float(ac[0]) + 1e-9)
    lo_lag = int(fps * 60.0 / 200.0)
    hi_lag = min(int(fps * 60.0 / 60.0), len(ac) - 1)
    if hi_lag <= lo_lag:
        return 0.0, []
    lag = lo_lag + int(np.argmax(ac[lo_lag:hi_lag]))
    bpm = 60.0 * float(fps) / float(max(lag, 1))
    while bpm < 80.0:
        bpm *= 2.0
    while bpm > 200.0:
        bpm /= 2.0
    period = 60.0 * float(fps) / bpm
    best_phase = 0.0
    best_score = -1.0
    phase = 0.0
    while phase < period:
        idx = np.arange(phase, len(onset_env), period)
        idx = np.round(idx).astype(int)
        idx = idx[idx >= 0]
        idx = idx[idx < len(onset_env)]
        if len(idx) >= 4:
            score = float(np.mean(onset_env[idx]))
            if score > best_score:
                best_score = score
                best_phase = float(phase)
        phase += 0.5
    grid = np.arange(best_phase, len(onset_env), period)
    beats = []
    for g in grid:
        beats.append(int(round(float(g))))
    return bpm, beats


def segment_sections(energy, novelty, min_frames=None):
    # Coarse structural segmentation from novelty peaks and energy levels.
    if min_frames is None:
        min_frames = FPS * 6
    n = len(energy)
    if n == 0:
        return []
    cand = []
    thresh = float(np.mean(novelty)) + 0.6 * float(np.std(novelty))
    for i in range(1, n - 1):
        if novelty[i] > thresh and novelty[i] >= novelty[i - 1] and novelty[i] > novelty[i + 1]:
            if not cand or i - cand[-1] >= min_frames:
                cand.append(int(i))
    bounds = []
    bounds.append(0)
    for c in cand:
        if 0 < c < n:
            bounds.append(int(c))
    bounds.append(n)
    bounds = sorted(set(bounds))
    sections = []
    for a, b in zip(bounds[:-1], bounds[1:]):
        if b - a < FPS:
            continue
        seg = energy[a:b]
        sections.append({
            'startFrame': int(a),
            'endFrame': int(b),
            'startSec': round(a / float(FPS), 3),
            'endSec': round(b / float(FPS), 3),
            'meanEnergy': round(float(np.mean(seg)), 5),
            'peakEnergy': round(float(np.max(seg)), 5),
        })
    return sections


# -------------------------------------------------------------------- main ---

def build_envelopes(mag, freqs, n_frames):
    # Broadband plus per-band envelopes, resampled onto film frames.
    mag_f = np.maximum(mag, 1e-10)
    db = 20.0 * np.log10(mag_f)
    rms = np.sqrt(np.mean(mag_f * mag_f, axis=0))
    diff = np.diff(db, axis=1)
    diff = np.maximum(diff, 0.0)
    prepend = np.zeros((db.shape[0], 1), dtype=np.float32)
    flux = np.mean(np.concatenate((prepend, diff), axis=1), axis=0)
    power = np.sum(mag_f, axis=0) + 1e-9
    centroid = np.sum(freqs.reshape(-1, 1) * mag_f, axis=0) / power
    out = {}
    out['rms'] = normalize(to_frames(rms, n_frames))
    out['flux'] = normalize(to_frames(flux, n_frames))
    out['centroid'] = normalize(to_frames(centroid, n_frames))
    for name in BANDS:
        lo, hi = BANDS[name]
        sel = (freqs >= lo) & (freqs < hi)
        if not np.any(sel):
            out['band_' + name] = np.zeros(n_frames, dtype=np.float32)
            continue
        env = np.sqrt(np.mean(mag_f[sel] * mag_f[sel], axis=0))
        out['band_' + name] = normalize(to_frames(env, n_frames))
    return out


def write_report(path, data, envs, onsets, sections):
    lines = []
    lines.append('# Audio Analysis - Life Force')
    lines.append('')
    lines.append('- Source: ' + data['source'])
    lines.append('- Duration: **%.2f s** (%.2f min)' % (data['durationSec'], data['durationSec'] / 60.0))
    lines.append('- Film frames: **%d** at %d fps' % (data['totalFrames'], data['fps']))
    lines.append('- Estimated tempo: **%.1f BPM**' % data['tempoBpm'])
    lines.append('- Beats detected: %d | Onsets detected: %d' % (len(data['beatFrames']), len(onsets)))
    lines.append('- Structural sections: %d' % len(sections))
    lines.append('')
    lines.append('## Onset density per 10 s window')
    lines.append('')
    lines.append('| Window | Onsets | Mean energy | Peak energy |')
    lines.append('| --- | --- | --- | --- |')
    total = int(data['durationSec'])
    w = 0
    while w < total:
        a = w * FPS
        b = min((w + 10) * FPS, data['totalFrames'])
        cnt = 0
        for o in onsets:
            if a <= o < b:
                cnt += 1
        seg = envs['rms'][a:b]
        lines.append('| %d-%d s | %d | %.3f | %.3f |' % (w, min(w + 10, total), cnt, float(np.mean(seg)), float(np.max(seg))))
        w += 10
    lines.append('')
    lines.append('## Detected sections')
    lines.append('')
    lines.append('| # | Start | End | Length | Mean E | Peak E |')
    lines.append('| --- | --- | --- | --- | --- | --- |')
    i = 1
    for s in sections:
        lines.append('| %d | %.2fs | %.2fs | %.2fs | %.4f | %.4f |' % (
            i, s['startSec'], s['endSec'], s['endSec'] - s['startSec'],
            s['meanEnergy'], s['peakEnergy']))
        i += 1
    lines.append('')
    lines.append('## Band energy')
    lines.append('')
    lines.append('| Band | Mean | Peak |')
    lines.append('| --- | --- | --- |')
    for name in BANDS:
        arr = envs['band_' + name]
        lines.append('| %s | %.3f | %.3f |' % (name, float(np.mean(arr)), float(np.max(arr))))
    lines.append('')
    lines.append('## First 60 onset times (seconds)')
    lines.append('')
    times = []
    for o in onsets[:60]:
        times.append('%.2f' % (o / float(FPS)))
    lines.append(', '.join(times))
    with open(path, 'w') as fh:
        fh.write('\n'.join(lines) + '\n')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--audio', required=True)
    ap.add_argument('--out', default='analysis')
    args = ap.parse_args()
    os.makedirs(args.out, exist_ok=True)

    log('decoding ' + args.audio)
    y, sr = decode_to_wav(args.audio, SR)
    duration = len(y) / float(sr)
    n_frames = int(math.floor(duration * FPS))
    log('duration %.3fs -> %d film frames' % (duration, n_frames))

    log('stft')
    mag, freqs = stft_mag(y)
    envs = build_envelopes(mag, freqs, n_frames)

    onset_env = smooth(envs['flux'], 3)
    onsets = pick_onsets(onset_env)
    bpm, beats = estimate_tempo(onset_env, FPS)
    log('tempo %.1f BPM, %d beats, %d onsets' % (bpm, len(beats), len(onsets)))

    novelty = smooth(np.abs(np.diff(smooth(envs['rms'], 15))), 5)
    sections = segment_sections(envs['rms'], novelty)
    log('%d structural sections' % len(sections))

    data = {
        'source': os.path.basename(args.audio),
        'fps': FPS,
        'sampleRate': sr,
        'durationSec': round(duration, 4),
        'totalFrames': n_frames,
        'peakAmplitude': round(float(np.max(np.abs(y))), 5),
        'tempoBpm': round(bpm, 3),
        'beatFrames': beats,
        'onsetFrames': onsets,
        'sections': sections,
        'envelopes': {},
    }
    for key in envs:
        data['envelopes'][key] = [round(float(v), 5) for v in envs[key]]

    json_path = os.path.join(args.out, 'beat_map.json')
    with open(json_path, 'w') as fh:
        json.dump(data, fh)
    log('wrote ' + json_path)

    md_path = os.path.join(args.out, 'AUDIO.md')
    write_report(md_path, data, envs, onsets, sections)
    log('wrote ' + md_path)
    return 0


if __name__ == '__main__':
    sys.exit(main())
