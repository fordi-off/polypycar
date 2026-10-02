"""Headless physics sanity tests: python -m pytest tests  (or python tests/test_physics.py)"""
import math
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from polypycar.terrain import Terrain  # noqa: E402
from polypycar.car import Car  # noqa: E402


def settle(car, secs=3):
    for _ in range(int(secs * 60)):
        car.control(1 / 60, 0, 0, 0, 0)
        car.step(1 / 60)


def test_terrain_deterministic():
    a, b = Terrain(42), Terrain(42)
    assert all(a.h(x) == b.h(x) for x in range(-500, 3000, 37))


def test_static_ride():
    t = Terrain(1)
    car = Car(t)
    settle(car)
    assert abs(car.a) < 0.05 and abs(car.vx) < 0.1
    assert all(0.03 < w.pen < 0.08 for w in car.wheels)           # tyres squish a little
    assert all(0.3 < w.l < 0.65 for w in car.wheels)              # springs mid-travel


def test_low_pressure_squishes_more():
    t = Terrain(1)
    pens = []
    for p in (1.0, 0.4):
        car = Car(t)
        car.pressure = p
        settle(car)
        pens.append(car.wheels[0].pen)
    assert pens[1] > pens[0] * 1.8


def test_accelerates_and_shifts():
    t = Terrain(1)
    car = Car(t)
    settle(car, 1)
    gears = set()
    for _ in range(60 * 7):   # flat start area only
        car.control(1 / 60, 1, 0, 0, 0)
        car.step(1 / 60)
        gears.add(car.gear)
    assert car.vx > 20 and {1, 2} <= gears and car.rpm < 7000


def test_reverse_and_brake():
    t = Terrain(1)
    car = Car(t)
    settle(car, 1)
    for _ in range(60 * 3):
        car.control(1 / 60, 0, 1, 0, 0)
        car.step(1 / 60)
    assert car.gear == -1 and car.vx < -2


def test_rough_terrain_stays_finite():
    t = Terrain(11)
    car = Car(t)
    car.reset(6000)
    for _ in range(60 * 40):
        car.control(1 / 60, 1, 0, 0, 0)
        car.step(1 / 60)
        assert math.isfinite(car.x) and math.isfinite(car.a) and abs(car.vx) < 100


if __name__ == '__main__':
    for name, fn in list(globals().items()):
        if name.startswith('test_'):
            fn()
            print('ok', name)
