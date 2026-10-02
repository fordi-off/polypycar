"""Sky gradient, sun, drifting low-poly clouds and faceted parallax mountain ranges."""
import math
import pygame
from .util import clamp, noise1, hash_i, mixc, shade, rgb

# (parallax, anchor frac of screen height, amplitude m, wavelength m, fog, seed)
LAYERS = [
    (0.035, 0.74, 6.5, 22.0, 0.55, 1),
    (0.09, 0.78, 5.0, 15.0, 0.38, 2),
    (0.20, 0.82, 3.4, 10.0, 0.20, 3),
    (0.38, 0.87, 1.7, 7.0, 0.06, 4),
]


class Scenery:
    def __init__(self):
        self.t = 0.0
        self.clouds = [(hash_i(i, 50) * 420, 0.08 + 0.3 * hash_i(i, 51), 0.7 + 1.3 * hash_i(i, 52), hash_i(i, 53)) for i in range(9)]
        self._strip = pygame.Surface((1, 48))
        self.flakes = [(hash_i(i, 60), hash_i(i, 61), 0.4 + 1.2 * hash_i(i, 62), hash_i(i, 63)) for i in range(260)]
        self.fog_surf = None
        self._mt = {}
        self._mt_s = None
        self.fog_key = None

    def update(self, dt):
        self.t += dt

    def draw_sky(self, screen, pal):
        W, H = screen.get_size()
        c0, c1 = pal['sky0'], pal['sky1']
        n = self._strip.get_height()
        for i in range(n):
            f = (i / (n - 1)) ** 0.85
            self._strip.set_at((0, i), rgb(mixc(c0, c1, f)))
        pygame.transform.scale(self._strip, (W, H), screen)
        # sun with soft low-poly halo
        sx, sy = int(W * 0.78), int(H * 0.2)
        for r, k in ((H * 0.1, 0.16), (H * 0.058, 1.0)):
            col = mixc(c1 if k < 1 else pal['sun'], pal['sun'], k)
            pts = [(sx + math.cos(a * math.tau / 14 + 0.2) * r, sy + math.sin(a * math.tau / 14 + 0.2) * r) for a in range(14)]
            pygame.draw.polygon(screen, rgb(col), pts)

    def draw_fog(self, screen, pal):
        """Soft horizon haze between the mountains and the ground (strength per biome)."""
        W, H = screen.get_size()
        col = tuple(int(c) // 6 * 6 for c in pal['sky1'])
        key = (W, H, col)
        if self.fog_key != key:
            self.fog_key = key
            self.fog_surf = pygame.Surface((W, H), pygame.SRCALPHA)
            for y in range(0, H, 2):
                f = y / H
                a = max(0.0, 1.0 - abs(f - 0.62) / 0.34)
                pygame.draw.rect(self.fog_surf, (col[0], col[1], col[2], int(255 * a * a)), (0, y, W, 2))
        self.fog_surf.set_alpha(int(255 * clamp(pal['fog'] * 1.6, 0, 1)))
        screen.blit(self.fog_surf, (0, 0))

    def draw_snow(self, screen, pal, cam_x, cam_y, s, car_vx):
        """Falling snow in three parallax depths; intensity per biome."""
        k = pal['snowfall']
        if k <= 0.02:
            return
        W, H = screen.get_size()
        n = int(len(self.flakes) * min(1.0, k))
        wind = 1.6
        for fx, fy, d, ph in self.flakes[:n]:
            speed = 0.6 + 1.1 * d
            x = (fx * W * 1.3 + (wind * d * 40 + 0) * self.t - cam_x * s * 0.35 * d + 25 * math.sin(self.t * 0.7 + ph * 6.3)) % (W * 1.3) - W * 0.15
            y = (fy * H + self.t * 60 * speed * d - cam_y * s * 0.05) % H
            r = max(1, int(1.2 * d * s / 36))
            pygame.draw.rect(screen, (255, 255, 255), (x, y, r + 1, r + 1))

    def draw_clouds(self, screen, cam_x, cam_y, s):
        W, H = screen.get_size()
        span = 420.0
        white = (255, 255, 255)
        for cx, fy, size, h in self.clouds:
            u = (cx - cam_x * 0.05 + self.t * (0.5 + h)) % span - span / 2
            px = W / 2 + u * s * 0.55
            py = H * fy + cam_y * 0.01 * s
            if px < -300 or px > W + 300:
                continue
            k = s * size
            for j, (ox, oy, w, hh) in enumerate(((-1.6, 0.2, 2.2, 0.8), (0.0, 0.0, 2.8, 1.2), (1.7, 0.25, 2.0, 0.8), (0.3, -0.5, 1.6, 0.8))):
                x, y, ww, h2 = px + ox * k, py + oy * k, w * k, hh * k * 0.75
                top = [(x - ww, y), (x - ww * 0.55, y - h2), (x + ww * 0.1, y - h2 * 1.15), (x + ww * 0.6, y - h2 * 0.8), (x + ww, y)]
                pygame.draw.polygon(screen, rgb(white), top)
                pygame.draw.polygon(screen, rgb(mixc(white, (190, 205, 235), 0.55)), [(x - ww, y), (x + ww, y), (x + ww * 0.55, y + h2 * 0.35), (x - ww * 0.5, y + h2 * 0.3)])

    def draw_mountains(self, screen, cam_x, cam_y, s, pal):
        W, H = screen.get_size()
        sky = mixc(pal['sky0'], pal['sky1'], 0.65)
        if self._mt_s != s:
            self._mt, self._mt_s = {}, s
        for li, (f, anchor, amp, wl, fog, seed) in enumerate(LAYERS):
            col = mixc(pal['mtn'], sky, fog)
            if li == 3:
                col = mixc(pal['tree'], sky, 0.25)
            base_y = H * anchor + cam_y * f * s
            lsc = s * 0.9
            step = 34 if li < 3 else 24
            du = step / lsc                      # ridge samples sit on a fixed grid in layer space
            shift = cam_x * f
            j = math.floor(((-step - W / 2) / lsc + shift) / du)
            pts = []
            while True:
                x = (j * du - shift) * lsc + W / 2
                if x > W + step:
                    break
                e = self._mt.get((li, j))
                if e is None:
                    u = j * du
                    hh = amp * (0.62 * (1 - abs(noise1(u / wl, seed * 17))) + 0.28 * (1 - abs(noise1(u / (wl * 0.41), seed * 31)))
                                + 0.10 * (1 - abs(noise1(u / (wl * 0.17), seed * 47))) - 0.2)
                    e = self._mt[(li, j)] = (hh, hash_i(j, seed))
                pts.append((x, base_y - e[0] * lsc, e[1]))
                j += 1
            bottom = H + 4
            for i in range(len(pts) - 1):
                xa, ya, _ = pts[i]
                xb, yb, hj = pts[i + 1]
                lit = 1.0 + (0.07 if yb > ya else -0.06) + 0.03 * (hj - 0.5)
                pygame.draw.polygon(screen, rgb(col, lit), ((xa, ya), (xb, yb), (xb, bottom)))
                pygame.draw.polygon(screen, rgb(col, lit * 0.9), ((xa, ya), (xb, bottom), (xa, bottom)))
        if len(self._mt) > 4000:
            self._mt.clear()
