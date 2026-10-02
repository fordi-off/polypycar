"""Low-poly terrain rendering.

Static part: each 24 m chunk is rasterised once into a pygame Surface at the current screen
scale (faceted sub-soil below the hard pan, hard surfaces like rock/logs/ice, trees, spires).
Dynamic part: the soft soil layer (snow / mud / dirt between the hard pan and the live surface)
is drawn every frame so ruts, packed tracks, thrown soil and exposed ground are always current."""
import math
import time
import pygame
from .util import clamp, hash_i, hash2, mixc, shade, rgb
from . import terrain as T

LIGHT = (0.45, 0.89)
ANCHOR_Y = 0.58   # must match game.ANCHOR
DEPTHS = (0.15, 0.9, 2.1, 3.9, 6.2, 9.5)
DECOR_TOP = 8.0
DEEP_BELOW = 9.0


def hard_tint(pal, mat):
    if mat == T.ROCK:
        return pal['rock']
    if mat == T.WOOD:
        return (124, 86, 52)
    if mat == T.ICE:
        return (172, 214, 236)
    return pal['dirt']


def soil_colors(pal, mat):
    """(fresh, compacted, bare-ground) colours of a soft surface."""
    dirt = pal['dirt']
    if mat == T.SNOW:
        return pal['snow'], mixc(pal['snow'], (178, 196, 222), 0.55), dirt
    if mat == T.MUD:
        m = mixc(dirt, (58, 42, 32), 0.8)
        return m, shade(m, 0.72), m
    if mat == T.PACKED:
        c = mixc(pal['snow'], (170, 182, 200), 0.38)
        return c, shade(c, 0.82), dirt
    if mat == T.GRAVEL:
        c = mixc(pal['rock'], dirt, 0.35)
        return c, shade(c, 0.85), dirt
    return pal['top'], shade(pal['top'], 0.78), dirt          # dirt / grass


class ChunkRenderer:
    def __init__(self, terrain, ppm):
        self.t = terrain
        self.ppm = ppm
        self.cache = {}
        self.pending = {}
        self.soil = {}

    def set_scale(self, ppm):
        if abs(ppm - self.ppm) > 1e-6:
            self.ppm = ppm
            self.cache.clear()
            self.pending.clear()
            self.soil.clear()

    def prune(self, ci_center, keep=3):
        for k in [k for k in self.cache if abs(k - ci_center) > keep]:
            del self.cache[k]
        for k in [k for k in self.soil if abs(k - ci_center) > keep]:
            del self.soil[k]

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
        h0s = [t.h0_at(i) for i in range(i0, i1 + 1)]
        fls = [t.floor_at(i) for i in range(i0, i1 + 1)]
        top = max(h0s) + DECOR_TOP
        bottom = min(fls) - DEEP_BELOW
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
        pts = [P(T.DX * i, t.floor_at(i)) for i in range(i0, i1 + 1, 2)]
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
                sy = min(t.floor_at(j) for j in range(c - 4, c + 5))
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
        # surface band, 0.2 m columns: hard surfaces (rock / logs / ice) are baked from their top;
        # under soft soil only the bare ground strip below the hard pan is baked
        ci0 = i0 + (i0 & 1)
        for i in range(ci0, i1 - 1, 2):
            if i % 40 == 0:
                yield
            xa, xb = i * T.DX, (i + 2) * T.DX
            h0a, h0b = t.h0_at(i), t.h0_at(i + 2)
            fa, fb = t.floor_at(i), t.floor_at(i + 2)
            m = t.mat_idx(i + 1)
            pal = T.palette_at(xa)
            soft = fa < h0a - 1e-6 or fb < h0b - 1e-6
            ya, yb = (fa, fb) if soft else (h0a, h0b)
            col = pal['dirt'] if soft else hard_tint(pal, m)
            sl = (yb - ya) / (xb - xa)
            il = 1 / math.sqrt(1 + sl * sl)
            lit = 0.78 + 0.36 * (-sl * il * LIGHT[0] + il * LIGHT[1])
            jit = 0.94 + 0.12 * hash_i(math.floor(xa / 0.5), 11)
            if not soft and m in (T.ROCK, T.WOOD):
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
        self.cache[ci] = (surf.convert_alpha(), X0, top, bottom)

    # ------------------------------------------------------------ live soil layer
    def soil_cols(self, ci):
        c = self.soil.get(ci)
        if c is None:
            t = self.t
            c = []
            pal = None
            for j in range(0, T.SC, 2):
                if j % 16 == 0:
                    pal = T.palette_at((ci * T.SC + j) * T.DX)
                c.append(soil_colors(pal, t.mat_idx(ci * T.SC + j + 1)))
            self.soil[ci] = c
        return c

    def draw_soil(self, scr, view, step=2):
        """Soft soil between the hard pan and the live surface, redrawn every frame."""
        t = self.t
        W, H, s = view.W, view.H, view.s
        ia = (math.floor((view.cx - W / 2 / s) / T.DX) - 4) & ~3
        ib = math.ceil((view.cx + W / 2 / s) / T.DX) + 4
        n = ib - ia + 5
        hp, fp, dp = t.h_at, t.floor_at, t.dens_at
        hs = [hp(i) for i in range(ia, ia + n)]
        fs = [fp(i) for i in range(ia, ia + n)]
        ds = [dp(i) for i in range(ia, ia + n)]
        poly = pygame.draw.polygon
        cx, cy = view.cx, view.cy
        ox, oy = W * 0.5, view.H * ANCHOR_Y
        dxs = T.DX * step * s
        sc = s
        cols = None
        ci_prev = None
        L0, L1 = LIGHT
        for k in range(0, n - step, step):
            ya, yb, fa, fb = hs[k], hs[k + step], fs[k], fs[k + step]
            th = ya - fa
            if th < 0.004 and yb - fb < 0.004:
                continue
            i = ia + k
            ci = i // T.SC
            if ci != ci_prev:
                cols = self.soil_cols(ci)
                ci_prev = ci
            fresh, packed, bare = cols[(i - ci * T.SC) >> 1]
            d = ds[k] * 0.9
            d = 1.0 if d > 1.0 else d
            r = fresh[0] + (packed[0] - fresh[0]) * d
            g = fresh[1] + (packed[1] - fresh[1]) * d
            b = fresh[2] + (packed[2] - fresh[2]) * d
            if th < 0.14:                      # thin soil: bare ground shows through
                f = th / 0.14 if th > 0 else 0.0
                r = bare[0] + (r - bare[0]) * f
                g = bare[1] + (g - bare[1]) * f
                b = bare[2] + (b - bare[2]) * f
            sl = (yb - ya) / (T.DX * step)
            il = 1.0 / math.sqrt(1.0 + sl * sl)
            lit = 0.8 + 0.34 * (-sl * il * L0 + il * L1)
            xa = (i * T.DX - cx) * sc + ox
            xb = xa + dxs
            sya, syb = oy - (ya - cy) * sc, oy - (yb - cy) * sc
            sfa, sfb = oy - (fa - cy) * sc + 1, oy - (fb - cy) * sc + 1
            c1 = (min(255, int(r * lit)), min(255, int(g * lit)), min(255, int(b * lit)))
            lt = lit * 0.93
            c2 = (min(255, int(r * lt)), min(255, int(g * lt)), min(255, int(b * lt)))
            poly(scr, c1, ((xa, sya), (xb, syb), (xb, sfb)))
            poly(scr, c2, ((xa, sya), (xb, sfb), (xa, sfa)))

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
            if any(t.mat_idx(i + d) not in (T.DIRT, T.SNOW, T.MUD, T.GRAVEL) for d in (-6, 0, 6)):
                continue
            if abs(t.slope(x)) > 0.7:
                continue
            kinds = pal['decor']
            kind = kinds[int(hash_i(n, 32) * len(kinds))]
            s = 0.75 + 0.9 * hash_i(n, 33)
            y = t.h0_at(i) - 0.2
            draw_decor(surf, P, kind, x, y, s, pal, n)


def _pl(surf, P, col, pts):
    pygame.draw.polygon(surf, rgb(col), [P(*p) for p in pts])


def draw_decor(surf, P, kind, x, y, s, pal, n):
    tree, trunk, rock = pal['tree'], pal['trunk'], pal['rock']
    if kind == 'pine':
        snow = pal['name'] in ('taiga', 'whiteout')
        _pl(surf, P, shade(trunk, 0.9), [(x - 0.09 * s, y), (x + 0.09 * s, y), (x + 0.07 * s, y + 0.9 * s), (x - 0.07 * s, y + 0.9 * s)])
        for j in range(4):
            by = y + (0.5 + j * 0.85) * s
            w = (1.5 - 0.27 * j) * s * 0.5
            hh = 1.35 * s
            ax = x + (hash_i(n * 7 + j, 40) - 0.5) * 0.1
            _pl(surf, P, shade(tree, 0.78), [(ax, by + hh), (x - w, by), (x, by)])
            _pl(surf, P, shade(tree, 1.12), [(ax, by + hh), (x, by), (x + w, by)])
            if snow:
                _pl(surf, P, tuple(pal['snow']), [(ax, by + hh), (ax - w * 0.42, by + hh * 0.58), (ax + w * 0.42, by + hh * 0.58)])
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
    elif kind == 'deadtree':
        tr = shade(trunk, 0.8)
        h = (2.6 + 1.4 * hash_i(n, 44)) * s
        _pl(surf, P, tr, [(x - 0.12 * s, y), (x + 0.12 * s, y), (x + 0.05 * s, y + h), (x - 0.05 * s, y + h)])
        for k, (hy, dx, up) in enumerate(((0.45, -1, 0.9), (0.62, 1, 1.0), (0.8, -1, 0.7))):
            by = y + hy * h
            ex, ey = x + dx * (0.6 + 0.3 * hash_i(n * 5 + k, 45)) * s, by + up * 0.7 * s
            _pl(surf, P, shade(trunk, 0.95), [(x, by), (x, by + 0.09 * s), (ex, ey + 0.05 * s), (ex, ey)])
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
