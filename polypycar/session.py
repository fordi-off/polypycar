"""A running world: terrain + one vehicle + camera + scenery + particles. The drive scene, the
menu backdrop and the garage preview all use this."""
import math
import pygame
from . import terrain as T
from . import vehicles as V
from .terrain import Terrain
from .car import Car
from .terrain_render import ChunkRenderer
from .scenery import Scenery
from .car_render import CarRenderer
from .particles import Particles
from . import gfx, gl_world
from .gfx import SurfacePainter

ANCHOR = 0.58           # the camera point sits this far down the screen
assert ANCHOR == 0.58   # terrain_render.ANCHOR_Y must match


class View:
    def __init__(self, W, H, s):
        self.W, self.H, self.s = W, H, s
        self.cx = self.cy = 0.0

    def tf(self, x, y):
        return ((x - self.cx) * self.s + self.W * 0.5, self.H * ANCHOR - (y - self.cy) * self.s)


class Controls:
    __slots__ = ('up', 'dn', 'hand', 'lean', 'shift_up', 'shift_dn')

    def __init__(self):
        self.up = self.dn = self.hand = self.lean = 0.0
        self.shift_up = self.shift_dn = False


class Session:
    def __init__(self, settings, vehicle_id, paint, world_cfg, seed, start_x=0.0):
        self.settings = settings
        self.spec = V.get(vehicle_id)
        self.world_cfg = world_cfg
        self.terrain = Terrain(seed, world_cfg)
        self.car = Car(self.terrain, self.spec)
        self.apply_settings()
        self.scenery = Scenery()
        self.carr = CarRenderer(self.spec, settings.q['car_ss'] if settings['car_aa'] else 1)
        self.carr.paint = paint % len(self.spec.paints)
        self.parts = Particles()
        self.chunks = ChunkRenderer(self.terrain, 30.0)
        self.view = View(1280, 720, 30.0)
        self.pal = T.palette_at(start_x)
        self.time = 0.0
        self.cam_offset = 0.0
        self.car.reset(start_x)
        self.car.pressure = settings['default_pressure']
        for _ in range(120):                       # let the suspension settle before the first frame
            self.car.control(1 / 60, 0, 0, 0, 0)
            self.car.step(1 / 60)
        self.view.cx, self.view.cy = self.car.x, self.car.y + 1.4
        self._glc = None

    def apply_settings(self):
        st = self.settings
        self.car.throttle_ramp = st['throttle_ramp']
        self.car.auto = st['auto_gearbox']

    # ------------------------------------------------------------------ simulation
    def update(self, dt, ctl):
        car, st = self.car, self.settings
        car.control(dt, ctl.up, ctl.dn, ctl.hand, ctl.lean, ctl.shift_up, ctl.shift_dn)
        car.step(dt)
        self.time += dt
        self.pal = T.palette_at(car.x)
        self.scenery.update(dt)
        self.carr.update(car, dt)
        self.parts.mult = st['particles'] * st.q['particles']
        self.parts.wheel_fx(car, dt, self.pal, self.carr.exhaust_world(car))
        self.parts.update(dt)
        self.terrain.prune(car.x)
        v = self.view
        look = 9.0 * st['camera_lookahead']
        tx = car.x + max(-look, min(look, car.vx * 0.45)) - self.cam_offset
        ty = car.y + 1.4
        v.cx += (tx - v.cx) * (1 - math.exp(-dt * 3.2))
        v.cy += (ty - v.cy) * (1 - math.exp(-dt * 2.2))

    def respawn(self, x=None):
        self.car.reset(self.car.x if x is None else x)

    # ------------------------------------------------------------------ drawing
    def draw(self, target):
        st = self.settings
        W, H = target.get_size()
        if gfx.ACTIVE is not None:
            return self.draw_gpu(gfx.ACTIVE, W, H)
        v = self.view
        v.W, v.H = W, H
        v.s = H / st['camera_zoom']
        self.chunks.set_scale(v.s)
        pal = self.pal
        sc = self.scenery
        q = st.q
        sc.draw_sky(target, pal)
        sp = SurfacePainter(target)
        sc.draw_clouds(sp, W, H, v.cx, v.cy, v.s)
        sc.draw_mountains(sp, W, H, v.cx, v.cy, v.s, pal, q['mountains'])
        if st['fog'] and q['fog']:
            sc.draw_fog(target, pal)
        c0 = math.floor((v.cx - W / 2 / v.s) / T.CHUNK_W)
        c1 = math.floor((v.cx + W / 2 / v.s) / T.CHUNK_W)
        for ci in range(c0, c1 + 1):
            surf, X0, top, bottom = self.chunks.get(ci)
            dx = round((X0 - v.cx) * v.s + W / 2)
            dy = round(H * ANCHOR - (top - v.cy) * v.s)
            target.blit(surf, (dx, dy))
            under = dy + surf.get_height() - 1
            if under < H:
                deep = tuple(int(c) for c in T.palette_at(ci * T.CHUNK_W + T.CHUNK_W / 2)['deep'])
                target.fill(deep, (dx, under, surf.get_width(), H - under))
        d = 1 if self.car.vx >= 0 else -1
        edge = c1 if d > 0 else c0
        far = 3 if abs(self.car.vx) > 28 else 2
        self.chunks.prefetch([edge + k * d for k in range(1, far + 1)] + [edge - d * (c1 - c0 + 1)], budget=0.006)
        self.chunks.prune((c0 + c1) // 2, keep=4)
        self.chunks.draw_soil(target, v, q['soil_step'])
        self.parts.draw(target, v)
        self.carr.draw(target, v, self.car, self.terrain)
        if self.world_cfg.snowfall:
            sc.draw_snow(target, pal, v.cx, v.cy, v.s, st['snow_density'] * q['snow'])

    def draw_gpu(self, gl, W, H):
        st, q, pal, sc, v = self.settings, self.settings.q, self.pal, self.scenery, self.view
        v.W, v.H = W, H
        v.s = H / st['camera_zoom']
        if self._glc is None or self._glc.gl is not gl:        # (re)created with the GL context
            self._glc = gl_world.GLChunks(gl, self.chunks)
        rec = gl.rec
        gl_world.sky(rec, W, H, pal)
        sc.draw_sun(rec, W, H, pal)
        sc.draw_clouds(rec, W, H, v.cx, v.cy, v.s)
        sc.draw_mountains(rec, W, H, v.cx, v.cy, v.s, pal, q['mountains'])
        if st['fog'] and q['fog']:
            gl_world.fog(rec, W, H, pal)
        gl.flush()
        c0 = math.floor((v.cx - W / 2 / v.s) / T.CHUNK_W)
        c1 = math.floor((v.cx + W / 2 / v.s) / T.CHUNK_W)
        self._glc.draw(v, c0, c1)
        d = 1 if self.car.vx >= 0 else -1
        edge = c1 if d > 0 else c0
        far = 3 if abs(self.car.vx) > 28 else 2
        self._glc.prefetch([edge + k * d for k in range(1, far + 1)] + [edge - d * (c1 - c0 + 1)], budget=0.006)
        self._glc.prune((c0 + c1) // 2, keep=4)
        self.chunks.prune_soil((c0 + c1) // 2, keep=4)
        rec.add_array(self.chunks.soil_vertices(v, q['soil_step']))
        self.parts.draw_gpu(rec, v)
        self.carr.draw_gpu(rec, v, self.car, self.terrain)
        if self.world_cfg.snowfall:
            rec.add_array(gl_world.snow_array(sc, W, H, v.cx, v.cy, v.s, pal, st['snow_density'] * q['snow']))
        gl.flush()
