"""Dust, mud splashes and sparks."""
import math
import random
import pygame
from .util import mixc, rgb

MAX = 420


class Particles:
    def __init__(self):
        self.p = []   # [x, y, vx, vy, life, max, size, (r,g,b), kind]  kind 0 dust, 1 mud, 2 spark
        self.overlay = None
        self.rnd = random.Random(7)

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
            if k == 0:
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
        ov = self.overlay
        ov.fill((0, 0, 0, 0))
        s = view.s
        for q in self.p:
            x, y = view.tf(q[0], q[1])
            f = q[4] / q[5]
            kind = q[8]
            if kind == 2:
                pygame.draw.line(ov, (255, 220, 120, 255), (x, y), (x - q[2] * 0.03 * s, y + q[3] * 0.03 * s), 2)
                continue
            r = q[6] * s * (1.4 - 0.4 * f if kind == 0 else 1.0)
            a = int(200 * f * (0.7 if kind == 0 else 1.0))
            col = (int(q[7][0]), int(q[7][1]), int(q[7][2]), a)
            ang = q[0] * 3.0
            pts = [(x + math.cos(ang + i * math.tau / 5) * r, y + math.sin(ang + i * math.tau / 5) * r) for i in range(5)]
            pygame.draw.polygon(ov, col, pts)
        surf.blit(ov, (0, 0))

    # --- spawning helpers driven by the car state
    def wheel_fx(self, car, dt, pal_top, terrain):
        rnd = self.rnd
        for w in car.wheels:
            if not w.touching or w.Fn < 200:
                continue
            slip = abs(w.slip)
            spd = abs(w.vt)
            loose = w.loose
            inten = (max(0.0, slip - 1.2) * 0.25 + spd * 0.025) * loose
            if w.mat == 1:
                inten *= 0.25
            n = inten * 70 * dt
            cnt = int(n) + (1 if rnd.random() < n - int(n) else 0)
            for _ in range(min(cnt, 4)):
                px, py = w.con[3], w.con[4]
                back = -1.0 if w.slip > 0 else 1.0
                sp = min(slip, 14.0)
                vx = w.tx * back * sp * 0.35 + car.vx * 0.25 + rnd.uniform(-0.8, 0.8)
                vy = w.ty * back * sp * 0.35 + rnd.uniform(0.5, 2.8)
                if w.mat == 3:
                    col = (82, 58, 42)
                    self.emit(px, py, vx, vy + 1.5, rnd.uniform(0.5, 0.9), rnd.uniform(0.05, 0.1), col, 1)
                else:
                    col = mixc(pal_top, (196, 180, 150), 0.45) if w.mat != 1 else (150, 150, 158)
                    self.emit(px, py, vx, vy, rnd.uniform(0.6, 1.3), rnd.uniform(0.12, 0.26), col, 0)
        if car.hit_f > 5000:
            hx, hy = car.hit
            n = min(6, int(car.hit_f / 9000) + 1)
            for _ in range(n):
                self.emit(hx, hy, car.vx * 0.3 + rnd.uniform(-3, 3), rnd.uniform(1, 5), rnd.uniform(0.2, 0.5), 0.05, (255, 220, 120), 2)
