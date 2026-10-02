"""Vehicle registry. Every vehicle is pure data: physics, engine curve, gearbox, driveline tree,
collision points and which art routine draws it. The garage graphs plot the very same engine
curve the physics integrates, so what you read there is what you get in the snow."""
import math
from dataclasses import dataclass, field

HP_DIV = 7127.0          # Nm * rpm / 7127 = hp (metric)


@dataclass
class Engine:
    name: str
    config: str                      # e.g. "12.0 L inline-6 turbo diesel"
    curve: list                      # [(rpm, Nm)] at full throttle, before torque_scale
    idle: float
    redline: float
    inertia: float = 1.6
    torque_scale: float = 1.0
    brake0: float = 60.0             # engine braking: brake0 + brake1 * rpm  (Nm)
    brake1: float = 0.06
    cylinders: int = 6
    _cache: dict = field(default_factory=dict, repr=False, compare=False)

    def torque_at(self, rpm):
        c = self.curve
        if rpm <= c[0][0]:
            return c[0][1] * self.torque_scale
        for i in range(1, len(c)):
            if rpm <= c[i][0]:
                a, b = c[i - 1], c[i]
                return (a[1] + (b[1] - a[1]) * ((rpm - a[0]) / (b[0] - a[0]))) * self.torque_scale
        return 0.0

    def hp_at(self, rpm):
        return self.torque_at(rpm) * rpm / HP_DIV

    def sweep(self, step=25):
        sw = self._cache.get(step)
        if sw is None:
            top = self.curve[-1][0]
            sw = self._cache[step] = [(r, self.torque_at(r), self.hp_at(r)) for r in range(0, int(top) + 1, step)]
        return sw

    def peak_torque(self):
        v = self._cache.get('pt')
        if v is None:
            v = self._cache['pt'] = max(((t, r) for r, t, _ in self.sweep() if r <= self.redline * 1.05))
        return v

    def peak_power(self):
        v = self._cache.get('pp')
        if v is None:
            v = self._cache['pp'] = max(((h, r) for r, _, h in self.sweep() if r <= self.redline * 1.05))
        return v


@dataclass
class VehicleSpec:
    id: str
    name: str
    tagline: str
    description: str
    kind: str
    engine: Engine
    gears: tuple
    reverse: float
    final: float
    drivetrain: dict
    body_pts: list
    art: str
    art_box: tuple                    # (width m, height m, y offset m) of the supersample buffer
    exhaust: tuple
    physics: dict = field(default_factory=dict)
    tires: str = ''
    diff_scale: float = 1.0
    paints: list = field(default_factory=list)


# ---------------------------------------------------------------- base physics (the 6x6 logger)
BASE = dict(
    mass=6500.0, inertia=42000.0,
    wheel_mass=140.0, wheel_r=0.62, wheel_i=38.0,
    mount_x=(3.0, -0.7, -2.4), mount_y=0.35,
    l0=0.98, lmin=0.30, lmax=0.98,
    k=(85000.0, 105000.0, 105000.0), k_prog=(260000.0, 320000.0, 320000.0),
    c_bump=8000.0, c_reb=12500.0, v_blow=0.8, blow=0.35,
    k_stop=1.1e6, c_stop=35000.0, k_lat=8.0e6, c_lat=45000.0,
    tire_k=480000.0, tire_c=4500.0, soil_c=14000.0, pen_max=0.26, k_rim=5.0e6, patch_gain=0.35, tire_w=1.3,
    B=7.0, C=1.3, v_min=0.5, eta=0.9,
    clutch_cap=2600.0, brake_t=16000.0,
    drag=3.8, air_torque=30000.0, ground_torque=6000.0, ang_damp=2500.0,
    body_k=500000.0, body_c=25000.0, body_mu=0.6,
)

LOGGER = VehicleSpec(
    id='logger6x6', name='Timberjack 6x6', tagline='Log hauler - heavy, patient, unstoppable',
    description='A 7-tonne cab-over with a big diesel and three driven axles. Slow, but with low range, '
                'a locked driveline and soft tyres it floats through snow that stops everything else.',
    kind='6x6 log truck',
    engine=Engine('FH-12 diesel', '12.0 L inline-6 turbo diesel',
                  [(0, 900), (600, 1300), (1000, 1750), (1400, 1900), (1900, 1800), (2300, 1450), (2600, 900), (2900, 0)],
                  idle=650, redline=2450, inertia=1.6, torque_scale=0.85, brake0=60, brake1=0.06, cylinders=6),
    gears=(7.0, 4.7, 3.2, 2.2, 1.5, 1.0), reverse=6.0, final=7.2,
    drivetrain=dict(tree=('center', 0, ('inter', 1, 2)), low_mult=2.3, disconnectable=[0],
                    default={'center': 1, 'inter': 1}),
    body_pts=[(3.95, -0.15), (3.95, 0.9), (3.5, 2.55), (1.9, 2.6), (1.8, 1.0), (-1.0, 1.0), (-4.0, 1.0),
              (-4.1, -0.2), (-3.0, -0.5), (-1.0, -0.5), (1.0, -0.5)],
    art='logger', art_box=(10.8, 6.6, 1.0), exhaust=(1.63, 3.5),
    physics={}, tires='1.24 m mud-terrain, wide', diff_scale=1.0,
    paints=[(226, 118, 34), (212, 58, 48), (236, 190, 44), (58, 118, 200), (66, 150, 98), (226, 228, 234), (40, 44, 54)],
)

PICKUP = VehicleSpec(
    id='pickup4x4', name='Ridgeback 4x4', tagline='Quick, light, and happiest on firm ground',
    description='A turbo-diesel pickup. Fast on dirt and gravel and nimble over obstacles, but with little torque '
                'at crawl speed and a light drivetrain: in deep snow and mud, wheelspin buries it quickly.',
    kind='4x4 pickup',
    engine=Engine('3.0 TD', '3.0 L V6 twin-turbo diesel',
                  [(0, 200), (800, 300), (1200, 420), (1800, 520), (2800, 540), (3400, 500), (4000, 420), (4600, 300), (5200, 0)],
                  idle=800, redline=4500, inertia=0.35, torque_scale=1.0, brake0=35, brake1=0.03, cylinders=6),
    gears=(4.6, 2.8, 1.9, 1.35, 1.0, 0.78), reverse=4.0, final=3.9,
    drivetrain=dict(tree=('center', 0, 1), low_mult=2.5, disconnectable=[0], default={'center': 1}),
    body_pts=[(2.3, -0.3), (2.3, 0.12), (2.16, 0.4), (1.0, 0.52), (0.4, 1.0), (-0.8, 1.02),
              (-0.95, 0.55), (-2.2, 0.5), (-2.2, -0.3), (-1.0, -0.38), (0.0, -0.4), (1.0, -0.38)],
    art='pickup', art_box=(7.4, 5.6, -0.1), exhaust=(-2.15, -0.1),
    physics=dict(
        mass=2500.0, inertia=4200.0, wheel_mass=70.0, wheel_r=0.47, wheel_i=2.6,
        mount_x=(1.35, -1.35), mount_y=0.09, l0=0.72, lmin=0.2, lmax=0.72,
        k=(58000.0, 62000.0), k_prog=(136000.0, 140000.0), c_bump=4400.0, c_reb=7000.0, v_blow=1.1, blow=0.35,
        k_stop=5.0e5, c_stop=12000.0, k_lat=5.0e6, c_lat=26000.0,
        tire_k=300000.0, tire_c=1700.0, soil_c=7000.0, pen_max=0.19, k_rim=3.0e6, tire_w=1.0,
        clutch_cap=1000.0, brake_t=7000.0, drag=1.7, air_torque=11000.0, ground_torque=3500.0, ang_damp=450.0,
        body_k=250000.0, body_c=11000.0, v_min=0.4),
    tires='0.94 m all-terrain', diff_scale=0.3,
    paints=[(226, 72, 52), (240, 170, 40), (58, 128, 222), (70, 172, 112), (232, 234, 240), (160, 84, 204), (30, 34, 44)],
)

HAULER = VehicleSpec(
    id='hauler8x8', name='Behemoth 8x8', tagline='Eleven tonnes of pure traction',
    description='A four-axle container hauler with a monster diesel. Four driven axles and huge tyres give '
                'it unreal pulling power - if you give the tyres enough footprint to hold it up.',
    kind='8x8 container hauler',
    engine=Engine('DX-13 diesel', '13.0 L inline-6 twin-turbo diesel',
                  [(0, 1200), (600, 1800), (1000, 2400), (1400, 2650), (1900, 2500), (2300, 2000), (2600, 1200), (2900, 0)],
                  idle=600, redline=2400, inertia=2.4, torque_scale=0.9, brake0=90, brake1=0.08, cylinders=6),
    gears=(8.0, 5.2, 3.6, 2.5, 1.7, 1.0), reverse=7.0, final=8.4,
    drivetrain=dict(tree=('center', ('front', 0, 1), ('rear', 2, 3)), low_mult=2.4, disconnectable=[0, 1],
                    default={'center': 1, 'front': 1, 'rear': 1}),
    body_pts=[(5.5, -0.2), (5.5, 1.0), (5.0, 2.8), (2.9, 2.9), (2.8, 1.1), (-6.4, 1.1), (-6.5, -0.2),
              (-4.0, -0.55), (0.0, -0.55), (3.0, -0.55)],
    art='hauler', art_box=(15.6, 7.6, 1.3), exhaust=(2.6, 3.9),
    physics=dict(
        mass=11000.0, inertia=125000.0, wheel_mass=180.0, wheel_r=0.72, wheel_i=55.0,
        mount_x=(4.3, 1.9, -2.5, -4.9), mount_y=0.4, l0=1.05, lmin=0.34, lmax=1.05,
        k=(100000.0, 110000.0, 125000.0, 125000.0), k_prog=(300000.0, 330000.0, 370000.0, 370000.0),
        c_bump=10500.0, c_reb=16500.0, v_blow=0.8, blow=0.35,
        k_stop=1.6e6, c_stop=50000.0, k_lat=1.2e7, c_lat=70000.0,
        tire_k=640000.0, tire_c=6500.0, soil_c=22000.0, pen_max=0.30, k_rim=7.0e6, tire_w=1.55,
        clutch_cap=5400.0, brake_t=24000.0, drag=5.0, air_torque=60000.0, ground_torque=9000.0, ang_damp=6000.0,
        body_k=800000.0, body_c=40000.0),
    tires='1.44 m super-single flotation', diff_scale=2.3,
    paints=[(40, 120, 130), (214, 86, 40), (230, 200, 60), (180, 60, 60), (226, 228, 234), (70, 100, 70), (40, 44, 54)],
)


RALLY = VehicleSpec(
    id='rally4x4', name='Zephyr GT Rally', tagline='Built to go flat out on gravel and tarmac',
    description='A 350 hp turbo rally coupe with a classic sports-car silhouette: light, low and fast, with a short-geared 6-speed and permanent AWD. '
                'Unbeatable on firm ground in the Rally Stage - and hopelessly out of its depth in snow or mud. '
                'Disconnect the front axle to slide it around as rear-wheel drive.',
    kind='4x4 rally coupe',
    engine=Engine('2.0 T', '2.0 L turbo petrol inline-4',
                  [(0, 150), (1000, 230), (2000, 330), (3000, 450), (4000, 520), (5000, 530), (5500, 520),
                   (6500, 480), (7200, 400), (7700, 250), (8200, 0)],
                  idle=1000, redline=7600, inertia=0.16, torque_scale=0.8, brake0=30, brake1=0.012, cylinders=4),
    gears=(3.4, 2.3, 1.7, 1.35, 1.1, 0.9), reverse=3.2, final=4.2,
    drivetrain=dict(tree=('center', 0, 1), has_range=False, low_mult=1.0, disconnectable=[0], default={'center': 1}),
    body_pts=[(2.12, -0.42), (2.2, -0.2), (2.05, 0.0), (1.25, 0.24), (0.5, 0.38), (0.18, 0.52), (-0.6, 0.55), (-1.3, 0.33),
              (-2.05, 0.14), (-2.2, -0.08), (-2.2, -0.42), (-1.0, -0.5), (0.0, -0.5), (1.0, -0.5)],
    art='rally', art_box=(6.2, 2.8, -0.1), exhaust=(-2.2, -0.35),
    physics=dict(
        mass=1350.0, inertia=2300.0, wheel_mass=32.0, wheel_r=0.33, wheel_i=1.1,
        mount_x=(1.25, -1.25), mount_y=0.08, l0=0.56, lmin=0.14, lmax=0.56,
        k=(50000.0, 52000.0), k_prog=(150000.0, 150000.0), c_bump=3700.0, c_reb=6400.0, v_blow=1.2, blow=0.4,
        k_stop=3.0e5, c_stop=9000.0, k_lat=4.0e6, c_lat=22000.0,
        tire_k=250000.0, tire_c=1500.0, soil_c=6000.0, pen_max=0.12, k_rim=2.5e6, tire_w=0.7, patch_gain=0.3,
        clutch_cap=800.0, brake_t=3300.0, drag=0.45, air_torque=6500.0, ground_torque=1800.0, ang_damp=230.0,
        body_k=160000.0, body_c=6500.0, v_min=0.4),
    tires='0.66 m rally tyres', diff_scale=0.18,
    paints=[(36, 92, 206), (214, 52, 48), (244, 200, 40), (60, 160, 96), (236, 238, 244), (40, 44, 54), (232, 120, 36)],
)

VEHICLES = [RALLY, PICKUP, LOGGER, HAULER]
BY_ID = {v.id: v for v in VEHICLES}


def get(vid):
    return BY_ID.get(vid, LOGGER)


def phys(spec):
    """Full physics dict for a vehicle (BASE with the vehicle's overrides)."""
    d = dict(BASE)
    d.update(spec.physics)
    d['n'] = len(d['mount_x'])
    return d


def stats(spec):
    """Numbers shown in the garage, derived from the same data the physics uses."""
    p = phys(spec)
    e = spec.engine
    mass = p['mass'] + p['wheel_mass'] * p['n']
    hp, hp_rpm = e.peak_power()
    tq, tq_rpm = e.peak_torque()
    R = p['wheel_r']
    top = 0.0
    for g in spec.gears:
        ratio = g * spec.final
        for rpm in range(int(e.idle), int(e.redline), 25):
            v = rpm * math.pi / 30 / ratio * R
            force = e.torque_at(rpm) * ratio * p['eta'] / R
            if force >= p['drag'] * v * v + 0.02 * mass * 9.81:
                top = max(top, v)
    low = spec.drivetrain.get('low_mult', 1.0)
    crawl = e.idle * math.pi / 30 / (spec.gears[0] * spec.final * low) * R
    drive = '%dx%d' % (2 * p['n'], 2 * p['n'])
    return dict(mass=mass, hp=hp, hp_rpm=hp_rpm, tq=tq, tq_rpm=tq_rpm, top_kmh=top * 3.6, crawl_kmh=crawl * 3.6,
                flotation=p['tire_w'] * R * p['n'] / mass * 1000.0, travel=p['l0'] - p['lmin'], drive=drive,
                axles=p['n'], wheel_d=2 * R)
