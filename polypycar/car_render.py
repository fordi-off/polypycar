"""Draws the 6x6 truck: sprung wheels with squishing polygon tyres sunk into the soil, coil-over
springs and shocks, faceted cab, log load, bobbing driver. Rendered 3x supersampled."""
import math
import pygame
from .util import clamp, mixc, shade, rgb

PAINTS = [(226, 118, 34), (212, 58, 48), (236, 190, 44), (58, 118, 200), (66, 150, 98), (226, 228, 234), (40, 44, 54)]
FRAME = (52, 56, 64)
SS = 3  # supersampling factor for the car buffer


def _arch(cx, w=0.85):
    return [(cx - w, -0.38), (cx - w + 0.05, 0.1), (cx - 0.55, 0.62), (cx - 0.2, 0.88),
            (cx + 0.2, 0.88), (cx + 0.55, 0.62), (cx + w - 0.05, 0.1), (cx + w, -0.38)]


SIL = ([(-4.1, -0.38)] + _arch(-2.4) + _arch(-0.7) + [(0.15, -0.38), (2.15, -0.38)] + _arch(3.0) +
       [(3.95, -0.38), (3.98, 0.25), (3.95, 1.0), (3.78, 2.15), (3.25, 2.68), (1.75, 2.6), (1.75, 1.0), (-4.0, 1.0), (-4.1, 0.9)])
CAB = [(1.75, -0.38)] + _arch(3.0)[0:] + [(3.95, -0.38), (3.98, 0.25), (3.95, 1.0), (3.78, 2.15), (3.25, 2.68), (1.75, 2.6)]
EXHAUST = (1.63, 3.5)       # chassis-local smoke origin


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

    def exhaust_world(self, car):
        ca, sa = math.cos(car.a), math.sin(car.a)
        x, y = EXHAUST
        return car.x + x * ca - y * sa, car.y + x * sa + y * ca

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
        k, c = 220.0, 16.0
        for i, a in enumerate((-lax * 0.012, -(lay + 9.81) * 0.01)):
            self.head_v[i] += (k * (a - self.head[i]) - c * self.head_v[i]) * dt
            self.head[i] = clamp(self.head[i] + self.head_v[i] * dt, -0.1, 0.1)

    def draw(self, surf, view, car, terrain):
        """Render into a 3x buffer, smooth-scale down and place with sub-pixel accuracy."""
        s = view.s
        BW, BH = 10.8, 6.6            # metres covered by the buffer
        cxw, cyw = car.x, car.y + 1.0
        px, py = view.tf(cxw - BW / 2, cyw + BH / 2)       # top-left in screen px (float)
        ix, iy = math.floor(px), math.floor(py)
        fx, fy = px - ix, py - iy
        w, h = int(BW * s) + 2, int(BH * s) + 2
        if self.buf is None or self.buf.get_size() != (w * SS, h * SS):
            self.buf = pygame.Surface((w * SS, h * SS), pygame.SRCALPHA)
        self.buf.fill((0, 0, 0, 0))
        sv = SubView(s * SS, fx * SS, fy * SS, cxw - BW / 2, cyw + BH / 2)
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
        dark = (34, 36, 44)
        deck = (74, 80, 90)

        # wheel wells
        for cx in cfg['mount_x']:
            poly((20, 20, 26), [(cx - 0.9, -0.4), (cx - 0.85, 0.15), (cx, 0.95), (cx + 0.85, 0.15), (cx + 0.9, -0.4)])
        # frame rails + fuel tanks (behind the wheels)
        poly(FRAME, [(-4.0, -0.52), (3.9, -0.52), (3.9, -0.3), (-4.0, -0.3)])
        poly((150, 156, 168), [(0.35, -0.78), (1.55, -0.78), (1.55, -0.28), (0.35, -0.28)], 0.95)
        poly((196, 202, 214), [(0.35, -0.55), (1.55, -0.55), (1.55, -0.28), (0.35, -0.28)], 1.0)

        for w in car.wheels:
            self._suspension(surf, view, car, w, ca, sa)
        for w in car.wheels:
            self._wheel(surf, view, w, cfg['wheel_r'], terrain)

        # body
        poly(deck, SIL)
        poly(deck, [(-4.0, 1.0), (1.75, 1.0), (1.75, 0.55), (-4.1, 0.55)], 1.15)
        poly(dark, [(-4.1, 0.9), (-4.0, 1.0), (1.75, 1.0), (1.75, 0.9)], 0.8)
        poly(base, CAB)
        poly(base, [(1.75, 0.6), (3.95, 0.6), (3.95, 1.0), (3.78, 1.4), (1.75, 1.4)], 0.84)          # lower door panel
        poly(base, [(1.75, 1.4), (3.78, 1.4), (3.78, 2.15), (3.25, 2.68), (1.75, 2.6)], 1.1)         # upper cab
        poly(base, [(3.25, 2.68), (3.78, 2.15), (3.4, 2.35), (2.4, 2.65)], 1.22)                      # roof highlight
        poly(base, [(3.98, 0.25), (3.95, 1.0), (3.78, 1.4), (3.9, 0.7)], 0.7)                         # nose shadow
        for cx in cfg['mount_x']:                                                                  # fender flares
            pts = L([(x, y + 0.03) for x, y in _arch(cx)[1:-1]])
            pygame.draw.lines(surf, rgb(dark), False, pts, max(2, int(view.s * 0.09)))
        # door seam + handle
        poly(dark, [(2.15, -0.2), (2.2, -0.2), (2.2, 1.4), (2.15, 1.4)], 0.9)
        poly((200, 204, 212), [(2.4, 1.15), (2.7, 1.15), (2.7, 1.22), (2.4, 1.22)])
        # windows
        glass_hi, glass_lo = (210, 238, 252), (110, 168, 204)
        poly(glass_lo, [(3.5, 1.55), (3.38, 2.38), (2.25, 2.38), (2.25, 1.55)])
        poly(glass_hi, [(3.5, 1.55), (3.38, 2.38), (2.25, 2.38)])
        poly(base, [(2.9, 1.55), (2.9, 2.38), (2.82, 2.38), (2.82, 1.55)], 0.8)
        poly(glass_hi, [(3.62, 1.55), (3.86, 1.5), (3.74, 2.28), (3.5, 2.38)], 0.95)
        # driver
        hx, hy = 3.1 + self.head[0] * 1.5, 1.95 + self.head[1] * 1.5
        poly((58, 68, 94), [(2.3, 1.55), (2.45, 1.8), (hx - 0.2, 1.8), (hx + 0.2, 1.8), (3.0, 1.55)])
        head = [(hx + math.cos(a * math.tau / 8) * 0.2, hy + math.sin(a * math.tau / 8) * 0.22) for a in range(8)]
        poly((238, 192, 152), head)
        poly((38, 44, 60), [(hx - 0.22, hy + 0.07), (hx + 0.22, hy + 0.07), (hx + 0.28, hy + 0.0), (hx + 0.1, hy + 0.27), (hx - 0.16, hy + 0.25)])
        # log load
        stake = (46, 48, 56)
        layers = ((1.0, 1.55, -3.95, -0.15), (1.55, 2.1, -3.85, -0.35), (2.1, 2.62, -3.6, -0.9))
        for li, (y0, y1, xl, xr) in enumerate(layers):
            seg = 4
            for k in range(seg):
                xa, xb = xl + (xr - xl) * k / seg, xl + (xr - xl) * (k + 1) / seg
                tone = (0.86, 1.0, 0.92, 1.06)[(k + li) % 4]
                poly((124, 88, 56), [(xa, y0), (xb, y0), (xb, y1), (xa, y1)], tone * 0.82)
                poly((124, 88, 56), [(xa, y0 + (y1 - y0) * 0.55), (xb, y0 + (y1 - y0) * 0.55), (xb, y1), (xa, y1)], tone * 1.1)
            cut = [(xl + math.cos(a * math.tau / 10) * 0.2, (y0 + y1) / 2 + math.sin(a * math.tau / 10) * 0.26) for a in range(10)]
            poly((206, 168, 112), cut)
        for sx in (-3.95, -0.12):
            poly(stake, [(sx - 0.05, 1.0), (sx + 0.05, 1.0), (sx + 0.05, 2.75), (sx - 0.05, 2.75)])
        # exhaust stack, snorkel, roof lights, mirror
        poly((150, 156, 168), [(1.55, 1.0), (1.72, 1.0), (1.72, 3.5), (1.55, 3.5)])
        poly((210, 214, 224), [(1.62, 1.0), (1.72, 1.0), (1.72, 3.5), (1.62, 3.5)])
        poly(dark, [(1.5, 3.42), (1.77, 3.42), (1.77, 3.55), (1.5, 3.55)])
        poly((40, 42, 50), [(3.66, 1.4), (3.82, 1.4), (3.82, 3.05), (3.66, 3.05)])
        poly((40, 42, 50), [(3.66, 2.95), (3.9, 3.0), (3.9, 3.12), (3.66, 3.1)])
        for lx in (2.35, 2.7, 3.05, 3.4):
            poly((255, 238, 150), [(lx, 2.64), (lx + 0.22, 2.7), (lx + 0.2, 2.86), (lx + 0.04, 2.84)])
        poly(dark, [(3.9, 1.8), (4.08, 1.78), (4.1, 2.1), (3.92, 2.12)])
        # bumper, winch, lamps
        poly((56, 58, 66), [(3.9, -0.4), (4.3, -0.38), (4.34, 0.12), (3.96, 0.2)])
        poly((226, 190, 40), [(4.05, -0.08), (4.28, -0.08), (4.28, 0.06), (4.05, 0.06)])
        poly((255, 248, 204), [(3.97, 0.55), (4.04, 0.58), (4.04, 0.86), (3.95, 0.84)])
        poly((236, 52, 56), [(-4.12, 0.62), (-4.06, 0.62), (-4.06, 0.86), (-4.12, 0.84)])
        # mud flaps behind rear wheels
        for cx in (-2.4, -0.7):
            poly((26, 26, 30), [(cx - 1.0, -0.38), (cx - 0.92, -0.38), (cx - 0.92, -0.95), (cx - 1.0, -0.95)])

    # ------------------------------------------------------------------
    def _suspension(self, surf, view, car, w, ca, sa):
        cfg = car.cfg
        tf = view.tf
        my = cfg['mount_y']
        mx_w = car.x + w.mx * ca - my * sa
        my_w = car.y + w.mx * sa + my * ca
        dxn, dyn = sa, -ca
        fx, fy = ca, sa
        # lower arm: chassis pivot -> hub
        pvx = car.x + (w.mx + 0.9) * ca + 0.3 * sa
        pvy = car.y + (w.mx + 0.9) * sa - 0.3 * ca
        pygame.draw.line(surf, (44, 46, 54), tf(pvx, pvy), tf(w.hx, w.hy), max(3, int(view.s * 0.16)))
        # shock (dark body + bright piston)
        ax, ay = mx_w + fx * 0.2, my_w + fy * 0.2
        bx, by = w.hx + fx * 0.1, w.hy + fy * 0.1
        pygame.draw.line(surf, (30, 30, 36), tf(ax, ay), tf(bx, by), max(4, int(view.s * 0.15)))
        mxp, myp = (ax + bx) / 2, (ay + by) / 2
        pygame.draw.line(surf, (210, 214, 224), tf(mxp, myp), tf(bx, by), max(2, int(view.s * 0.07)))
        # coil spring (zig-zag)
        n = 9
        pts = []
        lx0, ly0 = mx_w - fx * 0.08, my_w - fy * 0.08
        lx1, ly1 = w.hx - fx * 0.08 - dxn * 0.1, w.hy - fy * 0.08 - dyn * 0.1
        for i in range(n + 1):
            t = i / n
            off = 0.0 if i in (0, n) else (0.14 if i % 2 else -0.14)
            pts.append(tf(lx0 + (lx1 - lx0) * t + fx * off, ly0 + (ly1 - ly0) * t + fy * off))
        pygame.draw.lines(surf, (255, 176, 40), False, pts, max(2, int(view.s * 0.08)))

    def _wheel(self, surf, view, w, R, terrain):
        tf = view.tf
        cx, cy = w.hx, w.hy
        k0 = R / 0.42
        N = 26
        stretch = 1 + 0.4 * w.pen / R
        ang = -w.ang
        outer = []
        for k in range(N):
            a = ang + k * math.tau / N
            r = R if k % 2 == 0 else R - 0.085
            px = cx + math.cos(a) * r
            py = cy + math.sin(a) * r
            gh = terrain.h(px)
            if py < gh:
                py = gh
            outer.append(((cx + (px - cx) * stretch), py))
        S = [tf(*p) for p in outer]
        C = tf(cx, cy)
        pygame.draw.polygon(surf, (22, 22, 26), S)
        for k in range(N):
            tone = 42 if (k // 2) % 2 == 0 else 30
            pygame.draw.polygon(surf, (tone, tone, tone + 4), (C, S[k], S[(k + 1) % N]))
        side = [tf(cx + math.cos(ang + k * math.tau / 20) * 0.46, cy + math.sin(ang + k * math.tau / 20) * 0.46) for k in range(20)]
        pygame.draw.polygon(surf, (56, 56, 64), side)
        for k in range(10):
            a0, a1 = ang + k * math.tau / 10, ang + (k + 1) * math.tau / 10
            rim = ((cx, cy), (cx + math.cos(a0) * 0.33, cy + math.sin(a0) * 0.33), (cx + math.cos(a1) * 0.33, cy + math.sin(a1) * 0.33))
            tone = 190 if k % 2 else 146
            pygame.draw.polygon(surf, (tone, tone + 4, tone + 14), [tf(*p) for p in rim])
        for k in range(6):
            a = ang + k * math.tau / 6
            sp = [(cx + math.cos(a - 0.14) * 0.07, cy + math.sin(a - 0.14) * 0.07), (cx + math.cos(a - 0.09) * 0.3, cy + math.sin(a - 0.09) * 0.3),
                  (cx + math.cos(a + 0.09) * 0.3, cy + math.sin(a + 0.09) * 0.3), (cx + math.cos(a + 0.14) * 0.07, cy + math.sin(a + 0.14) * 0.07)]
            pygame.draw.polygon(surf, (70, 72, 82), [tf(*p) for p in sp])
        pygame.draw.polygon(surf, (226, 228, 236), [tf(cx + math.cos(ang + k * math.tau / 6) * 0.1, cy + math.sin(ang + k * math.tau / 6) * 0.1) for k in range(6)])
