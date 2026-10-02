"""Dust, mud splashes and sparks."""
import math
import random
import pygame
from .util import mixc, shade, rgb

MAX = 420


class Particles:
    def __init__(self):
        self.p = []   # [x, y, vx, vy, life, max, size, (r,g,b), kind]  kind 0 dust, 1 mud, 2 spark
        self.overlay = None
        self.dirty = None
        self.rnd = random.Random(7)
        self.mult = 1.0

    def emit(self, x, y, vx, vy, life, size, col, kind=0):
        if len(self.p) < MAX:
            self.p.append([x, y, vx, vy, life, life, size, col, kind])

    def update(self, dt):
        keep = []
        for q in self.p:
            q[4] -= dt
            if q[4] <= 0:
                continue
            k = q[8]
            if k == 3:
                q[2] *= 1 - 0.6 * dt
                q[3] = q[3] * (1 - 0.8 * dt) + 0.15 * dt
            elif k == 0:
                q[2] *= 1 - 1.8 * dt
                q[3] = q[3] * (1 - 1.8 * dt) + 0.6 * dt
            else:
                q[3] -= 9.8 * dt
            q[0] += q[2] * dt
            q[1] += q[3] * dt
            keep.append(q)
        self.p = keep

    def draw(self, surf, view):
        if not self.p:
            return
        if self.overlay is None or self.overlay.get_size() != surf.get_size():
            self.overlay = pygame.Surface(surf.get_size(), pygame.SRCALPHA)
            self.dirty = None
        ov = self.overlay
        if self.dirty is not None:                    # clear only what we drew last frame
            ov.fill((0, 0, 0, 0), self.dirty)
        s = view.s
        W, H = surf.get_size()
        x0 = y0 = 10 ** 9
        x1 = y1 = -10 ** 9
        draw_poly, draw_line = pygame.draw.polygon, pygame.draw.line
        cos, sin = math.cos, math.sin
        for q in self.p:
            x, y = view.tf(q[0], q[1])
            f = q[4] / q[5]
            kind = q[8]
            if kind == 2:
                ex, ey = x - q[2] * 0.03 * s, y + q[3] * 0.03 * s
                draw_line(ov, (255, 220, 120, 255), (x, y), (ex, ey), 2)
                lo_x, hi_x, lo_y, hi_y = min(x, ex) - 2, max(x, ex) + 2, min(y, ey) - 2, max(y, ey) + 2
            else:
                r = q[6] * s * ((1.4 - 0.4 * f) if kind == 0 else (2.4 - 1.4 * f) if kind == 3 else 1.0)
                if x < -r or y < -r or x > W + r or y > H + r:
                    continue
                a = int(200 * f * (0.7 if kind == 0 else 0.55 if kind == 3 else 1.0))
                col = (int(q[7][0]), int(q[7][1]), int(q[7][2]), a)
                ang = q[0] * 3.0
                ca_, sa_ = cos(ang) * r, sin(ang) * r
                draw_poly(ov, col, ((x + ca_, y + sa_), (x - sa_, y + ca_), (x - ca_, y - sa_), (x + sa_, y - ca_)))
                lo_x, hi_x, lo_y, hi_y = x - r * 1.5, x + r * 1.5, y - r * 1.5, y + r * 1.5
            if lo_x < x0: x0 = lo_x
            if hi_x > x1: x1 = hi_x
            if lo_y < y0: y0 = lo_y
            if hi_y > y1: y1 = hi_y
        if x1 < x0:
            self.dirty = None
            return
        rect = pygame.Rect(int(x0), int(y0), int(x1 - x0) + 2, int(y1 - y0) + 2).clip(pygame.Rect(0, 0, W, H))
        surf.blit(ov, rect.topleft, rect)
        self.dirty = rect

    def draw_gpu(self, rec, view):
        """Same particles as draw(), submitted as triangles to a Recorder."""
        s = view.s
        W, H = view.W, view.H
        cos, sin = math.cos, math.sin
        tf = view.tf
        for q in self.p:
            x, y = tf(q[0], q[1])
            f = q[4] / q[5]
            kind = q[8]
            if kind == 2:
                rec.line((255, 220, 120), (x, y), (x - q[2] * 0.03 * s, y + q[3] * 0.03 * s), 2)
                continue
            r = q[6] * s * ((1.4 - 0.4 * f) if kind == 0 else (2.4 - 1.4 * f) if kind == 3 else 1.0)
            if x < -r or y < -r or x > W + r or y > H + r:
                continue
            a = int(200 * f * (0.7 if kind == 0 else 0.55 if kind == 3 else 1.0))
            col = (q[7][0], q[7][1], q[7][2], a)
            ang = q[0] * 3.0
            ca_, sa_ = cos(ang) * r, sin(ang) * r
            p0, p1, p2, p3 = (x + ca_, y + sa_), (x - sa_, y + ca_), (x - ca_, y - sa_), (x + sa_, y - ca_)
            rec.tri(col, p0, p1, p2)
            rec.tri(col, p0, p2, p3)

    # --- spawning helpers driven by the truck state
    def wheel_fx(self, car, dt, pal, exhaust):
        from .terrain_render import soil_colors
        from . import terrain as T
        rnd = self.rnd
        for w in car.wheels:
            if not w.touching or w.Fn < 500:
                continue
            slip = abs(w.slip)
            spd = abs(w.vt)
            m = w.mat
            if m == T.ASPHALT:                       # tyre smoke when it really slides
                inten = max(0.0, slip - 2.2) * 0.22
                col = (214, 216, 222)
            elif m in (T.ROCK, T.WOOD, T.ICE):
                inten = max(0.0, slip - 1.5) * 0.1
                col = (190, 196, 206) if m == T.ICE else (150, 150, 158)
            else:
                inten = (max(0.0, slip - 0.6) * 0.7 + spd * 0.05) * (0.25 + w.soft)
                col = soil_colors(pal, m)[0]
            n = inten * 55 * dt * self.mult
            cnt = int(n) + (1 if rnd.random() < n - int(n) else 0)
            for _ in range(min(cnt, 5)):
                px, py = w.con[3], w.con[4]
                back = -1.0 if w.slip > 0 else 1.0
                sp = min(slip, 12.0)
                vx = w.tx * back * sp * 0.45 + car.vx * 0.3 + rnd.uniform(-0.8, 0.8)
                vy = w.ty * back * sp * 0.45 + rnd.uniform(0.5, 3.0)
                if m in (T.MUD, T.SNOW) and slip > 2.5 and rnd.random() < 0.45:
                    c = shade(col, 0.85) if m == T.MUD else col
                    self.emit(px, py, vx * 1.3, vy + 2.0, rnd.uniform(0.5, 0.9), rnd.uniform(0.06, 0.13), c, 1)
                else:
                    self.emit(px, py, vx, vy, rnd.uniform(0.7, 1.5), rnd.uniform(0.15, 0.32), col, 0)
        # diesel smoke
        thr = car.throttle
        if thr > 0.12 and exhaust:
            n = (0.4 + 2.2 * thr * thr) * 24 * dt * self.mult
            cnt = int(n) + (1 if rnd.random() < n - int(n) else 0)
            for _ in range(cnt):
                g = 70 + int(30 * (1 - thr))
                self.emit(exhaust[0], exhaust[1], car.vx * 0.5 + rnd.uniform(-0.3, 0.3), rnd.uniform(1.0, 2.2),
                          rnd.uniform(1.2, 2.2), rnd.uniform(0.12, 0.2), (g, g, g + 4), 3)
        if car.hit_f > 5000:
            hx, hy = car.hit
            n = min(6, int(car.hit_f / 9000) + 1)
            for _ in range(n):
                self.emit(hx, hy, car.vx * 0.3 + rnd.uniform(-3, 3), rnd.uniform(1, 5), rnd.uniform(0.2, 0.5), 0.05, (255, 220, 120), 2)
