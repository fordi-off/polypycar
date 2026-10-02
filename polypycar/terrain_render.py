"""Low-poly terrain rendering. Each 24 m chunk is rasterised once into a pygame Surface at
the current screen scale (faceted dirt layers, jagged surface band, trees/cacti/spires,
grass tufts) and then simply blitted every frame."""
import math
import time
import pygame
from .util import clamp, hash_i, hash2, mixc, shade, rgb
from . import terrain as T

LIGHT = (0.45, 0.89)
DEPTHS = (0.15, 0.9, 2.1, 3.9, 6.2, 9.5)
DECOR_TOP = 8.0
DEEP_BELOW = 9.0


def tint(pal, mat):
    if mat == T.ROCK:
        return pal['rock']
    if mat == T.WOOD:
        return (124, 86, 52)
    if mat == T.MUD:
        return (74, 51, 38)
    if mat == T.ROAD:
        return mixc(pal['dirt'], (222, 190, 142), 0.5)
    if mat == T.GRAVEL:
        return mixc(pal['rock'], pal['dirt'], 0.35)
    return pal['top']


class ChunkRenderer:
    def __init__(self, terrain, ppm):
        self.t = terrain
        self.ppm = ppm
        self.cache = {}
        self.pending = {}

    def set_scale(self, ppm):
        if abs(ppm - self.ppm) > 1e-6:
            self.ppm = ppm
            self.cache.clear()
            self.pending.clear()

    def prune(self, ci_center, keep=3):
        for k in [k for k in self.cache if abs(k - ci_center) > keep]:
            del self.cache[k]

    def get(self, ci):
        """Chunk surface, built synchronously if it isn't ready."""
        c = self.cache.get(ci)
        if c is None:
            gen = self.pending.pop(ci, None) or self._build(ci)
            for _ in gen:
                pass
            c = self.cache[ci]
        return c

    def prefetch(self, cis, budget=0.004):
        """Spend up to `budget` seconds building chunks that are about to become visible."""
        t0 = time.perf_counter()
        for ci in cis:
            if ci in self.cache:
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

    # ------------------------------------------------------------------ build
    def _build(self, ci):
        t, ppm = self.t, self.ppm
        x0 = ci * T.CHUNK_W
        x1 = x0 + T.CHUNK_W
        pad = 0.8
        X0, X1 = x0 - pad, x1 + pad
        i0, i1 = math.floor(X0 / T.DX), math.ceil(X1 / T.DX)
        hs = [t.h_at(i) for i in range(i0, i1 + 1)]
        top = max(hs) + DECOR_TOP
        bottom = min(hs) - DEEP_BELOW
        W = int((X1 - X0) * ppm) + 2
        H = int((top - bottom) * ppm) + 2
        surf = pygame.Surface((W, H), pygame.SRCALPHA)

        def P(x, y):
            return ((x - X0) * ppm, (top - y) * ppm)

        pal_c = T.palette_at((x0 + x1) / 2)
        poly = pygame.draw.polygon

        # decor (behind the ground)
        self._decor(surf, P, ppm, ci, x0, x1)
        yield

        # deep base
        pts = [P(T.DX * i, t.h_at(i)) for i in range(i0, i1 + 1, 2)]
        pts += [P(X1, bottom), P(X0, bottom)]
        poly(surf, rgb(pal_c['deep']), pts)

        yield
        # faceted dirt layers
        step = 0.8
        g0, g1 = math.floor(X0 / step), math.ceil(X1 / step)
        rows = []
        for k, d in enumerate(DEPTHS):
            row = []
            for gi in range(g0, g1 + 1):
                x = gi * step
                if k > 0:
                    x += (hash2(gi, k, 3) - 0.5) * 0.5
                c = round(x / T.DX)
                sy = min(t.h_at(j) for j in range(c - 4, c + 5))
                y = sy - d
                if k > 0:
                    y += (hash2(gi, k, 4) - 0.5) * 0.4 * (1 + k * 0.3)
                row.append(P(x, y))
            rows.append(row)
        pals = [T.palette_at(gi * step) for gi in range(g0, g1 + 1)]
        for k in range(len(DEPTHS) - 1):
            yield
            f = clamp((DEPTHS[k] + DEPTHS[k + 1]) * 0.5 / 9.5 * 1.15, 0, 1)
            for n in range(g1 - g0):
                gi = g0 + n
                a, b, c_, d_ = rows[k][n], rows[k][n + 1], rows[k + 1][n + 1], rows[k + 1][n]
                base = mixc(pals[n]['dirt'], pals[n]['deep'], f)
                if hash2(gi, k, 1) > 0.5:
                    tris = ((a, b, c_), (a, c_, d_))
                else:
                    tris = ((a, b, d_), (b, c_, d_))
                for idx, tri in enumerate(tris):
                    br = 0.86 + 0.26 * hash2(gi * 2 + idx, k, 2)
                    poly(surf, rgb(base, br), tri)

        yield
        # surface band (precise to the sample grid, 0.2 m columns)
        ci0 = i0 + (i0 & 1)
        for i in range(ci0, i1 - 1, 2):
            if i % 40 == 0:
                yield
            xa, xb = i * T.DX, (i + 2) * T.DX
            ya, yb = t.h_at(i), t.h_at(i + 2)
            m = t.mat_idx(i + 1)
            pal = T.palette_at(xa)
            col = tint(pal, m)
            sl = (yb - ya) / (xb - xa)
            il = 1 / math.sqrt(1 + sl * sl)
            lit = 0.78 + 0.36 * (-sl * il * LIGHT[0] + il * LIGHT[1])
            jit = 0.94 + 0.12 * hash_i(math.floor(xa / 0.5), 11)
            if m in (T.ROCK, T.WOOD):
                da = max(0.3, ya - t.base_height(xa) + 0.05)
                db = max(0.3, yb - t.base_height(xb) + 0.05)
            else:
                da = 0.32 + 0.28 * hash_i(math.floor(xa / 0.6), 9)
                db = 0.32 + 0.28 * hash_i(math.floor(xb / 0.6), 9)
            A, B = P(xa, ya), P(xb, yb)
            Cc, D = P(xb, yb - db), P(xa, ya - da)
            br = lit * jit
            if m in (T.ROCK, T.WOOD):
                br *= 0.92 + 0.16 * hash_i(i, 5)
            poly(surf, rgb(col, br), (A, B, Cc))
            poly(surf, rgb(col, br * (0.93 if hash_i(i, 6) > 0.5 else 1.06)), (A, Cc, D))

        yield
        # grass tufts
        if pal_c['name'] != 'canyon':
            for n in range(int(x0 / 0.35), int(x1 / 0.35)):
                if hash_i(n, 21) > 0.5:
                    continue
                x = n * 0.35 + hash_i(n, 22) * 0.3
                i = round(x / T.DX)
                if t.mat_idx(i) != T.GROUND:
                    continue
                y = t.h(x)
                h = 0.1 + 0.25 * hash_i(n, 23)
                lean = (hash_i(n, 24) - 0.5) * 0.18
                col = shade(T.palette_at(x)['tuft'], 0.85 + 0.3 * hash_i(n, 25))
                poly(surf, rgb(col), (P(x - 0.035, y - 0.03), P(x + 0.035, y - 0.03), P(x + lean, y + h)))
        self.cache[ci] = (surf, X0, top, bottom)

    # ------------------------------------------------------------------ decor
    def _decor(self, surf, P, ppm, ci, x0, x1):
        t = self.t
        slot = 1.5
        for n in range(math.floor((x0 + 1.8) / slot), math.floor((x1 - 1.8) / slot) + 1):
            x = n * slot + hash_i(n, 31) * 1.0
            if x < x0 + 1.8 or x > x1 - 1.8:
                continue
            pal = T.palette_at(x)
            if hash_i(n, 30) > pal['density']:
                continue
            i = round(x / T.DX)
            if any(t.mat_idx(i + d) != T.GROUND for d in (-6, 0, 6)):
                continue
            if abs(t.slope(x)) > 0.7:
                continue
            kinds = pal['decor']
            kind = kinds[int(hash_i(n, 32) * len(kinds))]
            s = 0.75 + 0.9 * hash_i(n, 33)
            y = t.h(x) - 0.15
            draw_decor(surf, P, kind, x, y, s, pal, n)


def _pl(surf, P, col, pts):
    pygame.draw.polygon(surf, rgb(col), [P(*p) for p in pts])


def draw_decor(surf, P, kind, x, y, s, pal, n):
    tree, trunk, rock = pal['tree'], pal['trunk'], pal['rock']
    if kind == 'pine':
        snow = pal['name'] == 'tundra'
        _pl(surf, P, shade(trunk, 0.9), [(x - 0.09 * s, y), (x + 0.09 * s, y), (x + 0.07 * s, y + 0.9 * s), (x - 0.07 * s, y + 0.9 * s)])
        for j in range(4):
            by = y + (0.5 + j * 0.85) * s
            w = (1.5 - 0.27 * j) * s * 0.5
            hh = 1.35 * s
            ax = x + (hash_i(n * 7 + j, 40) - 0.5) * 0.1
            _pl(surf, P, shade(tree, 0.78), [(ax, by + hh), (x - w, by), (x, by)])
            _pl(surf, P, shade(tree, 1.12), [(ax, by + hh), (x, by), (x + w, by)])
            if snow:
                _pl(surf, P, (240, 247, 255), [(ax, by + hh), (ax - w * 0.42, by + hh * 0.58), (ax + w * 0.42, by + hh * 0.58)])
    elif kind == 'broadleaf':
        _pl(surf, P, shade(trunk, 0.9), [(x - 0.11 * s, y), (x + 0.11 * s, y), (x + 0.07 * s, y + 1.3 * s), (x - 0.07 * s, y + 1.3 * s)])
        cy, r = y + 1.9 * s, 1.0 * s
        for ox, oy, rr in ((-0.45, -0.1, 0.72), (0.5, -0.15, 0.7), (0.0, 0.3, 1.0)):
            cx, cyy, R = x + ox * s, cy + oy * s, rr * r
            m = 8
            for k in range(m):
                a0, a1 = k / m * math.tau, (k + 1) / m * math.tau
                am = (a0 + a1) / 2
                lit = 0.85 + 0.3 * math.cos(am - 1.0)
                _pl(surf, P, shade(tree, lit), [(cx, cyy), (cx + math.cos(a0) * R, cyy + math.sin(a0) * R), (cx + math.cos(a1) * R, cyy + math.sin(a1) * R)])
    elif kind == 'bush':
        for ox, rr in ((-0.35, 0.45), (0.3, 0.5), (0.0, 0.62)):
            cx, cyy, R = x + ox * s, y + 0.3 * s, rr * s
            for k in range(6):
                a0, a1 = k / 6 * math.pi, (k + 1) / 6 * math.pi
                lit = 0.8 + 0.3 * math.cos((a0 + a1) / 2 - 1.0)
                _pl(surf, P, shade(tree, lit), [(cx, cyy - 0.2 * s), (cx + math.cos(a0) * R, cyy - 0.2 * s + math.sin(a0) * R), (cx + math.cos(a1) * R, cyy - 0.2 * s + math.sin(a1) * R)])
    elif kind == 'cactus':
        c = tree
        h = 2.0 * s
        w = 0.17 * s
        _pl(surf, P, shade(c, 0.8), [(x - w, y), (x, y), (x, y + h), (x - w * 0.7, y + h - 0.12)])
        _pl(surf, P, shade(c, 1.12), [(x, y), (x + w, y), (x + w * 0.7, y + h - 0.12), (x, y + h)])
        for side, hy, ah in ((-1, 0.9, 0.7), (1, 1.2, 0.55)):
            ay = y + hy * s
            x2 = x + side * 0.55 * s
            _pl(surf, P, shade(c, 0.9), [(x, ay), (x2, ay), (x2, ay + ah * s), (x2 + side * w * 1.1, ay + ah * s), (x2 + side * w * 1.1, ay - w), (x, ay - w)])
    elif kind == 'spire':
        c = pal['top'] if hash_i(n, 41) > 0.5 else rock
        h = (3.0 + 2.5 * hash_i(n, 42)) * s * 0.8
        w = (0.9 + 0.5 * hash_i(n, 43)) * s
        _pl(surf, P, shade(c, 0.75), [(x - w, y), (x - w * 0.55, y + h * 0.55), (x - w * 0.25, y + h), (x, y + h * 0.9), (x, y)])
        _pl(surf, P, shade(c, 1.1), [(x, y), (x, y + h * 0.9), (x + w * 0.3, y + h * 0.8), (x + w * 0.65, y + h * 0.5), (x + w, y)])
    elif kind == 'dune':
        w = 2.2 * s
        _pl(surf, P, shade(pal['top'], 0.92), [(x - w, y), (x - w * 0.2, y + 0.5 * s), (x + w * 0.1, y + 0.55 * s), (x + w, y)])
        _pl(surf, P, shade(pal['top'], 1.08), [(x + w * 0.1, y + 0.55 * s), (x + w, y), (x + w * 0.1, y)])
    else:  # rockdecor
        w = 0.8 * s
        _pl(surf, P, shade(rock, 0.8), [(x - w, y), (x - w * 0.5, y + 0.7 * s), (x, y + 0.9 * s), (x, y)])
        _pl(surf, P, shade(rock, 1.1), [(x, y), (x, y + 0.9 * s), (x + w * 0.6, y + 0.5 * s), (x + w, y)])
