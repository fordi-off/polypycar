# PolyPyCar - snow & mud

A slow, heavy, goal-less low-poly 2D offroad sandbox in Python (pygame). Just you, a loaded 6x6 log
truck and an endless procedurally generated trail of **snow, mud, dirt and ice**. It's a battle for
traction and power: the ground gives way under your wheels, you dig yourself in if you mash the
throttle, and the right setup (tyre pressure, low range, diff lock) is what gets you through.

```
pip install -r requirements.txt
python -m polypycar            # --seed 123, --no-sound, --size 1920x1080, --fullscreen
```

(The earlier fast arcade version is kept at the git tag `v0.1-arcade`.)

## Controls
| key | action |
|---|---|
| W / Up | gas - hold to build power, **tap / feather it** in soft ground |
| S / Down | brake, then reverse |
| **L** | diff lock (shares torque between all axles - big help when one wheel spins) |
| **G** | low range (crawler gearing) |
| `[` `]` | tyre pressure - soft tyres have a bigger footprint, so they float on snow and mud |
| Space | handbrake |
| T, Q / E | auto / manual gearbox, shift down / up |
| A D / Left Right | lean the truck (pitch; strong in the air) |
| R | recover: drop the truck upright where it is |
| C, H, Tab, M, F11, Esc | paint, hide HUD, telemetry, mute, fullscreen, quit |

## How the ground works
Every 10 cm of terrain has a soft layer (snow 0.3-1.0 m, mud, dirt, packed snow, gravel) on top of a
hard pan; rock, logs and ice are hard.
* **Bearing capacity**: the soil can only carry so much pressure. Wheels that load it harder than it
  can bear *sink* until the footprint is big enough - so deep snow swallows narrow, over-inflated tyres.
* **Compaction**: wheels pack the soil. The rear axles ride in the front wheels' firmer track, and
  your own tracks are firmer the second time through.
* **Digging**: a spinning wheel throws soil backwards and digs. Dig down to the bare ground and you're
  stuck in a pit (you can see the dirt underneath).
* **Resistance**: sinkage adds rolling resistance, mud and snow add drag, loose soil slumps back into ruts.

## The truck (`polypycar/car.py`)
* ~7 t chassis, three axles, every wheel its own sprung mass: progressive springs, bump / rebound
  damping with blow-off, bump stops, ~0.7 m of travel. Weight transfer, squat and pitch come out naturally.
* Tyres: radial spring in series with the soil, slip-based friction curve per surface, rolling resistance.
* Diesel with a real torque curve and inertia, slipping clutch, 6 gears + reverse, low range, 6x6 with an
  inter-axle coupling that you can lock. Friction is solved with a linearised implicit step at 960 Hz.

## Layout
`terrain.py` heightfield, soil layers, zones/obstacles, biomes (no pygame) · `terrain_render.py` faceted
chunk surfaces + live soil layer · `scenery.py` sky, fog, snowfall, mountains · `car_render.py` truck
(3x supersampled) · `particles.py` · `hud.py` · `audio.py` synthesised diesel · `game.py` loop.

Tests: `python tests/test_physics.py`.
