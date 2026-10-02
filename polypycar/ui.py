"""Small low-poly UI toolkit: fonts, faceted panels/buttons, widgets, scrolling pages and the
engine torque/power graph shared by the garage and the in-game telemetry app."""
import math
import pygame
from .util import clamp, mixc, shade, rgb

# ------------------------------------------------------------------ theme
BG = (22, 28, 40)
PANEL = (34, 42, 58)
PANEL_HI = (50, 61, 82)
EDGE = (86, 100, 128)
ACCENT = (255, 176, 56)
ACCENT_DK = (196, 120, 24)
CYAN = (92, 200, 232)
TEXT = (240, 244, 250)
DIM = (146, 158, 178)
OK = (110, 220, 150)
WARN = (240, 90, 72)
SHADOW = (0, 0, 0)

_fonts = {}


def font(size):
    size = max(8, int(size))
    f = _fonts.get(size)
    if f is None:
        f = _fonts[size] = pygame.font.Font(None, size)
    return f


_text_cache = {}


def _render(f, size, s, col):
    key = (size, s, col)
    img = _text_cache.get(key)
    if img is None:
        if len(_text_cache) > 1500:
            _text_cache.clear()
        img = _text_cache[key] = f.render(s, True, col)
    return img


def text(surf, s, pos, size=24, col=TEXT, anchor='tl', shadow=True, maxw=None):
    size = max(8, int(size))
    s = str(s)
    f = font(size)
    img = _render(f, size, s, col)
    if maxw and img.get_width() > maxw:
        img = pygame.transform.smoothscale(img, (int(maxw), img.get_height()))
    r = img.get_rect()
    setattr(r, {'tl': 'topleft', 'tr': 'topright', 'bl': 'bottomleft', 'br': 'bottomright', 'c': 'center',
                'ml': 'midleft', 'mr': 'midright', 'mt': 'midtop', 'mb': 'midbottom'}[anchor], pos)
    if shadow:
        sh = _render(f, size, s, SHADOW)
        if maxw and sh.get_width() > maxw:
            sh = pygame.transform.smoothscale(sh, (int(maxw), sh.get_height()))
        surf.blit(sh, r.move(max(1, size // 18), max(1, size // 14)))
    surf.blit(img, r)
    return r


def wrap(s, size, maxw):
    """Split text into lines that fit maxw pixels."""
    f = font(size)
    lines, cur = [], ''
    for word in str(s).split():
        t = (cur + ' ' + word).strip()
        if f.size(t)[0] <= maxw or not cur:
            cur = t
        else:
            lines.append(cur)
            cur = word
    if cur:
        lines.append(cur)
    return lines


def cut_pts(rect, cut):
    x, y, w, h = rect
    c = min(cut, w / 2, h / 2)
    return [(x + c, y), (x + w - c, y), (x + w, y + c), (x + w, y + h - c), (x + w - c, y + h), (x + c, y + h), (x, y + h - c), (x, y + c)]


def facet_box(surf, rect, col, cut=8, edge=None, lit=1.0):
    """Cut-corner box: lit upper facet, shaded lower facet, split on a slight diagonal."""
    x, y, w, h = rect
    cut = min(cut, h * 0.28, w * 0.3)
    p = cut_pts((x, y, w, h), cut)
    ml, mr = (x, y + h * 0.68), (x + w, y + h * 0.46)
    pygame.draw.polygon(surf, rgb(col, 1.08 * lit), [p[7], p[0], p[1], p[2], mr, ml])
    pygame.draw.polygon(surf, rgb(col, 0.82 * lit), [ml, mr, p[3], p[4], p[5], p[6]])
    if edge:
        pygame.draw.polygon(surf, edge, p, max(1, int(cut / 6)))


def panel(surf, rect, u, title=None, col=PANEL):
    facet_box(surf, rect, col, cut=10 * u, edge=EDGE)
    if title:
        text(surf, title, (rect[0] + 16 * u, rect[1] + 10 * u), int(26 * u), ACCENT)


def button(surf, rect, label, u, hover=False, focus=False, accent=False, active=False, disabled=False, size=26):
    base = ACCENT_DK if (accent or active) else PANEL_HI
    if disabled:
        base = (44, 50, 62)
    lit = 1.0 + (0.22 if hover and not disabled else 0.0)
    facet_box(surf, rect, base, cut=7 * u, edge=ACCENT if focus else (EDGE if not active else ACCENT), lit=lit)
    col = DIM if disabled else (TEXT if not (accent or active) else (255, 250, 235))
    text(surf, label, (rect[0] + rect[2] / 2, rect[1] + rect[3] / 2), int(size * u), col, 'c')


# ------------------------------------------------------------------ widgets
class Widget:
    height = 46
    focusable = True

    def draw(self, surf, rect, u, focused, mouse):
        pass

    def click(self, pos, rect, u):
        return False

    def drag(self, pos, rect, u):
        pass

    def key(self, k, u=1):
        return False

    def tick(self, dt):
        pass


class Header(Widget):
    focusable = False
    height = 54

    def __init__(self, label):
        self.label = label

    def draw(self, surf, rect, u, focused, mouse):
        x, y, w, h = rect
        text(surf, self.label, (x + 4 * u, y + h - 12 * u), int(30 * u), ACCENT, 'bl')
        pygame.draw.line(surf, EDGE, (x, y + h - 4 * u), (x + w, y + h - 4 * u), max(1, int(2 * u)))


class Spacer(Widget):
    focusable = False

    def __init__(self, h=14):
        self.height = h

    def draw(self, *a):
        pass


class Note(Widget):
    focusable = False
    height = 34

    def __init__(self, s):
        self.s = s

    def draw(self, surf, rect, u, focused, mouse):
        s = self.s() if callable(self.s) else self.s
        text(surf, s, (rect[0] + 4 * u, rect[1] + 6 * u), int(21 * u), DIM, shadow=False)


class Row(Widget):
    """Label on the left, control area on the right."""
    label = ''

    def split(self, rect, u):
        x, y, w, h = rect
        cw = min(w * 0.5, 380 * u)
        return (x, y, w - cw, h), (x + w - cw, y + 4 * u, cw, h - 8 * u)

    def frame(self, surf, rect, u, focused, hover):
        x, y, w, h = rect
        if focused or hover:
            facet_box(surf, (x, y + 2 * u, w, h - 4 * u), PANEL_HI if focused else PANEL, cut=6 * u, edge=ACCENT if focused else None)
        lab, ctl = self.split(rect, u)
        text(surf, self.label, (lab[0] + 14 * u, lab[1] + lab[3] / 2), int(25 * u), TEXT, 'ml')
        return ctl


class Button(Widget):
    def __init__(self, label, fn, accent=False, height=52, size=28, note=None):
        self.label, self.fn, self.accent, self.height, self.size, self.note = label, fn, accent, height, size, note

    def draw(self, surf, rect, u, focused, mouse):
        x, y, w, h = rect
        r = (x, y + 3 * u, w, h - 6 * u)
        hover = pygame.Rect(r).collidepoint(mouse)
        button(surf, r, self.label, u, hover, focused, self.accent, size=self.size)

    def click(self, pos, rect, u):
        self.fn()
        return True

    def key(self, k, u=1):
        if k in (pygame.K_RETURN, pygame.K_SPACE, pygame.K_KP_ENTER):
            self.fn()
            return True
        return False


class Toggle(Row):
    def __init__(self, label, get, set_, on='ON', off='OFF'):
        self.label, self.get, self.set, self.on, self.off = label, get, set_, on, off

    def draw(self, surf, rect, u, focused, mouse):
        ctl = self.frame(surf, rect, u, focused, pygame.Rect(rect).collidepoint(mouse))
        on = bool(self.get())
        button(surf, ctl, self.on if on else self.off, u, pygame.Rect(ctl).collidepoint(mouse), False, active=on, size=24)

    def click(self, pos, rect, u):
        self.set(not self.get())
        return True

    def key(self, k, u=1):
        if k in (pygame.K_RETURN, pygame.K_SPACE, pygame.K_LEFT, pygame.K_RIGHT, pygame.K_KP_ENTER):
            self.set(not self.get())
            return True
        return False


class Choice(Row):
    """Cycle through options with arrows. options: list of (value, label) or callable returning one."""

    def __init__(self, label, options, get, set_, disabled=None):
        self.label, self._opts, self.get, self.set = label, options, get, set_
        self.disabled = disabled              # callable -> True while the choice is locked

    def locked(self):
        return bool(self.disabled and self.disabled())

    @property
    def opts(self):
        return self._opts() if callable(self._opts) else self._opts

    def _idx(self):
        v = self.get()
        for i, (val, _) in enumerate(self.opts):
            if val == v:
                return i
        return 0

    def step(self, d):
        if self.locked():
            return
        o = self.opts
        self.set(o[(self._idx() + d) % len(o)][0])

    def draw(self, surf, rect, u, focused, mouse):
        ctl = self.frame(surf, rect, u, focused, pygame.Rect(rect).collidepoint(mouse))
        x, y, w, h = ctl
        aw = h
        lock = self.locked()
        for sgn, bx in ((-1, x), (1, x + w - aw)):
            r = (bx, y, aw, h)
            button(surf, r, '<' if sgn < 0 else '>', u, pygame.Rect(r).collidepoint(mouse) and not lock, False, size=26, disabled=lock)
        o = self.opts
        text(surf, o[self._idx()][1], (x + w / 2, y + h / 2), int(25 * u), DIM if lock else ACCENT, 'c', maxw=w - 2 * aw - 8 * u)

    def click(self, pos, rect, u):
        if self.locked():
            return True
        _, ctl = self.split(rect, u)
        self.step(-1 if pos[0] < ctl[0] + ctl[2] / 2 else 1)
        return True

    def key(self, k, u=1):
        if k == pygame.K_LEFT:
            self.step(-1)
            return True
        if k in (pygame.K_RIGHT, pygame.K_RETURN, pygame.K_SPACE, pygame.K_KP_ENTER):
            self.step(1)
            return True
        return False


class Slider(Row):
    def __init__(self, label, lo, hi, step, get, set_, fmt='{:.0f}'):
        self.label, self.lo, self.hi, self.stp, self.get, self.set, self.fmt = label, lo, hi, step, get, set_, fmt

    def _track(self, ctl, u):
        x, y, w, h = ctl
        return x + 62 * u, x + w - 8 * u

    def draw(self, surf, rect, u, focused, mouse):
        ctl = self.frame(surf, rect, u, focused, pygame.Rect(rect).collidepoint(mouse))
        x, y, w, h = ctl
        a, b = self._track(ctl, u)
        v = self.get()
        t = clamp((v - self.lo) / (self.hi - self.lo), 0, 1)
        cy = y + h / 2
        pygame.draw.polygon(surf, (24, 30, 42), [(a, cy - 4 * u), (b, cy - 4 * u), (b, cy + 4 * u), (a, cy + 4 * u)])
        pygame.draw.polygon(surf, ACCENT_DK, [(a, cy - 4 * u), (a + (b - a) * t, cy - 4 * u), (a + (b - a) * t, cy + 4 * u), (a, cy + 4 * u)])
        kx = a + (b - a) * t
        pygame.draw.polygon(surf, ACCENT, [(kx, cy - 13 * u), (kx + 8 * u, cy), (kx, cy + 13 * u), (kx - 8 * u, cy)])
        text(surf, self.fmt.format(v), (x + 4 * u, cy), int(23 * u), TEXT, 'ml')

    def _set_from(self, px, rect, u):
        _, ctl = self.split(rect, u)
        a, b = self._track(ctl, u)
        t = clamp((px - a) / (b - a), 0, 1)
        v = self.lo + t * (self.hi - self.lo)
        v = round(v / self.stp) * self.stp
        self.set(clamp(v, self.lo, self.hi))

    def click(self, pos, rect, u):
        self._set_from(pos[0], rect, u)
        return True

    def drag(self, pos, rect, u):
        self._set_from(pos[0], rect, u)

    def key(self, k, u=1):
        if k in (pygame.K_LEFT, pygame.K_RIGHT):
            d = -1 if k == pygame.K_LEFT else 1
            self.set(clamp(round((self.get() + d * self.stp) / self.stp) * self.stp, self.lo, self.hi))
            return True
        return False


class TextBox(Row):
    def __init__(self, label, get, set_, digits=True, maxlen=9, hint=''):
        self.label, self.get, self.set, self.digits, self.maxlen, self.hint = label, get, set_, digits, maxlen, hint
        self.editing = False
        self.buf = ''

    def draw(self, surf, rect, u, focused, mouse):
        ctl = self.frame(surf, rect, u, focused, pygame.Rect(rect).collidepoint(mouse))
        facet_box(surf, ctl, (24, 30, 42), cut=6 * u, edge=ACCENT if self.editing else EDGE)
        s = self.buf + ('_' if self.editing and (pygame.time.get_ticks() // 400) % 2 == 0 else '') if self.editing else str(self.get())
        if not self.editing and str(self.get()) in ('0', ''):
            s = self.hint
        text(surf, s, (ctl[0] + 12 * u, ctl[1] + ctl[3] / 2), int(25 * u), ACCENT if self.editing else TEXT, 'ml')

    def click(self, pos, rect, u):
        self.editing = True
        self.buf = '' if str(self.get()) == '0' else str(self.get())
        return True

    def key(self, k, u=1):
        if not self.editing:
            if k in (pygame.K_RETURN, pygame.K_KP_ENTER, pygame.K_SPACE):
                self.click(None, None, u)
                return True
            return False
        if k in (pygame.K_RETURN, pygame.K_KP_ENTER):
            self.editing = False
            try:
                self.set(int(self.buf) if self.buf else 0)
            except ValueError:
                pass
            return True
        if k == pygame.K_ESCAPE:
            self.editing = False
            return True
        if k == pygame.K_BACKSPACE:
            self.buf = self.buf[:-1]
            return True
        return True

    def textinput(self, ch):
        if self.editing and len(self.buf) < self.maxlen and (ch.isdigit() or not self.digits):
            self.buf += ch


class KeyRow(Row):
    """Rebindable action: two slots, click one then press a key (Esc cancels, Backspace clears)."""

    def __init__(self, action, label, settings):
        self.action, self.label, self.settings = action, label, settings
        self.slot_rects = [None, None]
        self.waiting = None        # slot index being rebound

    def draw(self, surf, rect, u, focused, mouse):
        ctl = self.frame(surf, rect, u, focused, pygame.Rect(rect).collidepoint(mouse))
        x, y, w, h = ctl
        names = self.settings.key_names(self.action)
        bw = (w - 8 * u) / 2
        for i in range(2):
            r = (x + i * (bw + 8 * u), y, bw, h)
            self.slot_rects[i] = r
            wait = self.waiting == i
            lab = 'press a key...' if wait else (names[i].upper() if names[i] else '-')
            button(surf, r, lab, u, pygame.Rect(r).collidepoint(mouse), False, active=wait, size=22)

    def click(self, pos, rect, u):
        _, ctl = self.split(rect, u)
        bw = (ctl[2] - 8 * u) / 2
        self.waiting = 0 if pos[0] < ctl[0] + bw + 4 * u else 1
        return True

    def key(self, k, u=1):
        if self.waiting is None:
            if k in (pygame.K_RETURN, pygame.K_SPACE, pygame.K_KP_ENTER):
                self.waiting = 0
                return True
            return False
        if k == pygame.K_ESCAPE:
            self.waiting = None
        elif k == pygame.K_BACKSPACE:
            self.settings.clear_bind(self.action, self.waiting)
            self.waiting = None
        else:
            self.settings.set_bind(self.action, self.waiting, k)
            self.waiting = None
        return True


# ------------------------------------------------------------------ scrolling page of widgets
class Page:
    def __init__(self, widgets):
        self.widgets = widgets
        self.focus = next((i for i, w in enumerate(widgets) if w.focusable), 0)
        self.scroll = 0.0
        self.rects = []
        self.drag_idx = None
        self.area = (0, 0, 0, 0)
        self.total_h = 0

    def _layout(self, area, u):
        x, y, w, h = area
        self.area = area
        self.rects = []
        cy = y - self.scroll
        for wd in self.widgets:
            hh = wd.height * u
            self.rects.append((x, cy, w, hh))
            cy += hh
        self.total_h = cy + self.scroll - y

    def draw(self, surf, area, u, mouse):
        self._layout(area, u)
        clip = surf.get_clip()
        surf.set_clip(area)
        for i, (wd, r) in enumerate(zip(self.widgets, self.rects)):
            if r[1] + r[3] < area[1] or r[1] > area[1] + area[3]:
                continue
            wd.draw(surf, r, u, i == self.focus, mouse)
        surf.set_clip(clip)
        if self.total_h > area[3]:        # scrollbar
            x, y, w, h = area
            th = max(30 * u, h * h / self.total_h)
            ty = y + (h - th) * (self.scroll / max(1, self.total_h - h))
            pygame.draw.polygon(surf, EDGE, [(x + w + 6 * u, ty), (x + w + 12 * u, ty + 3 * u), (x + w + 12 * u, ty + th - 3 * u), (x + w + 6 * u, ty + th)])

    def _ensure_visible(self, u):
        if not self.rects:
            return
        x, y, w, h = self.area
        r = self.rects[self.focus]
        if r[1] < y:
            self.scroll -= y - r[1] + 6 * u
        elif r[1] + r[3] > y + h:
            self.scroll += r[1] + r[3] - (y + h) + 6 * u
        self.scroll = clamp(self.scroll, 0, max(0, self.total_h - h))

    def hit(self, pos):
        if not pygame.Rect(self.area).collidepoint(pos):
            return None
        for i, r in enumerate(self.rects):
            if pygame.Rect(r).collidepoint(pos):
                return i
        return None

    def move(self, d, u):
        n = len(self.widgets)
        i = self.focus
        for _ in range(n):
            i = (i + d) % n
            if self.widgets[i].focusable:
                self.focus = i
                break
        self._ensure_visible(u)

    def event(self, e, u):
        """Returns True if consumed."""
        cur = self.widgets[self.focus] if self.widgets else None
        waiting = isinstance(cur, KeyRow) and cur.waiting is not None
        editing = isinstance(cur, TextBox) and cur.editing
        if e.type == pygame.KEYDOWN:
            if waiting or editing:
                return cur.key(e.key, u)
            if e.key == pygame.K_UP:
                self.move(-1, u)
                return True
            if e.key == pygame.K_DOWN:
                self.move(1, u)
                return True
            if cur and cur.key(e.key, u):
                return True
        elif e.type == pygame.TEXTINPUT and isinstance(cur, TextBox):
            cur.textinput(e.text)
            return True
        elif e.type == pygame.MOUSEMOTION:
            if self.drag_idx is not None and e.buttons[0]:
                self.widgets[self.drag_idx].drag(e.pos, self.rects[self.drag_idx], u)
                return True
            i = self.hit(e.pos)
            if i is not None and self.widgets[i].focusable and not waiting and not editing:
                self.focus = i
        elif e.type == pygame.MOUSEBUTTONDOWN and e.button == 1:
            i = self.hit(e.pos)
            if cur is not None and (waiting or editing):
                if isinstance(cur, KeyRow):
                    cur.waiting = None
                if isinstance(cur, TextBox):
                    cur.editing = False
            if i is not None and self.widgets[i].focusable:
                self.focus = i
                if self.widgets[i].click(e.pos, self.rects[i], u):
                    if isinstance(self.widgets[i], Slider):
                        self.drag_idx = i
                    return True
        elif e.type == pygame.MOUSEBUTTONUP and e.button == 1:
            self.drag_idx = None
        elif e.type == pygame.MOUSEWHEEL:
            self.scroll = clamp(self.scroll - e.y * 50 * u, 0, max(0, self.total_h - self.area[3]))
            return True
        return False


# ------------------------------------------------------------------ engine graph
def nice_ceil(v):
    if v <= 0:
        return 1
    e = 10 ** math.floor(math.log10(v))
    for m in (1, 1.5, 2, 2.5, 3, 4, 5, 6, 8, 10):
        if v <= m * e:
            return m * e
    return 10 * e


def draw_engine_graph(surf, rect, engine, u, hover_x=None, live=None, compact=False):
    """Torque (amber) and power (cyan) vs rpm - the curve the physics actually uses.
    live: (rpm, throttle) draws the operating point. Returns the (rpm, Nm, hp) under the cursor."""
    x, y, w, h = rect
    facet_box(surf, rect, (26, 32, 46), cut=8 * u, edge=EDGE)
    pad_l, pad_r, pad_t, pad_b = 54 * u, 54 * u, (14 if compact else 30) * u, 34 * u
    gx, gy, gw, gh = x + pad_l, y + pad_t, w - pad_l - pad_r, h - pad_t - pad_b
    sweep = engine.sweep(25)
    max_rpm = engine.redline * 1.18
    max_rpm = math.ceil(max_rpm / 500) * 500
    max_t = nice_ceil(max(t for _, t, _ in sweep) * 1.08)
    max_p = nice_ceil(max(p for _, _, p in sweep) * 1.08)

    def X(r):
        return gx + gw * r / max_rpm

    def YT(t):
        return gy + gh * (1 - t / max_t)

    def YP(p):
        return gy + gh * (1 - p / max_p)

    # redline zone + grid
    pygame.draw.polygon(surf, (70, 34, 38), [(X(engine.redline), gy), (gx + gw, gy), (gx + gw, gy + gh), (X(engine.redline), gy + gh)])
    for i in range(0, 5):
        yy = gy + gh * i / 4
        pygame.draw.line(surf, (50, 60, 80), (gx, yy), (gx + gw, yy), 1)
        text(surf, '%d' % round(max_t * (1 - i / 4)), (gx - 6 * u, yy), int(19 * u), ACCENT, 'mr', shadow=False)
        text(surf, '%d' % round(max_p * (1 - i / 4)), (gx + gw + 6 * u, yy), int(19 * u), CYAN, 'ml', shadow=False)
    step = 500 if max_rpm <= 4000 else 1000
    for r in range(0, int(max_rpm) + 1, step):
        pygame.draw.line(surf, (50, 60, 80), (X(r), gy), (X(r), gy + gh), 1)
        text(surf, '%d' % r, (X(r), gy + gh + 4 * u), int(19 * u), DIM, 'mt', shadow=False)
    text(surf, 'rpm', (gx + gw, gy + gh + 20 * u), int(19 * u), DIM, 'tr', shadow=False)
    if not compact:
        text(surf, 'Nm', (gx - 6 * u, gy - 16 * u), int(20 * u), ACCENT, 'mr', shadow=False)
        text(surf, 'hp', (gx + gw + 6 * u, gy - 16 * u), int(20 * u), CYAN, 'ml', shadow=False)
    pts = [(r, t, p) for r, t, p in sweep if r <= max_rpm]
    # filled torque area (low-poly strip) + lines
    area = [(X(pts[0][0]), gy + gh)] + [(X(r), YT(t)) for r, t, _ in pts[::2]] + [(X(pts[-1][0]), gy + gh)]
    pygame.draw.polygon(surf, (88, 60, 22), area)
    pygame.draw.lines(surf, ACCENT, False, [(X(r), YT(t)) for r, t, _ in pts[::2]], max(2, int(3 * u)))
    pygame.draw.lines(surf, CYAN, False, [(X(r), YP(p)) for r, _, p in pts[::2]], max(2, int(3 * u)))
    # peaks
    pt, prt = engine.peak_torque()
    pp, prp = engine.peak_power()
    pygame.draw.polygon(surf, ACCENT, [(X(prt), YT(pt) - 8 * u), (X(prt) + 7 * u, YT(pt)), (X(prt), YT(pt) + 8 * u), (X(prt) - 7 * u, YT(pt))])
    pygame.draw.polygon(surf, CYAN, [(X(prp), YP(pp) - 8 * u), (X(prp) + 7 * u, YP(pp)), (X(prp), YP(pp) + 8 * u), (X(prp) - 7 * u, YP(pp))])
    out = None
    if hover_x is not None and gx <= hover_x <= gx + gw:
        rpm = (hover_x - gx) / gw * max_rpm
        tq, hp_ = engine.torque_at(rpm), engine.hp_at(rpm)
        pygame.draw.line(surf, TEXT, (hover_x, gy), (hover_x, gy + gh), 1)
        pygame.draw.circle(surf, ACCENT, (hover_x, YT(tq)), max(3, int(5 * u)))
        pygame.draw.circle(surf, CYAN, (hover_x, YP(hp_)), max(3, int(5 * u)))
        out = (rpm, tq, hp_)
        lab = '%d rpm   %d Nm   %d hp' % (rpm, tq, hp_)
        bx = min(max(hover_x - 90 * u, gx), gx + gw - 190 * u)
        facet_box(surf, (bx, gy + 4 * u, 190 * u, 26 * u), (18, 22, 32), cut=5 * u, edge=EDGE)
        text(surf, lab, (bx + 95 * u, gy + 17 * u), int(20 * u), TEXT, 'c', shadow=False)
    if live:
        rpm, thr = live
        if rpm <= max_rpm:
            tq = engine.torque_at(rpm) * thr
            pygame.draw.line(surf, (255, 255, 255), (X(rpm), gy), (X(rpm), gy + gh), max(1, int(2 * u)))
            pygame.draw.circle(surf, (255, 255, 255), (X(rpm), YT(tq)), max(4, int(6 * u)))
            pygame.draw.circle(surf, ACCENT, (X(rpm), YT(tq)), max(3, int(4 * u)))
    return out
