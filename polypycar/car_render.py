"""Draws the truck: sprung wheels with squishing polygon tyres, coil-over springs and shocks,
faceted body, bobbing driver."""
import math
import pygame
from .util import clamp, mixc, shade, rgb

PAINTS = [(226, 72, 52), (240, 170, 40), (58, 128, 222), (70, 172, 112), (232, 234, 240), (160, 84, 204), (30, 34, 44)]


def _arch(cx):
    return [(cx - 0.62, -0.38), (cx - 0.58, -0.08), (cx - 0.45, 0.20), (cx - 0.2, 0.34),
            (cx + 0.2, 0.34), (cx + 0.45, 0.20), (cx + 0.58, -0.08), (cx + 0.62, -0.38)]


SIL = [(-2.20, -0.38)] + _arch(-1.35) + _arch(1.35) + [(2.25, -0.38), (2.34, -0.20), (2.30, 0.15), (2.16, 0.40),
                                                      (0.85, 0.52), (0.40, 1.00), (-0.80, 1.02), (-0.95, 0.55), (-2.15, 0.55), (-2.22, 0.48)]


SS = 3  # supersampling factor for the car buffer


class SubView:
    """World -> buffer transform for the supersampled car layer."""

    def __init__(self, s, ox, oy, wx, wy):
        self.s = s
        self.ox, self.oy, self.wx, self.wy = ox, oy, wx, wy

    def tf(self, x, y):
        return ((x - self.wx) * self.s + self.ox, self.oy - (y - self.wy) * self.s)


class CarRenderer:
    def __init__(self):
        self.buf = None
        self.paint = 0
        self.head = [0.0, 0.0]
        self.head_v = [0.0, 0.0]
        self.prev_v = None

    def next_paint(self):
        self.paint = (self.paint + 1) % len(PAINTS)

    # driver head: damped spring driven by chassis acceleration (in chassis frame)
    def update(self, car, dt):
        if dt <= 0:
            return
        vx, vy = car.vx, car.vy
        if self.prev_v is None:
            self.prev_v = (vx, vy)
        ax, ay = (vx - self.prev_v[0]) / dt, (vy - self.prev_v[1]) / dt
        self.prev_v = (vx, vy)
        ca, sa = math.cos(car.a), math.sin(car.a)
        lax, lay = ax * ca + ay * sa, -ax * sa + ay * ca
        k, c = 260.0, 18.0
        for i, a in enumerate((-lax * 0.012, -(lay + 9.81) * 0.01)):
            self.head_v[i] += (k * (a - self.head[i]) - c * self.head_v[i]) * dt
            self.head[i] = clamp(self.head[i] + self.head_v[i] * dt, -0.1, 0.1)

    def draw(self, surf, view, car, terrain):
        """Render into a 3x buffer, smooth-scale down and place with sub-pixel accuracy."""
        s = view.s
        BW, BH = 7.4, 5.6            # metres covered by the buffer
        cxw, cyw = car.x, car.y - 0.6
        px, py = view.tf(cxw - BW / 2, cyw + BH / 2)       # top-left in screen px (float)
        ix, iy = math.floor(px), math.floor(py)
        fx, fy = px - ix, py - iy
        w, h = int(BW * s) + 2, int(BH * s) + 2
        if self.buf is None or self.buf.get_size() != (w * SS, h * SS):
            self.buf = pygame.Surface((w * SS, h * SS), pygame.SRCALPHA)
        self.buf.fill((0, 0, 0, 0))
        sv = SubView(s * SS, (fx + 0) * SS + 0.0, fy * SS, cxw - BW / 2, cyw + BH / 2)
        self._draw(self.buf, sv, car, terrain)
        small = pygame.transform.smoothscale(self.buf, (w, h))
        surf.blit(small, (ix, iy))

    def _draw(self, surf, view, car, terrain):
        cfg = car.cfg
        ca, sa = math.cos(car.a), math.sin(car.a)
        tf = view.tf

        def L(pts):
            return [tf(car.x + x * ca - y * sa, car.y + x * sa + y * ca) for x, y in pts]

        def poly(col, pts, k=1.0):
            pygame.draw.polygon(surf, rgb(col, k), L(pts))

        base = PAINTS[self.paint]
        dark = (36, 38, 46)

        # wheel wells
        for cx in (-1.35, 1.35):
            poly((22, 22, 28), [(cx - 0.66, -0.4), (cx - 0.6, 0.22), (cx, 0.40), (cx + 0.6, 0.22), (cx + 0.66, -0.4)])

        for w in car.wheels:
            self._suspension(surf, view, car, w, ca, sa)
        for w in car.wheels:
            self._wheel(surf, view, w, cfg['wheel_r'], terrain)

        # underbody + body
        poly((30, 30, 36), [(-2.05, -0.46), (2.05, -0.46), (2.05, -0.3), (-2.05, -0.3)])
        poly(base, SIL)
        poly(base, [(-0.73, -0.38), (0.73, -0.38), (0.85, 0.15), (0.2, 0.34), (-0.2, 0.34), (-0.85, 0.15)], 0.82)
        poly(base, [(-0.85, 0.15), (-0.2, 0.34), (-0.9, 0.55), (-1.9, 0.55), (-1.95, 0.2)], 1.12)
        poly(base, [(0.85, 0.15), (0.2, 0.34), (0.9, 0.52), (1.95, 0.45), (1.9, 0.2)], 1.08)
        poly(base, [(2.30, 0.15), (2.16, 0.40), (0.85, 0.52), (1.95, 0.45), (2.25, 0.2)], 1.22)   # hood top
        poly(base, [(2.30, 0.15), (2.34, -0.20), (2.25, -0.38), (2.25, 0.2)], 0.78)               # nose
        poly(dark, [(-0.73, -0.38), (0.73, -0.38), (0.73, -0.24), (-0.73, -0.24)])                 # sill
        poly(base, [(-0.95, 0.55), (-0.8, 1.02), (0.4, 1.0), (0.85, 0.52)], 0.9)                  # cab
        # fender flares
        for cx in (-1.35, 1.35):
            pts = L([(x, y + 0.02) for x, y in _arch(cx)[1:-1]])
            pygame.draw.lines(surf, rgb(dark), False, pts, max(2, int(view.s * 0.07)))
        # bed
        poly((26, 26, 32), [(-0.95, 0.55), (-2.15, 0.55), (-2.2, 0.62), (-0.95, 0.62)])
        poly(base, [(-2.15, 0.55), (-2.22, 0.48), (-2.2, 0.66), (-2.12, 0.64)], 0.7)
        poly((46, 48, 56), [(-1.02, 0.6), (-1.0, 1.08), (-0.94, 1.08), (-0.94, 0.6)])           # roll bar
        poly((46, 48, 56), [(-1.02, 1.08), (-0.2, 1.1), (-0.2, 1.04), (-1.0, 1.02)])
        # windows
        glass_hi, glass_lo = (206, 238, 252), (112, 176, 212)
        poly(glass_lo, [(0.80, 0.58), (0.43, 0.95), (0.02, 0.95), (0.02, 0.58)])
        poly(glass_hi, [(0.80, 0.58), (0.43, 0.95), (0.02, 0.95)])
        poly(glass_lo, [(-0.06, 0.58), (-0.06, 0.95), (-0.72, 0.95), (-0.88, 0.58)])
        poly(glass_hi, [(-0.06, 0.95), (-0.72, 0.95), (-0.06, 0.58)])
        # driver
        hx, hy = -0.34 + self.head[0], 0.78 + self.head[1]
        poly((60, 70, 96), [(-0.7, 0.58), (-0.62, 0.7), (hx - 0.12, 0.7 + self.head[1] * 0.4), (hx + 0.12, 0.7), (0.0, 0.58)])
        head = [(hx + math.cos(a * math.tau / 8) * 0.13, hy + math.sin(a * math.tau / 8) * 0.14) for a in range(8)]
        poly((238, 192, 152), head)
        poly((210, 60, 52), [(hx - 0.14, hy + 0.04), (hx + 0.14, hy + 0.04), (hx + 0.18, hy + 0.0), (hx + 0.08, hy + 0.16), (hx - 0.1, hy + 0.15)])
        # roof, roof lights, bumpers, lamps
        poly(base, [(0.40, 1.00), (-0.80, 1.02), (-0.82, 0.95), (0.38, 0.93)], 0.62)
        for lx in (-0.6, -0.3, 0.0, 0.25):
            poly((255, 236, 150), [(lx, 1.03), (lx + 0.14, 1.03), (lx + 0.12, 1.12), (lx + 0.02, 1.12)])
        poly((58, 60, 68), [(2.2, -0.38), (2.44, -0.36), (2.46, -0.10), (2.28, -0.04), (2.22, -0.2)])
        poly((58, 60, 68), [(-2.2, -0.38), (-2.42, -0.36), (-2.44, -0.12), (-2.24, -0.06)])
        poly((255, 248, 200), [(2.26, 0.13), (2.33, 0.2), (2.25, 0.28), (2.16, 0.2)])
        poly((236, 52, 56), [(-2.22, 0.30), (-2.25, 0.48), (-2.14, 0.48), (-2.14, 0.30)])

    # ------------------------------------------------------------------
    def _suspension(self, surf, view, car, w, ca, sa):
        cfg = car.cfg
        tf = view.tf
        my = cfg['mount_y']
        mx_w = car.x + w.mx * ca - my * sa
        my_w = car.y + w.mx * sa + my * ca
        dxn, dyn = sa, -ca
        fx, fy = ca, sa
        sgn = 1 if w.mx > 0 else -1
        # lower arm: chassis pivot -> hub
        pvx = car.x + (w.mx - sgn * 0.6) * ca + 0.32 * sa
        pvy = car.y + (w.mx - sgn * 0.6) * sa - 0.32 * ca
        pygame.draw.line(surf, (44, 46, 54), tf(pvx, pvy), tf(w.hx, w.hy), max(3, int(view.s * 0.1)))
        # shock (dark body + bright piston)
        ax, ay = mx_w + fx * 0.14, my_w + fy * 0.14
        bx, by = w.hx + fx * 0.06, w.hy + fy * 0.06
        pygame.draw.line(surf, (30, 30, 36), tf(ax, ay), tf(bx, by), max(4, int(view.s * 0.11)))
        mxp, myp = (ax + bx) / 2, (ay + by) / 2
        pygame.draw.line(surf, (210, 214, 224), tf(mxp, myp), tf(bx, by), max(2, int(view.s * 0.05)))
        # coil spring (zig-zag)
        n = 8
        pts = []
        lx0, ly0 = mx_w - fx * 0.05, my_w - fy * 0.05
        lx1, ly1 = w.hx - fx * 0.05 - dxn * 0.08, w.hy - fy * 0.05 - dyn * 0.08
        for i in range(n + 1):
            t = i / n
            off = 0.0 if i in (0, n) else (0.1 if i % 2 else -0.1)
            pts.append(tf(lx0 + (lx1 - lx0) * t + fx * off, ly0 + (ly1 - ly0) * t + fy * off))
        pygame.draw.lines(surf, (255, 176, 40), False, pts, max(2, int(view.s * 0.06)))

    def _wheel(self, surf, view, w, R, terrain):
        tf = view.tf
        cx, cy = w.hx, w.hy
        k0 = R / 0.42
        N = 28
        stretch = 1 + 0.45 * w.pen / R
        ang = -w.ang
        outer = []
        for k in range(N):
            a = ang + k * math.tau / N
            r = R if k % 2 == 0 else R - 0.04 * k0
            px = cx + math.cos(a) * r
            py = cy + math.sin(a) * r
            gh = terrain.h(px)
            if py < gh:
                py = gh
            outer.append(((cx + (px - cx) * stretch), py))
        S = [tf(*p) for p in outer]
        C = tf(cx, cy)
        pygame.draw.polygon(surf, (24, 24, 28), S)
        for k in range(N):
            tone = 40 if (k // 2) % 2 == 0 else 30
            pygame.draw.polygon(surf, (tone, tone, tone + 4), (C, S[k], S[(k + 1) % N]))
        side = [tf(cx + math.cos(ang + k * math.tau / 20) * 0.31 * k0, cy + math.sin(ang + k * math.tau / 20) * 0.31 * k0) for k in range(20)]
        pygame.draw.polygon(surf, (58, 58, 66), side)
        for k in range(10):
            a0, a1 = ang + k * math.tau / 10, ang + (k + 1) * math.tau / 10
            rim = ((cx, cy), (cx + math.cos(a0) * 0.23 * k0, cy + math.sin(a0) * 0.23 * k0), (cx + math.cos(a1) * 0.23 * k0, cy + math.sin(a1) * 0.23 * k0))
            tone = 196 if k % 2 else 150
            pygame.draw.polygon(surf, (tone, tone + 4, tone + 14), [tf(*p) for p in rim])
        for k in range(5):
            a = ang + k * math.tau / 5
            sp = [(cx + math.cos(a - 0.14) * 0.05, cy + math.sin(a - 0.14) * 0.05), (cx + math.cos(a - 0.1) * 0.19, cy + math.sin(a - 0.1) * 0.19),
                  (cx + math.cos(a + 0.1) * 0.19, cy + math.sin(a + 0.1) * 0.19), (cx + math.cos(a + 0.14) * 0.05, cy + math.sin(a + 0.14) * 0.05)]
            pygame.draw.polygon(surf, (70, 72, 82), [tf(*p) for p in sp])
        pygame.draw.polygon(surf, (230, 232, 240), [tf(cx + math.cos(ang + k * math.tau / 6) * 0.065, cy + math.sin(ang + k * math.tau / 6) * 0.065) for k in range(6)])
