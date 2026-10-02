"""Sky gradient, sun, drifting low-poly clouds and faceted parallax mountain ranges."""
import math
import pygame
from .util import clamp, noise1, hash_i, mixc, shade, rgb
from .gfx import SurfacePainter

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
        self.sky_surf = None
        self.sky_key = None
        self.flakes = [(hash_i(i, 60), hash_i(i, 61), 0.4 + 1.2 * hash_i(i, 62), hash_i(i, 63)) for i in range(260)]
        self.fog_surf = None
        self._mt = {}
        self._mt_s = None
        self.fog_key = None

    def update(self, dt):
        self.t += dt

    def draw_sky(self, screen, pal):
        W, H = screen.get_size()
        c0 = tuple(int(c) // 3 * 3 for c in pal['sky0'])
        c1 = tuple(int(c) // 3 * 3 for c in pal['sky1'])
        key = (W, H, c0, c1)
        if self.sky_key != key:                       # the gradient only changes while blending between biomes
            self.sky_key = key
            n = self._strip.get_height()
            for i in range(n):
                f = (i / (n - 1)) ** 0.85
                self._strip.set_at((0, i), rgb(mixc(c0, c1, f)))
            if self.sky_surf is None or self.sky_surf.get_size() != (W, H):
                self.sky_surf = pygame.Surface((W, H)).convert()
            pygame.transform.scale(self._strip, (W, H), self.sky_surf)
        screen.blit(self.sky_surf, (0, 0))
        self.draw_sun(SurfacePainter(screen), W, H, pal)

    @staticmethod
    def draw_sun(paint, W, H, pal):
        """Sun with a soft low-poly halo."""
        sx, sy = int(W * 0.78), int(H * 0.2)
        for r, k in ((H * 0.1, 0.16), (H * 0.058, 1.0)):
            col = mixc(pal['sky1'] if k < 1 else pal['sun'], pal['sun'], k)
            paint.poly(rgb(col), [(sx + math.cos(a * math.tau / 14 + 0.2) * r, sy + math.sin(a * math.tau / 14 + 0.2) * r) for a in range(14)])

    def draw_fog(self, screen, pal):
        """Soft horizon haze between the mountains and the ground. Only the band that can show is built and blitted."""
        W, H = screen.get_size()
        strength = int(clamp(pal['fog'] * 1.6, 0, 1) * 16)
        if strength <= 0:
            return
        col = tuple(int(c) // 6 * 6 for c in pal['sky1'])
        y0, y1 = int(H * 0.28), int(H * 0.76)
        key = (W, H, col, strength)
        if self.fog_key != key:
            self.fog_key = key
            self.fog_surf = pygame.Surface((W, y1 - y0), pygame.SRCALPHA)
            k = strength / 16.0
            for y in range(y0, y1, 2):
                f = y / H
                a = max(0.0, 1.0 - abs(f - 0.62) / 0.34)
                pygame.draw.rect(self.fog_surf, (col[0], col[1], col[2], int(255 * a * a * k)), (0, y - y0, W, 2))
        screen.blit(self.fog_surf, (0, y0))

    def draw_snow(self, screen, pal, cam_x, cam_y, s, density=1.0):
        """Falling snow in three parallax depths; intensity per biome."""
        k = pal['snowfall'] * density
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

    def draw_clouds(self, paint, W, H, cam_x, cam_y, s):
        span = 420.0
        white = (255, 255, 255)
        shadow = rgb(mixc(white, (190, 205, 235), 0.55))
        for cx, fy, size, h in self.clouds:
            u = (cx - cam_x * 0.05 + self.t * (0.5 + h)) % span - span / 2
            px = W / 2 + u * s * 0.55
            py = H * fy + cam_y * 0.01 * s
            if px < -300 or px > W + 300:
                continue
            k = s * size
            for j, (ox, oy, w, hh) in enumerate(((-1.6, 0.2, 2.2, 0.8), (0.0, 0.0, 2.8, 1.2), (1.7, 0.25, 2.0, 0.8), (0.3, -0.5, 1.6, 0.8))):
                x, y, ww, h2 = px + ox * k, py + oy * k, w * k, hh * k * 0.75
                paint.poly((255, 255, 255), [(x - ww, y), (x - ww * 0.55, y - h2), (x + ww * 0.1, y - h2 * 1.15), (x + ww * 0.6, y - h2 * 0.8), (x + ww, y)])
                paint.poly(shadow, [(x - ww, y), (x + ww, y), (x + ww * 0.55, y + h2 * 0.35), (x - ww * 0.5, y + h2 * 0.3)])

    def draw_mountains(self, paint, W, H, cam_x, cam_y, s, pal, n_layers=4):
        sky = mixc(pal['sky0'], pal['sky1'], 0.65)
        if self._mt_s != s:
            self._mt, self._mt_s = {}, s
        pick = {2: (0, 3), 3: (0, 1, 3)}.get(n_layers, (0, 1, 2, 3))
        for li, (f, anchor, amp, wl, fog, seed) in enumerate(LAYERS):
            if li not in pick:
                continue
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
            # faceted ridge band down to just below the lowest ridge point, then one flat fill to the bottom
            ybase = min(H + 4, max(p[1] for p in pts) + 2)
            flat = rgb(col, 0.95)
            for i in range(len(pts) - 1):
                xa, ya, _ = pts[i]
                xb, yb, hj = pts[i + 1]
                lit = 1.0 + (0.07 if yb > ya else -0.06) + 0.03 * (hj - 0.5)
                paint.tri(rgb(col, lit), (xa, ya), (xb, yb), (xb, ybase))
                paint.tri(flat, (xa, ya), (xb, ybase), (xa, ybase))
            if ybase < H:
                paint.rect(flat, 0, ybase, W, H - ybase)
        if len(self._mt) > 4000:
            self._mt.clear()
