"""GPU world drawing: static terrain chunk meshes (built once, scale independent), sky / fog gradients and
the snowfall as one numpy-built batch."""
import math
import time
import numpy as np
from . import terrain as T
from .gfx import Recorder
from .terrain_render import ANCHOR_Y
from .util import clamp, mixc, rgb


class GLChunks:
    """Terrain chunk meshes in chunk-local metres; positioned with a per-chunk transform."""

    def __init__(self, gl, chunk_renderer):
        self.gl = gl
        self.cr = chunk_renderer
        self.meshes = {}
        self.pending = {}

    def _build(self, ci):
        cr = self.cr
        X0, X1, top, bottom = cr._extent(ci)
        x0 = ci * T.CHUNK_W
        rec = Recorder()
        yield from cr._emit(ci, rec, lambda x, y: (x - x0, y), X0, X1, bottom, underfill=True)
        self.meshes[ci] = self.gl.make_mesh(rec)

    def get(self, ci):
        m = self.meshes.get(ci)
        if m is None:
            for _ in (self.pending.pop(ci, None) or self._build(ci)):
                pass
            m = self.meshes[ci]
        return m

    def prefetch(self, cis, budget=0.004):
        t0 = time.perf_counter()
        for ci in cis:
            if ci in self.meshes:
                continue
            gen = self.pending.get(ci)
            if gen is None:
                gen = self.pending[ci] = self._build(ci)
            while time.perf_counter() - t0 < budget:
                try:
                    next(gen)
                except StopIteration:
                    self.pending.pop(ci, None)
                    break
            if time.perf_counter() - t0 >= budget:
                return

    def prune(self, center, keep=4):
        for k in [k for k in self.meshes if abs(k - center) > keep]:
            self.meshes.pop(k).release()
        for k in [k for k in self.pending if abs(k - center) > keep]:
            del self.pending[k]

    def draw(self, view, c0, c1):
        W, H, s = view.W, view.H, view.s
        sx, sy = 2.0 * s / W, 2.0 * s / H
        ty = 1.0 - 2.0 * ANCHOR_Y - 2.0 * view.cy * s / H
        for ci in range(c0, c1 + 1):
            self.gl.draw_mesh(self.get(ci), (sx, sy, (ci * T.CHUNK_W - view.cx) * sx, ty))


def sky(rec, W, H, pal):
    c0, c1 = pal['sky0'], pal['sky1']
    n = 6
    prev = c0
    for i in range(n):
        f0, f1 = (i / n) ** 0.85, ((i + 1) / n) ** 0.85
        a, b = mixc(c0, c1, f0), mixc(c0, c1, f1)
        rec.grad_rect(0, i * H / n, W, H / n + 1, rgb(a), rgb(b))


def fog(rec, W, H, pal):
    strength = clamp(pal['fog'] * 1.6, 0, 1)
    if strength <= 0:
        return
    col = rgb(pal['sky1'])
    y0, y1 = H * 0.28, H * 0.76
    n = 12
    for i in range(n):
        ya, yb = y0 + (y1 - y0) * i / n, y0 + (y1 - y0) * (i + 1) / n

        def alpha(y):
            a = max(0.0, 1.0 - abs(y / H - 0.62) / 0.34)
            return int(255 * a * a * strength)
        rec.grad_rect(0, ya, W, yb - ya, col + (alpha(ya),), col + (alpha(yb),))


def snow_array(sc, W, H, cam_x, cam_y, s, pal, density):
    k = pal['snowfall'] * density
    if k <= 0.02:
        return None
    if getattr(sc, '_fl', None) is None:
        sc._fl = np.array(sc.flakes, dtype=np.float64)
    n = int(len(sc.flakes) * min(1.0, k))
    fx, fy, d, ph = sc._fl[:n].T
    t = sc.t
    speed = 0.6 + 1.1 * d
    x = (fx * W * 1.3 + 1.6 * d * 40 * t - cam_x * s * 0.35 * d + 25 * np.sin(t * 0.7 + ph * 6.3)) % (W * 1.3) - W * 0.15
    y = (fy * H + t * 60 * speed * d - cam_y * s * 0.05) % H
    r = np.maximum(1, (1.2 * d * s / 36).astype(int)) + 1.0
    out = np.ones((n, 6, 6), dtype=np.float32)
    ox = (0, 1, 1, 0, 1, 0)
    oy = (0, 0, 1, 0, 1, 1)
    for v in range(6):
        out[:, v, 0] = x + ox[v] * r
        out[:, v, 1] = y + oy[v] * r
    return out.reshape(-1, 6)
