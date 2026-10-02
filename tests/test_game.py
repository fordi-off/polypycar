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
    assert s['pickup4x4']['mass'] < s['logger6x6']['mass'] < s['hauler8x8']['mass']
    assert s['pickup4x4']['top_kmh'] > s['hauler8x8']['top_kmh']
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


if __name__ == '__main__':
    for name, fn in list(globals().items()):
        if name.startswith('test_'):
            fn()
            print('ok', name)
