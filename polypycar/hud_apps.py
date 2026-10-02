"""In-game HUD: gauge cluster plus clickable 'apps' (transmission schematic, telemetry) on a dock."""
import math
import pygame
from . import ui
from .ui import text, panel, button, facet_box, ACCENT, CYAN, TEXT, DIM, OK, WARN, EDGE, PANEL, PANEL_HI
from .util import clamp, mixc, rgb
from . import terrain as T
from .drivetrain import MODE_NAMES, MODE_HELP, OPEN, LSD, LOCK

LINE_DIM = (84, 96, 120)


def _gear_poly(cx, cy, r, teeth=8, rot=0.0):
    pts = []
    for i in range(teeth * 2):
        a = rot + i * math.pi / teeth
        rr = r if i % 2 == 0 else r * 0.74
        pts.append((cx + math.cos(a) * rr, cy + math.sin(a) * rr))
        pts.append((cx + math.cos(a + math.pi / (teeth * 2)) * rr, cy + math.sin(a + math.pi / (teeth * 2)) * rr))
    return pts


class TransmissionApp:
    """Schematic driveline. Everything in it is a button wired to the live Drivetrain."""

    def __init__(self):
        self.hits = []          # (pygame.Rect, callback, tooltip)
        self.rect = pygame.Rect(0, 0, 0, 0)
        self.tip = ''

    # layout helpers -------------------------------------------------------
    @staticmethod
    def _depth(node):
        if isinstance(node, int):
            return 0
        return 1 + max(TransmissionApp._depth(c) for c in node[1:])

    def size(self, car, u):
        levels = self._depth(car.drive.tree)
        return int(660 * u), int((46 + 112 + 8 + 92 + 44 + levels * 70) * u)

    def _hit(self, rect, fn, tip=''):
        r = pygame.Rect(rect)
        self.hits.append((r, fn, tip))
        return r

    def click(self, pos):
        for r, fn, _ in reversed(self.hits):
            if r.collidepoint(pos) and fn:
                fn()
                return True
        return self.rect.collidepoint(pos)

    # drawing --------------------------------------------------------------
    def draw(self, surf, car, u, origin, mouse):
        w, h = self.size(car, u)
        x0, y0 = origin[0] - w, origin[1] - h
        self.rect = pygame.Rect(x0, y0, w, h)
        self.hits = []
        dr = car.drive
        panel(surf, (x0, y0, w, h), u, None)
        text(surf, 'TRANSMISSION', (x0 + 16 * u, y0 + 10 * u), int(26 * u), ACCENT)
        text(surf, '%s  -  %s%s' % (dr.drive_name(), 'LOW range' if dr.low else 'HIGH range', '  -  all diffs locked' if dr.all_locked else ''),
             (x0 + 190 * u, y0 + 14 * u), int(22 * u), DIM, shadow=False)
        self._hit((x0 + w - 36 * u, y0 + 8 * u, 28 * u, 28 * u), lambda: setattr(self, 'closed', True), 'Close')
        text(surf, 'x', (x0 + w - 22 * u, y0 + 22 * u), int(28 * u), DIM, 'c')

        # ---- top row: engine -> clutch -> gearbox -> transfer case
        ty = y0 + 46 * u
        eng = car.engine
        e_rect = (x0 + 14 * u, ty, 150 * u, 84 * u)
        facet_box(surf, e_rect, (58, 66, 88), cut=8 * u, edge=EDGE)
        # little engine block with pistons that jump with rpm
        for i in range(4):
            ph = math.sin(pygame.time.get_ticks() * 0.001 * car.rpm / 60 * math.tau * 0.5 + i * 1.57) * 0.5 + 0.5
            px = e_rect[0] + 12 * u + i * 16 * u
            pygame.draw.polygon(surf, (150, 158, 176), [(px, e_rect[1] + 8 * u + ph * 6 * u), (px + 11 * u, e_rect[1] + 8 * u + ph * 6 * u),
                                                        (px + 11 * u, e_rect[1] + 22 * u + ph * 6 * u), (px, e_rect[1] + 22 * u + ph * 6 * u)])
        text(surf, 'ENGINE', (e_rect[0] + e_rect[2] - 10 * u, e_rect[1] + 14 * u), int(19 * u), DIM, 'mr', shadow=False)
        text(surf, '%d rpm' % round(car.rpm), (e_rect[0] + 10 * u, e_rect[1] + 42 * u), int(24 * u), TEXT, 'ml')
        tq = max(0.0, car.Te)
        text(surf, '%d Nm  %d hp' % (round(tq), round(tq * car.rpm / 7127)), (e_rect[0] + 10 * u, e_rect[1] + 64 * u), int(20 * u), ACCENT, 'ml', shadow=False)
        thr_w = (e_rect[2] - 20 * u) * car.throttle
        pygame.draw.polygon(surf, (24, 30, 42), [(e_rect[0] + 10 * u, e_rect[1] + 76 * u), (e_rect[0] + e_rect[2] - 10 * u, e_rect[1] + 76 * u),
                                                 (e_rect[0] + e_rect[2] - 10 * u, e_rect[1] + 81 * u), (e_rect[0] + 10 * u, e_rect[1] + 81 * u)])
        pygame.draw.polygon(surf, ACCENT, [(e_rect[0] + 10 * u, e_rect[1] + 76 * u), (e_rect[0] + 10 * u + thr_w, e_rect[1] + 76 * u),
                                           (e_rect[0] + 10 * u + thr_w, e_rect[1] + 81 * u), (e_rect[0] + 10 * u, e_rect[1] + 81 * u)])
        cx_ = e_rect[0] + e_rect[2] + 8 * u
        c_rect = (cx_ + 14 * u, ty + 12 * u, 66 * u, 60 * u)
        self._arrow(surf, (cx_, ty + 42 * u), (c_rect[0], ty + 42 * u), u, 1.0, car)
        facet_box(surf, c_rect, (58, 66, 88), cut=7 * u, edge=EDGE)
        text(surf, 'CLUTCH', (c_rect[0] + c_rect[2] / 2, c_rect[1] + 12 * u), int(17 * u), DIM, 'c', shadow=False)
        eg = clamp(car.engage, 0, 1)
        pygame.draw.polygon(surf, (24, 30, 42), [(c_rect[0] + 8 * u, c_rect[1] + 24 * u), (c_rect[0] + c_rect[2] - 8 * u, c_rect[1] + 24 * u),
                                                 (c_rect[0] + c_rect[2] - 8 * u, c_rect[1] + 34 * u), (c_rect[0] + 8 * u, c_rect[1] + 34 * u)])
        pygame.draw.polygon(surf, OK if car.locked else ACCENT, [(c_rect[0] + 8 * u, c_rect[1] + 24 * u), (c_rect[0] + 8 * u + (c_rect[2] - 16 * u) * eg, c_rect[1] + 24 * u),
                                                                 (c_rect[0] + 8 * u + (c_rect[2] - 16 * u) * eg, c_rect[1] + 34 * u), (c_rect[0] + 8 * u, c_rect[1] + 34 * u)])
        text(surf, 'LOCKED' if car.locked else ('open' if eg < 0.1 else 'slip'), (c_rect[0] + c_rect[2] / 2, c_rect[1] + 47 * u), int(19 * u), OK if car.locked else ACCENT, 'c', shadow=False)

        gx = c_rect[0] + c_rect[2] + 8 * u
        g_rect = (gx + 14 * u, ty, 160 * u, 84 * u)
        self._arrow(surf, (gx, ty + 42 * u), (g_rect[0], ty + 42 * u), u, 1.0, car)
        facet_box(surf, g_rect, (58, 66, 88), cut=8 * u, edge=EDGE)
        text(surf, 'GEARBOX', (g_rect[0] + 10 * u, g_rect[1] + 12 * u), int(19 * u), DIM, 'ml', shadow=False)
        gname = 'R' if car.gear < 0 else 'N' if car.gear == 0 else str(car.gear)
        text(surf, gname, (g_rect[0] + 40 * u, g_rect[1] + 50 * u), int(58 * u), ACCENT if not car.auto else TEXT, 'c')
        mp = mouse
        bm = (g_rect[0] + 74 * u, g_rect[1] + 24 * u, 36 * u, 26 * u)
        bp = (g_rect[0] + 114 * u, g_rect[1] + 24 * u, 36 * u, 26 * u)
        for r_, lab, d_ in ((bm, '-', -1), (bp, '+', 1)):
            button(surf, r_, lab, u, pygame.Rect(r_).collidepoint(mp), False, size=26)
            self._hit(r_, (lambda d=d_: self._shift(car, d)), 'Shift %s (switches to manual)' % ('down' if d_ < 0 else 'up'))
        am = (g_rect[0] + 74 * u, g_rect[1] + 54 * u, 76 * u, 24 * u)
        button(surf, am, 'AUTO' if car.auto else 'MANUAL', u, pygame.Rect(am).collidepoint(mp), False, active=car.auto, size=20)
        self._hit(am, lambda: setattr(car, 'auto', not car.auto), 'Automatic or manual gearbox')

        tx = g_rect[0] + g_rect[2] + 8 * u
        t_rect = (tx + 14 * u, ty, w - (tx + 14 * u - x0) - 14 * u, 84 * u)
        self._arrow(surf, (tx, ty + 42 * u), (t_rect[0], ty + 42 * u), u, 1.0, car)
        facet_box(surf, t_rect, (58, 66, 88), cut=8 * u, edge=EDGE)
        text(surf, 'TRANSFER CASE', (t_rect[0] + 10 * u, t_rect[1] + 12 * u), int(19 * u), DIM, 'ml', shadow=False)
        hw = (t_rect[2] - 24 * u) / 2
        for i, (lab, low) in enumerate((('HIGH', False), ('LOW', True))):
            r_ = (t_rect[0] + 8 * u + i * (hw + 8 * u), t_rect[1] + 26 * u, hw, 34 * u)
            button(surf, r_, lab, u, pygame.Rect(r_).collidepoint(mp), False, active=(dr.low == low), size=22)
            self._hit(r_, (lambda lo=low: setattr(car, 'low', lo)),
                      'LOW range multiplies gearing by x%.1f - crawl speed, huge torque. HIGH is normal driving.' if low else 'HIGH range: normal gearing.')
            if low:
                self.hits[-1] = (self.hits[-1][0], self.hits[-1][1], self.hits[-1][2] % dr.low_mult)
        text(surf, 'ratio %.1f : 1' % abs(car.ratio), (t_rect[0] + t_rect[2] / 2, t_rect[1] + 72 * u), int(20 * u), ACCENT, 'c', shadow=False)

        # ---- driveline tree
        tree_y0 = ty + 112 * u
        dy = 70 * u
        levels = self._depth(dr.tree)
        leaf_y = tree_y0 + levels * dy + 8 * u
        mxs = [wl.mx for wl in car.wheels]
        lo, hi = min(mxs), max(mxs)
        ax0, ax1 = x0 + 70 * u, x0 + w - 70 * u
        axle_x = [ax0 + (m - lo) / max(1e-6, hi - lo) * (ax1 - ax0) for m in mxs]
        self._flow = [abs(wl.Tdrv) if dr.axle_on[i] else 0.0 for i, wl in enumerate(car.wheels)]
        tot = sum(self._flow) + 1e-6
        self._tot = tot
        root_x, _ = self._tree(surf, car, dr.tree, axle_x, tree_y0, dy, u, mp, 0)
        # feed from transfer case
        pygame.draw.line(surf, ACCENT if car.throttle > 0.05 else LINE_DIM, (t_rect[0] + t_rect[2] / 2, t_rect[1] + t_rect[3]),
                         (t_rect[0] + t_rect[2] / 2, tree_y0 - 26 * u), max(2, int(4 * u)))
        pygame.draw.line(surf, ACCENT if car.throttle > 0.05 else LINE_DIM, (t_rect[0] + t_rect[2] / 2, tree_y0 - 26 * u), (root_x, tree_y0 - 26 * u), max(2, int(4 * u)))
        pygame.draw.line(surf, ACCENT if car.throttle > 0.05 else LINE_DIM, (root_x, tree_y0 - 26 * u), (root_x, tree_y0 - 14 * u), max(2, int(4 * u)))
        # axles
        for i, wl in enumerate(car.wheels):
            self._axle(surf, car, i, axle_x[i], leaf_y, u, mp)
        # quick buttons + tooltip
        by = y0 + h - 38 * u
        lk = (x0 + 14 * u, by, 150 * u, 28 * u)
        button(surf, lk, 'LOCK ALL' if not dr.all_locked else 'UNLOCK ALL', u, pygame.Rect(lk).collidepoint(mp), False, active=dr.all_locked, size=20)
        self._hit(lk, lambda: setattr(car, 'diff_lock', not car.diff_lock), 'Lock (or reset) every differential at once')
        tip = ''
        for r_, fn, t_ in self.hits:
            if r_.collidepoint(mp):
                tip = t_
        text(surf, tip, (x0 + 180 * u, by + 14 * u), int(20 * u), TEXT if tip else DIM, 'ml', shadow=False, maxw=w - 196 * u)
        return self.rect

    @staticmethod
    def _shift(car, d):
        car.auto = False
        car.shift_to(car.gear + d)

    def _arrow(self, surf, a, b, u, share, car):
        col = ACCENT if car.throttle > 0.05 else LINE_DIM
        pygame.draw.line(surf, col, a, b, max(2, int(4 * u)))
        pygame.draw.polygon(surf, col, [(b[0], b[1]), (b[0] - 7 * u, b[1] - 5 * u), (b[0] - 7 * u, b[1] + 5 * u)])

    def _members(self, node):
        if isinstance(node, int):
            return [node]
        out = []
        for c in node[1:]:
            out += self._members(c)
        return out

    def _tree(self, surf, car, node, axle_x, y, dy, u, mp, depth):
        """Draws a diff node and its subtree. Returns (x of node, share of torque)."""
        if isinstance(node, int):
            return axle_x[node], self._flow[node] / self._tot
        dr = car.drive
        d = dr.diff(node[0])
        kids = []
        for ch in node[1:]:
            if isinstance(ch, int):
                kids.append((axle_x[ch], self._flow[ch] / self._tot, None))
            else:
                cx, sh = self._tree(surf, car, ch, axle_x, y + dy, dy, u, mp, depth + 1)
                kids.append((cx, sh, ch))
        xs = [self._cx(k[2], axle_x) if k[2] is not None else k[0] for k in kids]
        nx = sum(xs) / len(xs)
        # branch lines first (under the node)
        leaf_top = y + (self._depth(dr.tree) - depth) * dy
        for (kx, share, sub), cxk in zip(kids, xs):
            col = mixc(LINE_DIM, ACCENT, clamp(share * 1.6 * max(0.25, car.throttle), 0, 1))
            lw = max(2, int((3 + 7 * share) * u))
            ky = (y + dy - 22 * u) if sub is not None else (y + (self._depth(dr.tree) - depth) * dy - 20 * u)
            mid = y + 40 * u
            pygame.draw.line(surf, col, (nx, y), (nx, mid), lw)
            pygame.draw.line(surf, col, (nx, mid), (cxk, mid), lw)
            pygame.draw.line(surf, col, (cxk, mid), (cxk, ky), lw)
        # node
        pygame.draw.polygon(surf, (24, 30, 42), _gear_poly(nx, y, 20 * u, 8))
        pygame.draw.polygon(surf, PANEL_HI, _gear_poly(nx, y, 17 * u, 8, 0.1))
        modecol = {OPEN: DIM, LSD: CYAN, LOCK: WARN}[d.mode]
        pygame.draw.polygon(surf, modecol, [(nx - 8 * u, y - 8 * u), (nx + 8 * u, y - 8 * u), (nx + 8 * u, y + 8 * u), (nx - 8 * u, y + 8 * u)] if d.mode == LOCK else
                            [(nx + math.cos(i * math.tau / 10) * 8 * u, y + math.sin(i * math.tau / 10) * 8 * u) for i in range(10)])
        bw = 40 * u
        right_half = nx > self.rect.x + self.rect.w * 0.55
        text(surf, d.name.upper(), (nx + 26 * u, y) if right_half else (nx - 26 * u, y), int(19 * u), DIM, 'ml' if right_half else 'mr', shadow=False)
        n_m = len(d.modes)
        for i, m in enumerate(d.modes):
            if right_half:     # buttons go on the inside so they never leave the panel
                r_ = (nx - 26 * u - (n_m - i) * (bw + 3 * u) + 3 * u, y - 12 * u, bw, 24 * u)
            else:
                r_ = (nx + 26 * u + i * (bw + 3 * u), y - 12 * u, bw, 24 * u)
            button(surf, r_, MODE_NAMES[m], u, pygame.Rect(r_).collidepoint(mp), False, active=(d.mode == m), size=17)
            self._hit(r_, (lambda dd=d, mm=m: dd.__setattr__('mode', mm)), '%s diff - %s' % (d.name.upper(), MODE_HELP[m]))
        return nx, sum(k[1] for k in kids)

    def _cx(self, node, axle_x):
        mem = self._members(node)
        return sum(axle_x[i] for i in mem) / len(mem)

    def _axle(self, surf, car, i, x, y, u, mp):
        dr = car.drive
        wl = car.wheels[i]
        on = dr.axle_on[i]
        slip = clamp(abs(wl.slip) / 4.0, 0, 1) if wl.touching else 0.0
        tire = mixc((60, 70, 86), WARN, slip) if on else (46, 52, 64)
        # connect clutch above the axle
        cr = (x - 13 * u, y - 18 * u, 26 * u, 20 * u)
        can = i in dr.disconnectable
        if can:
            self._hit(cr, (lambda ii=i: dr.toggle_axle(ii)), 'Axle %d drive: click to %s (e.g. 6x6 <-> 6x4)' % (i + 1, 'disconnect' if on else 'connect'))
        hov = can and pygame.Rect(cr).collidepoint(mp)
        pygame.draw.polygon(surf, (24, 30, 42), [(cr[0], cr[1]), (cr[0] + cr[2], cr[1]), (cr[0] + cr[2], cr[1] + cr[3]), (cr[0], cr[1] + cr[3])])
        col = OK if on else (110, 70, 70)
        if on:
            pygame.draw.polygon(surf, col, [(cr[0] + 3 * u, cr[1] + 3 * u), (cr[0] + cr[2] - 3 * u, cr[1] + 3 * u), (cr[0] + cr[2] - 3 * u, cr[1] + cr[3] - 3 * u), (cr[0] + 3 * u, cr[1] + cr[3] - 3 * u)])
        else:
            pygame.draw.line(surf, col, (cr[0] + 4 * u, cr[1] + 4 * u), (cr[0] + cr[2] - 4 * u, cr[1] + cr[3] - 4 * u), max(2, int(3 * u)))
            pygame.draw.line(surf, col, (cr[0] + cr[2] - 4 * u, cr[1] + 4 * u), (cr[0] + 4 * u, cr[1] + cr[3] - 4 * u), max(2, int(3 * u)))
        pygame.draw.polygon(surf, ACCENT if hov else EDGE, [(cr[0], cr[1]), (cr[0] + cr[2], cr[1]), (cr[0] + cr[2], cr[1] + cr[3]), (cr[0], cr[1] + cr[3])], max(1, int(2 * u)))
        # axle bar + tyres (top view)
        top = y + 6 * u
        pygame.draw.polygon(surf, (90, 98, 116) if on else (64, 70, 84), [(x - 3 * u, top), (x + 3 * u, top), (x + 3 * u, top + 56 * u), (x - 3 * u, top + 56 * u)])
        for ty_ in (top - 4 * u, top + 38 * u):
            pygame.draw.polygon(surf, tire, [(x - 11 * u, ty_), (x + 11 * u, ty_), (x + 11 * u, ty_ + 22 * u), (x - 11 * u, ty_ + 22 * u)])
            pygame.draw.polygon(surf, rgb(tire, 1.25), [(x - 11 * u, ty_), (x + 11 * u, ty_), (x + 11 * u, ty_ + 7 * u), (x - 11 * u, ty_ + 7 * u)])
        text(surf, 'A%d' % (i + 1), (x + 18 * u, top + 28 * u), int(20 * u), TEXT if on else DIM, 'ml', shadow=False)
        if wl.touching and on:
            text(surf, '%.0f' % abs(wl.Tdrv / 1000.0) + 'kN·m' if False else '%.1f' % abs(wl.slip), (x, top + 66 * u), int(18 * u), WARN if slip > 0.5 else DIM, 'mt', shadow=False)


class TelemetryApp:
    def __init__(self):
        self.rect = pygame.Rect(0, 0, 0, 0)

    def size(self, u):
        return int(760 * u), int(300 * u)

    def draw(self, surf, car, u, origin, mouse, game):
        w, h = self.size(u)
        x0, y0 = origin[0] - w, origin[1] - h
        self.rect = pygame.Rect(x0, y0, w, h)
        panel(surf, (x0, y0, w, h), u, None)
        text(surf, 'TELEMETRY', (x0 + 16 * u, y0 + 10 * u), int(26 * u), ACCENT)
        ui.draw_engine_graph(surf, (x0 + 14 * u, y0 + 44 * u, 400 * u, 240 * u), car.engine, u, hover_x=mouse[0] if self.rect.collidepoint(mouse) else None,
                             live=(car.rpm, max(car.throttle, 0.02)), compact=True)
        tx = x0 + 430 * u
        text(surf, 'WHEEL        LOAD    SLIP   SINK   SURFACE', (tx, y0 + 50 * u), int(19 * u), DIM, shadow=False)
        for i, wl in enumerate(car.wheels):
            yy = y0 + 76 * u + i * 26 * u
            name = T.MATERIALS[wl.mat]['name'] if wl.touching else '-'
            col = WARN if abs(wl.slip) > 2 else TEXT
            text(surf, 'A%d%s' % (i + 1, '' if car.drive.axle_on[i] else ' off'), (tx, yy), int(21 * u), TEXT, shadow=False)
            text(surf, '%4.1fkN' % (wl.Fn / 1000), (tx + 80 * u, yy), int(21 * u), TEXT, shadow=False)
            text(surf, '%4.1f' % wl.slip, (tx + 150 * u, yy), int(21 * u), col, shadow=False)
            text(surf, '%2dcm' % round(wl.z * 100), (tx + 205 * u, yy), int(21 * u), TEXT, shadow=False)
            text(surf, name, (tx + 255 * u, yy), int(21 * u), DIM, shadow=False)
        yy = y0 + 76 * u + len(car.wheels) * 26 * u + 10 * u
        for k, line in enumerate(('gear %s  engage %.0f%%  %s' % (car.gear, car.engage * 100, 'locked' if car.locked else 'slipping'),
                                  'throttle %.0f%%   tyre %.0f psi' % (car.throttle * 100, car.pressure_psi),
                                  'speed %.1f m/s   pitch %.1f deg' % (car.vx, math.degrees(car.a)),
                                  'fps %.0f   seed %d   x %.0f m' % (game.fps, game.session.terrain.seed, car.x))):
            text(surf, line, (tx, yy + k * 24 * u), int(21 * u), DIM, shadow=False)


class Hud:
    def __init__(self, settings):
        self.settings = settings
        self.show = True
        self.trans = TransmissionApp()
        self.telem = TelemetryApp()
        self.open = {'trans': bool(settings['app_trans_open']), 'telem': False}
        self.hint_t = 14.0
        self.dock_rects = {}
        self.mouse = (0, 0)
        self.cursor_t = 0.0

    def toggle(self, app):
        self.open[app] = not self.open[app]
        if app == 'trans':
            self.settings['app_trans_open'] = self.open['trans']
        self.cursor_t = 3.0

    @property
    def wants_cursor(self):
        return self.cursor_t > 0 or any(self.open.values())

    def event(self, e, car, session):
        """Mouse interaction with the dock and apps. Returns True if consumed."""
        if not self.show:
            return False
        if e.type == pygame.MOUSEMOTION:
            self.mouse = e.pos
            self.cursor_t = 2.5
        if e.type == pygame.MOUSEBUTTONDOWN and e.button == 1:
            self.cursor_t = 2.5
            for k, r in self.dock_rects.items():
                if r.collidepoint(e.pos):
                    self.toggle(k)
                    return True
            if self.open['trans'] and self.trans.rect.collidepoint(e.pos):
                self.trans.closed = False
                self.trans.click(e.pos)
                if getattr(self.trans, 'closed', False):
                    self.toggle('trans')
                    self.trans.closed = False
                return True
            if self.open['telem'] and self.telem.rect.collidepoint(e.pos):
                return True
        return False

    def update(self, dt):
        self.hint_t = max(0.0, self.hint_t - dt)
        self.cursor_t = max(0.0, self.cursor_t - dt)

    # ------------------------------------------------------------------ drawing
    def draw(self, surf, game):
        if not self.show:
            return
        st = self.settings
        car = game.session.car
        W, H = surf.get_size()
        u = H / 720.0 * st['hud_scale']
        mouse = pygame.mouse.get_pos()
        if st['hud_gauge']:
            self._gauge(surf, car, u, W, H)
        self._axle_bars(surf, car, u, W, H)
        self._dock(surf, u, W, H, mouse)
        origin = (W - 14 * u, H - 78 * u)
        if self.open['trans']:
            self.trans.draw(surf, car, u, origin, mouse)
        if self.open['telem']:
            o2 = origin if not self.open['trans'] else (origin[0] - self.trans.rect.width - 12 * u, origin[1])
            self.telem.draw(surf, car, u, o2, mouse, game)
        pal = game.session.pal
        zone = game.session.terrain.zone_param(math.floor(car.x / 96))['theme']
        text(surf, '%s  -  %s  -  %+d m' % (pal['name'], zone, car.x), (18 * u, 14 * u), int(23 * u), TEXT)
        if st['hud_hints'] and self.hint_t > 0:
            a = clamp(self.hint_t / 3, 0, 1)
            kn = lambda a_: '/'.join(n.upper() for n in st.key_names(a_) if n)
            lines = ['%s gas (hold to build power, tap to feather)     %s brake / reverse     %s handbrake' % (kn('throttle'), kn('brake'), kn('handbrake')),
                     '%s transmission app  (click diffs, range and axles)     %s low range     %s lock diffs     %s / %s tyre pressure' % (kn('app_trans'), kn('toggle_low'), kn('toggle_lock'), kn('press_down'), kn('press_up')),
                     '%s menu     %s telemetry     %s hide HUD' % (kn('pause'), kn('app_telem'), kn('toggle_hud'))]
            for k, ln in enumerate(lines):
                img = ui.font(22 * u).render(ln, True, TEXT)
                img.set_alpha(int(255 * a))
                surf.blit(img, (W // 2 - img.get_width() // 2, int(54 * u) + k * 24 * u))

    def _gauge(self, surf, car, u, W, H):
        st = self.settings
        cx, cy, R = int(110 * u), int(H - 120 * u), 78 * u
        n = 26
        top = car.cfg['redline'] * 1.14
        frac = clamp(car.rpm / top, 0, 1)
        a0, sweep = math.radians(150), math.radians(240)
        for i in range(n):
            f0, f1 = i / n, (i + 1) / n - 0.012
            lit = f1 <= frac + 0.5 / n
            red = (i + 0.5) / n * top > car.cfg['redline'] * 0.96
            col = (240, 70, 60) if red else (250, 200, 80)
            col = col if lit else (50, 54, 66)
            p = []
            for f, rr in ((f0, R), (f1, R), (f1, R * 0.74), (f0, R * 0.74)):
                a = a0 + sweep * f
                p.append((cx + math.cos(a) * rr, cy + math.sin(a) * rr))
            pygame.draw.polygon(surf, col, p)
        g = 'R' if car.gear < 0 else 'N' if car.gear == 0 else str(car.gear)
        text(surf, ('L' if car.low else '') + g, (cx, cy - 4 * u), int(64 * u), TEXT, 'c')
        text(surf, 'AUTO' if car.auto else 'MANUAL', (cx, cy + 34 * u), int(22 * u), (200, 210, 230), 'c')
        mph = st['units'] == 'mph'
        spd = abs(car.speed) * (2.23694 if mph else 3.6)
        text(surf, str(int(spd)), (cx + R + 24 * u, cy - 6 * u), int(64 * u), TEXT, 'tl')
        text(surf, 'mph' if mph else 'km/h', (cx + R + 26 * u, cy + 34 * u), int(22 * u), (200, 210, 230))
        text(surf, 'TYRES %2d PSI' % round(car.pressure_psi), (cx - R, cy + R + 8 * u), int(30 * u), (200, 235, 255))
        flags = []
        if car.low:
            flags.append('LOW')
        if car.drive.all_locked:
            flags.append('DIFF LOCK')
        if car.drive.n_on < car.n:
            flags.append(car.drive.drive_name())
        if flags:
            text(surf, '  '.join(flags), (cx + R + 26 * u, cy + 60 * u), int(22 * u), ACCENT)

    def _axle_bars(self, surf, car, u, W, H):
        c = car.cfg
        n = car.n
        bx = W - 20 * u - 150 * u - n * 34 * u
        by = H - 14 * u
        for i, w in enumerate(car.wheels):
            comp = clamp((c['l0'] - w.l) / (c['l0'] - c['lmin']), 0, 1)
            x = bx + i * 34 * u
            pygame.draw.polygon(surf, (50, 54, 66), [(x, by), (x + 22 * u, by), (x + 22 * u, by - 56 * u), (x, by - 56 * u)])
            sl = clamp(abs(w.slip) / 4.0, 0, 1) if w.touching else 0.0
            col = mixc((110, 220, 150), (240, 80, 64), sl)
            pygame.draw.polygon(surf, rgb(col), [(x, by), (x + 22 * u, by), (x + 22 * u, by - 56 * u * comp), (x, by - 56 * u * comp)])

    def _dock(self, surf, u, W, H, mouse):
        st = self.settings
        size = 52 * u
        x = W - 14 * u - size
        y = H - 14 * u - size
        self.dock_rects = {}
        for key, label, bind in (('telem', 'TELEMETRY', 'app_telem'), ('trans', 'TRANSMISSION', 'app_trans')):
            r = pygame.Rect(x, y, size, size)
            self.dock_rects[key] = r
            hov = r.collidepoint(mouse)
            button(surf, (r.x, r.y, r.w, r.h), '', u, hov, False, active=self.open[key])
            cx, cy = r.centerx, r.centery
            if key == 'trans':
                pygame.draw.polygon(surf, TEXT, _gear_poly(cx, cy, 15 * u, 8, 0.2))
                pygame.draw.polygon(surf, PANEL if not self.open[key] else (120, 70, 20), [(cx + math.cos(i * math.tau / 10) * 6 * u, cy + math.sin(i * math.tau / 10) * 6 * u) for i in range(10)])
            else:
                for i, hh in enumerate((10, 20, 15)):
                    pygame.draw.polygon(surf, TEXT, [(cx - 15 * u + i * 11 * u, cy + 14 * u), (cx - 15 * u + i * 11 * u + 8 * u, cy + 14 * u),
                                                      (cx - 15 * u + i * 11 * u + 8 * u, cy + 14 * u - hh * u), (cx - 15 * u + i * 11 * u, cy + 14 * u - hh * u)])
            if hov:
                kn = '/'.join(n.upper() for n in st.key_names(bind) if n)
                text(surf, '%s [%s]' % (label, kn), (r.centerx, r.y - 6 * u), int(20 * u), TEXT, 'mb')
            x -= size + 8 * u
