"""Draws any vehicle: sprung wheels with squishing polygon tyres sunk into the soil, coil-over
springs and shocks (scaled to the vehicle), then the vehicle's own body art (vehicle_art.py).
Rendered supersampled into a buffer and smooth-scaled down for clean edges."""
import math
import pygame
from .util import clamp, rgb
from .vehicle_art import ART
from .gfx import SurfacePainter, Recorder, triangulate


class SubView:
    """World -> buffer transform for the supersampled car layer."""

    def __init__(self, s, ox, oy, wx, wy):
        self.s = s
        self.ox, self.oy, self.wx, self.wy = ox, oy, wx, wy

    def tf(self, x, y):
        return ((x - self.wx) * self.s + self.ox, self.oy - (y - self.wy) * self.s)


class Ctx:
    """What a body-art routine draws with: a painter plus chassis-local -> view coordinate mapping."""

    def __init__(self, paint, view, car, base, head, ca, sa):
        self.paint, self.view, self.car, self.base, self.head = paint, view, car, base, head
        self.ca, self.sa = ca, sa
        self.paint_color = None

    def L(self, pts):
        car, ca, sa, tf = self.car, self.ca, self.sa, self.view.tf
        return [tf(car.x + x * ca - y * sa, car.y + x * sa + y * ca) for x, y in pts]

    def poly(self, col, pts, k=1.0):
        verts = self.L(pts)
        if self.paint.needs_tris:
            self.paint.tris(rgb(col, k), verts, triangulate([tuple(p) for p in pts]))
        else:
            self.paint.poly(rgb(col, k), verts)


class CarRenderer:
    def __init__(self, spec, ss=3):
        self.spec = spec
        self.ss = ss
        self.buf = None
        self.paint = 0
        self.head = [0.0, 0.0]
        self.head_v = [0.0, 0.0]
        self.prev_v = None

    @property
    def paint_color(self):
        p = self.spec.paints
        return p[self.paint % len(p)]

    def next_paint(self):
        self.paint = (self.paint + 1) % len(self.spec.paints)

    def exhaust_world(self, car):
        ca, sa = math.cos(car.a), math.sin(car.a)
        x, y = self.spec.exhaust
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
        """Render into an SSx buffer, smooth-scale down and place with sub-pixel accuracy."""
        s = view.s
        BW, BH, yoff = self.spec.art_box
        ss = self.ss
        cxw, cyw = car.x, car.y + yoff
        px, py = view.tf(cxw - BW / 2, cyw + BH / 2)       # top-left in screen px (float)
        ix, iy = math.floor(px), math.floor(py)
        fx, fy = px - ix, py - iy
        w, h = int(BW * s) + 2, int(BH * s) + 2
        if ix > surf.get_width() or iy > surf.get_height() or ix + w < 0 or iy + h < 0:
            return
        if self.buf is None or self.buf.get_size() != (w * ss, h * ss):
            self.buf = pygame.Surface((w * ss, h * ss), pygame.SRCALPHA)
        self.buf.fill((0, 0, 0, 0))
        sv = SubView(s * ss, fx * ss, fy * ss, cxw - BW / 2, cyw + BH / 2)
        self._draw(SurfacePainter(self.buf), sv, car, terrain)
        if ss == 1:
            surf.blit(self.buf, (ix, iy))
        else:
            surf.blit(pygame.transform.smoothscale(self.buf, (w, h)), (ix, iy))

    def draw_gpu(self, paint, view, car, terrain):
        """GPU path: no supersample buffer - the GPU's MSAA and float coordinates give the smoothness."""
        self._draw(paint, view, car, terrain)

    def _draw(self, paint, view, car, terrain):
        cfg = car.cfg
        ca, sa = math.cos(car.a), math.sin(car.a)
        pre, post = ART[self.spec.art]
        ctx = Ctx(paint, view, car, self.paint_color, self.head, ca, sa)
        pre(ctx)
        for w in car.wheels:
            self._suspension(paint, view, car, w, ca, sa)
        for w in car.wheels:
            self._wheel(paint, view, w, cfg['wheel_r'], terrain)
        post(ctx)

    # ------------------------------------------------------------------
    def _suspension(self, paint, view, car, w, ca, sa):
        cfg = car.cfg
        k0 = cfg['wheel_r'] / 0.62
        tf = view.tf
        my = cfg['mount_y']
        mx_w = car.x + w.mx * ca - my * sa
        my_w = car.y + w.mx * sa + my * ca
        dxn, dyn = sa, -ca
        fx, fy = ca, sa
        sgn = 1 if w.mx > 0 else -1
        # lower arm: chassis pivot -> hub
        pvx = car.x + (w.mx - sgn * 0.9 * k0) * ca + 0.3 * k0 * sa
        pvy = car.y + (w.mx - sgn * 0.9 * k0) * sa - 0.3 * k0 * ca
        paint.line((44, 46, 54), tf(pvx, pvy), tf(w.hx, w.hy), max(3, int(view.s * 0.16 * k0)))
        # shock (dark body + bright piston)
        ax, ay = mx_w + fx * 0.2 * k0, my_w + fy * 0.2 * k0
        bx, by = w.hx + fx * 0.1 * k0, w.hy + fy * 0.1 * k0
        paint.line((30, 30, 36), tf(ax, ay), tf(bx, by), max(4, int(view.s * 0.15 * k0)))
        mxp, myp = (ax + bx) / 2, (ay + by) / 2
        paint.line((210, 214, 224), tf(mxp, myp), tf(bx, by), max(2, int(view.s * 0.07 * k0)))
        # coil spring (zig-zag)
        n = 9
        pts = []
        lx0, ly0 = mx_w - fx * 0.08 * k0, my_w - fy * 0.08 * k0
        lx1, ly1 = w.hx - fx * 0.08 * k0 - dxn * 0.1 * k0, w.hy - fy * 0.08 * k0 - dyn * 0.1 * k0
        for i in range(n + 1):
            t = i / n
            off = 0.0 if i in (0, n) else (0.14 if i % 2 else -0.14) * k0
            pts.append(tf(lx0 + (lx1 - lx0) * t + fx * off, ly0 + (ly1 - ly0) * t + fy * off))
        paint.lines((255, 176, 40), pts, max(2, int(view.s * 0.08 * k0)))

    def _wheel(self, paint, view, w, R, terrain):
        tf = view.tf
        cx, cy = w.hx, w.hy
        k0 = R / 0.62
        N = 26
        stretch = 1 + 0.4 * w.pen / R
        ang = -w.ang
        outer = []
        for k in range(N):
            a = ang + k * math.tau / N
            r = R if k % 2 == 0 else R - 0.085 * k0
            px = cx + math.cos(a) * r
            py = cy + math.sin(a) * r
            gh = terrain.h(px)
            if py < gh:
                py = gh
            outer.append(((cx + (px - cx) * stretch), py))
        S = [tf(*p) for p in outer]
        C = tf(cx, cy)
        paint.fan((22, 22, 26), C, S)
        for k in range(N):
            tone = 42 if (k // 2) % 2 == 0 else 30
            paint.tri((tone, tone, tone + 4), C, S[k], S[(k + 1) % N])
        side = [tf(cx + math.cos(ang + k * math.tau / 20) * 0.46 * k0, cy + math.sin(ang + k * math.tau / 20) * 0.46 * k0) for k in range(20)]
        paint.fan((56, 56, 64), C, side)
        for k in range(10):
            a0, a1 = ang + k * math.tau / 10, ang + (k + 1) * math.tau / 10
            rim = ((cx, cy), (cx + math.cos(a0) * 0.33 * k0, cy + math.sin(a0) * 0.33 * k0), (cx + math.cos(a1) * 0.33 * k0, cy + math.sin(a1) * 0.33 * k0))
            tone = 190 if k % 2 else 146
            paint.tri((tone, tone + 4, tone + 14), *[tf(*p) for p in rim])
        for k in range(6):
            a = ang + k * math.tau / 6
            sp = [(cx + math.cos(a - 0.14) * 0.07 * k0, cy + math.sin(a - 0.14) * 0.07 * k0), (cx + math.cos(a - 0.09) * 0.3 * k0, cy + math.sin(a - 0.09) * 0.3 * k0),
                  (cx + math.cos(a + 0.09) * 0.3 * k0, cy + math.sin(a + 0.09) * 0.3 * k0), (cx + math.cos(a + 0.14) * 0.07 * k0, cy + math.sin(a + 0.14) * 0.07 * k0)]
            paint.poly((70, 72, 82), [tf(*p) for p in sp])
        paint.fan((226, 228, 236), C, [tf(cx + math.cos(ang + k * math.tau / 6) * 0.1 * k0, cy + math.sin(ang + k * math.tau / 6) * 0.1 * k0) for k in range(6)])
