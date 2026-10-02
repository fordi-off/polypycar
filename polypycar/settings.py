"""Persistent settings + key bindings (JSON in ~/.polypycar, override with $POLYPYCAR_HOME)."""
import copy
import json
import os
from pathlib import Path

import pygame

# action id -> (label, group, default keys [primary, secondary])
ACTIONS = [
    ('throttle', 'Throttle', 'Driving', ['w', 'up']),
    ('brake', 'Brake / reverse', 'Driving', ['s', 'down']),
    ('lean_back', 'Lean back (nose up)', 'Driving', ['a', 'left']),
    ('lean_fwd', 'Lean forward (nose down)', 'Driving', ['d', 'right']),
    ('handbrake', 'Handbrake', 'Driving', ['space']),
    ('reset', 'Recover vehicle', 'Driving', ['r']),
    ('shift_up', 'Shift up (manual)', 'Transmission', ['e']),
    ('shift_down', 'Shift down (manual)', 'Transmission', ['q']),
    ('toggle_auto', 'Auto / manual gearbox', 'Transmission', ['t']),
    ('toggle_low', 'Low / high range', 'Transmission', ['g']),
    ('toggle_lock', 'Lock / unlock all diffs', 'Transmission', ['l']),
    ('press_down', 'Tyre pressure -', 'Vehicle', ['[']),
    ('press_up', 'Tyre pressure +', 'Vehicle', [']']),
    ('paint', 'Next paint', 'Vehicle', ['c']),
    ('app_trans', 'Transmission app', 'Interface', ['x']),
    ('app_telem', 'Telemetry', 'Interface', ['tab']),
    ('toggle_hud', 'Hide / show HUD', 'Interface', ['h']),
    ('zoom_in', 'Camera zoom in', 'Interface', ['=']),
    ('zoom_out', 'Camera zoom out', 'Interface', ['-']),
    ('mute', 'Mute sound', 'Interface', ['m']),
    ('fullscreen', 'Toggle fullscreen', 'Interface', ['f11']),
    ('pause', 'Pause / menu', 'Interface', ['escape']),
]
ACTION_IDS = [a[0] for a in ACTIONS]
ACTION_LABEL = {a[0]: a[1] for a in ACTIONS}

DEFAULTS = {
    # video
    'display_mode': 'windowed',          # windowed | borderless | fullscreen
    'resolution': [1280, 720],
    'render_scale': 1.0,
    'fps_target': 60,                    # 0 = unlimited
    'show_fps': False,
    'quality': 'high',                   # low | medium | high
    'snow_density': 1.0,
    'particles': 1.0,
    'fog': True,
    'car_aa': True,
    # audio
    'master_volume': 0.8,
    'engine_volume': 0.8,
    'wind_volume': 0.5,
    # gameplay
    'units': 'kmh',
    'throttle_ramp': 0.9,                # keyboard: how fast holding the gas builds power (1/s)
    'camera_zoom': 22.0,                 # metres of world visible vertically
    'camera_lookahead': 1.0,
    'auto_gearbox': True,
    'default_pressure': 1.0,
    # interface
    'ui_scale': 1.0,
    'hud_scale': 1.0,
    'hud_gauge': True,
    'hud_hints': True,
    'app_trans_open': False,
    # selections
    'last': {'vehicle': 'logger6x6', 'paint': 0, 'map': 'endless', 'difficulty': 'normal', 'seed': 0, 'snowfall': True},
    'binds': {a[0]: list(a[3]) for a in ACTIONS},
}

RESOLUTIONS = [(1024, 576), (1280, 720), (1366, 768), (1600, 900), (1920, 1080), (2560, 1440), (3840, 2160)]
FPS_OPTIONS = [30, 45, 60, 75, 90, 120, 144, 165, 240, 0]
QUALITY = {
    'low': dict(particles=0.4, snow=0.35, soil_step=3, fog=False, car_ss=2, mountains=2),
    'medium': dict(particles=0.75, snow=0.7, soil_step=2, fog=True, car_ss=2, mountains=3),
    'high': dict(particles=1.0, snow=1.0, soil_step=2, fog=True, car_ss=3, mountains=4),
}


def config_dir():
    d = Path(os.environ.get('POLYPYCAR_HOME') or (Path.home() / '.polypycar'))
    return d


def _merge(base, over):
    out = copy.deepcopy(base)
    for k, v in (over or {}).items():
        if k in out:
            if isinstance(out[k], dict) and isinstance(v, dict):
                out[k] = _merge(out[k], v)
            elif type(out[k]) == type(v) or (isinstance(out[k], (int, float)) and isinstance(v, (int, float)) and not isinstance(v, bool)):
                out[k] = v
    return out


class Settings:
    def __init__(self, path=None):
        self.path = Path(path) if path else config_dir() / 'settings.json'
        self.data = copy.deepcopy(DEFAULTS)
        self._codes = {}
        self.load()

    # -------------------------------------------------------------- io
    def load(self):
        try:
            with open(self.path, 'r', encoding='utf-8') as f:
                self.data = _merge(DEFAULTS, json.load(f))
        except (OSError, ValueError):
            self.data = copy.deepcopy(DEFAULTS)
        for a in ACTION_IDS:                      # fill in any action missing from an older file
            self.data['binds'].setdefault(a, list(DEFAULTS['binds'][a]))
        self._codes.clear()

    def save(self):
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix('.tmp')
            with open(tmp, 'w', encoding='utf-8') as f:
                json.dump(self.data, f, indent=2)
            os.replace(tmp, self.path)
            return True
        except OSError:
            return False

    def __getitem__(self, k):
        return self.data[k]

    def __setitem__(self, k, v):
        self.data[k] = v

    def reset_all(self):
        last = self.data['last']
        self.data = copy.deepcopy(DEFAULTS)
        self.data['last'] = last
        self._codes.clear()

    # -------------------------------------------------------------- quality presets
    @property
    def q(self):
        return QUALITY.get(self.data['quality'], QUALITY['high'])

    # -------------------------------------------------------------- key binds
    @staticmethod
    def code(name):
        try:
            return pygame.key.key_code(name)
        except (ValueError, pygame.error):
            return None

    def keys(self, action):
        """pygame key codes bound to an action (cached)."""
        c = self._codes.get(action)
        if c is None:
            c = [k for k in (self.code(n) for n in self.data['binds'].get(action, []) if n) if k is not None]
            self._codes[action] = c
        return c

    def key_names(self, action):
        b = self.data['binds'].get(action, [])
        return [(b[i] if i < len(b) else '') for i in range(2)]

    def action_for_key(self, key):
        for a in ACTION_IDS:
            if key in self.keys(a):
                return a
        return None

    def set_bind(self, action, slot, key):
        """Bind `key` (pygame code) to slot 0/1 of action. A key already used elsewhere is swapped
        into the slot we're replacing so nothing is left silently unbound."""
        name = pygame.key.name(key)
        if not name:
            return None
        binds = self.data['binds']
        mine = binds.setdefault(action, ['', ''])
        while len(mine) < 2:
            mine.append('')
        old = mine[slot]
        swapped = None
        for a, names in binds.items():
            for i, n in enumerate(names):
                if n == name and not (a == action and i == slot):
                    names[i] = old if a != action else old
                    swapped = a
        mine[slot] = name
        self._codes.clear()
        return swapped

    def clear_bind(self, action, slot):
        b = self.data['binds'].setdefault(action, ['', ''])
        while len(b) < 2:
            b.append('')
        b[slot] = ''
        self._codes.clear()

    def reset_binds(self):
        self.data['binds'] = {a[0]: list(a[3]) for a in ACTIONS}
        self._codes.clear()

    def held(self, action, pressed):
        """pressed: pygame.key.get_pressed() sequence."""
        for k in self.keys(action):
            try:
                if pressed[k]:
                    return True
            except IndexError:
                pass
        return False
