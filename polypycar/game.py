"""Main loop: input, camera, drawing."""
import math
import pygame
from .util import clamp, rgb, mixc
from . import terrain as T
from .terrain import Terrain
from .car import Car
from .terrain_render import ChunkRenderer
from .scenery import Scenery
from .car_render import CarRenderer
from .particles import Particles
from .hud import Hud
from .audio import Audio

VIEW_METERS = 22.0
ANCHOR = 0.58   # camera point sits this far down the screen


class View:
    def __init__(self, W, H, s):
        self.W, self.H, self.s = W, H, s
        self.cx = self.cy = 0.0

    def tf(self, x, y):
        return ((x - self.cx) * self.s + self.W * 0.5, self.H * ANCHOR - (y - self.cy) * self.s)


class Game:
    def __init__(self, seed=1337, sound=True, size=(1280, 720), fullscreen=False):
        pygame.init()
        flags = pygame.RESIZABLE | (pygame.FULLSCREEN if fullscreen else 0)
        self.screen = pygame.display.set_mode(size, flags)
        pygame.display.set_caption('PolyPyCar - snow & mud')
        self.clock = pygame.time.Clock()
        self.terrain = Terrain(seed)
        self.car = Car(self.terrain)
        self.car.reset(0.0)
        self.scenery = Scenery()
        self.carr = CarRenderer()
        self.parts = Particles()
        self.hud = Hud()
        self.audio = Audio(sound)
        W, H = self.screen.get_size()
        self.view = View(W, H, H / VIEW_METERS)
        self.chunks = ChunkRenderer(self.terrain, self.view.s)
        self.view.cx, self.view.cy = self.car.x, self.car.y + 1.0
        self.pal = T.palette_at(self.car.x)
        self.running = True
        self.time = 0.0
        self.autodrive = False
        self.auto_thr = 1.0
        # settle the car and warm the chunk cache so the first frame is clean
        for _ in range(120):
            self.car.control(1 / 60, 0, 0, 0, 0)
            self.car.step(1 / 60)
        self.view.cy = self.car.y + 1.0

    # ------------------------------------------------------------------ input
    def handle_events(self):
        shift_up = shift_dn = False
        for e in pygame.event.get():
            if e.type == pygame.QUIT:
                self.running = False
            elif e.type == pygame.VIDEORESIZE:
                pass
            elif e.type == pygame.KEYDOWN:
                k = e.key
                if k == pygame.K_ESCAPE:
                    self.running = False
                elif k == pygame.K_r:
                    self.car.reset(self.car.x)
                elif k == pygame.K_t:
                    self.car.auto = not self.car.auto
                elif k == pygame.K_l:
                    self.car.toggle_diff_lock()
                elif k == pygame.K_g:
                    self.car.toggle_low()
                elif k == pygame.K_c:
                    self.carr.next_paint()
                elif k == pygame.K_h:
                    self.hud.show = not self.hud.show
                elif k == pygame.K_TAB:
                    self.hud.debug = not self.hud.debug
                elif k == pygame.K_m:
                    self.audio.toggle()
                elif k == pygame.K_LEFTBRACKET:
                    self.car.adjust_pressure(-0.05)
                elif k == pygame.K_RIGHTBRACKET:
                    self.car.adjust_pressure(0.05)
                elif k == pygame.K_e:
                    shift_up = True
                elif k == pygame.K_q:
                    shift_dn = True
                elif k == pygame.K_F11:
                    pygame.display.toggle_fullscreen()
        return shift_up, shift_dn

    def read_controls(self):
        k = pygame.key.get_pressed()
        up = 1.0 if (k[pygame.K_w] or k[pygame.K_UP]) else 0.0
        dn = 1.0 if (k[pygame.K_s] or k[pygame.K_DOWN]) else 0.0
        hand = 1.0 if k[pygame.K_SPACE] else 0.0
        lean = (1.0 if (k[pygame.K_LEFT] or k[pygame.K_a]) else 0.0) - (1.0 if (k[pygame.K_RIGHT] or k[pygame.K_d]) else 0.0)
        if self.autodrive:
            up, dn = self.auto_thr, 0.0
        return up, dn, hand, lean

    # ------------------------------------------------------------------ frame
    def update(self, dt):
        su, sd = self.handle_events()
        up, dn, hand, lean = self.read_controls()
        car = self.car
        car.control(dt, up, dn, hand, lean, su, sd)
        car.step(dt)
        self.time += dt
        self.pal = T.palette_at(car.x)
        self.scenery.update(dt)
        self.carr.update(car, dt)
        self.parts.wheel_fx(car, dt, self.pal, self.carr.exhaust_world(car))
        self.parts.update(dt)
        self.audio.update(car)
        self.hud.hint_t = max(0.0, self.hud.hint_t - dt) if self.time > 2 else self.hud.hint_t
        self.terrain.prune(car.x)

        # camera: look ahead along velocity, smooth + slow vertically
        v = self.view
        tx = car.x + clamp(car.vx * 0.45, -9, 9)
        ty = car.y + 1.4
        v.cx += (tx - v.cx) * (1 - math.exp(-dt * 3.2))
        v.cy += (ty - v.cy) * (1 - math.exp(-dt * 2.2))
        W, H = self.screen.get_size()
        if (W, H) != (v.W, v.H):
            v.W, v.H, v.s = W, H, H / VIEW_METERS
            self.chunks.set_scale(v.s)

    def draw(self):
        scr, v = self.screen, self.view
        pal = self.pal
        self.scenery.draw_sky(scr, pal)
        self.scenery.draw_clouds(scr, v.cx, v.cy, v.s)
        self.scenery.draw_mountains(scr, v.cx, v.cy, v.s, pal)
        self.scenery.draw_fog(scr, pal)

        W, H, s = v.W, v.H, v.s
        c0 = math.floor((v.cx - W / 2 / s) / T.CHUNK_W)
        c1 = math.floor((v.cx + W / 2 / s) / T.CHUNK_W)
        for ci in range(c0, c1 + 1):
            surf, X0, top, bottom = self.chunks.get(ci)
            dx = round((X0 - v.cx) * s + W / 2)
            dy = round(H * ANCHOR - (top - v.cy) * s)
            scr.blit(surf, (dx, dy))
            under = dy + surf.get_height() - 1
            if under < H:
                deep = rgb(T.palette_at(ci * T.CHUNK_W + T.CHUNK_W / 2)['deep'])
                scr.fill(deep, (dx, under, surf.get_width(), H - under))
        # build chunks ahead of travel in small slices so there are no hitches
        d = 1 if self.car.vx >= 0 else -1
        edge = c1 if d > 0 else c0
        self.chunks.prefetch([edge + d, edge + 2 * d, edge - d * (c1 - c0 + 1)], budget=0.005)
        self.chunks.prune((c0 + c1) // 2, keep=4)

        self.chunks.draw_soil(scr, v)
        self.parts.draw(scr, v)
        self.carr.draw(scr, v, self.car, self.terrain)
        self.scenery.draw_snow(scr, pal, v.cx, v.cy, v.s, self.car.vx)
        self.hud.draw(scr, self.car, self)

    def run(self):
        while self.running:
            dt = min(self.clock.tick(60) / 1000.0, 1 / 20)
            self.update(dt)
            self.draw()
            pygame.display.flip()
        pygame.quit()
