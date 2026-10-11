#!/usr/bin/env python3
# Deterministic frame renderer for the NewEra intro film.
#
# Reads analysis/beat_map.json (measured) plus scenes/scenes.json (authored) and
# writes PNG frames, then encodes them with ffmpeg. All timing comes from the
# measured beat map, so re-analysing the track re-times the whole film.

from __future__ import annotations

import argparse
import json
import math
import os
import subprocess
import sys

import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageFilter

FALLBACK_DURATION = 125.0
MAX_FILM_SEC = 140.0

FONT_CANDIDATES = [
    'assets/fonts/Inter-Bold.ttf',
    'assets/fonts/Inter-SemiBold.ttf',
    'assets/fonts/Inter-Medium.ttf',
    'assets/fonts/Inter-Regular.ttf',
    'assets/fonts/JetBrainsMono-Medium.ttf',
    '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf',
    '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',
]

VIGNETTE_CACHE = dict()

FONT_URLS = {
    'Inter-Bold.ttf': 'https://github.com/rsms/inter/raw/master/docs/font-files/Inter-Bold.ttf',
    'Inter-SemiBold.ttf': 'https://github.com/rsms/inter/raw/master/docs/font-files/Inter-SemiBold.ttf',
    'Inter-Medium.ttf': 'https://github.com/rsms/inter/raw/master/docs/font-files/Inter-Medium.ttf',
    'Inter-Regular.ttf': 'https://github.com/rsms/inter/raw/master/docs/font-files/Inter-Regular.ttf',
    'JetBrainsMono-Medium.ttf': 'https://github.com/JetBrains/JetBrainsMono/raw/master/fonts/ttf/JetBrainsMono-Medium.ttf',
}


def log(msg):
    print('render: ' + str(msg), flush=True)


def hex_rgb(value):
    v = value.lstrip('#')
    return (int(v[0:2], 16), int(v[2:4], 16), int(v[4:6], 16))


def mix(a, b, t):
    t = max(0.0, min(1.0, float(t)))
    return (int(a[0] + (b[0] - a[0]) * t),
            int(a[1] + (b[1] - a[1]) * t),
            int(a[2] + (b[2] - a[2]) * t))


# ------------------------------------------------------------------ easing ---

def ease_out_expo(t):
    t = max(0.0, min(1.0, float(t)))
    if t >= 1.0:
        return 1.0
    return 1.0 - pow(2.0, -10.0 * t)


def ease_in_out_cubic(t):
    t = max(0.0, min(1.0, float(t)))
    if t < 0.5:
        return 4.0 * t * t * t
    f = -2.0 * t + 2.0
    return 1.0 - (f * f * f) / 2.0


def ease_out_quint(t):
    t = max(0.0, min(1.0, float(t)))
    return 1.0 - pow(1.0 - t, 5.0)


def ease_in_quad(t):
    t = max(0.0, min(1.0, float(t)))
    return t * t


def ease_out_back(t, overshoot=0.04):
    t = max(0.0, min(1.0, float(t)))
    c = 1.0 + overshoot
    f = t - 1.0
    return 1.0 + c * f * f * f + overshoot * f * f


EASES = {
    'outExpo': ease_out_expo,
    'inOutCubic': ease_in_out_cubic,
    'outQuint': ease_out_quint,
    'inQuad': ease_in_quad,
    'outBack': ease_out_back,
}


# ------------------------------------------------------------------- fonts ---

def ensure_fonts(fontdir='assets/fonts'):
    os.makedirs(fontdir, exist_ok=True)
    have = []
    for name in FONT_URLS:
        dest = os.path.join(fontdir, name)
        if os.path.exists(dest) and os.path.getsize(dest) > 20000:
            have.append(dest)
            continue
        url = FONT_URLS[name]
        p = subprocess.run(['curl', '-sSL', '--max-time', '90', '-o', dest, url],
                           capture_output=True, text=True)
        if p.returncode == 0 and os.path.exists(dest) and os.path.getsize(dest) > 20000:
            have.append(dest)
        else:
            log('font fetch failed: ' + name)
    # Always include any system font we can find, so the renderer never falls
    # back to the 6px bitmap default on a runner with no network.
    for cand in FONT_CANDIDATES:
        if os.path.exists(cand) and cand not in have:
            have.append(cand)
    return have


class FontBook:
    # Caches font instances per role and pixel size.

    def __init__(self, bold, semi, medium, regular, mono):
        self.paths = {
            'display': bold or semi or regular,
            'body': regular or medium,
            'mono': mono or medium or regular,
        }
        self.cache = {}

    def get(self, role, size):
        size = max(6, int(round(size)))
        key = (role, size)
        if key in self.cache:
            return self.cache[key]
        path = self.paths.get(role) or self.paths.get('body')
        try:
            font = ImageFont.truetype(path, size)
        except Exception:
            font = ImageFont.load_default()
        self.cache[key] = font
        return font


def find_font(paths, needle):
    for p in paths:
        if needle.lower() in os.path.basename(p).lower():
            return p
    return None


def build_fontbook(available):
    bold = find_font(available, 'bold')
    semi = find_font(available, 'semibold')
    medium = find_font(available, 'medium')
    regular = find_font(available, 'regular')
    mono = find_font(available, 'mono')
    if not regular and not medium:
        regular = FONT_CANDIDATES[-1]
    if not bold and not semi:
        bold = FONT_CANDIDATES[-2]
    log('fonts: display=%s body=%s mono=%s' % (
        os.path.basename(bold or 'none'),
        os.path.basename(regular or 'none'),
        os.path.basename(mono or 'none')))
    return FontBook(bold, semi, medium, regular, mono)


# --------------------------------------------------------------- type draw ---

def measure_tracked(draw, text, font, tracking):
    widths = []
    for ch in text:
        bbox = draw.textbbox((0, 0), ch, font=font)
        widths.append(bbox[2] - bbox[0])
    total = 0.0
    for w in widths:
        total += w + tracking
    if widths:
        total -= tracking
    return total, widths


def draw_tracked(draw, xy, text, font, fill, tracking, anchor='center'):
    total, widths = measure_tracked(draw, text, font, tracking)
    x, y = xy
    if anchor == 'center':
        x = x - total / 2.0
    elif anchor == 'right':
        x = x - total
    cursor = x
    for i, ch in enumerate(text):
        bbox = draw.textbbox((0, 0), ch, font=font)
        draw.text((cursor - bbox[0], y), ch, font=font, fill=fill)
        cursor += widths[i] + tracking
    return total


# ------------------------------------------------------------------ canvas ---

class Canvas:
    # Thin wrapper over a PIL image that keeps drawing in normalized units.

    def __init__(self, width, height, bg):
        self.w = width
        self.h = height
        self.bg = bg
        self.img = Image.new('RGB', (width, height), bg)
        self.draw = ImageDraw.Draw(self.img, 'RGBA')

    def px(self, u):
        return u * self.w

    def py(self, u):
        return u * self.h

    def size(self, u):
        # Type sizes are expressed as a fraction of frame height.
        return u * self.h

    def point(self, x, y):
        return (self.px(x), self.py(y))

    def rect(self, x, y, w, h, fill=None, outline=None, width=1):
        self.draw.rectangle([self.px(x), self.py(y), self.px(x + w), self.py(y + h)],
                            fill=fill, outline=outline, width=width)

    def line(self, x1, y1, x2, y2, fill=None, width=1):
        self.draw.line([self.px(x1), self.py(y1), self.px(x2), self.py(y2)],
                       fill=fill, width=width)

    def circle(self, cx, cy, r, fill=None, outline=None, width=1):
        rx = self.px(r)
        ry = self.py(r)
        box = [self.px(cx) - rx, self.py(cy) - ry, self.px(cx) + rx, self.py(cy) + ry]
        self.draw.ellipse(box, fill=fill, outline=outline, width=width)

    def text_center(self, text, font, fill, y, tracking=0.0):
        bbox = self.draw.textbbox((0, 0), 'Hg', font=font)
        hgt = bbox[3] - bbox[1]
        draw_tracked(self.draw, (self.px(0.5), self.py(y) - hgt / 2.0),
                     text, font, fill, tracking, 'center')

    def vignette(self, strength=0.06):
        # Single vertical ink vignette; the brief allows exactly one.
        # The mask is cached per size: rebuilding it every frame costs minutes.
        key = (self.w, self.h, round(float(strength), 4))
        mask = VIGNETTE_CACHE.get(key)
        if mask is None:
            grad = Image.new('L', (1, self.h))
            for y in range(self.h):
                t = abs((y / float(self.h)) - 0.5) * 2.0
                grad.putpixel((0, y), int(255 * strength * (t ** 2)))
            mask = grad.resize((self.w, self.h))
            VIGNETTE_CACHE[key] = mask
        dark = Image.new('RGB', (self.w, self.h), (0, 0, 0))
        self.img = Image.composite(dark, self.img, mask)
        self.draw = ImageDraw.Draw(self.img, 'RGBA')


# --------------------------------------------------------------- beat data ---

class BeatMap:
    # Frame-indexed access to the measured audio envelopes.

    def __init__(self, data):
        self.data = data
        self.env = data.get('envelopes', {})
        self.beats = set(data.get('beatFrames', []))
        self.onsets = set(data.get('onsetFrames', []))

    def val(self, frame, key):
        arr = self.env.get(key)
        if not arr:
            return 0.0
        if frame < 0:
            frame = 0
        if frame >= len(arr):
            frame = len(arr) - 1
        return float(arr[frame])

    def smooth_val(self, frame, key, radius=3):
        total = 0.0
        count = 0
        for i in range(frame - radius, frame + radius + 1):
            total += self.val(i, key)
            count += 1
        return total / float(max(count, 1))

    def on_beat(self, frame):
        return frame in self.beats

    def on_onset(self, frame):
        return frame in self.onsets

    def nearest_beat(self, frame):
        best = frame
        best_d = 10 ** 9
        for b in self.beats:
            d = abs(b - frame)
            if d < best_d:
                best_d = d
                best = b
        return best


def scene_bounds(scene, total_frames):
    return (int(round(scene['start'] * total_frames)),
            int(round(scene['end'] * total_frames)))


def scene_for_frame(scenes, frame, total_frames):
    for sc in scenes:
        a, b = scene_bounds(sc, total_frames)
        if a <= frame < b:
            return sc, a, b
    return None, 0, 0


# -------------------------------------------------------------- elements ---


def element_progress(frame, start_frame, length_frames, ease='outExpo'):
    if length_frames <= 0:
        return 1.0
    t = (frame - start_frame) / float(length_frames)
    fn = EASES.get(ease, ease_out_expo)
    return fn(t)


def element_alive(frame, start_frame, end_frame):
    return start_frame <= frame < end_frame


def draw_hairline(cv, el, frame, sf, ef, palette, beats):
    dur = int(el.get('draw', 14))
    p = element_progress(frame, sf, dur, 'outQuint')
    y = el.get('y', 0.5)
    w = el.get('width', 0.6)
    col = hex_rgb(palette.get(el.get('color', 'paper'), '#F4F5F7'))
    x0 = 0.5 - w / 2.0
    x1 = x0 + w * p
    if el.get('from', 'left') == 'right':
        x1 = 0.5 + w / 2.0
        x0 = x1 - w * p
    cv.line(x0, y, x1, y, fill=col + (235,), width=max(1, int(cv.h * 0.0016)))


def draw_text_element(cv, el, frame, sf, ef, fonts, palette, bm):
    enter = el.get('enter', 'maskUp')
    enter_frames = int(el.get('enterFrames', 20))
    p = element_progress(frame, sf, enter_frames, 'outExpo')
    size = cv.size(el.get('size', 0.06))
    font = fonts.get(el.get('style', 'display'), size)
    col = hex_rgb(palette.get(el.get('color', 'paper'), '#F4F5F7'))
    tracking = el.get('tracking', 0.0) * size
    y = el.get('y', 0.5)
    text = el.get('text', '')
    lines = text.split('\n')
    alpha = 255
    yoff = 0.0
    if enter == 'maskUp':
        yoff = (1.0 - p) * 0.09
        alpha = int(255 * min(1.0, p * 1.6))
    elif enter == 'maskDown':
        yoff = -(1.0 - p) * 0.09
        alpha = int(255 * min(1.0, p * 1.6))
    elif enter == 'fade':
        alpha = int(255 * p)
    line_h = size * 1.16
    total_h = line_h * len(lines)
    for i, line in enumerate(lines):
        ly = y - (total_h / (2.0 * cv.h)) + (i * line_h) / cv.h + yoff
        cv.text_center(line, font, col + (alpha,), ly, tracking)


def draw_dots(cv, el, frame, sf, ef, palette, bm, beats):
    cols = int(el.get('cols', 12))
    rows = int(el.get('rows', 7))
    jitter = float(el.get('jitter', 0.015))
    base_op = float(el.get('opacity', 0.16))
    col = hex_rgb(palette.get('muted', '#6B7280'))
    pulse = bm.smooth_val(frame, el.get('pulse', 'flux'), 3)
    radius = cv.h * (0.0022 + 0.0016 * pulse)
    for r in range(rows):
        for c in range(cols):
            ux = 0.5 + (c - (cols - 1) / 2.0) * 0.072
            uy = 0.5 + (r - (rows - 1) / 2.0) * 0.11
            phase = (r * cols + c) * 0.37
            jx = math.sin(frame * 0.11 + phase) * jitter
            jy = math.cos(frame * 0.09 + phase) * jitter
            op = int(255 * base_op * (0.55 + 0.45 * pulse))
            cx = cv.px(ux + jx)
            cy = cv.py(uy + jy)
            cv.draw.ellipse([cx - radius, cy - radius, cx + radius, cy + radius],
                            fill=col + (op,))


def draw_grid_assemble(cv, el, frame, sf, ef, palette, bm, beats):
    cols = int(el.get('cols', 9))
    rows = int(el.get('rows', 5))
    spread = float(el.get('spread', 0.5))
    dur = int(el.get('enterFrames', 30))
    p = element_progress(frame, sf, dur, 'outExpo')
    accent_line = el.get('accentLine', -1)
    paper = hex_rgb(palette.get('paper', '#F4F5F7'))
    accent = hex_rgb(palette.get('accent', '#4D7CFE'))
    span_x = 0.70
    span_y = 0.52
    for r in range(rows):
        for c in range(cols):
            t = ((r * cols + c) / float(cols * rows))
            local = max(0.0, min(1.0, (p - t * 0.5) / 0.5))
            if local <= 0.0:
                continue
            e = ease_out_expo(local)
            tx = 0.5 + (c - (cols - 1) / 2.0) * (span_x / (cols - 1))
            ty = 0.5 + (r - (rows - 1) / 2.0) * (span_y / (rows - 1))
            sx = 0.5 + (tx - 0.5) * (1.0 + spread * (1.0 - e))
            sy = 0.5 + (ty - 0.5) * (1.0 + spread * (1.0 - e))
            ux = sx + (tx - sx) * e
            uy = sy + (ty - sy) * e
            col = accent if r == accent_line else paper
            op = int(180 * e)
            rad = cv.h * 0.0035
            cx = cv.px(ux)
            cy = cv.py(uy)
            cv.draw.ellipse([cx - rad, cy - rad, cx + rad, cy + rad],
                            fill=col + (op,))


def draw_ring(cv, el, frame, sf, ef, palette, bm):
    band = el.get('band', 'bass')
    energy = bm.smooth_val(frame, 'band_' + band, 2)
    max_r = float(el.get('maxR', 0.4))
    r = max_r * (0.12 + 0.88 * energy)
    stroke = max(1, int(cv.h * float(el.get('stroke', 0.0015))))
    accent = hex_rgb(palette.get('accent', '#4D7CFE'))
    cv.circle(el.get('cx', 0.5), el.get('cy', 0.5), r,
              outline=accent + (int(120 + 90 * energy),), width=stroke)


def draw_slam(cv, el, frame, sf, ef, fonts, palette, bm, words):
    if not words:
        return
    idx = 0
    per = float(el.get('perWordFrames', 0))
    if per <= 0:
        span = ef - sf
        per = max(4.0, span / float(len(words)))
    idx = int((frame - sf) / per)
    idx = max(0, min(len(words) - 1, idx))
    word_frame = int(sf + idx * per)
    local = (frame - word_frame) / 10.0
    p = ease_out_back(local, 0.04)
    size = cv.size(el.get('size', 0.12))
    font = fonts.get(el.get('style', 'display'), size)
    accent = hex_rgb(palette.get('accent', '#4D7CFE'))
    paper = hex_rgb(palette.get('paper', '#F4F5F7'))
    is_accent = (idx == el.get('accentIndex', -1))
    col = accent if is_accent else paper
    scale = 0.96 + 0.04 * p
    big = fonts.get(el.get('style', 'display'), size * scale)
    alpha = int(255 * max(0.0, min(1.0, p * 1.4)))
    cv.text_center(words[idx], big, col + (alpha,), el.get('y', 0.5), 0.0)


def draw_wordmark(cv, el, frame, sf, ef, fonts, palette, bm):
    word = el.get('word', 'NEWERA')
    size = cv.size(el.get('size', 0.18))
    per_letter = int(el.get('perLetter', 5))
    paper = hex_rgb(palette.get('paper', '#F4F5F7'))
    accent = hex_rgb(palette.get('accent', '#4D7CFE'))
    font = fonts.get('display', size)
    n = len(word)
    total = 0.0
    widths = []
    for ch in word:
        bb = cv.draw.textbbox((0, 0), ch, font=font)
        w = bb[2] - bb[0]
        widths.append(w)
        total += w + size * 0.04
    total -= size * 0.04
    cursor = cv.px(0.5) - total / 2.0
    reveal_end = sf + per_letter * n
    sweep = float(el.get('accentSweep', 0) and 1 or 0)
    for i, ch in enumerate(word):
        ls = sf + i * per_letter
        p = element_progress(frame, ls, 8, 'outBack')
        if p <= 0.0:
            cursor += widths[i] + size * 0.04
            continue
        col = paper
        if sweep:
            sweep_t = (frame - sf) / float(max(1, ef - sf))
            band = abs(i / float(max(1, n - 1)) - sweep_t)
            if band < 0.18:
                col = mix(paper, accent, 1.0 - band / 0.18)
        bb = cv.draw.textbbox((0, 0), ch, font=font)
        y = cv.py(el.get('y', 0.47)) - (bb[3] - bb[1]) / 2.0 - bb[1]
        alpha = int(255 * min(1.0, p * 1.3))
        lift = (1.0 - p) * cv.h * 0.03
        cv.draw.text((cursor - bb[0], y + lift), ch, font=font, fill=col + (alpha,))
        cursor += widths[i] + size * 0.04


def draw_cards(cv, el, frame, sf, ef, fonts, palette, bm, cards):
    if not cards:
        return
    per = float(el.get('perCard', 0.24))
    span = ef - sf
    per_frames = max(8.0, span * per)
    n = len(cards)
    idx = int((frame - sf) / per_frames)
    idx = max(0, min(n - 1, idx))
    card_frame = sf + idx * per_frames
    local = (frame - card_frame) / 16.0
    p = element_progress(frame, card_frame, 16, 'outExpo')
    if local < 0:
        p = 0.0
    card = cards[idx]
    paper = hex_rgb(palette.get('paper', '#F4F5F7'))
    muted = hex_rgb(palette.get('muted', '#6B7280'))
    accent = hex_rgb(palette.get('accent', '#4D7CFE'))
    is_accent = (idx == el.get('accentCard', -1))
    title_col = accent if is_accent else paper
    x0 = 0.14
    w = 0.72
    y0 = 0.40 + (1.0 - p) * 0.05
    alpha = int(255 * min(1.0, p * 1.5))
    cv.rect(x0, y0, w, 0.0016, fill=title_col + (alpha,))
    tsize = cv.size(el.get('size', 0.055))
    tfont = fonts.get('display', tsize)
    cv.text_center(card.get('title', ''), tfont, title_col + (alpha,), y0 + 0.075, 0.0)
    lfont = fonts.get('body', cv.size(0.024))
    cv.text_center(card.get('line', ''), lfont, muted + (alpha,), y0 + 0.145, 0.0)
    draw_icon(cv, card.get('icon', 'plan'), 0.5, y0 + 0.235,
              cv.h * float(el.get('iconStroke', 0.003)),
              title_col + (alpha,))
    steps = n
    dot_y = 0.90
    for i in range(steps):
        col = accent if i <= idx else muted
        op = 220 if i <= idx else 90
        cv.circle(0.5 + (i - (steps - 1) / 2.0) * 0.024, dot_y, 0.004,
                  fill=col + (op,))


def draw_icon(cv, kind, cx, cy, stroke, color):
    if kind == 'plan':
        for i in range(3):
            y = cy - stroke * 6 + i * stroke * 6
            cv.line(cx - stroke * 14, y, cx + stroke * 14, y, fill=color, width=max(1, int(stroke)))
            cv.circle(cx - stroke * 18, y, stroke * 2, fill=color)
    elif kind == 'build':
        cv.rect(cx - stroke * 14, cy - stroke * 14, stroke * 28, stroke * 28, outline=color, width=max(1, int(stroke)))
        cv.line(cx - stroke * 14, cy - stroke * 4, cx + stroke * 14, cy - stroke * 4, fill=color, width=max(1, int(stroke)))
    elif kind == 'verify':
        cv.circle(cx, cy, stroke * 15, outline=color, width=max(1, int(stroke)))
        cv.line(cx - stroke * 7, cy, cx - stroke * 1, cy + stroke * 7, fill=color, width=max(1, int(stroke)))
        cv.line(cx - stroke * 1, cy + stroke * 7, cx + stroke * 9, cy - stroke * 7, fill=color, width=max(1, int(stroke)))
    else:
        cv.line(cx, cy - stroke * 16, cx, cy + stroke * 6, fill=color, width=max(1, int(stroke)))
        cv.line(cx, cy + stroke * 6, cx - stroke * 8, cy - stroke * 2, fill=color, width=max(1, int(stroke)))
        cv.line(cx, cy + stroke * 6, cx + stroke * 8, cy - stroke * 2, fill=color, width=max(1, int(stroke)))
        cv.line(cx - stroke * 14, cy + stroke * 16, cx + stroke * 14, cy + stroke * 16, fill=color, width=max(1, int(stroke)))


def draw_counters(cv, el, frame, sf, ef, fonts, palette, bm, counters):
    if not counters:
        return
    n = len(counters)
    paper = hex_rgb(palette.get('paper', '#F4F5F7'))
    muted = hex_rgb(palette.get('muted', '#6B7280'))
    accent = hex_rgb(palette.get('accent', '#4D7CFE'))
    span = max(1.0, float(ef - sf))
    for i, c in enumerate(counters):
        delay = i * 0.12
        p = element_progress(frame, sf + int(span * delay), int(span * 0.45), 'outExpo')
        val = int(round(c.get('to', 0) * p))
        cx = 0.5 + (i - (n - 1) / 2.0) * 0.26
        size = cv.size(el.get('size', 0.085))
        font = fonts.get('display', size)
        txt = format(val, ',') + str(c.get('suffix', ''))
        cv.text_center(txt, font, paper + (255,), el.get('y', 0.40), 0.0)
        lfont = fonts.get('mono', cv.size(0.020))
        cv.text_center(c.get('label', ''), lfont, muted + (230,), el.get('y', 0.40) + 0.095, cv.size(0.006))
        cv.circle(cx, 0.30, 0.0035, fill=accent + (200,))


def draw_dot(cv, el, frame, sf, ef, palette, bm):
    band = el.get('band', 'sub')
    energy = bm.smooth_val(frame, 'band_' + band, 2)
    accent = hex_rgb(palette.get('accent', '#4D7CFE'))
    r = float(el.get('r', 0.006)) * (1.0 + 0.6 * energy)
    cv.circle(el.get('cx', 0.5), el.get('cy', 0.8), r, fill=accent + (255,))
    cv.circle(el.get('cx', 0.5), el.get('cy', 0.8), r * 2.6,
              outline=accent + (int(80 * energy),), width=max(1, int(cv.h * 0.0012)))


def draw_cursor(cv, el, frame, sf, ef, palette, bm):
    accent = hex_rgb(palette.get('accent', '#4D7CFE'))
    if not bm.on_beat(frame) and (frame % 8) > 4:
        return
    x = el.get('x', 0.6)
    y = el.get('y', 0.66)
    w = 0.011
    h = 0.030
    cv.rect(x, y - h / 2.0, w, h, fill=accent + (235,))


# ------------------------------------------------------------- dispatcher ---

def compose_frame(cv, scene, frame, sf, ef, ctx):
    fonts = ctx['fonts']
    palette = ctx['palette']
    bm = ctx['beats']
    els = scene.get('elements', [])
    for el in els:
        kind = el.get('kind', 'text')
        estart = sf + int(round(el.get('at', 0.0) * (ef - sf)))
        eend = ef
        if not element_alive(frame, estart, eend):
            continue
        if kind == 'hairline':
            draw_hairline(cv, el, frame, estart, eend, palette, bm)
        elif kind == 'text':
            draw_text_element(cv, el, frame, estart, eend, fonts, palette, bm)
        elif kind == 'dots':
            draw_dots(cv, el, frame, estart, eend, palette, bm, bm)
        elif kind == 'gridAssemble':
            draw_grid_assemble(cv, el, frame, estart, eend, palette, bm, bm)
        elif kind == 'ring':
            draw_ring(cv, el, frame, estart, eend, palette, bm)
        elif kind == 'slam':
            draw_slam(cv, el, frame, estart, eend, fonts, palette, bm,
                      scene.get('slamWords', []))
        elif kind == 'wordmark':
            draw_wordmark(cv, el, frame, estart, eend, fonts, palette, bm)
        elif kind == 'cards':
            draw_cards(cv, el, frame, estart, eend, fonts, palette, bm,
                       scene.get('cards', []))
        elif kind == 'counters':
            draw_counters(cv, el, frame, estart, eend, fonts, palette, bm,
                          scene.get('counters', []))
        elif kind == 'dot':
            draw_dot(cv, el, frame, estart, eend, palette, bm)
        elif kind == 'cursor':
            draw_cursor(cv, el, frame, estart, eend, palette, bm)


def apply_cut_transition(cv, scene, frame, sf):
    # Hard cuts are instant; fade scenes get a short ink fade at the head.
    if scene.get('cut') != 'fade':
        return
    head = 8
    if frame - sf >= head:
        return
    t = (frame - sf) / float(head)
    alpha = int(255 * (1.0 - ease_out_expo(t)))
    overlay = Image.new('RGBA', cv.img.size, (8, 9, 12, alpha))
    cv.img = Image.alpha_composite(cv.img.convert('RGBA'), overlay).convert('RGB')
    cv.draw = ImageDraw.Draw(cv.img, 'RGBA')


def fade_out_tail(cv, frame, ef, frames=16):
    if frame < ef - frames:
        return
    t = (frame - (ef - frames)) / float(max(1, frames))
    alpha = int(255 * ease_in_quad(t))
    overlay = Image.new('RGBA', cv.img.size, (8, 9, 12, alpha))
    cv.img = Image.alpha_composite(cv.img.convert('RGBA'), overlay).convert('RGB')
    cv.draw = ImageDraw.Draw(cv.img, 'RGBA')


# ------------------------------------------------------------ sound design ---

def synth_sound_design(beatmap, out_path, sr=44100, duration=None):
    # Synthesise impacts, swooshes, ticks, a riser and a final sub hit.
    # Nothing is sampled: every sound is generated from scratch here.
    if duration is None:
        duration = beatmap['durationSec']
    n = int(duration * sr)
    track = np.zeros(n, dtype=np.float32)
    onsets = beatmap.get('onsetFrames', [])
    sections = beatmap.get('sections', [])
    fps = beatmap.get('fps', 30)
    rng = np.random.default_rng(7)

    def add(sig, at_sec, gain=1.0):
        i0 = int(at_sec * sr)
        if i0 < 0 or i0 >= n:
            return
        i1 = min(n, i0 + len(sig))
        track[i0:i1] += sig[:i1 - i0] * gain

    # Section-boundary impacts: sine sweep 180 down to 40 Hz over 120 ms.
    for s in sections:
        ln = int(0.12 * sr)
        t = np.linspace(0.0, 0.12, ln, endpoint=False)
        freq = 180.0 * np.power(40.0 / 180.0, t / 0.12)
        phase = 2.0 * np.pi * np.cumsum(freq) / float(sr)
        env = np.exp(-t * 26.0)
        add((np.sin(phase) * env * 0.34).astype(np.float32), s['startSec'])

    # Downbeat impacts every 8 beats for body.
    beats = beatmap.get('beatFrames', [])
    for i, b in enumerate(beats):
        if i % 8 != 0:
            continue
        ln = int(0.18 * sr)
        t = np.linspace(0.0, 0.18, ln, endpoint=False)
        freq = 120.0 * np.power(45.0 / 120.0, t / 0.18)
        phase = 2.0 * np.pi * np.cumsum(freq) / float(sr)
        env = np.exp(-t * 20.0)
        add((np.sin(phase) * env * 0.22).astype(np.float32), b / float(fps))

    # Swooshes: filtered noise sweep, 200 ms, on a subset of onsets.
    for i, o in enumerate(onsets):
        if i % 6 != 3:
            continue
        ln = int(0.20 * sr)
        noise = rng.standard_normal(ln).astype(np.float32)
        sweep = np.linspace(0.0, 1.0, ln)
        out = np.zeros(ln, dtype=np.float32)
        acc = 0.0
        for k in range(ln):
            a = 0.02 + 0.5 * sweep[k]
            acc = acc + a * (noise[k] - acc)
            out[k] = acc
        env = np.sin(np.pi * sweep) ** 2
        add((out * env * 0.30).astype(np.float32), o / float(fps))

    # Ticks: 2 kHz blip, 15 ms, on beats inside high-energy sections.
    for b in beats:
        sec = b / float(fps)
        loud = False
        for s in sections:
            if s['startSec'] <= sec < s['endSec']:
                loud = s['meanEnergy'] > 0.55
                break
        if not loud:
            continue
        ln = int(0.015 * sr)
        t = np.linspace(0.0, 0.015, ln, endpoint=False)
        env = np.exp(-t * 220.0)
        add((np.sin(2 * np.pi * 2000.0 * t) * env * 0.10).astype(np.float32), sec)

    # Riser: 2 s noise plus pitch ramp into the loudest section.
    if sections:
        peak_sec = max(sections, key=lambda s: s['peakEnergy'])['startSec']
        ln = int(2.0 * sr)
        t = np.linspace(0.0, 2.0, ln, endpoint=False)
        noise = rng.standard_normal(ln).astype(np.float32)
        env = np.power(t / 2.0, 2.2)
        tone = np.sin(2 * np.pi * (200.0 + 900.0 * np.power(t / 2.0, 2)) * t)
        add(((noise * 0.5 + tone * 0.5) * env * 0.26).astype(np.float32),
            max(0.0, peak_sec - 2.0))

    # Final sub hit: 45 Hz sine, 300 ms, on the last downbeat.
    if beats:
        last = beats[-1] / float(fps)
        ln = int(0.30 * sr)
        t = np.linspace(0.0, 0.30, ln, endpoint=False)
        env = np.exp(-t * 7.0)
        add((np.sin(2 * np.pi * 45.0 * t) * env * 0.42).astype(np.float32), last)

    peak = float(np.max(np.abs(track))) or 1.0
    track = (track / peak) * 0.72
    write_wav(out_path, track, sr)
    log('wrote sound design ' + out_path)
    return out_path


def write_wav(path, samples, sr):
    import wave as wavmod
    data = np.clip(samples, -1.0, 1.0)
    ints = (data * 32767.0).astype(np.int16)
    with wavmod.open(path, 'wb') as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sr)
        wf.writeframes(ints.tobytes())


# --------------------------------------------------------------- audio mix ---

def decode_audio(path, sr=44100):
    # Decode any audio to mono float32 at sr using ffmpeg, no filter graphs.
    import tempfile
    import wave as wavmod
    with tempfile.TemporaryDirectory() as tmp:
        out = os.path.join(tmp, 'a.wav')
        cmd = ['ffmpeg', '-hide_banner', '-loglevel', 'error', '-y',
               '-i', path, '-ac', '1', '-ar', str(sr), '-f', 'wav', out]
        p = subprocess.run(cmd, capture_output=True, text=True)
        if p.returncode != 0:
            raise RuntimeError('decode failed: ' + p.stderr.strip())
        with wavmod.open(out, 'rb') as wf:
            n = wf.getnframes()
            raw = wf.readframes(n)
            width = wf.getsampwidth()
        dtype = {1: np.int8, 2: np.int16, 4: np.int32}.get(width, np.int16)
        scale = {1: 128.0, 2: 32768.0, 4: 2147483648.0}.get(width, 32768.0)
    data = np.frombuffer(raw, dtype=dtype).astype(np.float32) / scale
    return data


def mix_audio(bgm_path, sfx_path, out_path, duration, sr=44100,
              bgm_gain=0.92, sfx_gain=0.55):
    # Mix the soundtrack with the synthesised design in numpy.
    # The BGM is never ducked: it is the spine of the film.
    bgm = decode_audio(bgm_path, sr)
    n = int(duration * sr)
    if len(bgm) < n:
        bgm = np.pad(bgm, (0, n - len(bgm)))
    bgm = bgm[:n] * bgm_gain
    sfx = None
    if sfx_path and os.path.exists(sfx_path):
        sfx = decode_audio(sfx_path, sr)
    if sfx is not None:
        if len(sfx) < n:
            sfx = np.pad(sfx, (0, n - len(sfx)))
        sfx = sfx[:n] * sfx_gain
        mix = bgm + sfx
    else:
        mix = bgm
    peak = float(np.max(np.abs(mix))) or 1.0
    target = 0.89
    if peak > target:
        mix = mix * (target / peak)
    write_wav(out_path, mix, sr)
    log('wrote mix ' + out_path)
    return out_path


def encode(frames_dir, audio_path, out_path, fps):
    cmd = ['ffmpeg', '-hide_banner', '-loglevel', 'error', '-y',
           '-framerate', str(fps),
           '-i', os.path.join(frames_dir, 'f_%06d.png')]
    if audio_path and os.path.exists(audio_path):
        cmd += ['-i', audio_path, '-map', '0:v', '-map', '1:a',
                '-c:a', 'aac', '-b:a', '320k', '-shortest']
    cmd += ['-c:v', 'libx264', '-preset', 'medium', '-crf', '17',
            '-pix_fmt', 'yuv420p', '-profile:v', 'high', '-level', '4.1',
            '-movflags', '+faststart', out_path]
    p = subprocess.run(cmd, capture_output=True, text=True)
    if p.returncode != 0:
        raise RuntimeError('encode failed: ' + p.stderr.strip())
    log('encoded ' + out_path)
    return out_path


def make_webm(mp4_path, webm_path):
    cmd = ['ffmpeg', '-hide_banner', '-loglevel', 'error', '-y',
           '-i', mp4_path, '-c:v', 'libvpx-vp9', '-crf', '33', '-b:v', '0',
           '-row-mt', '1', '-c:a', 'libopus', '-b:a', '160k', webm_path]
    p = subprocess.run(cmd, capture_output=True, text=True)
    if p.returncode != 0:
        log('webm encode failed: ' + p.stderr.strip()[:300])
        return None
    log('encoded ' + webm_path)
    return webm_path


def contact_sheet(frames_dir, out_path, count=40, cols=5, cell_w=384):
    # Build a contact sheet with PIL so no ffmpeg filter graph is needed.
    names = sorted(n for n in os.listdir(frames_dir) if n.endswith('.png'))
    if not names:
        return None
    step = max(1, int(len(names) / count))
    picked = names[::step][:count]
    thumbs = []
    for n in picked:
        im = Image.open(os.path.join(frames_dir, n)).convert('RGB')
        ratio = cell_w / float(im.width)
        im = im.resize((cell_w, max(1, int(im.height * ratio))))
        thumbs.append(im)
    if not thumbs:
        return None
    cell_h = thumbs[0].height
    rows = int((len(thumbs) + cols - 1) / cols)
    sheet = Image.new('RGB', (cols * cell_w, rows * cell_h), (8, 9, 12))
    for i, im in enumerate(thumbs):
        col = i % cols
        row = int(i / cols)
        sheet.paste(im, (col * cell_w, row * cell_h))
    sheet.save(out_path)
    log('wrote contact sheet ' + out_path)
    return out_path


def probe(path):
    p = subprocess.run(['ffprobe', '-v', 'quiet', '-print_format', 'json',
                        '-show_format', '-show_streams', path],
                       capture_output=True, text=True)
    if p.returncode != 0:
        return None
    return json.loads(p.stdout)


# -------------------------------------------------------------------- main ---

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--scenes', default='scenes/scenes.json')
    ap.add_argument('--beats', default='analysis/beat_map.json')
    ap.add_argument('--audio', default='audio/bgm.mp3')
    ap.add_argument('--out', default='frames')
    ap.add_argument('--media', default='media')
    ap.add_argument('--skip-frames', action='store_true')
    args = ap.parse_args()

    with open(args.scenes) as fh:
        sheet = json.load(fh)
    meta = sheet.get('meta', dict())
    fps = int(meta.get('fps', 30))
    width = int(meta.get('width', 1920))
    height = int(meta.get('height', 1080))
    palette = sheet.get('palette', dict())
    scenes = sheet.get('scenes', [])

    beat_data = None
    if os.path.exists(args.beats):
        with open(args.beats) as fh:
            beat_data = json.load(fh)
    if beat_data is None:
        log('no beat map found, using fallback duration')
        beat_data = {'fps': fps, 'durationSec': FALLBACK_DURATION,
                     'totalFrames': int(FALLBACK_DURATION * fps),
                     'beatFrames': [], 'onsetFrames': [], 'sections': [],
                     'envelopes': dict()}

    duration = float(beat_data.get('durationSec', FALLBACK_DURATION))
    # The acceptance window is 110-140s. If the supplied track is longer, the
    # film is cut at the cap and the mix is trimmed to match.
    if duration > MAX_FILM_SEC:
        log('track is %.1fs, cutting film at the %.0fs cap' % (duration, MAX_FILM_SEC))
        duration = MAX_FILM_SEC
    total_frames = int(round(duration * fps))
    bm = BeatMap(beat_data)
    log('film: %d frames (%.2fs) at %d fps' % (total_frames, duration, fps))

    available = ensure_fonts('assets/fonts')
    fonts = build_fontbook(available)
    ctx = {'fonts': fonts, 'palette': palette, 'beats': bm}

    os.makedirs(args.out, exist_ok=True)
    os.makedirs(args.media, exist_ok=True)

    if not args.skip_frames:
        for frame in range(total_frames):
            scene, sf, ef = scene_for_frame(scenes, frame, total_frames)
            if scene is None:
                continue
            bg = hex_rgb(palette.get(scene.get('bg', 'ink'), '#08090C'))
            cv = Canvas(width, height, bg)
            compose_frame(cv, scene, frame, sf, ef, ctx)
            apply_cut_transition(cv, scene, frame, sf)
            if frame >= total_frames - 16:
                fade_out_tail(cv, frame, total_frames, 16)
            cv.vignette(0.06)
            cv.img.save(os.path.join(args.out, 'f_%06d.png' % frame))
            if frame % 60 == 0:
                log('frame %d of %d' % (frame, total_frames))

    sfx_path = os.path.join(args.media, 'sfx.wav')
    synth_sound_design(beat_data, sfx_path)
    mix_path = os.path.join(args.media, 'mix.wav')
    mix_audio(args.audio, sfx_path, mix_path, duration)

    mp4 = os.path.join(args.media, 'newera-intro.mp4')
    encode(args.out, mix_path, mp4, fps)
    make_webm(mp4, os.path.join(args.media, 'newera-intro.webm'))
    contact_sheet(args.out, os.path.join(args.media, 'contact-sheet.jpg'))

    info = probe(mp4)
    report = {'ffprobe': info, 'frames': total_frames,
              'durationSec': duration, 'fps': fps}
    with open(os.path.join(args.media, 'render-report.json'), 'w') as fh:
        json.dump(report, fh, indent=2)
    log('done')
    return 0


if __name__ == '__main__':
    sys.exit(main())
