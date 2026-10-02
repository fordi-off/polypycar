"""Headless physics sanity tests:  python tests/test_physics.py   (or pytest tests)"""
import math
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from polypycar import terrain as T  # noqa: E402
from polypycar.car import Car  # noqa: E402


class Flat(T.Terrain):
    """Flat test field of one material."""

    def __init__(self, mat, soft=1.0):
        super().__init__(5)
        self.m, self.sf = mat, soft

    def raw_height(self, x):
        return 0.0

    def raw_mat(self, x):
        return self.m

    def raw_floor(self, x, m, h0):
        S = T.MATERIALS[m]['S']
        return h0 - S * self.sf if S > 0 else h0


def drive(mat, secs, throttle=1.0, pressure=1.0, low=False, lock=False, start=-100):
    car = Car(Flat(mat))
    car.reset(start)
    car.pressure, car.low, car.diff_lock = pressure, low, lock
    car._update_ratio()
    for _ in range(120):
        car.control(1 / 60, 0, 0, 0, 0)
        car.step(1 / 60)
    for _ in range(int(secs * 60)):
        car.control(1 / 60, throttle, 0, 0, 0)
        car.step(1 / 60)
    return car, car.x - start


def test_terrain_deterministic():
    a, b = T.Terrain(42), T.Terrain(42)
    assert all(a.h(x) == b.h(x) for x in range(-500, 3000, 37))


def test_static_ride_on_hard_ground():
    car = Car(Flat(T.ROCK))
    for _ in range(180):
        car.control(1 / 60, 0, 0, 0, 0)
        car.step(1 / 60)
    assert abs(math.degrees(car.a)) < 1.5 and abs(car.vx) < 0.1
    assert all(0.02 < w.pen < 0.12 for w in car.wheels)           # tyres squish a little
    assert all(0.55 < w.l < 0.95 for w in car.wheels)             # springs mid-travel
    loads = [w.Fn for w in car.wheels]
    assert max(loads) / min(loads) < 1.4                          # 6x6 shares the weight


def test_dirt_drive_and_shifts():
    car, dist = drive(T.DIRT, 20)
    assert car.vx > 10 and car.gear >= 5 and dist > 150


def test_soil_is_deformable_and_compacts():
    car, dist = drive(T.SNOW, 10, throttle=0.3, pressure=0.7, low=True, lock=True)
    t = car.t
    assert dist > 5
    path = range(round(-100 / T.DX), round(car.x / T.DX))
    assert max(t.dens_at(j) for j in path) > 0.3                        # wheels packed the track
    assert min(t.h_at(j) - t.h0_at(j) for j in path) < -0.01            # and left a rut


def test_wheelspin_digs_you_in():
    stuck, d1 = drive(T.SNOW, 20, throttle=0.6, pressure=1.0)
    assert d1 < 5 and max(w.z for w in stuck.wheels) > 0.5


def test_pressure_low_range_and_lock_get_you_through_snow():
    _, high = drive(T.SNOW, 20, throttle=0.6, pressure=1.0, low=False, lock=False)
    _, setup = drive(T.SNOW, 20, throttle=0.6, pressure=0.7, low=True, lock=True)
    assert setup > 40 and setup > 10 * max(high, 1.0)


def test_diff_lock_helps_in_mud():
    _, a = drive(T.MUD, 20, pressure=0.7, lock=False)
    _, b = drive(T.MUD, 20, pressure=0.7, lock=True)
    assert b > a * 1.2


def test_ice_is_slippery():
    ice, d_ice = drive(T.ICE, 6, throttle=1.0)
    dirt, d_dirt = drive(T.DIRT, 6, throttle=1.0)
    assert d_ice < d_dirt * 0.75
    assert max(abs(w.slip) for w in ice.wheels) > 3 * max(abs(w.slip) for w in dirt.wheels)


def test_reverse():
    car = Car(Flat(T.DIRT))
    for _ in range(60):
        car.control(1 / 60, 0, 0, 0, 0)
        car.step(1 / 60)
    for _ in range(60 * 5):
        car.control(1 / 60, 0, 1, 0, 0)
        car.step(1 / 60)
    assert car.gear == -1 and car.vx < -0.5


def test_rough_terrain_stays_finite():
    car = Car(T.Terrain(11))
    car.reset(2200)
    for _ in range(60 * 40):
        car.control(1 / 60, 0.7, 0, 0, 0)
        car.step(1 / 60)
        assert math.isfinite(car.x) and math.isfinite(car.a) and abs(car.vx) < 80


if __name__ == '__main__':
    for name, fn in list(globals().items()):
        if name.startswith('test_'):
            fn()
            print('ok', name)
