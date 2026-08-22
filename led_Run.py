#!/usr/bin/env python3
"""led_Run.py — drives the WS281x strip wired to this Pi.

Runs as a STANDALONE process: ledPlayer.threaderLED() kills the previous copy
and launches `sudo python3 led_Run.py` (system Python — NeoPixel needs root
for the PWM/DMA hardware, see requirements.sh). It reads the active
tblLEDConfig row for pin / pixel count / MAX brightness, takes the latest
payload out of the tblLED mailbox and plays the scene's patterns on repeat
(in 'order', equal orders shuffled — see plan()) until the next scene kills
it; a duration-0 pattern holds forever.

Everything hardware-specific lives in main(); the routines only talk to a
Strip, so tests drive them with a fake pixel buffer and a fake clock.

Brightness has two layers (see led_patterns):
  * Strip.cap      — this box's hardware MAX (tblLEDConfig.brightness). A
                     strip's far end browns out when the amps run short, so
                     the operator caps output where red still reaches the end
                     as red instead of orange. Never exceeded.
  * pattern level  — the scene's creative 0–1 value (payload 'brightness').
  Output = cap × level × any per-frame pulse a routine applies via set_level().
"""

import json
import math
import os
import random
import sqlite3
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
import led_patterns as reg  # noqa: E402

DB_PATH = os.path.join(os.path.dirname(os.path.realpath(__file__)), 'ScenePlay.db')


# ---------------------------------------------------------------------------
# Strip wrapper
# ---------------------------------------------------------------------------
def _clamp(v, lo, hi):
    return lo if v < lo else hi if v > hi else v


class Strip:
    """Thin wrapper over a NeoPixel-like buffer (indexable, .fill(), .show(),
    .brightness) that owns the brightness cap and the pattern deadline."""

    def __init__(self, pixels, count, max_brightness, clock=time.monotonic,
                 sleep=time.sleep):
        self.px = pixels
        self.n = int(count)
        self.cap = _clamp(float(max_brightness), 0.0, 1.0)
        self._clock = clock
        self._sleep = sleep
        self.level = 1.0
        self.factor = 1.0
        self.deadline = None
        self._apply()

    # -- brightness -------------------------------------------------------
    def _apply(self):
        self.px.brightness = self.cap * self.level * self.factor

    def set_level(self, factor):
        """Per-frame pulse, 0–1 of the pattern's level. Can't exceed the cap."""
        self.factor = _clamp(float(factor), 0.0, 1.0)
        self._apply()

    @property
    def output(self):
        return self.px.brightness

    # -- lifecycle --------------------------------------------------------
    def begin(self, p):
        """Start a pattern: set its level, arm its deadline."""
        self.level = _clamp(float(p.get('brightness', 1.0)), 0.0, 1.0)
        self.factor = 1.0
        self._apply()
        dur = float(p.get('duration') or 0)
        self.deadline = (self._clock() + dur) if dur > 0 else None

    def running(self):
        return self.deadline is None or self._clock() < self.deadline

    def hold(self):
        """Sleep until the deadline (forever when there is none)."""
        while self.running():
            self._sleep(0.25 if self.deadline is None else
                        max(0.0, min(0.25, self.deadline - self._clock())))

    # -- pixels -----------------------------------------------------------
    def __setitem__(self, i, c):
        self.px[i] = (int(c[0]), int(c[1]), int(c[2]))

    def __getitem__(self, i):
        return self.px[i]

    def fill(self, c):
        self.px.fill((int(c[0]), int(c[1]), int(c[2])))

    def show(self):
        self.px.show()

    def off(self):
        self.fill((0, 0, 0))
        self.show()

    def sleep(self, seconds):
        if seconds > 0:
            self._sleep(seconds)

    def sleep_ms(self, ms):
        self.sleep(ms / 1000.0)


def _scale(c, f):
    return (min(255, int(c[0] * f)), min(255, int(c[1] * f)), min(255, int(c[2] * f)))


def _lerp(a, b, t):
    return (min(255, int(a[0] + (b[0] - a[0]) * t)),
            min(255, int(a[1] + (b[1] - a[1]) * t)),
            min(255, int(a[2] + (b[2] - a[2]) * t)))


def wheel(pos):
    if pos < 85:
        return (pos * 3, 255 - pos * 3, 0)
    elif pos < 170:
        pos -= 85
        return (255 - pos * 3, 0, pos * 3)
    pos -= 170
    return (0, pos * 3, 255 - pos * 3)


def hsv_to_rgb(h, s, v):
    i = int(h * 6.0)
    f = (h * 6.0) - i
    p = int(v * (1.0 - s) * 255.0)
    q = int(v * (1.0 - f * s) * 255.0)
    t = int(v * (1.0 - (1.0 - f) * s) * 255.0)
    v = int(v * 255.0)
    i = i % 6
    return [(v, t, p), (q, v, p), (p, v, t), (p, q, v), (t, p, v), (v, p, q)][i]


# ---------------------------------------------------------------------------
# Routines — every one is fn(strip, p) and loops on strip.running()
# ---------------------------------------------------------------------------
def solid(s, p):
    s.fill(p['color'])
    s.show()
    s.hold()


def color_wipe(s, p):
    rng = range(0, s.n, 1) if p['direction'] > 0 else range(s.n - 1, -1, -1)
    for i in rng:
        if not s.running():
            return
        s[i] = p['color']
        s.show()
        s.sleep_ms(p['speed'])
    s.hold()


def beam(s, p):
    step = 1 if p['direction'] > 0 else -1
    while s.running():
        rng = range(0, s.n, 1) if step > 0 else range(s.n - 1, -1, -1)
        for i in rng:
            if not s.running():
                break
            s[i] = p['color']
            s.show()
            s.fill((0, 0, 0))
            s.sleep_ms(p['speed'])
        s.off()


def marquee(s, p):
    odd = True
    even_n = s.n if s.n % 2 == 0 else s.n - 1
    while s.running():
        for i in range(even_n):
            s[i] = p['color'] if odd else p['color2']
            odd = not odd
        s.show()
        odd = not odd
        s.sleep_ms(p['speed'])


def marquee_effect(s, p):
    """Comet: bright head with a fading tail over a background color."""
    trail = int(p['trail'])
    tail = [1.0] + [0.55 * (0.45 ** t) for t in range(trail)]
    step = 1 if p['direction'] > 0 else -1
    pos = 0 if step > 0 else s.n - 1
    while s.running():
        s.fill(p['color'])
        for t, inten in enumerate(tail):
            s[(pos - step * t) % s.n] = _scale(p['color2'], inten)
        s.show()
        s.sleep_ms(p['speed'])
        pos = (pos + step) % s.n


def _color_rand(component, diff):
    diff = min(int(diff), 100)
    component = int(component)
    if component < diff:
        component = diff
    if component > 255 - diff:
        component = 255 - diff
    return random.randint(component - diff, component + diff)


def sparkle(s, p):
    """Fill, then twinkle random pixels to nearby shades while the strip's
    level gently pulses (the pulse is a 0.6–1.0 factor of the pattern level,
    so it can never climb past the hardware cap the way the old version did)."""
    color, var = p['color'], p['variance']
    s.fill(color)
    s.show()
    factor, rising = 1.0, False
    while s.running():
        i = random.randint(0, s.n - 1)
        s[i] = (_color_rand(color[0], var[0]), _color_rand(color[1], var[1]),
                _color_rand(color[2], var[2]))
        factor += 0.008 if rising else -0.008
        if factor <= 0.6:
            rising = True
        elif factor >= 1.0:
            rising = False
        s.set_level(factor)
        s.show()
        s.sleep_ms(random.randint(1, max(1, int(p['speed']))))


class _Eye:
    LENGTH = 10

    def __init__(self, s, color):
        self.s = s
        self.base = [int(color[0]), int(color[1]), int(color[2])]
        self.p_ct = s.n - 1
        bright = [0.25 if i == 0 else i * 0.25 for i in range(self.LENGTH // 2)]
        bright += [bright[i - 1] for i in range(self.LENGTH // 2, 0, -1)]
        self.parts = []   # [location, color]
        for loc in range(self.LENGTH):
            if loc in (0, self.LENGTH - 1):
                self.parts.append([loc, [0, 0, 0]])
            else:
                self.parts.append([loc, [int(self.base[k] * bright[loc]) for k in range(3)]])

    def move(self, num, wait_ms):
        s, L = self.s, self.LENGTH
        future = [num - i for i in range(L // 2, 0, -1)] + \
                 [num + i - L // 2 for i in range(L // 2, L)]
        start = end = 0
        direction = 1
        for j, part in enumerate(self.parts):
            if j == L // 2:
                start, end = part[0], future[j]
                if start > end:
                    direction = -1
        for k in range(start, end, direction):
            if not s.running():
                return
            for part in self.parts:
                part[0] += direction
                if part[0] < 0:
                    part[0] = self.p_ct - part[0] - 1
                elif part[0] > self.p_ct:
                    part[0] = self.p_ct - part[0] + 1
                loc = int(_clamp(part[0], 0, self.p_ct))
                s[loc] = [min(int(c), 255) for c in part[1]]
            s.show()
            s.sleep(wait_ms / 50 if end - 2 <= k <= end else wait_ms / 1000)


def eye_look(s, p):
    a, b = _Eye(s, p['color']), _Eye(s, p['color'])
    while s.running():
        a.move(random.randint(0, s.n - 1), p['speed'])
        b.move(random.randint(0, s.n - 1), p['speed'])


def rainbow_cycle(s, p):
    j = 0
    step = 1 if p['direction'] > 0 else -1
    while s.running():
        for i in range(s.n):
            s[i] = wheel(((i * 256 // s.n) + j) & 255)
        s.show()
        s.sleep_ms(p['speed'])
        j = (j + step) % 256


def rainbow_rotate(s, p):
    color, up = [0, 0, 0], [True, True, True]
    j = 0
    while s.running():
        up[0] = bool(j & 256)
        up[1] = bool(j & 512)
        up[2] = not (j & 768)
        for i in range(3):
            if up[i]:
                if color[i] >= 254:
                    up[i] = False
                else:
                    color[i] += 1
            else:
                if color[i] <= 1:
                    up[i] = True
                else:
                    color[i] -= 1
        s.fill(color)
        s.show()
        s.sleep_ms(p['speed'])
        j += 1


def fireworks_simulation(s, p):
    color, trail_c, wait_ms = p['color'], p['color2'], p['speed']
    TRAIL_LEN, SPARK_COUNT, SPARK_RADIUS = 3, int(p['sparks']), 22
    step = 1 if p['direction'] > 0 else -1
    while s.running():
        launch = (random.randint(0, s.n // 3) if step > 0
                  else random.randint(2 * s.n // 3, s.n - 1))
        burst = launch + step * random.randint(s.n // 4, s.n // 2)
        burst = max(0, min(s.n - 1, burst))
        pos = launch
        while (step > 0 and pos <= burst) or (step < 0 and pos >= burst):
            if not s.running():
                return
            s.fill((0, 0, 0))
            for t in range(TRAIL_LEN + 1):
                tp = pos - step * t
                if 0 <= tp < s.n:
                    s[tp] = _scale(trail_c, 1.0 - (t / (TRAIL_LEN + 1)))
            s.show()
            s.sleep_ms(wait_ms)
            pos += step
        s.fill((0, 0, 0))
        HALO = 5
        for off in range(-HALO, HALO + 1):
            q = burst + off
            if 0 <= q < s.n:
                s[q] = _scale(color, 1.0 - (abs(off) / (HALO + 1)))
        s.show()
        s.sleep_ms(wait_ms * 3)
        sparks = []
        for _ in range(SPARK_COUNT):
            sparks.append({
                'pos': float(burst), 'dir': 1 if random.random() < 0.5 else -1,
                'dist': random.randint(SPARK_RADIUS // 2, SPARK_RADIUS),
                'traveled': 0.0, 'speed': random.uniform(0.3, 0.9), 'intensity': 1.0,
                'color': tuple(min(255, max(0, c + random.randint(-40, 40))) for c in color),
                'fade': random.uniform(0.025, 0.055),
            })
        while any(sp['intensity'] > 0.015 for sp in sparks):
            if not s.running():
                return
            s.fill((0, 0, 0))
            for sp in sparks:
                if sp['intensity'] <= 0.015:
                    continue
                if sp['traveled'] < sp['dist']:
                    sp['pos'] += sp['dir'] * sp['speed']
                    sp['traveled'] += sp['speed']
                if sp['traveled'] >= sp['dist']:
                    sp['fade'] = min(0.07, sp['fade'] * 1.06)
                sp['intensity'] = max(0.0, sp['intensity'] - sp['fade'])
                q = int(sp['pos'])
                tail = q - sp['dir']
                if 0 <= q < s.n:
                    s[q] = _scale(sp['color'], sp['intensity'])
                if sp['traveled'] < sp['dist'] and 0 <= tail < s.n:
                    s[tail] = _scale(sp['color'], sp['intensity'] * 0.4)
            s.show()
            s.sleep_ms(wait_ms)
        s.off()
        s.sleep(random.uniform(0.3, 0.8))


def fireworks_finale(s, p):
    wait_ms = p['speed']
    while s.running():
        for _ in range(10):
            if not s.running():
                return
            trail_c = tuple(random.randint(0, 255) for _ in range(3))
            burst_c = tuple(random.randint(0, 255) for _ in range(3))
            start = random.randint(0, s.n - 1)
            center = min(s.n - 1, start + random.randint(5, 15))
            for i in range(start, center):
                if 0 <= i < s.n - 1:
                    s[i] = trail_c
                    s.show()
                    s.sleep_ms(wait_ms / 2)
                    s[i] = (0, 0, 0)
            fizzle = {}
            for off in range(-10, 11):
                q = center + off
                if 0 <= q < s.n:
                    fizzle[q] = 1.0 - (abs(off) / 11) * 0.5
            for q, inten in fizzle.items():
                s[q] = _scale(burst_c, inten)
            s.show()
            s.sleep_ms(wait_ms * 2)
            while any(v > 0.02 for v in fizzle.values()):
                if not s.running():
                    return
                for q in fizzle:
                    fizzle[q] = max(0.0, fizzle[q] - random.uniform(0.03, 0.07))
                    s[q] = _scale(burst_c, fizzle[q])
                s.show()
                s.sleep_ms(wait_ms)
        s.sleep_ms(wait_ms * 2)
    s.off()


def shimmer_sine_wave(s, p):
    color, glint, wait_ms = p['color'], p['color2'], p['speed']
    WAVE_CYCLES, RATE, DECAY = 2.5, 0.06, 0.18
    phase = 0.0
    shimmer = [0.0] * s.n
    while s.running():
        phase += p['direction'] * (2 * math.pi / s.n) * 0.8
        for i in range(s.n):
            if random.random() < RATE:
                shimmer[i] = 1.0
        for i in range(s.n):
            wave = (math.sin(phase + i * (2 * math.pi * WAVE_CYCLES / s.n)) + 1) / 2
            s[i] = (min(255, int(color[0] * wave) + int(glint[0] * shimmer[i])),
                    min(255, int(color[1] * wave) + int(glint[1] * shimmer[i])),
                    min(255, int(color[2] * wave) + int(glint[2] * shimmer[i])))
            shimmer[i] = max(0.0, shimmer[i] - DECAY)
        s.show()
        s.sleep_ms(wait_ms)


def shimmer_effect(s, p):
    color, bright = p['color'], p['color2']
    drift = 1.0 if p['direction'] > 0 else -1.0
    BASE_SPEED = 0.03
    mult = [random.uniform(0.6, 1.4) + drift * 0.3 * (i / s.n) for i in range(s.n)]
    phases = [random.uniform(0, 2 * math.pi) for _ in range(s.n)]
    while s.running():
        for i in range(s.n):
            phases[i] += BASE_SPEED * mult[i]
            s[i] = _lerp(color, bright, (math.sin(phases[i]) + 1) / 2)
        s.show()
        s.sleep_ms(p['speed'])
    s.off()


def aurora_drift(s, p):
    wave_count = max(1, int(s.n * 0.1))
    waves = [{'position': random.randint(0, s.n - 1), 'speed': random.uniform(0.5, 1.5),
              'hue': random.uniform(0, 1)} for _ in range(wave_count)]
    while s.running():
        s.fill((0, 0, 0))
        for w in waves:
            w['position'] = (w['position'] + w['speed']) % s.n
            w['hue'] = (w['hue'] + 0.05) % 1.0
            wc = hsv_to_rgb(w['hue'], 1.0, 1.0)
            for i in range(-5, 6):
                s[int((w['position'] + i) % s.n)] = _scale(wc, 1.0 - abs(i) / 5.0)
        s.show()
        s.sleep_ms(p['speed'])
    s.off()


def cosmic_vortex(s, p):
    pulse_speed, swirl_speed, center_brightness = 0.05, 2, 1.5
    t0 = s._clock()
    while s.running():
        now = s._clock() - t0
        g = (math.sin(now * pulse_speed * 2 * math.pi) + 1) / 2 * 0.8 + 0.2
        for i in range(s.n):
            angle = (i / s.n) * 2 * math.pi
            distance = i / s.n
            hue = ((angle + now * swirl_speed * 2 * math.pi) / (2 * math.pi) + distance) % 1.0
            s[i] = tuple(min(max(int(c * (1 - distance) * center_brightness), 0), 255)
                         for c in hsv_to_rgb(hue, 1.0, g))
        s.show()
        s.sleep_ms(p['speed'])
    s.off()


def serenity_flow(s, p):
    color, far, wait_ms = p['color'], p['color2'], p['speed']
    GROW = max(1, int(2500 / max(1, wait_ms)))
    HOLD = max(1, int(800 / max(1, wait_ms)))
    FADE = max(1, int(3500 / max(1, wait_ms)))
    DARK = max(1, int(600 / max(1, wait_ms)))
    denom = max(1, s.n - 1)

    def frame(envelope, shimmer_phase, color_phase, shim_amp):
        for i in range(s.n):
            pos = (i / denom) if p['direction'] > 0 else (1.0 - i / denom)
            spread = (math.sin(color_phase + pos * math.pi) + 1) / 2
            shim = 1.0 + shim_amp * math.sin(shimmer_phase + i * 0.4)
            s[i] = tuple(min(255, max(0, int((color[k] + (far[k] - color[k]) * spread)
                                             * envelope * shim))) for k in range(3))
        s.show()
        s.sleep_ms(wait_ms)

    while s.running():
        shimmer_speed = random.uniform(0.008, 0.018)
        shimmer_phase = random.uniform(0, 2 * math.pi)
        color_phase = random.uniform(0, 2 * math.pi)
        for f in range(GROW):
            if not s.running():
                return
            shimmer_phase += shimmer_speed
            color_phase += 0.006
            frame(math.sin((f / GROW) * (math.pi / 2)), shimmer_phase, color_phase, 0.06)
        for _ in range(HOLD):
            if not s.running():
                return
            shimmer_phase += shimmer_speed
            color_phase += 0.006
            frame(1.0, shimmer_phase, color_phase, 0.06)
        for f in range(FADE):
            if not s.running():
                return
            shimmer_phase += shimmer_speed * 0.5
            color_phase += 0.003
            frame(math.cos((f / FADE) * (math.pi / 2)), shimmer_phase, color_phase, 0.03)
        s.off()
        for _ in range(DARK):
            if not s.running():
                return
            s.sleep_ms(wait_ms)
    s.off()


def tranquil_drift(s, p):
    color, c2 = p['color'], p['color2']
    phase = breath_phase = 0.0
    while s.running():
        phase += p['direction'] * (2 * math.pi / s.n) * 0.5
        breath_phase += 0.012
        breath = 0.775 + 0.225 * math.sin(breath_phase)
        for i in range(s.n):
            blend = (math.sin(phase + i * (2 * math.pi / s.n) * 2) + 1) / 2
            s[i] = tuple(max(0, min(255, int((color[k] * (1.0 - blend) + c2[k] * blend) * breath)))
                         for k in range(3))
        s.show()
        s.sleep_ms(p['speed'])


def digital_dreamscape(s, p):
    wait_ms, color_variation, glitch_frequency = p['speed'], 0.9, 3
    phases = [random.uniform(0, 2 * math.pi) for _ in range(s.n)]
    t0 = s._clock()
    while s.running():
        now = s._clock() - t0
        for i in range(s.n):
            w1 = math.sin((i / s.n) * 4 * math.pi + now * wait_ms + phases[i]) * 0.5
            w2 = math.sin((i / s.n) * 2 * math.pi + now * wait_ms * 0.75) * 0.25
            total = (w1 + w2 + 1) / 2
            r = int((math.sin(now * color_variation + phases[i]) + 1) * 127.5)
            g = int((math.sin(now * color_variation + phases[i] + 2) + 1) * 127.5)
            b = int((math.sin(now * color_variation + phases[i] + 4) + 1) * 127.5)
            if random.random() < glitch_frequency:
                gf = random.uniform(0.5, 1.5)
                r, g, b = int(r * gf), int(g * gf), int(b * gf)
            s[i] = (min(max(int(r * total), 0), 255), min(max(int(g * total), 0), 255),
                    min(max(int(b * total), 0), 255))
        s.show()
        s.sleep_ms(wait_ms)
    s.off()


def lightning_strike(s, p):
    sky, bolt, wait_ms = p['color'], p['color2'], p['speed']
    step = 1 if p['direction'] > 0 else -1
    while s.running():
        s.fill(sky)                      # the lull shows the sky, not stale pixels
        s.show()
        quiet = max(1, int(wait_ms * random.uniform(1.5, 2.5) / 30))
        for _ in range(quiet):
            if not s.running():
                return
            if random.random() < 0.03:
                s.fill(_scale(bolt, random.uniform(0.03, 0.08)))
                s.show()
                s.sleep(0.02)
                s.fill(sky)
                s.show()
            s.sleep(0.03)
        origin = random.randint(0, s.n - 1)
        length = random.randint(max(1, s.n // 4), max(1, s.n // 2))
        lit = []
        pos = origin
        s.fill(sky)
        for _ in range(length):
            if not s.running():
                return
            pos = (pos + step * random.choices([-1, 1, 2, 3], weights=[15, 40, 30, 15])[0]) % s.n
            lit.append(pos)
            s[pos] = _scale(bolt, random.uniform(0.75, 1.0))
            if lit and random.random() < 0.70:
                s[random.choice(lit)] = _scale(bolt, random.uniform(0.2, 0.8))
            s.show()
            s.sleep(random.uniform(0.005, 0.025))
        for i in range(s.n):
            s[i] = _scale(bolt, random.uniform(0.88, 1.0))
        s.show()
        s.sleep_ms(wait_ms * random.uniform(0.5, 1.0))
        for n in range(14):
            fade = 0.75 ** (n + 1)
            blend = 1.0 - fade
            c = tuple(min(255, int((bolt[k] * fade) + (sky[k] * blend * fade))) for k in range(3))
            s.fill(c)
            s.show()
            s.sleep(0.045)
        s.off()


def thunderstorm(s, p):
    rain, flash, wait_ms = p['color'], p['color2'], p['speed']
    RAIN_DENSITY, FRAME_MS, RUMBLE_SPEED = float(p['density']), 30, 0.015
    step = 1.4 if p['direction'] > 0 else -1.4
    tail_step = -1 if p['direction'] > 0 else 1
    spawn = 0.0 if p['direction'] > 0 else float(s.n - 1)
    droplets = []
    rumble_phase = 0.0
    while s.running():
        frames = max(1, int(wait_ms * random.uniform(0.5, 1.5) / FRAME_MS))
        for _ in range(frames):
            if not s.running():
                return
            rumble_phase += RUMBLE_SPEED
            rumble = (math.sin(rumble_phase) + 1) / 2 * 0.08
            if random.random() < RAIN_DENSITY:
                droplets.append([spawn, random.uniform(0.6, 1.0)])
            frame = [[min(255, int(rain[k] * (rumble + 0.15))) for k in range(3)]
                     for _ in range(s.n)]
            surviving = []
            for d in droplets:
                pos, inten = d
                for t in range(4):
                    q = int(pos) + tail_step * t
                    if 0 <= q < s.n:
                        tf = inten * (0.55 ** t)
                        for k in range(3):
                            frame[q][k] = min(255, frame[q][k] + int(rain[k] * tf))
                d[0] += step
                d[1] *= 0.97
                if 0 <= int(d[0]) < s.n and d[1] > 0.05:
                    surviving.append(d)
            droplets[:] = surviving
            for i in range(s.n):
                s[i] = frame[i]
            s.show()
            s.sleep_ms(FRAME_MS)
        flashes = 2 if random.random() < 0.3 else 1
        for f in range(flashes):
            for i in range(s.n):
                s[i] = _scale(flash, random.uniform(0.85, 1.0))
            s.show()
            s.sleep(random.uniform(wait_ms * 0.5, wait_ms) / 1000.0)
            if flashes == 2 and f == 0:
                s.off()
                s.sleep(random.uniform(wait_ms * 0.5, wait_ms) / 1000.0)
        for n in range(12):
            fade = 0.72 ** (n + 1)
            for i in range(s.n):
                s[i] = _scale(flash, fade * random.uniform(0.9, 1.0))
            s.show()
            s.sleep(0.04)
    s.off()


def color_chase(s, p):
    wait_ms = p['speed']
    TAIL_LEN, CATCH, CHASER_BASE, PREY_BASE, WOBBLE = 5, 2.0, 1.0, 0.55, 0.25
    PORTAL_CHANCE, HALO = 0.008, 12
    prey_step = 1 if p['direction'] > 0 else -1
    chaser_pos = 0.0 if prey_step == 1 else float(s.n - 1)
    prey_pos = _clamp(chaser_pos + prey_step * (s.n // 3), 0.0, float(s.n - 1))
    chaser_c, prey_c = list(p['color2']), list(p['color'])

    def particle(pos, col, tail_step):
        q = int(pos)
        for t in range(TAIL_LEN + 1):
            tp = q + tail_step * t
            if 0 <= tp < s.n:
                s[tp] = _scale(col, 0.55 ** t)

    def portal(pos, col):
        for fi in range(3):
            inten = 1.0 - fi / 3
            for off in range(-3, 4):
                q = int(pos) + off
                if 0 <= q < s.n:
                    s[q] = _scale(col, inten * (0.6 ** abs(off)))
            s.show()
            s.sleep_ms(wait_ms)

    while s.running():
        chaser_dir = 1 if prey_pos > chaser_pos else -1
        chaser_pos += chaser_dir * (CHASER_BASE + random.uniform(-WOBBLE, WOBBLE))
        prey_pos += prey_step * (PREY_BASE + random.uniform(-WOBBLE, WOBBLE))
        if prey_pos >= s.n - 1:
            prey_pos, prey_step = float(s.n - 1), -1
        elif prey_pos <= 0:
            prey_pos, prey_step = 0.0, 1
        chaser_pos = _clamp(chaser_pos, 0.0, float(s.n - 1))
        if s.n > 6 and random.random() < PORTAL_CHANCE:
            portal(prey_pos, prey_c)
            for _ in range(50):
                new_pos = float(random.randint(2, s.n - 3))
                if abs(new_pos - chaser_pos) > s.n // 5:
                    break
            prey_pos = new_pos
            portal(prey_pos, prey_c)
        if abs(chaser_pos - prey_pos) <= CATCH:
            impact = int((chaser_pos + prey_pos) / 2)
            for fi in range(10):
                if not s.running():
                    return
                fl = 1.0 - (fi / 10)
                s.fill((0, 0, 0))
                for off in range(-HALO, HALO + 1):
                    q = impact + off
                    if 0 <= q < s.n:
                        df = fl * (0.82 ** abs(off))
                        s[q] = tuple(min(255, int((chaser_c[k] + prey_c[k]) / 2 * df)) for k in range(3))
                s.show()
                s.sleep_ms(wait_ms)
            chaser_c, prey_c = prey_c, chaser_c
            chaser_pos = float(impact)
            prey_step = random.choice([-1, 1])
            prey_pos = _clamp(float(impact) + prey_step * (s.n // 3), 0.0, float(s.n - 1))
            continue
        s.fill((0, 0, 0))
        particle(prey_pos, prey_c, -prey_step)
        particle(chaser_pos, chaser_c, -chaser_dir)
        s.show()
        s.sleep_ms(wait_ms)
    s.off()


def ember_rise(s, p):
    cool, hot = p['color'], p['color2']
    SPAWN_RATE, MAX_EMBERS, TAIL_LEN = float(p['density']), 60, 6
    step = 1 if p['direction'] > 0 else -1
    spawn = 0.0 if step > 0 else float(s.n - 1)
    embers = []
    while s.running():
        if len(embers) < MAX_EMBERS and random.random() < SPAWN_RATE:
            speed = random.uniform(0.3, 1.0)
            embers.append({'pos': spawn + random.uniform(-1.5, 1.5), 'speed': speed,
                           'heat': 1.0, 'fade': (speed / s.n) * random.uniform(0.7, 1.1)})
        frame = [(0, 0, 0)] * s.n
        surviving = []
        for e in embers:
            e['pos'] += step * e['speed']
            e['heat'] = max(0.0, e['heat'] - e['fade'])
            if e['heat'] <= 0.01 or not (0 <= int(e['pos']) < s.n):
                continue
            for t in range(TAIL_LEN):
                q = int(e['pos']) - step * t
                if 0 <= q < s.n:
                    th = e['heat'] * (0.5 ** t)
                    tc = _lerp(cool, hot, th)
                    frame[q] = (min(255, frame[q][0] + tc[0]), min(255, frame[q][1] + tc[1]),
                                min(255, frame[q][2] + tc[2]))
            surviving.append(e)
        embers[:] = surviving
        for i in range(s.n):
            s[i] = frame[i]
        s.show()
        s.sleep_ms(p['speed'])
    s.off()


def wave_positions(n, direction=1):
    """Where each pixel sits between open sea (0.0) and shore (1.0).
    The strip circles the table with its ends meeting, so the seam (both
    ends) is the sea and the strip's midpoint is the shore: a wave leaves
    the seam along both halves at once and breaks on the far side with no
    visible join. direction -1 swaps sea and shore."""
    if n <= 1:
        return [1.0] * n
    mid = (n - 1) / 2.0
    xs = [1.0 - abs(i - mid) / mid for i in range(n)]
    return [1.0 - x for x in xs] if direction < 0 else xs


def wave_crash(s, p):
    """One wave at a time: approach (swell rises and steepens as it travels
    toward the break point), crash (flash + foam burst), wash (foam sheet
    runs up the beach), recede (it drains back, leaving dark wet sand),
    lull (dim water with ripples). Wave size and spacing vary naturally
    around 'speed' (ms between waves); about one in four is a bigger set
    wave. Pixels past the break point are the beach and stay dark between
    waves."""
    water, foam = p['color'], p['color2']
    FRAME = 0.03
    BREAK_X = 0.72                   # where the crest crashes (0 sea … 1 shore)
    period = max(2.0, float(p['speed']) / 1000.0)
    xs = wave_positions(s.n, p['direction'])
    ripple = 0.0

    def paint(level, fmix):
        level = _clamp(level, 0.0, 1.0)
        fmix = _clamp(fmix, 0.0, 1.0)
        return _lerp(_scale(water, level), _scale(foam, level), fmix)

    while s.running():
        size = 1.0 if random.random() < 0.25 else random.uniform(0.55, 0.9)
        approach = 3.2 * (0.8 + 0.4 * size)
        crash = 0.5
        wash = 1.4 + 0.8 * size
        recede = 1.8 + 0.6 * size
        lull = max(0.6, period * random.uniform(0.65, 1.35) - (approach + crash + wash + recede))
        total = approach + crash + wash + recede + lull
        t = 0.0
        while t < total and s.running():
            ripple += 0.05
            crest_pos = crest_w = crest_amp = foam_face = 0.0
            foam_back = foam_front = foam_amp = flash = wet = 0.0
            if t < approach:
                u = t / approach
                crest_pos = BREAK_X * (u ** 1.25)          # accelerates toward the break
                crest_w = 0.24 - 0.12 * u                   # steepens
                crest_amp = size * (0.3 + 0.7 * u)
                foam_face = max(0.0, (u - 0.55) / 0.45) * 0.85
            elif t < approach + crash:
                u = (t - approach) / crash
                crest_pos, crest_w, crest_amp = BREAK_X, 0.12, size * (1.0 - u)
                foam_back, foam_front = BREAK_X - 0.15, BREAK_X + (1.0 - BREAK_X) * 0.35 * u
                foam_amp = size * (0.7 + 0.3 * u)
                flash = size * (1.0 - u) ** 2
            elif t < approach + crash + wash:
                u = (t - approach - crash) / wash
                foam_back = BREAK_X - 0.15 + 0.30 * u
                foam_front = BREAK_X + (1.0 - BREAK_X) * (0.35 + 0.65 * (u ** 0.7))
                foam_amp = size * (1.0 - 0.45 * u)
                wet = 0.5 * u
            elif t < approach + crash + wash + recede:
                u = (t - approach - crash - wash) / recede
                foam_front = 1.0 - 0.55 * u
                foam_back = BREAK_X + 0.15 - 0.25 * u
                foam_amp = size * 0.55 * (1.0 - u)
                wet = 0.5 * (1.0 - u)
            for i, x in enumerate(xs):
                level = 0.18 + 0.06 * math.sin(ripple + x * 9.0)
                if x > BREAK_X:                             # the beach: dark unless wet
                    level = level * max(0.0, 1.0 - (x - BREAK_X) / (1.0 - BREAK_X)) + wet * 0.25
                fmix = 0.0
                if crest_amp > 0.0:
                    d = (x - crest_pos) / crest_w
                    g = math.exp(-d * d)
                    level += crest_amp * g
                    fmix = max(fmix, foam_face * g * (1.0 if x >= crest_pos else 0.35))
                if foam_amp > 0.0 and foam_back <= x <= foam_front:
                    edge = 1.0 - (foam_front - x) / max(1e-3, foam_front - foam_back)
                    f = foam_amp * (0.35 + 0.65 * edge)
                    if random.random() < 0.2:
                        f *= 1.35                            # fizz
                    level = max(level, f)
                    fmix = max(fmix, f)
                if flash > 0.0:                             # the crash lights the shore side only
                    local = flash * _clamp((x - 0.4) / 0.32, 0.0, 1.0)
                    level = max(level, local)
                    fmix = max(fmix, local)
                s[i] = paint(level, fmix)
            s.show()
            s.sleep(FRAME)
            t += FRAME
    s.off()


def perimeter_distances(n, ratio=1.5, seam_at_corner=True):
    """Distance of each pixel from the table's centre, 0–1 of the corner
    distance, for a strip that runs around a rectangle `ratio` times as long
    as it is wide. With the seam at a corner pixel 0 IS that corner; with the
    seam mid-side pixel 0 is the middle of a long side. Long-side midpoints
    are nearest the centre, then short-side midpoints, corners farthest."""
    if n <= 0:
        return []
    L, W = max(1.0, float(ratio)), 1.0
    P = 2 * (L + W)
    rmax = math.hypot(L / 2, W / 2)
    offset = 0.0 if seam_at_corner else L / 2
    out = []
    for i in range(n):
        d = (offset + P * i / n) % P
        if d < L:
            x, y = -L / 2 + d, -W / 2
        elif d < L + W:
            x, y = L / 2, -W / 2 + (d - L)
        elif d < 2 * L + W:
            x, y = L / 2 - (d - L - W), W / 2
        else:
            x, y = -L / 2, W / 2 - (d - 2 * L - W)
        out.append(math.hypot(x, y) / rmax)
    return out


def raindrop(s, p):
    """Rings from drops at the table's centre. Each drop is a decaying wave
    packet (a few crests and troughs) expanding at a fixed speed; a pixel
    shows it when the packet's radius passes its own distance from the
    centre, so the rings roll through the strip nearest-first. Drops come
    at random around 'speed' ms and may overlap; between them the water
    sits dim and still with a faint shimmer."""
    water, glint = p['color'], p['color2']
    FRAME = 0.03
    RING_SPEED = 0.45      # corner-distances per second (~2.2 s centre → corner)
    WAVELENGTH = 0.26      # crest-to-crest, in corner-distances
    SIGMA = 1.0 * WAVELENGTH
    DECAY = 6.0            # seconds for a packet to fade to ~37 %
    period = max(0.5, float(p['speed']) / 1000.0)
    rs = perimeter_distances(s.n, p['ratio'], int(p['seam']) == 1)
    drops = []             # impact times
    t = 0.0
    next_drop = random.uniform(0.2, 0.8)
    shimmer = 0.0
    while s.running():
        if t >= next_drop:
            drops.append(t)
            next_drop = t + period * random.uniform(0.5, 1.5)
        shimmer += 0.03
        packets = []
        keep = []
        for t0 in drops:
            age = t - t0
            radius = RING_SPEED * age
            amp = math.exp(-age / DECAY)
            if amp > 0.02 and radius - 3 * SIGMA < 1.05:
                packets.append((radius, amp))
                keep.append(t0)
        drops = keep
        for i, r in enumerate(rs):
            base = 0.16 + 0.03 * math.sin(shimmer + r * 7.0 + i * 0.3)
            disp = 0.0
            for radius, amp in packets:
                d = r - radius
                env = math.exp(-(d / SIGMA) ** 2)
                if env < 0.01:
                    continue
                disp += amp * env * math.cos(2 * math.pi * d / WAVELENGTH) / (max(r, 0.3) ** 0.3)
            disp = _clamp(1.4 * disp, -1.0, 1.0)
            level = _clamp(base + 0.8 * disp, 0.03, 1.0)
            fmix = _clamp(disp, 0.0, 1.0)                 # crests glint, troughs go dark
            s[i] = _lerp(_scale(water, level), _scale(glint, level), fmix)
        s.show()
        s.sleep(FRAME)
        t += FRAME
    s.off()


def fire_color(ember, flame, h):
    """Heat 0–1 → color: near-black ember glow → ember → flame → white-hot."""
    hot = tuple(min(255, c + 160) for c in flame)
    h = _clamp(h, 0.0, 1.0)
    if h < 0.45:
        return _lerp(_scale(ember, 0.1), ember, h / 0.45)
    if h < 0.85:
        return _lerp(ember, flame, (h - 0.45) / 0.40)
    return _lerp(flame, hot, (h - 0.85) / 0.15)


def bonfire(s, p):
    """Per-pixel heat that cools and diffuses around the ring (the strip's
    ends meet, so heat wraps across the seam), fed by random tongues of
    flame (density), shaped by slow gusts, with sparks that flash white and
    cool away. Heat maps to ember → flame → white-hot through fire_color."""
    ember, flame = p['color'], p['color2']
    n = s.n
    frame_s = max(0.005, float(p['speed']) / 1000.0)
    activity = float(p['density'])
    spark_rate = float(p['sparks'])
    heat = [0.3] * n
    sparks = {}            # pixel -> flash life (1.0 → 0), independent of the gust
    gust, gust_target, gust_timer = 1.0, 1.0, 0.0
    while s.running():
        # gusts: drift toward a new random strength every 1–3 s
        gust_timer -= frame_s
        if gust_timer <= 0:
            gust_target = random.uniform(0.6, 1.1)
            gust_timer = random.uniform(1.0, 3.0)
        gust += (gust_target - gust) * 0.04
        # cool + diffuse around the ring
        new = []
        for i in range(n):
            v = heat[i] * 0.6 + heat[i - 1] * 0.2 + heat[(i + 1) % n] * 0.2
            v -= random.uniform(0.0, 0.07)
            new.append(max(0.2 + random.uniform(-0.03, 0.03), v))   # embers never go out
        heat = new
        # tongues of flame: a warm bump a few pixels wide
        if n > 0 and random.random() < activity:
            centre = random.randrange(n)
            width = random.uniform(1.5, 5.0)
            amp = random.uniform(0.45, 1.0)
            for off in range(-8, 9):
                j = (centre + off) % n
                heat[j] = min(1.0, heat[j] + amp * math.exp(-(off / width) ** 2))
        # sparks: a pixel flashes white-hot for a few frames, leaving heat behind
        if n > 0 and random.random() < spark_rate * frame_s:
            j = random.randrange(n)
            sparks[j] = 1.0
            heat[j] = 1.0
        for j in list(sparks):
            sparks[j] *= 0.55
            if sparks[j] < 0.05:
                del sparks[j]
        for i in range(n):
            c = fire_color(ember, flame, heat[i] * gust)
            life = sparks.get(i)
            if life:
                c = _lerp(c, (255, 255, 230), life)
            s[i] = c
        s.show()
        s.sleep(frame_s)
    s.off()


def joyful_celebration(s, p):
    colors = [(255, 0, 0), (125, 125, 0), (255, 255, 0), (0, 255, 0), (0, 0, 255),
              (75, 0, 130), (238, 130, 238)]
    pulse_speed, chase_ms, confetti = 0.1, p['speed'], 0.06
    while s.running():
        for bright in list(range(0, 256, 5)) + list(range(255, -1, -5)):
            if not s.running():
                return
            for i in range(s.n):
                s[i] = _scale(colors[i % len(colors)], bright / 255)
            s.show()
            s.sleep(pulse_speed)
        for i in range(s.n):
            if not s.running():
                return
            s[i] = colors[i % len(colors)]
            s.show()
            s.sleep_ms(chase_ms)
            s[i] = (0, 0, 0)
        if random.random() < confetti:
            i = random.randint(0, s.n - 1)
            s[i] = (255, 255, 255)
            s.show()
            s.sleep(0.1)
            s[i] = (0, 0, 0)


# Registry type -> routine. The test suite pins this to led_patterns.PATTERNS.
FUNCS = {
    'solid': solid,
    'color_wipe': color_wipe,
    'beam': beam,
    'marquee': marquee,
    'marquee_effect': marquee_effect,
    'sparkle': sparkle,
    'eye': eye_look,
    'rainbow_wave': rainbow_cycle,
    'rainbow_rotate': rainbow_rotate,
    'lightning_strike': lightning_strike,
    'thunderstorm': thunderstorm,
    'fireworks_simulation': fireworks_simulation,
    'fireworks_finale': fireworks_finale,
    'shimmer_sine_wave': shimmer_sine_wave,
    'shimmer_effect': shimmer_effect,
    'wave_crash': wave_crash,
    'raindrop': raindrop,
    'ember_rise': ember_rise,
    'bonfire': bonfire,
    'serenity_flow': serenity_flow,
    'tranquil_drift': tranquil_drift,
    'color_chase': color_chase,
    'aurora_drift': aurora_drift,
    'cosmic_vortex': cosmic_vortex,
    'digital_dreamscape': digital_dreamscape,
    'joyful_celebration': joyful_celebration,
}


# ---------------------------------------------------------------------------
# Player
# ---------------------------------------------------------------------------
def plan(patterns, last=None):
    """One pass through a scene's patterns: rows sorted by 'order', rows that
    SHARE an order shuffled, and the first pick nudged so the pattern that
    just finished (`last`) doesn't play twice back-to-back."""
    groups = {}
    for p in patterns:
        groups.setdefault(int(p.get('order', 0)), []).append(p)
    seq = []
    for order in sorted(groups):
        g = list(groups[order])
        random.shuffle(g)
        if len(g) > 1 and last is not None and g[0] is last:
            g[0], g[-1] = g[-1], g[0]
        seq.extend(g)
        last = seq[-1]
    return seq


def run(strip, payload, max_passes=None):
    """Play a wire payload ({"patterns": [...]} JSON string or dict) on
    `strip`. Rows play in 'order' (equal orders shuffled — see plan) and the
    list REPEATS until the next scene kills this process. A duration-0
    pattern holds forever, so anything after it never plays; to end dark on
    purpose, finish the scene with a black Solid. Unknown types and
    malformed entries are skipped; no playable pattern = lights off.
    `max_passes` bounds the loop for tests (None = forever)."""
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except (TypeError, ValueError):
            payload = {}
    raw = (payload or {}).get('patterns') or []
    patterns = [p for p in (reg.normalize(x) for x in raw) if p]
    if not patterns:
        strip.off()
        return
    last = None
    passes = 0
    while max_passes is None or passes < max_passes:
        for p in plan(patterns, last):
            strip.begin(p)
            FUNCS[p['type']](strip, p)
            last = p
        passes += 1
    strip.off()


# ---------------------------------------------------------------------------
# Hardware entry point
# ---------------------------------------------------------------------------
def active_config(db_path=DB_PATH):
    """(pin, ledCount, max_brightness) for the active tblLEDConfig row, or None."""
    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute(
            "SELECT pin, ledCount, brightness FROM tblLEDConfig WHERE active = 1 "
            "ORDER BY ledConfig_ID LIMIT 1").fetchone()
    finally:
        conn.close()
    if not row:
        return None
    pin, count, cap = row
    return int(pin), int(count or 0), float(cap if cap is not None else 0.08)


def take_payload(db_path=DB_PATH):
    """Read-and-clear the tblLED mailbox. Latest row wins; an empty table
    (rapid double activation already consumed it) means lights off."""
    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute("SELECT ledJSON FROM tblLED ORDER BY led_ID").fetchall()
        conn.execute("DELETE FROM tblLED")
        conn.commit()
    finally:
        conn.close()
    return rows[-1][0] if rows else reg.OFF_PAYLOAD


def main():
    cfg = active_config()
    if not cfg or cfg[1] <= 0:
        print('led_Run: no active tblLEDConfig row — nothing to drive')
        return
    pin, count, cap = cfg
    import board      # noqa: E402  (Pi-only; kept out of the testable module top)
    import neopixel   # noqa: E402
    pixel_pin = getattr(board, f'D{pin}', None)
    if pixel_pin is None:
        print(f'led_Run: GPIO pin {pin} is not a board pin')
        return
    pixels = neopixel.NeoPixel(pixel_pin, count, brightness=cap, auto_write=False,
                               pixel_order=neopixel.GRB)
    run(Strip(pixels, count, cap), take_payload())


if __name__ == '__main__':
    main()
