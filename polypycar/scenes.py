"""Menu scenes: main menu, settings, garage, map select, and the drive / pause scenes."""
import math
import random
import pygame

from . import ui, vehicles as V, worlds, terrain as T
from .ui import (text, panel, facet_box, button, Page, Button, Toggle, Choice, Slider, TextBox, KeyRow, Header,
                 Spacer, Note, ACCENT, ACCENT_DK, CYAN, TEXT, DIM, OK, WARN, EDGE, PANEL, PANEL_HI, BG)
from .util import clamp, mixc, shade, rgb, noise1, hash_i
from .session import Session, Controls, View
from .settings import ACTIONS, RESOLUTIONS, FPS_OPTIONS
from .terrain_render import draw_decor
from .hud_apps import Hud
from .audio import Audio
from .car import Car
from .car_render import CarRenderer


class Scene:
    overlay = False
    capturing = False      # True while the scene is waiting for a raw key (rebinding / text entry)

    def __init__(self, app):
        self.app = app

    def on_enter(self):
        pass

    def on_exit(self):
        pass

    def event(self, e):
        pass

    def update(self, dt):
        pass

    def draw(self, surf):
        pass

    @property
    def u(self):
        return self.app.u


# ====================================================================== backdrop (demo drive behind menus)
class Backdrop:
    def __init__(self, app):
        self.app = app
        st = app.settings
        last = st['last']
        self.session = Session(st, last['vehicle'], last['paint'], worlds.make('snowfield', 'easy', True), 11, start_x=30.0)
        c = self.session.car
        c.pressure, c.low = 0.7, True
        c.drive.set_all_locked(True)
        self.ctl = Controls()
        self.ctl.up = 0.5
        self.stuck = 0.0
        self.vehicle = last['vehicle']
        self.shade = None

    def update(self, dt):
        s = self.session
        v = s.view
        s.cam_offset = 0.2 * v.W / max(1.0, v.s)           # park the vehicle on the right, clear of the menu
        s.update(dt, self.ctl)
        if abs(s.car.vx) < 0.4:
            self.stuck += dt
            if self.stuck > 5.0:                 # dug in: hop ahead and carry on
                s.car.reset(s.car.x + 70)
                self.stuck = 0.0
        else:
            self.stuck = 0.0

    def draw(self, surf, dim=0.35):
        self.session.draw(surf)
        W, H = surf.get_size()
        if self.shade is None or self.shade.get_size() != (W, H):
            self.shade = pygame.Surface((W, H), pygame.SRCALPHA)
            for x in range(0, W, 8):                # darker on the left where the menu sits
                a = int(215 * max(0.0, 1.0 - x / (W * 0.62)) ** 1.3) + 25
                pygame.draw.rect(self.shade, (10, 14, 24, min(235, a)), (x, 0, 8, H))
        surf.blit(self.shade, (0, 0))


# ====================================================================== main menu
class MainMenu(Scene):
    def __init__(self, app):
        super().__init__(app)
        self.page = Page([
            Button('DRIVE', self.drive, accent=True, height=62, size=36),
            Button('Quick start (last setup)', self.quick, height=54),
            Button('Settings', lambda: app.push(SettingsScene(app)), height=54),
            Button('Quit', app.quit, height=54),
        ])
        self.t = 0.0

    def on_enter(self):
        last = self.app.settings['last']
        bd = self.app.backdrop
        if bd is None or bd.vehicle != last['vehicle']:
            self.app.backdrop = Backdrop(self.app)

    def drive(self):
        self.app.push(GarageScene(self.app))

    def quick(self):
        self.app.start_drive()

    def event(self, e):
        if e.type == pygame.KEYDOWN and e.key == pygame.K_ESCAPE:
            return
        self.page.event(e, self.u)

    def update(self, dt):
        self.t += dt

    def draw(self, surf):
        u = self.u
        W, H = surf.get_size()
        self.app.backdrop.draw(surf)
        # title with extruded facets
        tx, ty = 70 * u, 70 * u
        size = int(118 * u)
        for i in range(7, 0, -1):
            text(surf, 'POLYPYCAR', (tx + i * 2.2 * u, ty + i * 2.2 * u), size, rgb(ACCENT_DK, 0.55 + 0.06 * (7 - i)), shadow=False)
        text(surf, 'POLYPYCAR', (tx, ty), size, (255, 236, 190), shadow=False)
        text(surf, 'SNOW  &  MUD  OFFROAD', (tx + 6 * u, ty + 118 * u), int(34 * u), CYAN)
        self.page.draw(surf, (70 * u, 300 * u, 420 * u, H - 340 * u), u, pygame.mouse.get_pos())
        text(surf, 'v0.3', (W - 18 * u, H - 14 * u), int(20 * u), DIM, 'br', shadow=False)
        text(surf, 'Mouse or arrow keys + Enter', (70 * u, H - 30 * u), int(20 * u), DIM, 'bl', shadow=False)


# ====================================================================== settings
class SettingsScene(Scene):
    overlay = True
    TABS = ['Video', 'Audio', 'Gameplay', 'Interface', 'Controls']

    def __init__(self, app):
        super().__init__(app)
        self.tab = 0
        self.pages = {}
        self.tab_rects = []
        self.back_rect = None

    # ---- page builders
    def _build(self, name):
        st = self.app.settings
        app = self.app

        def setter(key, after=None):
            def f(v):
                st[key] = v
                if after:
                    after()
            return f

        def getter(key):
            return lambda: st[key]

        pct = '{:.0%}'
        if name == 'Video':
            desk = app.desktop
            res = [r for r in RESOLUTIONS if r[0] <= desk[0] and r[1] <= desk[1]]
            if tuple(desk) not in res:
                res.append(tuple(desk))
            cur = tuple(st['resolution'])
            if cur not in res:
                res.append(cur)
            res.sort()
            return Page([
                Header('Display'),
                Choice('Display mode', [('windowed', 'Windowed'), ('borderless', 'Borderless fullscreen'), ('fullscreen', 'Exclusive fullscreen')],
                       getter('display_mode'), setter('display_mode', app.apply_display)),
                Choice('Resolution', [(r, '%d x %d%s' % (r[0], r[1], '  (native)' if r == tuple(desk) else '')) for r in res],
                       lambda: tuple(st['resolution']), lambda v: (st.__setitem__('resolution', list(v)), app.apply_display())),
                Note('Borderless fullscreen always uses the desktop resolution; use render scale to go lighter.'),
                Choice('Render scale', [(s_, '%d%%' % round(s_ * 100)) for s_ in (0.5, 0.6, 0.7, 0.8, 0.9, 1.0)],
                       getter('render_scale'), setter('render_scale')),
                Choice('FPS limit', [(f, 'Unlimited' if f == 0 else '%d fps' % f) for f in FPS_OPTIONS], getter('fps_target'), setter('fps_target')),
                Toggle('Show FPS counter', getter('show_fps'), setter('show_fps')),
                Header('Graphics'),
                Choice('Quality preset', [('low', 'Low'), ('medium', 'Medium'), ('high', 'High')], getter('quality'), setter('quality')),
                Slider('Snowfall density', 0.0, 1.5, 0.05, getter('snow_density'), setter('snow_density'), pct),
                Slider('Particles', 0.0, 1.5, 0.05, getter('particles'), setter('particles'), pct),
                Toggle('Horizon fog', getter('fog'), setter('fog')),
                Toggle('Vehicle anti-aliasing', getter('car_aa'), setter('car_aa')),
                Note('Quality sets mountain layers, soil detail and snow amount. Vehicle AA applies on the next drive.'),
            ])
        if name == 'Audio':
            return Page([
                Header('Volume'),
                Slider('Master', 0.0, 1.0, 0.05, getter('master_volume'), setter('master_volume'), pct),
                Slider('Engine', 0.0, 1.0, 0.05, getter('engine_volume'), setter('engine_volume'), pct),
                Slider('Wind', 0.0, 1.0, 0.05, getter('wind_volume'), setter('wind_volume'), pct),
                Note('All sound is synthesised live from the vehicle you drive.'),
            ])
        if name == 'Gameplay':
            return Page([
                Header('Driving'),
                Choice('Units', [('kmh', 'km/h'), ('mph', 'mph')], getter('units'), setter('units')),
                Slider('Throttle build-up', 0.3, 4.0, 0.1, getter('throttle_ramp'), setter('throttle_ramp'), '{:.1f} / s'),
                Note('How quickly holding the gas builds power. Lower = easier to feather in soft ground.'),
                Toggle('Automatic gearbox by default', getter('auto_gearbox'), setter('auto_gearbox'), 'AUTO', 'MANUAL'),
                Slider('Default tyre pressure', 0.3, 1.4, 0.05, getter('default_pressure'), setter('default_pressure'), '{:.0%}'),
                Header('Camera'),
                Slider('Zoom (metres visible)', 14.0, 34.0, 1.0, getter('camera_zoom'), setter('camera_zoom'), '{:.0f} m'),
                Slider('Look-ahead', 0.0, 2.0, 0.1, getter('camera_lookahead'), setter('camera_lookahead'), '{:.1f}x'),
            ])
        if name == 'Interface':
            return Page([
                Header('Scale'),
                Slider('Menu scale', 0.8, 1.4, 0.05, getter('ui_scale'), setter('ui_scale'), pct),
                Slider('HUD scale', 0.7, 1.5, 0.05, getter('hud_scale'), setter('hud_scale'), pct),
                Header('HUD'),
                Toggle('Gauge cluster', getter('hud_gauge'), setter('hud_gauge')),
                Toggle('Control hints at start', getter('hud_hints'), setter('hud_hints')),
                Toggle('Transmission app open by default', getter('app_trans_open'), setter('app_trans_open')),
            ])
        # Controls
        rows = [Note('Click a slot, then press a key.  Backspace clears, Esc cancels.  A key already in use is swapped.')]
        group = None
        for aid, label, grp, _ in ACTIONS:
            if grp != group:
                group = grp
                rows.append(Header(grp))
            rows.append(KeyRow(aid, label, st))
        rows += [Spacer(10), Button('Reset all key bindings', lambda: (st.reset_binds(), self.pages.pop('Controls', None)), height=50)]
        return Page(rows)

    @property
    def capturing(self):
        pg = self.page()
        cur = pg.widgets[pg.focus] if pg.widgets else None
        return (isinstance(cur, KeyRow) and cur.waiting is not None) or (isinstance(cur, TextBox) and cur.editing)

    def page(self):
        name = self.TABS[self.tab]
        if name not in self.pages:
            self.pages[name] = self._build(name)
        return self.pages[name]

    # ---- scene
    def on_exit(self):
        self.app.settings.save()

    def back(self):
        self.app.pop()

    def event(self, e):
        u = self.u
        pg = self.page()
        cur = pg.widgets[pg.focus] if pg.widgets else None
        busy = (isinstance(cur, KeyRow) and cur.waiting is not None) or (isinstance(cur, TextBox) and cur.editing)
        if e.type == pygame.KEYDOWN and not busy:
            if e.key == pygame.K_ESCAPE:
                self.back()
                return
            if e.key in (pygame.K_PAGEUP, pygame.K_q):
                self.tab = (self.tab - 1) % len(self.TABS)
                return
            if e.key in (pygame.K_PAGEDOWN, pygame.K_e):
                self.tab = (self.tab + 1) % len(self.TABS)
                return
        if e.type == pygame.MOUSEBUTTONDOWN and e.button == 1:
            for i, r in enumerate(self.tab_rects):
                if r.collidepoint(e.pos):
                    self.tab = i
                    return
            if self.back_rect and self.back_rect.collidepoint(e.pos):
                self.back()
                return
        pg.event(e, u)

    def draw(self, surf):
        u = self.u
        W, H = surf.get_size()
        mouse = pygame.mouse.get_pos()
        veil = pygame.Surface((W, H), pygame.SRCALPHA)
        veil.fill((10, 14, 24, 175))
        surf.blit(veil, (0, 0))
        pw = min(W - 60 * u, 940 * u)
        px = (W - pw) / 2
        panel(surf, (px, 28 * u, pw, H - 56 * u), u)
        text(surf, 'SETTINGS', (px + 24 * u, 44 * u), int(44 * u), ACCENT)
        self.tab_rects = []
        tx = px + 24 * u
        for i, name in enumerate(self.TABS):
            w_ = 120 * u if name != 'Interface' else 128 * u
            r = pygame.Rect(tx, 100 * u, w_, 40 * u)
            self.tab_rects.append(r)
            button(surf, (r.x, r.y, r.w, r.h), name, u, r.collidepoint(mouse), False, active=(i == self.tab), size=24)
            tx += w_ + 8 * u
        self.back_rect = pygame.Rect(px + pw - 150 * u, 100 * u, 126 * u, 40 * u)
        button(surf, tuple(self.back_rect), 'Back', u, self.back_rect.collidepoint(mouse), False, accent=True, size=24)
        self.page().draw(surf, (px + 24 * u, 152 * u, pw - 52 * u, H - 56 * u - 152 * u - 28 * u), u, mouse)
        text(surf, 'Q / E or PgUp / PgDn: switch tab     Esc: back     changes are saved automatically', (px + 24 * u, H - 54 * u), int(20 * u), DIM, 'tl', shadow=False)


# ====================================================================== garage
class FlatRock(T.Terrain):
    """Hard flat floor for the garage preview."""

    def raw_height(self, x):
        return 0.0

    def raw_mat(self, x):
        return T.ROCK

    def raw_floor(self, x, m, h0):
        return h0


class Rig:
    """A vehicle sitting on the garage floor, bobbing on its suspension."""

    def __init__(self, spec, paint, ss=3):
        self.spec = spec
        self.terrain = FlatRock(1)
        self.car = Car(self.terrain, spec)
        self.car.reset(0.0)
        for _ in range(180):
            self.car.control(1 / 60, 0, 0, 0, 0)
            self.car.step(1 / 60)
        self.rend = CarRenderer(spec, ss)
        self.rend.paint = paint % len(spec.paints)
        self.t = 0.0
        self.next_bump = 1.0

    def update(self, dt):
        self.t += dt
        c = self.car
        c.control(dt, 0, 0, 0, 0)
        c.throttle = 0.12 + 0.06 * math.sin(self.t * 3.1)      # idle blip so the exhaust ticks over
        c.step(dt)
        c.brake_out = 1.0                                       # hold it in place
        c.vx *= 0.9
        c.x *= 0.995
        self.rend.update(c, dt)
        if self.t > self.next_bump:                              # small hop to show off the springs
            c.vy -= 0.9
            self.next_bump = self.t + 3.6


class GarageScene(Scene):
    def __init__(self, app, change_only=False):
        super().__init__(app)
        st = app.settings
        self.idx = max(0, next((i for i, v in enumerate(V.VEHICLES) if v.id == st['last']['vehicle']), 0))
        self.paint = st['last']['paint']
        self.rigs = {}
        self.hover_graph = None
        self.hits = []
        self.stat_cache = {v.id: V.stats(v) for v in V.VEHICLES}
        self.maxes = {k: max(s[k] for s in self.stat_cache.values()) for k in ('hp', 'tq', 'mass', 'top_kmh', 'flotation', 'travel')}
        self.page = Page([Button('CONTINUE  ->  Choose map', self.cont, accent=True, height=54), Button('Back', app.pop, height=46)])
        self.t = 0.0

    @property
    def spec(self):
        return V.VEHICLES[self.idx]

    def rig(self):
        sp = self.spec
        r = self.rigs.get(sp.id)
        if r is None:
            r = self.rigs[sp.id] = Rig(sp, self.paint, self.app.settings.q['car_ss'])
        r.rend.paint = self.paint % len(sp.paints)
        return r

    def save(self):
        last = self.app.settings['last']
        last['vehicle'] = self.spec.id
        last['paint'] = self.paint % len(self.spec.paints)

    def cont(self):
        self.save()
        self.app.push(MapScene(self.app))

    def change(self, d):
        self.idx = (self.idx + d) % len(V.VEHICLES)
        self.paint = min(self.paint, len(self.spec.paints) - 1)

    def event(self, e):
        u = self.u
        if e.type == pygame.KEYDOWN:
            if e.key == pygame.K_ESCAPE:
                self.app.pop()
                return
            if e.key == pygame.K_LEFT:
                self.change(-1)
                return
            if e.key == pygame.K_RIGHT:
                self.change(1)
                return
            if e.key in self.app.settings.keys('paint') or e.key == pygame.K_c:
                self.paint = (self.paint + 1) % len(self.spec.paints)
                return
        if e.type == pygame.MOUSEBUTTONDOWN and e.button == 1:
            for r, fn in self.hits:
                if r.collidepoint(e.pos):
                    fn()
                    return
        self.page.event(e, u)

    def update(self, dt):
        self.t += dt
        self.rig().update(dt)

    def _bar(self, surf, x, y, w, label, value, text_, frac, u, col=ACCENT):
        text(surf, label, (x, y), int(21 * u), DIM, 'tl', shadow=False)
        text(surf, text_, (x + w, y), int(21 * u), TEXT, 'tr', shadow=False)
        by = y + 22 * u
        pygame.draw.polygon(surf, (24, 30, 42), [(x, by), (x + w, by), (x + w - 3 * u, by + 9 * u), (x + 3 * u, by + 9 * u)])
        fw = max(6 * u, w * clamp(frac, 0.02, 1.0))
        pygame.draw.polygon(surf, col, [(x, by), (x + fw, by), (x + fw - 3 * u, by + 9 * u), (x + 3 * u, by + 9 * u)])

    def draw(self, surf):
        u = self.u
        W, H = surf.get_size()
        mouse = pygame.mouse.get_pos()
        sp = self.spec
        stt = self.stat_cache[sp.id]
        # --- garage backdrop: dusk gradient, floor, spot
        for i in range(24):
            f = i / 23
            pygame.draw.rect(surf, rgb(mixc((26, 34, 52), (62, 74, 98), f)), (0, i * H / 24, W, H / 24 + 2))
        floor_y = H * 0.72
        pygame.draw.polygon(surf, (28, 34, 46), [(0, floor_y), (W, floor_y), (W, H), (0, H)])
        pygame.draw.polygon(surf, (38, 46, 62), [(0, floor_y), (W, floor_y), (W, floor_y + 10 * u), (0, floor_y + 10 * u)])
        for k in range(-8, 12):
            pygame.draw.line(surf, (36, 44, 60), (W * 0.3 + k * 70 * u, floor_y + 10 * u), (W * 0.3 + k * 190 * u, H), max(1, int(2 * u)))
        text(surf, 'GARAGE', (36 * u, 24 * u), int(46 * u), ACCENT)
        text(surf, 'Choose your vehicle - the graph shows the exact engine curve the game simulates', (36 * u, 70 * u), int(22 * u), DIM, shadow=False)

        # --- preview area (left)
        pw = W * 0.52
        prev = pygame.Rect(36 * u, 100 * u, pw, H - 232 * u)
        # podium spot
        cx = prev.centerx
        pygame.draw.polygon(surf, (52, 62, 84), [(cx - prev.w * 0.46, floor_y + 4 * u), (cx + prev.w * 0.46, floor_y + 4 * u), (cx + prev.w * 0.4, floor_y + 26 * u), (cx - prev.w * 0.4, floor_y + 26 * u)])
        pygame.draw.polygon(surf, (70, 82, 108), [(cx - prev.w * 0.46, floor_y + 4 * u), (cx + prev.w * 0.46, floor_y + 4 * u), (cx + prev.w * 0.46 - 6 * u, floor_y + 9 * u), (cx - prev.w * 0.46 + 6 * u, floor_y + 9 * u)])
        rig = self.rig()
        bw = sp.art_box[0]
        sc = prev.w * 0.9 / bw
        sc = min(sc, (floor_y - prev.y - 70 * u) / (sp.art_box[1] * 0.8))
        car = rig.car
        view = View(W, H, sc)
        ground_y = floor_y + 4 * u
        view.cx = car.x - (prev.centerx - W / 2) / sc          # centre the vehicle in the preview area
        view.cy = (ground_y - H * 0.58) / sc                     # world y=0 sits on the podium
        rig.rend.draw(surf, view, car, rig.terrain)
        # name + switcher
        text(surf, sp.name, (prev.centerx, floor_y + 52 * u), int(46 * u), TEXT, 'c')
        text(surf, sp.tagline, (prev.centerx, floor_y + 86 * u), int(24 * u), CYAN, 'c', maxw=prev.w)
        self.hits = []
        for sgn, bx in ((-1, prev.x + 4 * u), (1, prev.right - 64 * u)):
            r = pygame.Rect(bx, floor_y + 32 * u, 60 * u, 60 * u)
            button(surf, tuple(r), '<' if sgn < 0 else '>', u, r.collidepoint(mouse), False, size=40)
            self.hits.append((r, (lambda d=sgn: self.change(d))))
        # dots
        for i in range(len(V.VEHICLES)):
            pygame.draw.polygon(surf, ACCENT if i == self.idx else EDGE, [(cx - 30 * u + i * 30 * u + math.cos(a * math.tau / 6) * 6 * u, floor_y + 110 * u + math.sin(a * math.tau / 6) * 6 * u) for a in range(6)])
        # paint swatches
        sx = prev.x + 10 * u
        text(surf, 'PAINT', (sx, prev.y + 6 * u), int(20 * u), DIM, shadow=False)
        for i, col in enumerate(sp.paints):
            r = pygame.Rect(sx + i * 42 * u, prev.y + 30 * u, 34 * u, 34 * u)
            facet_box(surf, tuple(r), col, cut=6 * u, edge=ACCENT if i == self.paint % len(sp.paints) else EDGE)
            self.hits.append((r, (lambda k=i: setattr(self, 'paint', k))))

        # --- stats (right)
        rx = prev.right + 36 * u
        rw = W - rx - 30 * u
        panel(surf, (rx - 14 * u, 20 * u, rw + 28 * u, H - 40 * u), u)
        text(surf, sp.kind.upper(), (rx, 34 * u), int(22 * u), ACCENT, shadow=False)
        y = 62 * u
        for ln in ui.wrap(sp.description, int(21 * u), rw):
            text(surf, ln, (rx, y), int(21 * u), TEXT, shadow=False)
            y += 22 * u
        y += 8 * u
        bw2 = (rw - 16 * u) / 2
        mx = self.maxes
        items = [
            ('Power', stt['hp'], '%d hp @ %d' % (stt['hp'], stt['hp_rpm']), stt['hp'] / mx['hp'], ACCENT),
            ('Torque', stt['tq'], '%d Nm @ %d' % (stt['tq'], stt['tq_rpm']), stt['tq'] / mx['tq'], ACCENT),
            ('Weight', stt['mass'], '%.1f t' % (stt['mass'] / 1000), stt['mass'] / mx['mass'], (150, 170, 200)),
            ('Top speed', stt['top_kmh'], '%d km/h' % stt['top_kmh'], stt['top_kmh'] / mx['top_kmh'], CYAN),
            ('Crawl speed', stt['crawl_kmh'], '%.1f km/h' % stt['crawl_kmh'], 1.0 - min(1.0, stt['crawl_kmh'] / 3.6) * 0.9, CYAN),
            ('Flotation', stt['flotation'], '%.2f' % stt['flotation'], stt['flotation'] / mx['flotation'] * 0.9, OK),
        ]
        for i, (lab, val, txt, fr, col) in enumerate(items):
            cx_ = rx + (i % 2) * (bw2 + 16 * u)
            cy_ = y + (i // 2) * 52 * u
            self._bar(surf, cx_, cy_, bw2, lab, val, txt, fr, u, col)
        y += 3 * 52 * u + 4 * u
        text(surf, '%s   -   %d axles   -   %.0f cm tyres   -   %.0f cm travel   -   %s' % (stt['drive'], stt['axles'], stt['wheel_d'] * 100, stt['travel'] * 100, sp.tires),
             (rx, y), int(20 * u), DIM, shadow=False, maxw=rw)
        y += 28 * u
        e = sp.engine
        text(surf, 'ENGINE  -  %s' % e.config, (rx, y), int(24 * u), ACCENT, shadow=False, maxw=rw * 0.62)
        text(surf, 'idle %d  /  redline %d rpm' % (e.idle, e.redline), (rx + rw, y + 3 * u), int(20 * u), DIM, 'tr', shadow=False)
        y += 28 * u
        gh = 222 * u
        g = pygame.Rect(rx, y, rw, gh)
        hover = mouse[0] if g.collidepoint(mouse) else None
        ui.draw_engine_graph(surf, tuple(g), e, u, hover_x=hover)
        self.page.draw(surf, (rx, H - 148 * u, rw, 126 * u), u, mouse)


# ====================================================================== map select
def draw_map_preview(surf, rect, bid, u, t=0.0, ground_col=None):
    b = T.BIOMES[bid]
    x, y, w, h = rect
    clip = surf.get_clip()
    surf.set_clip(rect)
    for i in range(14):
        f = i / 13
        pygame.draw.rect(surf, rgb(mixc(b['sky0'], b['sky1'], f)), (x, y + h * i / 14, w, h / 14 + 2))
    gy = y + h * 0.66
    for li, (amp, col_f, wl, seed) in enumerate(((0.34, 0.55, 40, 3), (0.2, 0.3, 24, 7))):
        pts = [(x - 4, gy)]
        for k in range(0, int(w / 8) + 2):
            px = x + k * 8
            hh = amp * h * (0.55 + 0.45 * (1 - abs(noise1(px / (wl * u * 0.6) + seed, seed))))
            pts.append((px, gy - hh))
        pts.append((x + w + 4, gy))
        pygame.draw.polygon(surf, rgb(mixc(b['mtn'], b['sky1'], col_f)), pts)
    snowy = bid in (worlds.TAIGA, worlds.WHITEOUT)
    top = b['snow'] if snowy else (mixc(b['dirt'], (58, 42, 32), 0.7) if bid == worlds.MUDLANDS else b['top'])
    pygame.draw.polygon(surf, rgb(b['dirt'], 0.85), [(x, gy + 5 * u), (x + w, gy + 5 * u), (x + w, y + h), (x, y + h)])
    pygame.draw.polygon(surf, rgb(b['deep']), [(x, gy + h * 0.2), (x + w, gy + h * 0.16), (x + w, y + h), (x, y + h)])
    pygame.draw.polygon(surf, rgb(top), [(x, gy), (x + w, gy), (x + w, gy + 8 * u), (x, gy + 9 * u)])
    pm = h / 6.5

    def P(wx, wy):
        return (x + w * 0.5 + wx * pm, gy + 4 * u - wy * pm)

    kinds = b['decor']
    for k, wx in enumerate((-2.2, -0.9, 1.4, 2.3)):
        draw_decor(surf, P, kinds[k % len(kinds)], wx, 0.0, 0.8 + 0.25 * (k % 2), b, k + 50 + bid)
    if bid in (worlds.TAIGA, worlds.WHITEOUT):
        for i in range(34):
            fx = (hash_i(i, 5) * w + t * 20 * (0.5 + hash_i(i, 6))) % w
            fy = (hash_i(i, 7) * h + t * 40 * (0.5 + hash_i(i, 8))) % h
            pygame.draw.rect(surf, (255, 255, 255), (x + fx, y + fy, 2 * u + 1, 2 * u + 1))
    surf.set_clip(clip)


class MapScene(Scene):
    def __init__(self, app):
        super().__init__(app)
        st = app.settings
        last = st['last']
        self.idx = next((i for i, m in enumerate(worlds.MAPS) if m.id == last['map']), 0)
        self.t = 0.0
        self.card_rects = []

        def get_diff():
            return st['last']['difficulty']

        def set_diff(v):
            st['last']['difficulty'] = v

        self.page = Page([
            Choice('Difficulty', [(d.id, d.name) for d in worlds.DIFFICULTIES], get_diff, set_diff),
            TextBox('World seed', lambda: st['last']['seed'], lambda v: st['last'].__setitem__('seed', v), hint='random every time'),
            Toggle('Snowfall', lambda: st['last']['snowfall'], lambda v: st['last'].__setitem__('snowfall', v)),
            Spacer(8),
            Button('START DRIVING', self.start, accent=True, height=58, size=32),
            Button('Back', app.pop, height=46),
        ])
        self.page.focus = 4

    @property
    def capturing(self):
        cur = self.page.widgets[self.page.focus]
        return isinstance(cur, TextBox) and cur.editing

    def start(self):
        self.save()
        self.app.start_drive()

    def save(self):
        self.app.settings['last']['map'] = worlds.MAPS[self.idx].id

    def event(self, e):
        u = self.u
        cur = self.page.widgets[self.page.focus]
        editing = isinstance(cur, TextBox) and cur.editing
        if e.type == pygame.KEYDOWN and not editing:
            if e.key == pygame.K_ESCAPE:
                self.app.pop()
                return
            if e.key == pygame.K_LEFT and not isinstance(cur, (Choice, Slider)):
                self.idx = (self.idx - 1) % len(worlds.MAPS)
                return
            if e.key == pygame.K_RIGHT and not isinstance(cur, (Choice, Slider)):
                self.idx = (self.idx + 1) % len(worlds.MAPS)
                return
        if e.type == pygame.MOUSEBUTTONDOWN and e.button == 1:
            for i, r in enumerate(self.card_rects):
                if r.collidepoint(e.pos):
                    self.idx = i
                    return
        self.page.event(e, u)

    def update(self, dt):
        self.t += dt

    def draw(self, surf):
        u = self.u
        W, H = surf.get_size()
        mouse = pygame.mouse.get_pos()
        for i in range(24):
            pygame.draw.rect(surf, rgb(mixc((26, 34, 52), (46, 58, 82), i / 23)), (0, i * H / 24, W, H / 24 + 2))
        text(surf, 'CHOOSE A MAP', (36 * u, 24 * u), int(46 * u), ACCENT)
        text(surf, 'Same truck, very different day', (36 * u, 70 * u), int(22 * u), DIM, shadow=False)
        n = len(worlds.MAPS)
        gap = 14 * u
        cw = (W - 72 * u - gap * (n - 1)) / n
        ch = cw * 1.12
        y = 104 * u
        self.card_rects = []
        for i, m in enumerate(worlds.MAPS):
            x = 36 * u + i * (cw + gap)
            r = pygame.Rect(x, y, cw, ch)
            self.card_rects.append(r)
            sel = i == self.idx
            hov = r.collidepoint(mouse)
            facet_box(surf, tuple(r), PANEL_HI if sel else PANEL, cut=10 * u, edge=ACCENT if sel else (EDGE if not hov else CYAN))
            prev = pygame.Rect(r.x + 8 * u, r.y + 8 * u, r.w - 16 * u, r.h * 0.62)
            draw_map_preview(surf, tuple(prev), m.preview, u, self.t)
            pygame.draw.rect(surf, ACCENT if sel else EDGE, prev, max(1, int(2 * u)))
            text(surf, m.name, (r.centerx, prev.bottom + 22 * u), int(28 * u), TEXT if sel else (200, 208, 224), 'c', maxw=r.w - 12 * u)
            text(surf, m.tagline, (r.centerx, prev.bottom + 46 * u), int(19 * u), CYAN if sel else DIM, 'c', shadow=False, maxw=r.w - 12 * u)
        m = worlds.MAPS[self.idx]
        d = worlds.DIFF_BY_ID[self.app.settings['last']['difficulty']]
        y2 = y + ch + 18 * u
        lines = ui.wrap(m.description, int(23 * u), W * 0.5)
        for k, ln in enumerate(lines):
            text(surf, ln, (36 * u, y2 + k * 25 * u), int(23 * u), TEXT, shadow=False)
        text(surf, '%s: %s' % (d.name, d.description), (36 * u, y2 + (len(lines) + 0.4) * 25 * u), int(21 * u), ACCENT, shadow=False)
        biomes = ', '.join(T.BIOMES[b]['name'] for b in m.biomes)
        text(surf, 'Terrain: %s' % biomes, (36 * u, y2 + (len(lines) + 1.5) * 25 * u), int(21 * u), DIM, shadow=False)
        self.page.draw(surf, (W - 560 * u, y2 - 6 * u, 524 * u, H - y2 - 12 * u), u, mouse)
        text(surf, 'Left / Right: pick map     Esc: back', (36 * u, H - 24 * u), int(20 * u), DIM, 'bl', shadow=False)


# ====================================================================== driving
class DriveScene(Scene):
    def __init__(self, app, cfg):
        super().__init__(app)
        st = app.settings
        self.cfg = dict(cfg)
        seed = cfg['seed'] or random.randrange(1, 10 ** 6)
        self.seed = seed
        world = worlds.make(cfg['map'], cfg['difficulty'], cfg['snowfall'])
        self.session = Session(st, cfg['vehicle'], cfg['paint'], world, seed, start_x=0.0)
        self.hud = Hud(st)
        self.audio = Audio(st, self.session.spec)
        self.ctl = Controls()
        self.fps = 60.0
        self.world_surf = None
        self.toast_t = 0.0

    def on_enter(self):
        self.session.apply_settings()
        self.session.car.throttle_ramp = self.app.settings['throttle_ramp']
        self.session.carr.ss = self.app.settings.q['car_ss'] if self.app.settings['car_aa'] else 1

    def on_exit(self):
        self.audio.stop()
        pygame.mouse.set_visible(True)

    def on_resume(self):
        self.on_enter()

    # ---- input
    def event(self, e):
        st = self.app.settings
        car = self.session.car
        if e.type == pygame.KEYDOWN:
            a = st.action_for_key(e.key)
            # an action bound to several actions? first match wins
            if a == 'pause':
                self.app.push(PauseScene(self.app, self))
            elif a == 'reset':
                self.session.respawn()
            elif a == 'toggle_auto':
                car.auto = not car.auto
            elif a == 'toggle_low':
                car.toggle_low()
            elif a == 'toggle_lock':
                car.toggle_diff_lock()
            elif a == 'shift_up':
                self.ctl.shift_up = True
            elif a == 'shift_down':
                self.ctl.shift_dn = True
            elif a == 'press_down':
                car.adjust_pressure(-0.05)
            elif a == 'press_up':
                car.adjust_pressure(0.05)
            elif a == 'paint':
                self.session.carr.next_paint()
            elif a == 'app_trans':
                self.hud.toggle('trans')
            elif a == 'app_telem':
                self.hud.toggle('telem')
            elif a == 'toggle_hud':
                self.hud.show = not self.hud.show
            elif a == 'zoom_in':
                st['camera_zoom'] = clamp(st['camera_zoom'] - 2, 14, 34)
            elif a == 'zoom_out':
                st['camera_zoom'] = clamp(st['camera_zoom'] + 2, 14, 34)
            elif a == 'mute':
                self.audio.toggle()
        self.hud.event(e, car, self.session)

    def update(self, dt):
        st = self.app.settings
        pressed = pygame.key.get_pressed()
        c = self.ctl
        c.up = 1.0 if st.held('throttle', pressed) else 0.0
        c.dn = 1.0 if st.held('brake', pressed) else 0.0
        c.hand = 1.0 if st.held('handbrake', pressed) else 0.0
        c.lean = (1.0 if st.held('lean_back', pressed) else 0.0) - (1.0 if st.held('lean_fwd', pressed) else 0.0)
        # keep the vehicle clear of an open app panel
        v = self.session.view
        want = -0.2 * v.W / max(1.0, v.s) if (self.hud.show and (self.hud.open['trans'] or self.hud.open['telem'])) else 0.0
        self.session.cam_offset += (want - self.session.cam_offset) * (1 - math.exp(-4.0 * dt))
        self.session.update(dt, c)
        c.shift_up = c.shift_dn = False
        self.hud.update(dt)
        self.fps = self.app.fps
        pal = self.session.pal
        snow = pal['snowfall'] if self.session.world_cfg.snowfall else 0.0
        self.audio.update(self.session.car, snow)
        pygame.mouse.set_visible(self.hud.wants_cursor)

    def draw(self, surf):
        st = self.app.settings
        W, H = surf.get_size()
        rs = st['render_scale']
        if rs < 0.99:
            sz = (max(320, int(W * rs)), max(180, int(H * rs)))
            if self.world_surf is None or self.world_surf.get_size() != sz:
                self.world_surf = pygame.Surface(sz)
            self.session.draw(self.world_surf)
            pygame.transform.scale(self.world_surf, (W, H), surf)
        else:
            self.session.draw(surf)
        self.hud.draw(surf, self)


class PauseScene(Scene):
    overlay = True

    def __init__(self, app, drive):
        super().__init__(app)
        self.drive = drive
        a = app
        self.page = Page([
            Button('Resume', a.pop, accent=True, height=56),
            Button('Settings', lambda: a.push(SettingsScene(a)), height=50),
            Button('Restart run  (new seed)', self.restart, height=50),
            Button('Garage / change vehicle', lambda: a.goto(GarageScene(a)), height=50),
            Button('Main menu', lambda: a.goto(None), height=50),
            Button('Quit game', a.quit, height=50),
        ])

    def on_enter(self):
        self.drive.audio.stop()
        pygame.mouse.set_visible(True)

    def restart(self):
        cfg = dict(self.drive.cfg)
        cfg['seed'] = 0
        self.app.start_drive(cfg)

    def event(self, e):
        if e.type == pygame.KEYDOWN and e.key in self.app.settings.keys('pause'):
            self.app.pop()
            return
        self.page.event(e, self.u)

    def draw(self, surf):
        u = self.u
        W, H = surf.get_size()
        veil = pygame.Surface((W, H), pygame.SRCALPHA)
        veil.fill((8, 12, 20, 170))
        surf.blit(veil, (0, 0))
        pw, ph = 480 * u, 480 * u
        panel(surf, ((W - pw) / 2, (H - ph) / 2, pw, ph), u)
        text(surf, 'PAUSED', (W / 2, (H - ph) / 2 + 38 * u), int(46 * u), ACCENT, 'c')
        d = self.drive
        text(surf, '%s  -  %s  -  seed %d' % (d.session.spec.name, worlds.MAP_BY_ID[d.cfg['map']].name, d.seed), (W / 2, (H - ph) / 2 + 74 * u), int(20 * u), DIM, 'c', shadow=False, maxw=pw - 20 * u)
        self.page.draw(surf, ((W - pw) / 2 + 40 * u, (H - ph) / 2 + 96 * u, pw - 80 * u, ph - 110 * u), u, pygame.mouse.get_pos())
