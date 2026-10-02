"""Synthesised engine note: a bank of looping harmonic samples cross-faded by rpm."""
import math
import numpy as np
import pygame

SR = 22050
RPMS = [800 + 300 * i for i in range(22)]


def _make(rpm):
    f = rpm / 60.0 * 3.0                      # 6-cylinder firing frequency
    cycles = max(2, round(f * 0.25))
    n = int(round(cycles / f * SR))
    t = np.arange(n) / n * cycles * math.tau
    w = np.zeros(n)
    for h, a in enumerate((1.0, 0.62, 0.5, 0.34, 0.26, 0.16, 0.1, 0.07), start=1):
        w += a * np.sin(h * t + 0.7 * h)
    w += 0.45 * np.sin(0.5 * t) + 0.25 * np.sin(1.5 * t)
    w = np.tanh(w * 0.9)
    return (w * 0.55 * 32767).astype(np.int16)


class Audio:
    def __init__(self, enabled=True):
        self.ok = False
        self.muted = not enabled
        if not enabled:
            return
        try:
            pygame.mixer.init(SR, -16, 1, 512)
            pygame.mixer.set_num_channels(4)
            self.sounds = [pygame.mixer.Sound(buffer=_make(r).tobytes()) for r in RPMS]
            self.ch = [pygame.mixer.Channel(0), pygame.mixer.Channel(1)]
            self.cur = [None, None]
            self.ok = True
        except Exception:
            self.ok = False

    def toggle(self):
        self.muted = not self.muted
        if self.muted and self.ok:
            for c in self.ch:
                c.stop()
            self.cur = [None, None]

    def update(self, car):
        if not self.ok or self.muted:
            return
        rpm = min(max(car.rpm, RPMS[0]), RPMS[-1] - 1)
        pos = (rpm - RPMS[0]) / 300.0
        i = int(pos)
        frac = pos - i
        gain = 0.18 + 0.5 * car.throttle
        if car.limiter:
            gain *= 0.6 + 0.4 * math.sin(pygame.time.get_ticks() * 0.09)
        for layer, vol in ((i, (1 - frac) * gain), (i + 1, frac * gain)):
            slot = layer & 1
            if self.cur[slot] != layer:
                self.ch[slot].play(self.sounds[layer], loops=-1)
                self.cur[slot] = layer
            self.ch[slot].set_volume(max(0.0, min(1.0, vol)))
