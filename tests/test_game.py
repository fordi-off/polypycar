"""Tests for the game layer: drivetrain, vehicles, worlds, settings. Headless:  python tests/test_game.py"""
import math
import os
import sys
import tempfile

os.environ.setdefault('SDL_VIDEODRIVER', 'dummy')
os.environ.setdefault('SDL_AUDIODRIVER', 'dummy')
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
import pygame  # noqa: E402

pygame.init()
from polypycar import vehicles as V, worlds, terrain as T  # noqa: E402
from polypycar.drivetrain import Drivetrain, OPEN, LSD, LOCK  # noqa: E402
from polypycar.car import Car  # noqa: E402
from polypycar.settings import Settings, ACTION_IDS  # noqa: E402
from test_physics import Flat, drive  # noqa: E402


# ------------------------------------------------------------------ drivetrain
def test_diff_biases_toward_the_slower_output():
    d = Drivetrain(dict(tree=('center', 0, 1)), 2)
    out = [0, 0]
    d.set_mode('center', LSD)
    d.distribute(1000, [10.0, 5.0], out)          # axle 0 spinning faster
    assert out[1] > out[0] and abs(sum(out) - 2000) < 1e-6


def test_open_diff_gives_less_bias_than_locked():
    d = Drivetrain(dict(tree=('center', 0, 1)), 2)
    out_o, out_l = [0, 0], [0, 0]
    d.set_mode('center', OPEN)
    d.distribute(1000, [10.0, 0.0], out_o)
    d.set_mode('center', LOCK)
    d.distribute(1000, [10.0, 0.0], out_l)
    assert abs(out_l[1] - out_l[0]) > abs(out_o[1] - out_o[0]) * 5


def test_disconnecting_an_axle_gives_it_no_torque():
    d = Drivetrain(dict(tree=('center', 0, ('inter', 1, 2)), disconnectable=[0]), 3)
    d.toggle_axle(0)
    out = [0, 0, 0]
    d.distribute(500, [1.0, 1.0, 1.0], out)
    assert out[0] == 0 and d.drive_name() == '6x4'
    d.toggle_axle(1)                              # not disconnectable: ignored
    assert d.axle_on[1]


def test_lock_all_and_reset():
    for spec in V.VEHICLES:
        car = Car(Flat(T.ROCK), spec)
        car.diff_lock = True
        assert car.drive.all_locked
        car.diff_lock = False
        assert not car.drive.all_locked


# ------------------------------------------------------------------ vehicles & engines
def test_engine_curves_are_sane_and_used_by_the_physics():
    for spec in V.VEHICLES:
        e = spec.engine
        tq, rpm_t = e.peak_torque()
        hp, rpm_p = e.peak_power()
        assert e.idle < rpm_t < rpm_p <= e.redline * 1.3
        assert abs(e.hp_at(rpm_p) - e.torque_at(rpm_p) * rpm_p / 7127.0) < 1e-6
        car = Car(Flat(T.ROCK), spec)
        assert car.engine is e
        for rpm in (e.idle, rpm_t, e.redline):
            assert abs(car.engine_torque(rpm, 1.0) - e.torque_at(rpm)) < 1e-6 or rpm < e.idle + 1


def test_every_vehicle_settles_level_and_drives():
    for spec in V.VEHICLES:
        car = Car(Flat(T.ROCK), spec)
        for _ in range(240):
            car.control(1 / 60, 0, 0, 0, 0)
            car.step(1 / 60)
        assert abs(math.degrees(car.a)) < 1.5, spec.name
        loads = [w.Fn for w in car.wheels]
        assert max(loads) / min(loads) < 1.5, spec.name
        for _ in range(60 * 8):
            car.control(1 / 60, 1.0, 0, 0, 0)
            car.step(1 / 60)
        assert car.vx > 6, spec.name


def test_vehicle_stats_are_ordered():
    s = {v.id: V.stats(v) for v in V.VEHICLES}
    assert s['rally4x4']['mass'] < s['pickup4x4']['mass'] < s['logger6x6']['mass'] < s['hauler8x8']['mass']
    assert s['rally4x4']['top_kmh'] > s['pickup4x4']['top_kmh'] > s['hauler8x8']['top_kmh']
    assert s['hauler8x8']['hp'] > s['logger6x6']['hp'] > s['pickup4x4']['hp']


def test_low_range_changes_the_ratio():
    car = Car(Flat(T.ROCK), V.LOGGER)
    hi = car.ratio
    car.low = True
    assert abs(car.ratio / hi - V.LOGGER.drivetrain['low_mult']) < 1e-6


def test_axle_disconnect_changes_traction():
    full, d_full = drive(T.DIRT, 6, throttle=1.0)
    car = Car(Flat(T.DIRT))
    car.drive.toggle_axle(0)
    car.reset(-100)
    for _ in range(300):
        car.control(1 / 60, 1.0, 0, 0, 0)
        car.step(1 / 60)
    assert car.wheels[0].Tdrv == 0 and car.drive.drive_name() == '6x4'


# ------------------------------------------------------------------ worlds
def test_every_map_and_difficulty_generates():
    for m in worlds.MAPS:
        for d in worlds.DIFFICULTIES:
            t = T.Terrain(5, worlds.make(m.id, d.id))
            for x in range(0, 6000, 53):
                assert math.isfinite(t.h(x))
            allowed = set(m.biomes)
            assert all(T.biome_id_at(x) in allowed for x in range(-500, 6000, 250)), m.id


def test_difficulty_makes_soil_deeper():
    easy = T.Terrain(5, worlds.make('whiteout', 'easy'))
    brutal = T.Terrain(5, worlds.make('whiteout', 'brutal'))
    z = [z for z in range(3, 60) if easy.zone_param(z)['surface'] == T.SNOW][0]
    assert brutal.zone_param(z)['soft'] > easy.zone_param(z)['soft'] * 1.3


def test_start_biome():
    assert T.biome_id_at(0) is not None
    t = T.Terrain(9, worlds.make('endless'))
    assert T.BIOMES[T.biome_id_at(0)]['name'] == 'highland'
    t = T.Terrain(9, worlds.make('mudbog'))
    assert T.BIOMES[T.biome_id_at(0)]['name'] == 'mudlands'


# ------------------------------------------------------------------ rally stage + rally car
def test_rally_map_is_all_firm_ground():
    for d in worlds.DIFFICULTIES:
        t = T.Terrain(4, worlds.make('rally', d.id))
        for z in range(0, 60):
            assert t.zone_param(z)['surface'] in (T.HARDPACK, T.GRAVEL, T.ASPHALT)
        assert max(t.h_at(i) - t.floor_at(i) for i in range(0, 20000, 7)) < 0.1      # no deep soil anywhere
        assert all(T.biome_id_at(x) == T.SUNBELT for x in range(-400, 6000, 200))


def test_rally_car_is_fast_on_firm_ground_and_useless_in_snow():
    car = Car(Flat(T.ASPHALT), V.RALLY)
    car.reset(-100)
    for _ in range(120):
        car.control(1 / 60, 0, 0, 0, 0)
        car.step(1 / 60)
    peak = 0.0
    for _ in range(60 * 30):
        car.control(1 / 60, 1.0, 0, 0, 0)
        car.step(1 / 60)
        peak = max(peak, car.vx * 3.6)
    assert peak > 190
    snow = Car(Flat(T.SNOW), V.RALLY)
    snow.reset(-100)
    snow.pressure = 0.5
    for _ in range(120):
        snow.control(1 / 60, 0, 0, 0, 0)
        snow.step(1 / 60)
    for _ in range(60 * 20):
        snow.control(1 / 60, 0.5, 0, 0, 0)
        snow.step(1 / 60)
    assert snow.x + 100 < 40


def test_single_range_vehicle_ignores_low_range():
    car = Car(Flat(T.ASPHALT), V.RALLY)
    assert not car.drive.has_range
    r = car.ratio
    car.low = True
    assert not car.low and car.ratio == r


def test_rally_map_suits_the_rally_car_not_the_hauler():
    def run(spec):
        t = T.Terrain(7, worlds.make('rally', 'normal'))
        c = Car(t, spec)
        c.reset(0)
        for _ in range(60 * 25):
            c.control(1 / 60, 1.0, 0, 0, 0)
            c.step(1 / 60)
        return c.x
    assert run(V.RALLY) > run(V.HAULER) * 1.4


# ------------------------------------------------------------------ display
def test_borderless_uses_the_desktop_resolution_and_keeps_the_windowed_size():
    from polypycar.app import App
    s = Settings(os.path.join(tempfile.mkdtemp(), 's.json'))
    s['resolution'] = [1280, 720]
    app = App(s)
    app.desktop = (1920, 1080)
    App._desktop = staticmethod(lambda: (1920, 1080))
    s['display_mode'] = 'borderless'
    app.apply_display()
    assert app.desktop == (1920, 1080)
    assert s['resolution'] == [1280, 720]                 # windowed choice untouched
    from polypycar.scenes import SettingsScene
    page = SettingsScene(app)._build('Video')
    res = [w for w in page.widgets if getattr(w, 'label', '') == 'Resolution'][0]
    assert res.locked() and res.opts == [((1920, 1080), '1920 x 1080  (desktop)')]
    before = list(s['resolution'])
    res.step(1)
    res.click((0, 0), (0, 0, 800, 50), 1.0)
    assert s['resolution'] == before                      # cannot be changed while borderless
    s['display_mode'] = 'windowed'
    assert not res.locked() and len(res.opts) > 1


# ------------------------------------------------------------------ settings & keys
def test_settings_roundtrip_and_robust_load():
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, 's.json')
        s = Settings(path)
        s['fps_target'] = 144
        s['display_mode'] = 'borderless'
        s.save()
        s2 = Settings(path)
        assert s2['fps_target'] == 144 and s2['display_mode'] == 'borderless'
        with open(path, 'w') as f:
            f.write('{ not json')
        s3 = Settings(path)                       # corrupt file => defaults, no crash
        assert s3['fps_target'] == 60
        with open(path, 'w') as f:
            f.write('{"fps_target": "fast", "binds": {"throttle": ["k"]}}')
        s4 = Settings(path)                       # wrong types ignored, partial binds kept, others filled in
        assert s4['fps_target'] == 60 and s4.key_names('throttle')[0] == 'k' and 'brake' in s4.data['binds']


def test_key_rebinding_swaps_conflicts():
    s = Settings(os.path.join(tempfile.mkdtemp(), 's.json'))
    assert s.keys('throttle')
    swapped = s.set_bind('handbrake', 0, pygame.K_w)
    assert swapped == 'throttle'
    assert s.key_names('handbrake')[0] == 'w' and s.key_names('throttle')[0] == 'space'
    assert s.action_for_key(pygame.K_w) == 'handbrake'
    s.clear_bind('handbrake', 0)
    assert s.key_names('handbrake')[0] == ''
    s.reset_binds()
    assert s.key_names('handbrake')[0] == 'space'
    assert all(s.keys(a) for a in ACTION_IDS)


def test_default_binds_have_no_conflicts():
    s = Settings(os.path.join(tempfile.mkdtemp(), 's.json'))
    seen = {}
    for a in ACTION_IDS:
        for k in s.keys(a):
            assert k not in seen, '%s clashes with %s' % (a, seen.get(k))
            seen[k] = a


def test_trophy_truck_is_rear_drive_by_default_and_very_powerful():
    spec = V.get('trophy4x4')
    car = Car(T.Terrain(1, worlds.make('rally', 'normal')), spec)
    assert car.drive.axle_on == [False, True] and car.drive.drive_name() == '4x2'
    car.drive.toggle_axle(0)
    assert car.drive.drive_name() == '4x4'
    st = V.stats(spec)
    assert st['hp'] > 900 and st['hp'] > 2 * V.stats(V.get('pickup4x4'))['hp'] and st['travel'] > 0.7


# ------------------------------------------------------------------ GPU renderer (skipped without moderngl / EGL)
def test_triangulate_concave_polygon_area():
    from polypycar.gfx import triangulate
    pts = [(0, 0), (4, 0), (4, 4), (2, 1), (0, 4)]                   # concave 'M' shape
    idx = triangulate(pts)
    area = sum(abs((pts[idx[k + 1]][0] - pts[idx[k]][0]) * (pts[idx[k + 2]][1] - pts[idx[k]][1]) -
                   (pts[idx[k + 2]][0] - pts[idx[k]][0]) * (pts[idx[k + 1]][1] - pts[idx[k]][1])) / 2 for k in range(0, len(idx), 3))
    assert abs(area - 10.0) < 1e-9, area


def test_gpu_renderer_draws_the_world_offscreen():
    try:
        import moderngl
        ctx = moderngl.create_standalone_context(backend='egl')
    except Exception:
        print('   (no offscreen OpenGL here - skipped)')
        return
    from polypycar import gfx
    from polypycar.session import Session
    from polypycar.settings import Settings
    st = Settings(os.path.join(tempfile.mkdtemp(), 's.json'))
    gl = gfx.GLRenderer(ctx, target=ctx.simple_framebuffer((640, 360)))
    old = gfx.ACTIVE
    gfx.ACTIVE = gl
    try:
        sess = Session(st, 'logger6x6', 0, worlds.make('snowfield', 'normal', True), 3)
        for _ in range(30):
            sess.update(1 / 60, __import__('polypycar.session', fromlist=['Controls']).Controls())
        gl.begin(640, 360)
        sess.draw(pygame.Surface((640, 360)))
        raw = gl.target.read(components=3)
        img = pygame.image.frombuffer(raw, (640, 360), 'RGB')
        sky, ground = img.get_at((20, 360 - 8)), img.get_at((320, 360 - 40))
        assert tuple(sky) != tuple(ground)
        assert sum(ground[:3]) > 30                                    # terrain mesh was drawn, not left at the clear colour
        assert sess.chunks.soil_vertices(sess.view, 2) is None or sess.chunks.soil_vertices(sess.view, 2).shape[1] == 6
    finally:
        gfx.ACTIVE = old


if __name__ == '__main__':
    for name, fn in list(globals().items()):
        if name.startswith('test_'):
            fn()
            print('ok', name)
