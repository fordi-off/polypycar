"""Procedural infinite terrain with deformable soil.

Every 10 cm sample carries:
  h     current surface height (changes when wheels dig / press / pile soil)
  h0    original surface height
  fl    hard "pan" below the soil. Soil thickness = h - fl (snow / mud / dirt are soft, rock is not)
  dens  compaction 0..1 (wheels pack the soil: second pass is firmer, rear axles use front tracks)
  mat   surface material

World is built from 96 m zones with themes (timber, mire, drifts, steep...) stamped with
obstacles, blended over biomes (taiga, mudlands, highland, whiteout).
No pygame in here so it can be unit-tested headless.
"""
import math
from . import worlds
from .util import clamp, lerp, smooth, hash_i, noise1, Rng, hexc, mixc

DX = 0.1          # sample spacing (m)
SC = 240          # samples per chunk (24 m)
ZL = 96.0         # zone length (m)
CHUNK_W = DX * SC

DIRT, ROCK, WOOD, MUD, GRAVEL, SNOW, ICE, PACKED, ASPHALT, HARDPACK = range(10)
# mu: friction, S: nominal soft depth (m), ks: soil stiffness (N/m), pb: bearing pressure (Pa),
# crr: rolling resistance, drag: viscous drag (N s/m), dig: digging rate when a wheel spins (m/s per m/s slip)
MATERIALS = [
    dict(name='dirt',   mu=0.85, S=0.12, ks=1.2e6, pb=170e3, crr=0.024, drag=0,    dig=0.012, loose=0.5),
    dict(name='rock',   mu=1.00, S=0.0,  ks=1e9,   pb=1e9,   crr=0.012, drag=0,    dig=0.0,  loose=0.1),
    dict(name='wood',   mu=0.70, S=0.0,  ks=1e9,   pb=1e9,   crr=0.012, drag=0,    dig=0.0,  loose=0.05),
    dict(name='mud',    mu=0.52, S=0.55, ks=4.0e5, pb=20e3,  crr=0.060, drag=2200, dig=0.06, loose=1.0),
    dict(name='gravel', mu=0.72, S=0.06, ks=2.0e6, pb=320e3, crr=0.035, drag=0,    dig=0.015, loose=0.55),
    dict(name='snow',   mu=0.36, S=0.60, ks=4.5e5, pb=12e3,  crr=0.035, drag=500,  dig=0.07, loose=1.0),
    dict(name='ice',    mu=0.13, S=0.0,  ks=1e9,   pb=1e9,   crr=0.008, drag=0,    dig=0.0,  loose=0.0),
    dict(name='packed', mu=0.58, S=0.12, ks=9e5,   pb=110e3, crr=0.020, drag=0,    dig=0.02, loose=0.3),
    dict(name='asphalt', mu=1.12, S=0.0, ks=1e9,   pb=1e9,   crr=0.011, drag=0,    dig=0.0,  loose=0.0),
    dict(name='hardpack', mu=0.96, S=0.03, ks=6e6, pb=450e3, crr=0.014, drag=0,    dig=0.004, loose=0.15),
]

# ------------------------------------------------------------------ biomes
TAIGA, MUDLANDS, HIGHLAND, WHITEOUT, SUNBELT = range(5)
COLOR_KEYS = ['top', 'dirt', 'deep', 'rock', 'sky0', 'sky1', 'mtn', 'tree', 'trunk', 'snow', 'sun']
_BIOME_SRC = [
    dict(name='taiga', decor=['pine', 'pine', 'pine', 'rockdecor'], density=0.30, fog=0.30, snowfall=0.75,
         top='#c9d3df', dirt='#6d5b4c', deep='#3a3330', rock='#7b8696', sky0='#869cb6', sky1='#dde7f0',
         mtn='#8aa0ba', tree='#2c5c52', trunk='#4a382c', snow='#f2f6fc', sun='#f4f7fb',
         surf={SNOW: .50, PACKED: .15, ICE: .06, DIRT: .19, MUD: .10}),
    dict(name='mudlands', decor=['deadtree', 'pine', 'deadtree', 'bush'], density=0.22, fog=0.38, snowfall=0.0,
         top='#7a6444', dirt='#5c4636', deep='#33271f', rock='#6c6a68', sky0='#7d8c8a', sky1='#cdd2c6',
         mtn='#6f7f78', tree='#3d5a3a', trunk='#3a2b20', snow='#e6eaf0', sun='#e8e6d8',
         surf={MUD: .42, DIRT: .30, GRAVEL: .13, SNOW: .10, PACKED: .05}),
    dict(name='highland', decor=['broadleaf', 'broadleaf', 'pine', 'bush'], density=0.28, fog=0.12, snowfall=0.0,
         top='#9a8a52', dirt='#8a5f3e', deep='#4d3626', rock='#8a8f98', sky0='#6f9fd0', sky1='#e6ebf0',
         mtn='#8a9ab0', tree='#c0782c', trunk='#5c4030', snow='#f2f6fb', sun='#fff1c0',
         surf={DIRT: .45, GRAVEL: .20, MUD: .20, SNOW: .10, PACKED: .05}),
    dict(name='whiteout', decor=['pine', 'pine', 'rockdecor'], density=0.12, fog=0.58, snowfall=1.0,
         top='#e8eef6', dirt='#7d8798', deep='#444e5f', rock='#8a93a2', sky0='#b2c0d0', sky1='#eef2f6',
         mtn='#b6c4d6', tree='#35605e', trunk='#4a4038', snow='#f7faff', sun='#f8fafd',
         surf={SNOW: .72, PACKED: .10, ICE: .10, DIRT: .08}),
    dict(name='sunbelt', decor=['bush', 'cactus', 'bush', 'dune', 'broadleaf'], density=0.16, fog=0.10, snowfall=0.0,
         top='#d2b074', dirt='#b0773f', deep='#5c3d26', rock='#9a8a7a', sky0='#3b94e0', sky1='#d4ecff',
         mtn='#7096c0', tree='#648c3c', trunk='#6a4a32', snow='#f5f8fc', sun='#fff4c8',
         surf={HARDPACK: .35, GRAVEL: .30, ASPHALT: .35}),
]
BIOMES = []
for _b in _BIOME_SRC:
    d = dict(_b)
    for k in COLOR_KEYS:
        d[k] = hexc(d[k])
    BIOMES.append(d)

BIOME_LEN = 1000.0
BIOME_BLEND = 80.0
_biome_seed = [0]
_world = [worlds.make()]


def _biome_id(k):
    w = _world[0].map
    seq = w.sequence
    if 0 <= k < len(seq):
        return seq[k]                         # forced opening order
    if k == -1:
        return seq[0] if len(w.biomes) == 1 else MUDLANDS if MUDLANDS in w.biomes else w.biomes[0]
    pool = w.biomes
    return pool[int(hash_i(k, _biome_seed[0] + 77) * len(pool)) % len(pool)]


def biome_at(x):
    """-> (a, b, t): blend of biome a -> b with weight t."""
    x = x + BIOME_LEN * 0.5                 # segment 0 is centred on the start line
    k = math.floor((x + BIOME_BLEND) / BIOME_LEN)
    bx = k * BIOME_LEN
    t = smooth((x - bx + BIOME_BLEND) / (BIOME_BLEND * 2))
    a, b = _biome_id(k - 1), _biome_id(k)
    if x - bx > BIOME_BLEND:
        a, t = b, 0.0
    return a, b, t


def biome_id_at(x):
    a, b, t = biome_at(x)
    return b if t > 0.5 else a


def palette_at(x):
    a, b, t = biome_at(x)
    A, B = BIOMES[a], BIOMES[b]
    o = {'decor': B['decor'] if t > 0.5 else A['decor'], 'name': B['name'] if t > 0.5 else A['name'],
         'density': lerp(A['density'], B['density'], t), 'fog': lerp(A['fog'], B['fog'], t),
         'snowfall': lerp(A['snowfall'], B['snowfall'], t)}
    for k in COLOR_KEYS:
        o[k] = mixc(A[k], B[k], t)
    return o


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


def _f_hole(f, x):
    v = abs((x - f['x0']) / (f['x1'] - f['x0']) * 2 - 1)
    return -f['h'] * (1 - v ** 3)


def _f_log(f, x):
    c = (f['x0'] + f['x1']) * 0.5
    r = f['r']
    dx = x - c
    if abs(dx) >= r:
        return 0.0
    return max(0.0, math.sqrt(r * r - dx * dx) - 0.4 * r)


def _f_ledge(f, x):
    up = smooth((x - f['x0']) / 0.45)
    dn = smooth((x - (f['x1'] - 0.9)) / 0.9)
    return f['h'] * up * (1 - dn)


def _f_flat(f, x):
    return 0.0


def _f_kicker(f, x):
    u = (x - f['x0']) / (f['x1'] - f['x0'])
    return f['h'] * u ** 1.25


FEATURE = dict(rock=_f_rock, mound=_f_mound, ripple=_f_ripple, hole=_f_hole, log=_f_log,
               ledge=_f_ledge, flat=_f_flat, kicker=_f_kicker)

THEMES = {
    'cruise': ['mound', 'mound', 'ripple', 'rock', 'ice'],
    'rocky': ['rock', 'rock', 'rockfield', 'ledge', 'rock', 'climb'],
    'timber': ['log', 'logs', 'log', 'ledge', 'rock'],
    'mire': ['rut', 'rut', 'mudstretch', 'log', 'drift', 'rut'],
    'drifts': ['drift', 'drift', 'drift', 'mound', 'ice', 'rock'],
    'steep': ['climb', 'climb', 'mound', 'ledge', 'rock', 'drift'],
    'rally_flow': ['crest', 'whoops', 'mound', 'wash', 'whoops'],
    'rally_jumps': ['kicker', 'crest', 'kicker', 'mound', 'wash'],
    'rally_rough': ['wash', 'whoops', 'rocksm', 'wash', 'mound'],
    'rally_clear': ['mound', 'wash', 'mound'],
    'mixed': ['rock', 'log', 'rut', 'ledge', 'climb', 'drift', 'mudstretch', 'rockfield', 'ice', 'logs'],
}
THEME_NAMES = ['cruise', 'rocky', 'timber', 'mire', 'drifts', 'steep', 'mixed']      # themes the default maps pick from


class Terrain:
    def __init__(self, seed=1337, world=None):
        self.seed = int(seed)
        self.world = world or worlds.make()
        _world[0] = self.world
        _biome_seed[0] = self.seed
        self.chunks = {}
        self.zones = {}
        self.zp = {}
        self._ci = None
        self._ch = None
        self._surf = {}
        self.yield_rate = 4.0
        self.compact_rate = 0.55

    def difficulty(self, x):
        d = self.world.diff
        return clamp(d.start + (1.0 - d.start) * clamp((abs(x) - 120) / d.span, 0, 1), 0, 1)

    # ---- zone-level parameters (blended smoothly between neighbouring zones)
    def zone_param(self, z):
        p = self.zp.get(z)
        if p:
            return p
        s = self.seed

        def H(k):
            return hash_i(z, s + k)
        xc = (z + 0.5) * ZL
        d = self.difficulty(xc)
        near = abs(xc) < 100
        theme = 'cruise'
        mt = self.world.map
        if not near and mt.themes:
            theme = mt.themes[int(H(26) * len(mt.themes)) % len(mt.themes)]
        elif not near:
            w = [3 * (1 - d) + 0.4, 1, 1, 1 + d, 1, 1 + 0.5 * d, 1 + d]
            pick = H(26) * sum(w)
            for i, v in enumerate(w):
                pick -= v
                if pick <= 0:
                    theme = THEME_NAMES[i]
                    break
        bid = biome_id_at(xc)
        ov = self.world.map.surf
        weights = (ov.get(bid) if ov and bid in ov else BIOMES[bid]['surf'])
        pick = H(25) * sum(weights.values())
        surface = DIRT
        for m, v in weights.items():
            pick -= v
            if pick <= 0:
                surface = m
                break
        if near:
            surface = mt.start_surface if mt.start_surface is not None else (DIRT if abs(xc) < 60 else PACKED)
        soft = 1.0
        wm = self.world.map.soft * self.world.diff.soft
        if surface == SNOW:
            soft = (0.6 + 0.9 * H(27)) * (0.8 + 0.4 * d) * wm
        elif surface == MUD:
            soft = (0.8 + 0.5 * H(28)) * (0.85 + 0.3 * d) * wm
        rel = self.world.map.relief
        p = dict(hill=(0.3 + 0.7 * H(21)) * rel, rough=H(22) ** 1.6 * (0.1 + 0.6 * d),
                 climb=(H(24) * (0.2 + 0.8 * d) if H(23) > 0.45 else 0.0) * rel,
                 theme=theme, surface=surface, soft=soft)
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
        snowy = biome_id_at(x0 + ZL / 2) in (TAIGA, WHITEOUT)
        pool = THEMES[zp['theme']]
        cursor = x0 + 6 + r() * 10
        guard = 0
        while cursor < x_end - 4 and guard < 40:
            guard += 1
            typ = pool[int(r() * len(pool))]
            end = self._add_feature(lst, typ, cursor, r, sc, d, x_end, snowy, zp)
            gap_scale = (1.8 if zp['theme'] == 'cruise' else 1.0) * self.world.diff.gaps * self.world.map.gaps
            cursor = end + lerp(16, 5.5, d) * (0.6 + 0.8 * r()) * gap_scale
        return lst

    @staticmethod
    def _add_feature(lst, typ, x0, r, sc, d, x_end, snowy, zp):
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
            w = 9 + r() * 14
            return push(dict(t='mound', x0=x0, x1=x0 + w, h=(0.7 + 1.6 * r()) * sc))
        if typ == 'climb':
            w = 18 + r() * 16
            return push(dict(t='mound', x0=x0, x1=x0 + w, h=(2.0 + 3.2 * r()) * (0.6 + 0.6 * sc)))
        if typ == 'ripple':
            ln = 8 + r() * 12
            return push(dict(t='ripple', x0=x0, x1=x0 + ln, h=(0.06 + 0.12 * r()) * (0.6 + sc), n=round(ln / (1.6 + r() * 1.6))))
        if typ == 'log':
            rad = (0.22 + 0.2 * r()) * (0.8 + 0.5 * d)
            return push(dict(t='log', x0=x0, x1=x0 + rad * 2, r=rad, mat=WOOD))
        if typ == 'logs':
            x = x0
            for _ in range(2 + int(r() * 2)):
                rad = (0.22 + 0.2 * r()) * (0.8 + 0.5 * d)
                x = push(dict(t='log', x0=x, x1=x + rad * 2, r=rad, mat=WOOD)) + 2.0 + r() * 2.5
            return x
        if typ == 'ledge':
            L = 3 + r() * 6
            return push(dict(t='ledge', x0=x0, x1=x0 + L, h=(0.25 + 0.4 * r()) * (0.7 + 0.5 * sc), mat=ROCK))
        if typ == 'drift':           # heap of deep soft stuff (snow in the cold biomes, mud otherwise)
            w = 8 + r() * 10
            fd = zp['soft'] * (0.6 if snowy else 0.55) + 0.9 + 1.0 * d
            return push(dict(t='mound', x0=x0, x1=x0 + w, h=(0.5 + 0.8 * r()) * (0.7 + 0.5 * sc),
                             mat=SNOW if snowy else MUD, fd=fd, whole=True))
        if typ == 'rut':             # deep mud hole
            w = 3.5 + r() * 3.5
            return push(dict(t='hole', x0=x0, x1=x0 + w, h=(0.25 + 0.35 * r()) * (0.7 + sc * 0.6), mat=MUD, fd=1.1 + 0.8 * d, whole=True))
        if typ == 'mudstretch':
            L = 9 + r() * 10
            return push(dict(t='hole', x0=x0, x1=x0 + L, h=0.15, mat=MUD, fd=0.9 + 0.7 * d, whole=True))
        if typ == 'ice':
            L = 7 + r() * 8
            return push(dict(t='flat', x0=x0, x1=x0 + L, mat=ICE, whole=True))
        if typ == 'kicker':                   # dirt jump: ramp up, then nothing
            L = 8 + r() * 5
            return push(dict(t='kicker', x0=x0, x1=x0 + L, h=(0.6 + 1.3 * r()) * (0.55 + 0.6 * sc)))
        if typ == 'crest':                    # big rounded crest you can take at speed
            w = 14 + r() * 12
            return push(dict(t='mound', x0=x0, x1=x0 + w, h=(1.2 + 2.2 * r()) * (0.6 + 0.6 * sc)))
        if typ == 'whoops':                   # long rhythm section
            wl = 6 + r() * 4
            n = 3 + int(r() * 4)
            return push(dict(t='ripple', x0=x0, x1=x0 + wl * n, h=(0.25 + 0.35 * r()) * (0.5 + 0.7 * sc), n=n))
        if typ == 'wash':                     # washboard
            ln = 12 + r() * 16
            return push(dict(t='ripple', x0=x0, x1=x0 + ln, h=(0.04 + 0.06 * r()) * (0.6 + sc), n=round(ln / (0.9 + r() * 0.5))))
        if typ == 'rocksm':                   # a few small rocks to dodge or bump over
            n = 1 + int(r() * 3)
            x = x0
            for _ in range(n):
                w = 0.5 + 0.8 * r()
                H = (0.07 + 0.11 * r()) * (0.6 + sc)
                x = push(dict(t='rock', x0=x, x1=x + w, pts=_rock_profile(r, H), mat=ROCK)) + 2 + r() * 4
            return x
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
            if f['t'] in ('rock', 'log'):
                if FEATURE[f['t']](f, x) > 0.004:
                    m = f['mat']
            elif f.get('whole'):
                if f['x0'] + 0.3 < x < f['x1'] - 0.3 or f['t'] == 'flat':
                    m = f['mat']
            else:
                m = f['mat']  # ledge: whole footprint
        return m

    def raw_floor(self, x, m, h0):
        z = math.floor(x / ZL)
        S = MATERIALS[m]['S']
        fl = h0 - (S * self.zone_param(z)['soft'] if S > 0 else 0.0)
        if S > 0:
            for f in self.zone_features(z):
                if 'fd' in f and f['x0'] <= x <= f['x1']:
                    fl = self.base(x) - f['fd']
        return min(fl, h0)

    def base_height(self, x):
        return self.base(x)

    # ---- chunked samples:  (h, mat, floor, density, h0)
    def chunk(self, ci):
        c = self.chunks.get(ci)
        if c is not None:
            return c
        hs, ms, fls, h0s = [], [], [], []
        for i in range(SC + 1):
            x = (ci * SC + i) * DX
            h0 = self.raw_height(x)
            m = self.raw_mat(x)
            hs.append(h0)
            h0s.append(h0)
            ms.append(m)
            fls.append(self.raw_floor(x, m, h0))
        c = (hs, ms, fls, [0.0] * (SC + 1), h0s)
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

    def floor_at(self, i):
        ci = i // SC
        return self.chunk(ci)[2][i - ci * SC]

    def dens_at(self, i):
        ci = i // SC
        return self.chunk(ci)[3][i - ci * SC]

    def h0_at(self, i):
        ci = i // SC
        return self.chunk(ci)[4][i - ci * SC]

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
        """Soil/material properties under x (shared dict, don't keep a reference)."""
        i = round(x / DX)
        ci = i // SC
        c = self.chunk(ci)
        j = i - ci * SC
        m = c[1][j]
        M = MATERIALS[m]
        o = self._surf
        o['mat'] = m
        o['mu'] = M['mu']
        o['ks'] = M['ks']
        o['pb'] = M['pb']
        o['crr'] = M['crr']
        o['drag'] = M['drag']
        o['dig'] = M['dig']
        o['loose'] = M['loose']
        th = c[0][j] - c[2][j]
        o['soft'] = 0.0 if M['S'] <= 0 else clamp(th / 0.12, 0.0, 1.0)
        o['dens'] = c[3][j]
        o['h0'] = c[4][j]
        o['thick'] = th
        return o

    # ---- soil deformation under a wheel
    def disturb(self, cx, cy, R, px, ratio, spin, back, dt):
        """Wheel centre (cx,cy), radius R, contact x `px`.
        ratio: wheel load / bearing capacity (>1 => soil yields), spin: wheel slip speed beyond
        the dig threshold (m/s), back: +1/-1 direction soil is thrown (along +x)."""
        ky = 0.0
        if ratio > 1.0:
            ky = clamp(self.yield_rate * (ratio - 1.0) * dt, 0.0, 0.35)
        i0 = math.floor((cx - R) / DX)
        i1 = math.floor((cx + R) / DX) + 1
        sqrt = math.sqrt
        removed = 0.0
        comp = self.compact_rate * dt
        for i in range(i0, i1 + 1):
            dx = i * DX - cx
            if dx <= -R or dx >= R:
                continue
            arc = cy - sqrt(R * R - dx * dx)
            ci = i // SC
            c = self.chunk(ci)
            j = i - ci * SC
            hi = c[0][j]
            if hi <= arc:
                continue
            fli = c[2][j]
            if hi <= fli + 1e-4:
                continue
            M = MATERIALS[c[1][j]]
            new = hi - (hi - arc) * ky
            if spin > 0.0:
                new -= spin * M['dig'] * dt
            if new < fli:
                new = fli
            removed += hi - new
            c[0][j] = new
            d = c[3][j]
            c[3][j] = d + comp * (1.0 - d)
        if removed > 0.0 or ky > 0.0:
            self._relax(i0 - 4, i1 + 4)
        if removed > 0.0 and spin > 0.0:
            # throw part of it behind the wheel as a berm
            ic = round(px / DX) + back * (int(0.5 * R / DX) + 2)
            per = removed * 0.55 / 7.0
            for k in range(7):
                i = ic + back * k
                ci = i // SC
                c = self.chunk(ci)
                j = i - ci * SC
                top = c[4][j] + 0.25
                v = c[0][j] + per
                c[0][j] = v if v < top else top

    def _relax(self, i0, i1):
        """Loose soil slumps to its angle of repose (steep trench walls collapse inwards)."""
        slope = 0.55 * DX          # max height step per sample
        for i in range(i0, i1):
            ci = i // SC
            c = self.chunk(ci)
            j = i - ci * SC
            ci2 = (i + 1) // SC
            c2 = c if ci2 == ci else self.chunk(ci2)
            j2 = (i + 1) - ci2 * SC
            a, b = c[0][j], c2[0][j2]
            d = a - b
            if d > slope:               # a higher: move soil from a to b (only soft soil above the pan)
                mv = min((d - slope) * 0.5, a - c[2][j])
                if mv > 0:
                    c[0][j] = a - mv
                    c2[0][j2] = b + mv
            elif d < -slope:
                mv = min((-d - slope) * 0.5, b - c2[2][j2])
                if mv > 0:
                    c2[0][j2] = b - mv
                    c[0][j] = a + mv

    # ---- circle (wheel) vs polyline
    def contact_circle(self, cx, cy, R, out):
        """Fills out=[pen, nx, ny, px, py]; True on contact."""
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
