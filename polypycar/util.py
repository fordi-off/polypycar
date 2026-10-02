"""Shared math / noise / colour helpers."""
import math

M32 = 0xFFFFFFFF


def clamp(v, a, b):
    return a if v < a else b if v > b else v


def lerp(a, b, t):
    return a + (b - a) * t


def smooth(t):
    """Quintic smoothstep, input clamped to 0..1."""
    t = 0.0 if t < 0 else 1.0 if t > 1 else t
    return t * t * t * (t * (t * 6 - 15) + 10)


def hash_i(i, s=0):
    """Integer hash -> [0, 1)."""
    h = ((int(i) * 374761393) & M32) ^ (((int(s) + 0x9E3779B9) * 668265263) & M32)
    h = ((h ^ (h >> 13)) * 1274126177) & M32
    h ^= h >> 16
    return h / 4294967296.0


def hash2(i, j, s=0):
    return hash_i(((int(i) * 73856093) & M32) ^ ((int(j) * 19349663) & M32), s)


def noise1(x, s=0):
    """1D value noise, C2 continuous, range -1..1."""
    i = math.floor(x)
    f = x - i
    a = hash_i(i, s) * 2 - 1
    b = hash_i(i + 1, s) * 2 - 1
    return a + (b - a) * smooth(f)


class Rng:
    """mulberry32."""

    def __init__(self, seed):
        self.a = int(seed) & M32

    def __call__(self):
        self.a = (self.a + 0x6D2B79F5) & M32
        t = self.a
        t = ((t ^ (t >> 15)) * (1 | t)) & M32
        t = ((t + (((t ^ (t >> 7)) * (61 | t)) & M32)) ^ t) & M32
        return ((t ^ (t >> 14)) & M32) / 4294967296.0


def hexc(h):
    h = h.lstrip('#')
    return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))


def mixc(a, b, t):
    return (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t, a[2] + (b[2] - a[2]) * t)


def shade(c, k):
    return (c[0] * k, c[1] * k, c[2] * k)


def rgb(c, k=1.0):
    """Colour tuple (floats ok) -> clamped int rgb tuple for pygame."""
    r = int(c[0] * k)
    g = int(c[1] * k)
    b = int(c[2] * k)
    return (0 if r < 0 else 255 if r > 255 else r,
            0 if g < 0 else 255 if g > 255 else g,
            0 if b < 0 else 255 if b > 255 else b)
