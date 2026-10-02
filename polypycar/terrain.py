"""Procedural infinite terrain: a deterministic heightfield sampled every 10 cm.

  base(x)    smooth rolling hills (zone parameterised, blended between zones)
  features   rocks, logs, whoops, ledges, ramps, mud pits... stamped additively into
             96 m "zones" (each zone gets a theme, so roads feel different)
  material   per-sample surface id (grip / rolling resistance / colours)
  biome      palette + grip multiplier blended over long distances

No pygame in here so it can be unit-tested headless.
"""
import math
from .util import clamp, lerp, smooth, hash_i, noise1, Rng, hexc, mixc

DX = 0.1          # sample spacing (m)
SC = 240          # samples per chunk (24 m)
ZL = 96.0         # zone length (m)
CHUNK_W = DX * SC

GROUND, ROCK, WOOD, MUD, GRAVEL, ROAD = range(6)
# mu: base friction, loose: how much low tyre pressure helps, crr: rolling resistance,
# drag: viscous drag (mud), bgrip: biome grip multiplier applies
MATERIALS = [
    dict(name='ground', mu=0.90, loose=0.6, crr=0.016, drag=0, bgrip=True),
    dict(name='rock', mu=1.00, loose=0.1, crr=0.010, drag=0, bgrip=False),
    dict(name='wood', mu=0.75, loose=0.05, crr=0.012, drag=0, bgrip=False),
    dict(name='mud', mu=0.50, loose=1.0, crr=0.070, drag=900, bgrip=False),
    dict(name='gravel', mu=0.74, loose=0.55, crr=0.032, drag=0, bgrip=True),
    dict(name='road', mu=1.00, loose=0.3, crr=0.013, drag=0, bgrip=True),
]

# ------------------------------------------------------------------ biomes
COLOR_KEYS = ['top', 'dirt', 'deep', 'rock', 'sky0', 'sky1', 'mtn', 'tree', 'trunk', 'tuft', 'sun']
_BIOME_SRC = [
    dict(name='meadow', grip=1.0, decor=['broadleaf', 'broadleaf', 'pine', 'bush'], density=0.34,
         top='#78c85a', dirt='#93613d', deep='#523724', rock='#8e95a3', sky0='#4a9fe6', sky1='#d4f0ff',
         mtn='#7aa5cf', tree='#35a05a', trunk='#6c4a33', tuft='#5fb84a', sun='#fff1b0'),
    dict(name='desert', grip=0.84, decor=['cactus', 'cactus', 'bush', 'dune'], density=0.18,
         top='#ecc572', dirt='#cc8a4c', deep='#7c4b2d', rock='#b9774e', sky0='#3f86cf', sky1='#ffe5b0',
         mtn='#dba073', tree='#58a04a', trunk='#7d5a38', tuft='#c9a64f', sun='#fff3c8'),
    dict(name='canyon', grip=0.95, decor=['spire', 'spire', 'bush', 'rockdecor'], density=0.2,
         top='#df7f50', dirt='#ac4e34', deep='#5e2b24', rock='#82525a', sky0='#3763a8', sky1='#ffd0a6',
         mtn='#b4645d', tree='#6c9a4a', trunk='#6b4636', tuft='#c0743f', sun='#ffe2b8'),
    dict(name='tundra', grip=0.55, decor=['pine', 'pine', 'pine', 'rockdecor'], density=0.3,
         top='#f3f8ff', dirt='#9aa8c0', deep='#4a566f', rock='#6f7c94', sky0='#7a9bd6', sky1='#eef5ff',
         mtn='#a6bbe0', tree='#2c6c6d', trunk='#5a4636', tuft='#d5e4f7', sun='#ffffff'),
]
BIOMES = []
for _b in _BIOME_SRC:
    d = dict(_b)
    for k in COLOR_KEYS:
        d[k] = hexc(d[k])
    BIOMES.append(d)

BIOME_LEN = 1200.0
BIOME_BLEND = 90.0
_biome_seed = [0]


def _biome_id(k):
    if k == 0 or k == -1:
        return 0  # always start in the meadow
    return int(hash_i(k, _biome_seed[0] + 77) * len(BIOMES)) % len(BIOMES)


def biome_at(x):
    """-> (a, b, t): blend of biome a -> b with weight t."""
    k = math.floor((x + BIOME_BLEND) / BIOME_LEN)
    bx = k * BIOME_LEN
    t = smooth((x - bx + BIOME_BLEND) / (BIOME_BLEND * 2))
    a, b = _biome_id(k - 1), _biome_id(k)
    if x - bx > BIOME_BLEND:
        a, t = b, 0.0
    return a, b, t


def palette_at(x):
    a, b, t = biome_at(x)
    A, B = BIOMES[a], BIOMES[b]
    o = {'grip': lerp(A['grip'], B['grip'], t), 'decor': B['decor'] if t > 0.5 else A['decor'],
         'density': lerp(A['density'], B['density'], t), 'name': B['name'] if t > 0.5 else A['name']}
    for k in COLOR_KEYS:
        o[k] = mixc(A[k], B[k], t)
    return o


def grip_at(x):
    a, b, t = biome_at(x)
    return lerp(BIOMES[a]['grip'], BIOMES[b]['grip'], t)


# ---------------------------------------------------------------- features
def _rock_profile(r, H):
    n = 3 + int(r() * 3)
    pts = [(0.0, 0.0)]
    peak = int(r() * n)
    for k in range(n):
        u = (k + 1) / (n + 1) + (r() - 0.5) * (0.5 / (n + 1))
        pts.append((u, H if k == peak else H * (0.4 + 0.55 * r())))
    pts.append((1.0, 0.0))
    return pts


def _f_rock(f, x):
    u = (x - f['x0']) / (f['x1'] - f['x0'])
    p = f['pts']
    for i in range(1, len(p)):
        if u <= p[i][0]:
            a, b = p[i - 1], p[i]
            return a[1] + (b[1] - a[1]) * ((u - a[0]) / (b[0] - a[0]))
    return 0.0


def _f_mound(f, x):
    u = (x - f['x0']) / (f['x1'] - f['x0'])
    return f['h'] * (0.5 - 0.5 * math.cos(u * math.tau))


def _f_ripple(f, x):
    u = (x - f['x0']) / (f['x1'] - f['x0'])
    win = min(1.0, u * 5, (1 - u) * 5)
    return f['h'] * 0.5 * (1 - math.cos(u * f['n'] * math.tau)) * smooth(win)


def _f_pothole(f, x):
    v = abs((x - f['x0']) / (f['x1'] - f['x0']) * 2 - 1)
    return -f['h'] * (1 - v ** 4)


def _f_log(f, x):
    c = (f['x0'] + f['x1']) * 0.5
    r = f['r']
    dx = x - c
    if abs(dx) >= r:
        return 0.0
    return max(0.0, math.sqrt(r * r - dx * dx) - 0.4 * r)


def _f_ledge(f, x):
    up = smooth((x - f['x0']) / 0.38)
    dn = smooth((x - (f['x1'] - 0.7)) / 0.7)
    return f['h'] * up * (1 - dn)


def _f_kicker(f, x):
    u = (x - f['x0']) / (f['x1'] - f['x0'])
    return f['h'] * u ** 1.25


def _f_mud(f, x):
    u = (x - f['x0']) / (f['x1'] - f['x0'])
    return -0.16 * (0.5 - 0.5 * math.cos(u * math.tau))


FEATURE = dict(rock=_f_rock, mound=_f_mound, ripple=_f_ripple, pothole=_f_pothole, log=_f_log,
               ledge=_f_ledge, kicker=_f_kicker, mud=_f_mud)

THEMES = {
    'cruise': ['mound', 'mound', 'ripple', 'rock'],
    'rocky': ['rock', 'rock', 'rockfield', 'ledge', 'rock'],
    'whoops': ['ripple', 'whoops', 'whoops', 'mound', 'rock'],
    'jumps': ['kicker', 'mound', 'kicker', 'ripple'],
    'swamp': ['mud', 'mud', 'pothole', 'log', 'pothole'],
    'logs': ['log', 'log', 'ledge', 'rock', 'logs'],
    'mixed': ['rock', 'log', 'whoops', 'ledge', 'pothole', 'mound', 'kicker', 'mud', 'rockfield', 'ripple'],
}
THEME_NAMES = list(THEMES)


class Terrain:
    def __init__(self, seed=1337):
        self.seed = int(seed)
        _biome_seed[0] = self.seed
        self.chunks = {}
        self.zones = {}
        self.zp = {}
        self._ci = None
        self._ch = None
        self._surf = {'mat': 0, 'mu': 0.9, 'loose': 0.6, 'crr': 0.016, 'drag': 0.0}

    @staticmethod
    def difficulty(x):
        return clamp((abs(x) - 120) / 3200, 0, 1)

    # ---- zone-level parameters (blended smoothly between neighbouring zones)
    def zone_param(self, z):
        p = self.zp.get(z)
        if p:
            return p
        s = self.seed

        def H(k):
            return hash_i(z, s + k)
        d = self.difficulty((z + 0.5) * ZL)
        near = abs((z + 0.5) * ZL) < 100
        theme = 'cruise'
        if not near:
            w = [3 * (1 - d) + 0.4, 1, 1, 1, 0.8 + d, 0.8 + d, 1 + d]
            pick = H(26) * sum(w)
            for i, v in enumerate(w):
                pick -= v
                if pick <= 0:
                    theme = THEME_NAMES[i]
                    break
        sr = H(25)
        surface = GROUND if theme == 'swamp' else GROUND if sr < 0.5 else ROAD if sr < 0.8 else GRAVEL
        p = dict(hill=0.3 + 0.7 * H(21), rough=H(22) ** 1.6 * (0.12 + 0.88 * d),
                 climb=H(24) * (0.15 + 0.85 * d) if H(23) > 0.55 else 0.0, theme=theme, surface=surface)
        self.zp[z] = p
        return p

    def params(self, x):
        u = x / ZL - 0.5
        i0 = math.floor(u)
        t = smooth(u - i0)
        a, b = self.zone_param(i0), self.zone_param(i0 + 1)
        return (lerp(a['hill'], b['hill'], t), lerp(a['rough'], b['rough'], t), lerp(a['climb'], b['climb'], t))

    # ---- features for a zone
    def zone_features(self, z):
        lst = self.zones.get(z)
        if lst is not None:
            return lst
        lst = []
        self.zones[z] = lst
        zp = self.zone_param(z)
        x0 = z * ZL
        x_end = x0 + ZL - 5
        d = self.difficulty(x0 + ZL / 2)
        if abs(x0 + ZL / 2) < 100:
            return lst
        r = Rng(int(hash_i(z, self.seed + 5) * 4294967296))
        sc = 0.55 + 0.6 * d
        pool = THEMES[zp['theme']]
        cursor = x0 + 6 + r() * 10
        guard = 0
        while cursor < x_end - 4 and guard < 40:
            guard += 1
            typ = pool[int(r() * len(pool))]
            end = self._add_feature(lst, typ, cursor, r, sc, d, x_end)
            gap_scale = 1.8 if zp['theme'] == 'cruise' else 1.0
            cursor = end + lerp(16, 4.5, d) * (0.6 + 0.8 * r()) * gap_scale
        return lst

    @staticmethod
    def _add_feature(lst, typ, x0, r, sc, d, x_end):
        def push(f):
            if f['x1'] <= x_end:
                lst.append(f)
            return f['x1']
        if typ == 'rock':
            w = (0.7 + 1.6 * r()) * (0.85 + 0.4 * sc)
            H = (0.16 + 0.42 * r()) * sc
            return push(dict(t='rock', x0=x0, x1=x0 + w, pts=_rock_profile(r, H), mat=ROCK))
        if typ == 'rockfield':
            n = 3 + int(r() * (3 + 3 * d))
            x = x0
            for _ in range(n):
                w = (0.6 + 1.3 * r()) * (0.85 + 0.4 * sc)
                H = (0.12 + 0.4 * r()) * sc
                x = push(dict(t='rock', x0=x, x1=x + w, pts=_rock_profile(r, H), mat=ROCK)) + 0.5 + r() * 2.5
            return x
        if typ == 'mound':
            w = 8 + r() * 14
            return push(dict(t='mound', x0=x0, x1=x0 + w, h=(0.8 + 2.2 * r()) * sc))
        if typ == 'ripple':
            wl = 0.7 + r() * 0.5
            ln = 10 + r() * 14
            return push(dict(t='ripple', x0=x0, x1=x0 + ln, h=(0.05 + 0.07 * r()) * (0.6 + sc), n=round(ln / wl)))
        if typ == 'whoops':
            wl = 2.2 + r() * 2.8
            n = 3 + int(r() * 5)
            return push(dict(t='ripple', x0=x0, x1=x0 + wl * n, h=(0.14 + 0.28 * r()) * sc, n=n))
        if typ == 'pothole':
            w = 1.5 + r() * 2.2
            return push(dict(t='pothole', x0=x0, x1=x0 + w, h=(0.15 + 0.35 * r()) * sc, mat=MUD))
        if typ == 'log':
            rad = (0.2 + 0.17 * r()) * (0.8 + 0.5 * d)
            return push(dict(t='log', x0=x0, x1=x0 + rad * 2, r=rad, mat=WOOD))
        if typ == 'logs':
            x = x0
            for _ in range(2 + int(r() * 2)):
                rad = (0.2 + 0.17 * r()) * (0.8 + 0.5 * d)
                x = push(dict(t='log', x0=x, x1=x + rad * 2, r=rad, mat=WOOD)) + 1.8 + r() * 2.5
            return x
        if typ == 'ledge':
            L = 3 + r() * 6
            return push(dict(t='ledge', x0=x0, x1=x0 + L, h=(0.2 + 0.32 * r()) * (0.7 + 0.5 * sc), mat=ROCK))
        if typ == 'kicker':
            L = 6 + r() * 4
            return push(dict(t='kicker', x0=x0, x1=x0 + L, h=(0.9 + 1.5 * r()) * (0.6 + 0.6 * sc), mat=WOOD))
        if typ == 'mud':
            L = 6 + r() * 7
            return push(dict(t='mud', x0=x0, x1=x0 + L, mat=MUD))
        return x0 + 1

    # ---- continuous height (used to fill chunks)
    def base(self, x):
        hill, rough, climb = self.params(x)
        s = self.seed
        fade = smooth((abs(x) - 25) / 90)  # flat start area
        h = (20 * noise1(x / 340, s + 11) + 9 * noise1(x / 130, s + 12)) * hill
        h += 5.5 * noise1(x / 45, s + 13) * climb
        h += (0.55 * noise1(x / 11, s + 14) + 0.18 * noise1(x / 3.7, s + 15) + 0.05 * noise1(x / 1.3, s + 16)) * rough
        return h * fade

    def raw_height(self, x):
        h = self.base(x)
        for f in self.zone_features(math.floor(x / ZL)):
            if f['x0'] <= x <= f['x1']:
                h += FEATURE[f['t']](f, x)
        return h

    def raw_mat(self, x):
        z = math.floor(x / ZL)
        m = self.zone_param(z)['surface']
        for f in self.zone_features(z):
            if 'mat' not in f or x < f['x0'] or x > f['x1']:
                continue
            t = f['t']
            fh = FEATURE[t](f, x)
            if t in ('rock', 'log'):
                if fh > 0.004:
                    m = f['mat']
            elif t == 'pothole':
                if fh < -0.06:
                    m = f['mat']
            elif t == 'mud':
                if f['x0'] + 0.4 < x < f['x1'] - 0.4:
                    m = f['mat']
            else:
                m = f['mat']  # ledge, kicker: whole footprint
        return m

    def base_height(self, x):
        return self.base(x)

    # ---- chunked samples
    def chunk(self, ci):
        c = self.chunks.get(ci)
        if c is not None:
            return c
        hs = []
        ms = []
        for i in range(SC + 1):
            x = (ci * SC + i) * DX
            hs.append(self.raw_height(x))
            ms.append(self.raw_mat(x))
        c = (hs, ms)
        self.chunks[ci] = c
        return c

    def prune(self, cx, keep=14):
        cc = math.floor(cx / CHUNK_W)
        for k in [k for k in self.chunks if abs(k - cc) > keep]:
            del self.chunks[k]
        self._ci = None

    def h_at(self, i):
        ci = i // SC
        if ci != self._ci:
            self._ch = self.chunk(ci)[0]
            self._ci = ci
        return self._ch[i - ci * SC]

    def mat_idx(self, i):
        ci = i // SC
        return self.chunk(ci)[1][i - ci * SC]

    def h(self, x):
        f = x / DX
        i = math.floor(f)
        t = f - i
        a = self.h_at(i)
        return a + (self.h_at(i + 1) - a) * t

    def slope(self, x):
        i = math.floor(x / DX)
        return (self.h_at(i + 1) - self.h_at(i)) / DX

    def mat_at(self, x):
        return self.mat_idx(round(x / DX))

    def surface(self, x):
        """Surface properties at x (shared dict, don't keep a reference)."""
        m = self.mat_at(x)
        M = MATERIALS[m]
        o = self._surf
        o['mat'] = m
        o['mu'] = M['mu'] * (grip_at(x) if M['bgrip'] else 1.0)
        o['loose'] = M['loose']
        o['crr'] = M['crr']
        o['drag'] = M['drag']
        return o

    def contact_circle(self, cx, cy, R, out):
        """Circle (wheel) vs polyline. Fills out=[pen, nx, ny, px, py]; True on contact."""
        h_at = self.h_at
        i0 = math.floor((cx - R) / DX)
        i1 = math.floor((cx + R) / DX)
        best = 0.0
        bnx = bny = 0.0
        RR = R * R
        sqrt = math.sqrt
        for i in range(i0, i1 + 1):
            x0 = i * DX
            y0 = h_at(i)
            ey = h_at(i + 1) - y0
            px = cx - x0
            py = cy - y0
            len2 = DX * DX + ey * ey
            s = (px * DX + py * ey) / len2
            if 0.0 < s < 1.0:
                ln = sqrt(len2)
                nx = -ey / ln
                ny = DX / ln
                pen = R - (px * nx + py * ny)
                if pen <= best:
                    continue
            else:
                sc = 0.0 if s <= 0.0 else 1.0
                dx = cx - (x0 + sc * DX)
                dy = cy - (y0 + sc * ey)
                d2 = dx * dx + dy * dy
                if d2 >= RR:
                    continue
                d = sqrt(d2)
                pen = R - d
                if pen <= best:
                    continue
                if d < 1e-6:
                    nx, ny = 0.0, 1.0
                else:
                    nx, ny = dx / d, dy / d
            best = pen
            bnx, bny = nx, ny
        if best <= 0.0:
            out[0] = 0.0
            return False
        out[0] = best
        out[1] = bnx
        out[2] = bny
        out[3] = cx - bnx * (R - best)
        out[4] = cy - bny * (R - best)
        return True
