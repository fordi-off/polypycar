"""Minimal low-poly HUD: speed, gear, rpm wedge gauge, tyre pressure, suspension bars."""
import math
import pygame
from .util import clamp, mixc, rgb


class Hud:
    def __init__(self):
        self.big = pygame.font.Font(None, 64)
        self.mid = pygame.font.Font(None, 30)
        self.small = pygame.font.Font(None, 22)
        self.show = True
        self.debug = False
        self.hint_t = 14.0

    def text(self, surf, font, s, pos, col=(255, 255, 255), shadow=True, anchor='tl'):
        img = font.render(s, True, col)
        r = img.get_rect()
        setattr(r, {'tl': 'topleft', 'tr': 'topright', 'bl': 'bottomleft', 'c': 'center', 'br': 'bottomright'}[anchor], pos)
        if shadow:
            sh = font.render(s, True, (0, 0, 0))
            surf.blit(sh, r.move(1, 2))
        surf.blit(img, r)

    def draw(self, surf, car, game):
        if not self.show:
            return
        W, H = surf.get_size()
        u = H / 720.0
        cx, cy, R = int(110 * u), int(H - 120 * u), 78 * u
        # rpm gauge: wedge segments over 240 degrees
        n = 26
        frac = clamp(car.rpm / 7000, 0, 1)
        a0, sweep = math.radians(150), math.radians(240)
        for i in range(n):
            f0, f1 = i / n, (i + 1) / n - 0.012
            lit = f1 <= frac + 1 / n * 0.5
            red = i / n > 0.84
            col = (240, 70, 60) if red else (250, 200, 80)
            col = col if lit else (50, 54, 66)
            ra, rb = R, R * 0.74
            p = []
            for f, rr in ((f0, ra), (f1, ra), (f1, rb), (f0, rb)):
                a = a0 + sweep * f
                p.append((cx + math.cos(a) * rr, cy + math.sin(a) * rr))
            pygame.draw.polygon(surf, col, p)
        g = 'R' if car.gear < 0 else 'N' if car.gear == 0 else str(car.gear)
        self.text(surf, self.big, g, (cx, cy - 4 * u), anchor='c')
        self.text(surf, self.small, ('AUTO' if car.auto else 'MANUAL'), (cx, cy + 34 * u), (200, 210, 230), anchor='c')
        kmh = int(abs(car.speed) * 3.6)
        self.text(surf, self.big, str(kmh), (cx + R + 24 * u, cy - 6 * u), anchor='tl')
        self.text(surf, self.small, 'km/h', (cx + R + 26 * u, cy + 34 * u), (200, 210, 230))
        # tyre pressure
        self.text(surf, self.mid, 'TYRES %2d PSI' % round(car.pressure_psi), (cx - R, cy + R + 8 * u), (200, 235, 255))
        # suspension travel bars (right-bottom)
        bx, by = W - 120 * u, H - 40 * u
        c = car.cfg
        for i, w in enumerate(car.wheels):
            comp = clamp((c['l0'] - w.l) / (c['l0'] - c['lmin']), 0, 1)
            x = bx + i * 46 * u
            pygame.draw.polygon(surf, (50, 54, 66), [(x, by), (x + 22 * u, by), (x + 22 * u, by - 70 * u), (x, by - 70 * u)])
            col = mixc((110, 220, 150), (240, 90, 70), comp ** 2)
            pygame.draw.polygon(surf, rgb(col), [(x, by), (x + 22 * u, by), (x + 22 * u, by - 70 * u * comp), (x, by - 70 * u * comp)])
        self.text(surf, self.small, 'SUSPENSION', (bx - 4 * u, by + 6 * u), (200, 210, 230))
        # top-left info
        pal = game.pal
        dist = car.x
        self.text(surf, self.small, '%s  ·  %s  ·  %+d m' % (pal['name'], game.terrain.zone_param(math.floor(car.x / 96))['theme'], dist), (18 * u, 14 * u), (255, 255, 255))
        if self.hint_t > 0:
            a = clamp(self.hint_t / 3, 0, 1)
            lines = ['W / UP  gas        S / DOWN  brake / reverse        A D / LEFT RIGHT  lean (pitch)',
                     'SPACE handbrake    [ ]  tyre pressure    T  auto/manual (Q/E shift)    R  reset    C  paint',
                     'H  hud    TAB  telemetry    M  sound    F11  fullscreen    ESC  quit']
            for k, ln in enumerate(lines):
                img = self.small.render(ln, True, (255, 255, 255))
                img.set_alpha(int(255 * a))
                surf.blit(img, (W // 2 - img.get_width() // 2, int(54 * u) + k * 22))
        if self.debug:
            ws = car.wheels
            rows = ['rpm %5d  gear %d  engage %.2f  %s' % (car.rpm, car.gear, car.engage, 'LOCK' if car.locked else 'slip'),
                    'F: load %5d N  slip %5.1f m/s  pen %3d mm  travel %.2f' % (ws[0].Fn, ws[0].slip, ws[0].pen * 1000, ws[0].l),
                    'R: load %5d N  slip %5.1f m/s  pen %3d mm  travel %.2f' % (ws[1].Fn, ws[1].slip, ws[1].pen * 1000, ws[1].l),
                    'fps %d  seed %d' % (game.clock.get_fps(), game.terrain.seed)]
            for k, ln in enumerate(rows):
                self.text(surf, self.small, ln, (18 * u, 40 * u + k * 20), (255, 240, 160))
