"""Synthesised sound: an engine bank per vehicle (looping harmonic samples cross-faded by rpm, pitched
from the vehicle's cylinder count and rev range) plus wind. No audio files."""
import math
import numpy as np
import pygame

SR = 22050


def _engine_loop(rpm, cylinders):
    f = rpm / 60.0 * cylinders / 2.0            # firing frequency of a 4-stroke
    cycles = max(2, round(f * 0.25))
    n = int(round(cycles / f * SR))
    t = np.arange(n) / n * cycles * math.tau
    w = np.zeros(n)
    for h, a in enumerate((0.8, 1.0, 0.8, 0.55, 0.4, 0.28, 0.18, 0.12, 0.08), start=1):
        w += a * np.sin(h * t + 0.9 * h * h * 0.1)
    w += 0.7 * np.sin(0.5 * t) + 0.35 * np.sin(1.5 * t)           # lumpy firing order
    w = np.tanh(w * 1.1)
    return (w * 0.55 * 32767).astype(np.int16)


def _wind_loop():
    rng = np.random.default_rng(3)
    n = SR * 3
    x = rng.standard_normal(n)
    for k in (60, 25):                                           # circular box filters => seamless loop
        c = np.cumsum(np.concatenate([x, x[:k]]))
        x = (c[k:k + n] - c[:n]) / k
    x /= np.abs(x).max()
    return (x * 0.5 * 32767).astype(np.int16)


class Audio:
    def __init__(self, settings, spec):
        self.settings = settings
        self.ok = False
        self.muted = False
        try:
            if not pygame.mixer.get_init():
                pygame.mixer.init(SR, -16, 1, 512)
            pygame.mixer.set_num_channels(6)
            e = spec.engine
            lo = max(300.0, e.idle * 0.6)
            hi = e.redline * 1.16
            n = 16
            self.rpms = [lo + (hi - lo) * i / (n - 1) for i in range(n)]
            self.sounds = [pygame.mixer.Sound(buffer=_engine_loop(r, e.cylinders).tobytes()) for r in self.rpms]
            self.step = (hi - lo) / (n - 1)
            self.ch = [pygame.mixer.Channel(0), pygame.mixer.Channel(1)]
            self.cur = [None, None]
            self.wind_ch = pygame.mixer.Channel(2)
            self.wind = pygame.mixer.Sound(buffer=_wind_loop().tobytes())
            self.wind_ch.play(self.wind, loops=-1)
            self.wind_ch.set_volume(0.0)
            self.ok = True
        except Exception:
            self.ok = False

    def stop(self):
        if self.ok:
            try:
                for c in self.ch + [self.wind_ch]:
                    c.stop()
            except pygame.error:
                pass
        self.cur = [None, None]

    def toggle(self):
        self.muted = not self.muted
        if self.muted and self.ok:
            for c in self.ch:
                c.stop()
            self.wind_ch.set_volume(0.0)
            self.cur = [None, None]

    def update(self, car, snowfall=0.0):
        if not self.ok or self.muted:
            return
        st = self.settings
        master = st['master_volume']
        rpm = min(max(car.rpm, self.rpms[0]), self.rpms[-1] - 1)
        pos = (rpm - self.rpms[0]) / self.step
        i = int(pos)
        frac = pos - i
        gain = (0.2 + 0.45 * car.throttle) * st['engine_volume'] * master
        if car.limiter:
            gain *= 0.6 + 0.4 * math.sin(pygame.time.get_ticks() * 0.09)
        for layer, vol in ((i, (1 - frac) * gain), (i + 1, frac * gain)):
            slot = layer & 1
            if self.cur[slot] != layer:
                self.ch[slot].play(self.sounds[layer], loops=-1)
                self.cur[slot] = layer
            self.ch[slot].set_volume(max(0.0, min(1.0, vol)))
        wind = min(1.0, abs(car.vx) / 28.0 + 0.25 * snowfall) * st['wind_volume'] * master * 0.6
        self.wind_ch.set_volume(max(0.0, min(1.0, wind)))
