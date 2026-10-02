# PolyPyCar

A chill, goal-less, low-poly 2D offroad sandbox in Python (pygame). Just you, a truck and an
endless procedurally generated road that keeps changing: rocks, logs, whoops, washboard, ledges,
ramps, potholes and mud pits, across meadow / desert / canyon / tundra biomes. It gets rougher
the further you drive.

```
pip install -r requirements.txt
python -m polypycar            # --seed 123, --no-sound, --size 1920x1080, --fullscreen
```

## Controls
| key | action |
|---|---|
| W / Up | gas |
| S / Down | brake, then reverse |
| A D / Left Right | lean the truck (pitch; strong in the air) |
| Space | handbrake |
| `[` `]` | tyre pressure (soft = squishy + more grip on loose ground) |
| T, Q / E | auto / manual gearbox, shift down / up |
| R | reset upright | 
| C | paint colour |
| H, Tab, M, F11 | hide HUD, telemetry, mute, fullscreen |

## What's simulated (`polypycar/car.py`)
* **Chassis** rigid body with pitch inertia; weight transfer, squat and dive come out naturally.
* **Suspension** per wheel: progressive spring, separate bump/rebound damping with blow-off,
  bump stops, 0.5 m of travel. Each wheel is its own sprung mass.
* **Tyres** radial spring/damper against the terrain polyline (rolls over rocks, falls into
  potholes), stiffness set by pressure, rim bottoming, visibly squishing polygon tyres.
* **Grip** slip-based friction curve with per-surface friction, rolling resistance and mud drag;
  stable at 960 Hz via a linearised implicit friction step.
* **Drivetrain** torque curve, engine inertia, idle governor, rev limiter, slipping auto-clutch,
  5 gears + reverse, final drive, limited-slip AWD, brakes, handbrake.

## Layout
`terrain.py` heightfield + zones/features + biomes (no pygame) · `terrain_render.py` faceted chunk
surfaces · `scenery.py` sky/mountains/clouds · `car_render.py` truck (3x supersampled) ·
`particles.py` · `hud.py` · `audio.py` synthesised engine · `game.py` loop.

Tests: `python tests/test_physics.py`.
