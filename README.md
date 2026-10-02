# PolyPyCar - snow & mud

A slow, heavy, goal-less low-poly 2D offroad game in Python (pygame). Pick a vehicle in the garage, pick a
map, and crawl through an endless procedurally generated world of **snow, mud, dirt and ice**. It's a battle
for traction and power: the ground gives way under your wheels, you dig yourself in if you mash the
throttle, and the right setup (tyre pressure, low range, diff locks) is what gets you through.

```
pip install -r requirements.txt
python -m polypycar            # --windowed to force a window, --reset-settings to start fresh
```

## The game
* **Main menu** with a live demo drive behind it. **Drive** -> **Garage** -> **Map** -> go. *Quick start* repeats your last setup.
* **Garage**: three vehicles with their own engine, gearbox, driveline and body. The engine panel plots the
  real torque and horsepower curves - the very data the physics runs on (hover the graph to read it).
  | vehicle | | engine |
  |---|---|---|
  | Zephyr GT Rally | sleek AWD rally coupe, built for the Rally Stage | 2.0 L turbo petrol, 350 hp, 248 km/h |
  | Ridgeback 4x4 | quick, light pickup | 3.0 L twin-turbo diesel, 239 hp |
  | Timberjack 6x6 | log truck, the all-rounder | 12.0 L diesel, 409 hp, 1615 Nm |
  | Behemoth 8x8 | 12-tonne container hauler | 13.0 L twin-turbo diesel, 600 hp, 2385 Nm |
* **Maps**: Endless Trail, Snowfield, Mud Bog, Highland Pass, Whiteout and **Rally Stage** (a flat-out speed map: hard-packed road,
  gravel and asphalt, crests, rhythm sections and jumps - no mud or snow) - each with Easy / Normal / Hard / Brutal
  and an optional seed. Biomes: taiga, mudlands, highland, whiteout, sunbelt.
* **Settings** (saved automatically to `~/.polypycar/settings.json`, or `$POLYPYCAR_HOME`):
  display mode (windowed / borderless fullscreen / exclusive fullscreen; borderless always uses your true desktop
  resolution, so the resolution row is locked there), resolution, render scale, FPS limit
  (30 - 240 or unlimited), FPS counter, quality preset, snowfall and particle amount, fog, vehicle AA, master /
  engine / wind volume, units (km/h or mph), throttle build-up speed, camera zoom and look-ahead, default tyre
  pressure and gearbox, HUD and menu scale, and **full key rebinding** (two slots per action, conflicts are swapped).

## Driving
| default key | action |
|---|---|
| W / Up | gas - hold to build power, **tap / feather it** in soft ground |
| S / Down | brake, then reverse |
| **X** | **transmission app** (click it - see below) |
| G / L | low range / lock all diffs (same switches as the app) |
| `[` `]` | tyre pressure - soft tyres have a bigger footprint, so they float on snow and mud |
| Space | handbrake |
| T, Q / E | auto / manual gearbox, shift down / up |
| A D / Left Right | lean the vehicle (pitch; strong in the air) |
| R | recover the vehicle upright |
| Tab, H, M, -/=, F11, F12, Esc | telemetry, hide HUD, mute, camera zoom, fullscreen, screenshot, pause menu |

### Transmission app
A schematic of the real driveline, drawn from the vehicle's own drivetrain: engine -> clutch -> gearbox ->
transfer case -> a tree of differentials -> axles. **Everything in it is a button that changes the physics**:
gearbox auto/manual and shifting, **HIGH / LOW range**, each differential **OPEN / LSD / LOCK**, and per-axle
**disconnect** (6x6 -> 6x4). Line thickness and colour show where the torque goes; tyres turn red when they spin.
So "low gear + fully locked 6x6" is two clicks. A telemetry app plots the live operating point on the engine curve.

## How the ground works
Every 10 cm of terrain has a soft layer (snow 0.3 - 1.0 m, mud, dirt, packed snow, gravel) on a hard pan; rock,
logs and ice are hard.
* **Bearing capacity**: soil can only carry so much pressure; wheels that load it harder *sink* until the
  footprint is big enough - deep snow swallows narrow, over-inflated tyres.
* **Compaction**: wheels pack the soil. Rear axles ride in the front wheels' firmer track.
* **Digging**: a spinning wheel throws soil backwards and digs - dig to bare ground and you're in a pit.
* **Resistance**: sinkage adds rolling resistance, mud and snow add drag, loose soil slumps back into ruts.

## Code map (`polypycar/`)
`car.py` physics: suspension, tyres on soil, engine, clutch, tree-driven drivetrain (960 Hz, implicit friction and
clutch so huge ratios stay stable) · `drivetrain.py` differential tree · `vehicles.py` vehicle specs, engines and
derived stats - **add a vehicle by adding a spec + art routine** · `vehicle_art.py` body art · `terrain.py` /
`worlds.py` world generation, soil, biomes, map types · `terrain_render.py`, `scenery.py`, `car_render.py`,
`particles.py` rendering · `session.py` a running world · `hud_apps.py` HUD and apps · `ui.py` widgets and the engine
graph · `scenes.py` menus, garage, map select, drive, pause · `settings.py` · `app.py` window, display modes, FPS ·
`audio.py` synthesised sound.

Tests: `python tests/test_physics.py` and `python tests/test_game.py`.
