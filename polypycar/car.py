"""Vehicle simulation (side-view, 2D).

 * Chassis: rigid body with mass + pitch inertia.
 * Each wheel is its own sprung particle ("hub") tied to the chassis by a spring/damper along
   the chassis' down axis (progressive spring, bump/rebound damping with blow-off, bump stops)
   and a very stiff lateral constraint.
 * Tyre: radial spring/damper against the terrain polyline (stiffness scales with pressure,
   progressive, rim bottoming) + slip-based friction (Pacejka-style curve), rolling resistance,
   mud drag. Low pressure => softer, more grip on loose ground.
 * Drivetrain: engine torque curve + inertia, rev limiter, idle governor, slipping clutch
   (solved implicitly, auto engage), 5-speed + reverse, final drive, viscous limited-slip
   coupling between the two driven wheels (AWD), brakes, handbrake.
 * Friction is a linearised implicit step so it stays stable with big gear ratios and light
   wheels at a fixed 960 Hz.
"""
import math
from .util import clamp

G = 9.81
TAU = math.tau
SUBSTEP = 1.0 / 960.0

CFG = dict(
    mass=1250.0, inertia=2100.0,
    wheel_mass=50.0, wheel_r=0.47, wheel_i=1.9,
    mount_x=(1.35, -1.35), mount_y=0.09,
    # suspension
    l0=0.72, lmin=0.20, lmax=0.72,
    k=30000.0, k_prog=70000.0, c_bump=2300.0, c_reb=3700.0, v_blow=1.1, blow=0.35,
    k_stop=260000.0, c_stop=6000.0, k_lat=3.0e6, c_lat=14000.0,
    # tyre
    tire_k=155000.0, tire_c=900.0, pen_max=0.19, k_rim=1.6e6, patch_gain=0.4,
    # friction curve
    B=10.0, C=1.45, v_min=0.35,
    # drivetrain
    engine_i=0.24, idle=950.0, redline=6600.0, torque_scale=0.78, eta=0.92,
    final=4.6, gears=(3.6, 2.2, 1.45, 1.0, 0.76), reverse=3.4,
    clutch_cap=560.0, lsd_k=140.0, lsd_max=1400.0, brake_t=3600.0,
    # aero / misc
    drag=1.7, air_torque=5200.0, ground_torque=1500.0, ang_damp=160.0,
    body_k=190000.0, body_c=7000.0, body_mu=0.55,
)

# full-throttle torque (Nm) vs rpm
TORQUE = [(0, 120), (800, 200), (1500, 290), (2500, 360), (3500, 395), (4500, 405),
          (5500, 370), (6200, 320), (6800, 250), (7400, 0)]


def torque_at(rpm):
    if rpm <= 0:
        return TORQUE[0][1]
    for i in range(1, len(TORQUE)):
        if rpm <= TORQUE[i][0]:
            a, b = TORQUE[i - 1], TORQUE[i]
            return a[1] + (b[1] - a[1]) * ((rpm - a[0]) / (b[0] - a[0]))
    return 0.0


# chassis collision points (chassis-local): bumpers, skid plate, roof, bed corners
BODY_PTS = [(2.3, -0.3), (2.3, 0.12), (2.16, 0.4), (1.0, 0.52), (0.4, 1.0), (-0.8, 1.02),
            (-0.95, 0.55), (-2.2, 0.5), (-2.2, -0.3), (-1.0, -0.38), (0.0, -0.4), (1.0, -0.38)]


class Wheel:
    __slots__ = ('mx', 'hx', 'hy', 'vx', 'vy', 'om', 'ang', 'con', 'touching', 'Fn', 'slip', 'vt',
                 'Fx', 'l', 'mat', 'loose', 'mu_e', 'G', 'g', 'tx', 'ty', 'crr', 'drag', 'pen', 'Fhx', 'Fhy')

    def __init__(self, mx):
        self.mx = mx
        self.hx = self.hy = self.vx = self.vy = self.om = self.ang = 0.0
        self.con = [0.0, 0.0, 1.0, 0.0, 0.0]  # pen, nx, ny, px, py
        self.touching = False
        self.Fn = self.slip = self.vt = self.Fx = self.l = 0.0
        self.mat = 0
        self.loose = self.mu_e = self.G = self.g = self.crr = self.drag = self.pen = 0.0
        self.tx, self.ty = 1.0, 0.0
        self.Fhx = self.Fhy = 0.0


class Car:
    def __init__(self, terrain):
        self.t = terrain
        self.cfg = dict(CFG)
        self.pressure = 1.0  # ratio vs nominal (~32 psi)
        self.auto = True
        self.wheels = [Wheel(x) for x in self.cfg['mount_x']]
        self.hit_f = 0.0
        self.hit = (0.0, 0.0)
        self.hit_v = (0.0, 0.0)
        self.hand = 0.0
        self.lean = 0.0
        self.acc = 0.0
        self.reset(0.0)

    # ------------------------------------------------------------------ state
    def reset(self, x):
        c, t = self.cfg, self.t
        a = math.atan2(t.h(x + 1.4) - t.h(x - 1.4), 2.8)
        ground = max(t.h(x + dx * 0.2) for dx in range(-12, 13))
        self.x, self.y, self.a = x, ground + 1.6, a * 0.5
        self.vx = self.vy = self.w = 0.0
        ca, sa = math.cos(self.a), math.sin(self.a)
        for w in self.wheels:
            mx = self.x + w.mx * ca - c['mount_y'] * sa
            my = self.y + w.mx * sa + c['mount_y'] * ca
            l = c['l0'] - 0.2
            w.hx, w.hy = mx + sa * l, my - ca * l
            w.vx = w.vy = w.om = w.ang = w.Fn = 0.0
            w.touching = False
        self.we = c['idle'] * TAU / 60
        self.gear = 1
        self.ratio = c['gears'][0] * c['final']
        self.shift_t = 0.0
        self.since_shift = 1.0
        self.engage = 0.04
        self.throttle = 0.0
        self.brake_out = 0.0
        self.rpm = c['idle']
        self.speed = 0.0
        self.airborne = False
        self.locked = False
        self.limiter = False
        self.odo = 0.0

    @property
    def pressure_psi(self):
        return self.pressure * 32

    def adjust_pressure(self, d):
        self.pressure = clamp(self.pressure + d, 0.3, 1.4)

    def set_gear(self, g):
        c = self.cfg
        if g == self.gear:
            return
        self.gear = g
        self.ratio = 0.0 if g == 0 else (-c['reverse'] * c['final'] if g < 0 else c['gears'][g - 1] * c['final'])
        self.shift_t = 0.3
        self.since_shift = 0.0

    # --------------------------------------------- per-frame driver logic
    def control(self, dt, up, dn, hand, lean, shift_up=False, shift_dn=False):
        c = self.cfg
        vf = self.vx * math.cos(self.a) + self.vy * math.sin(self.a)
        self.speed = vf
        thr = brk = 0.0
        if up > 0.05 and dn < 0.05:
            if vf < -1.5:
                brk = up
            else:
                thr = up
                if self.gear <= 0 and self.auto:
                    self.set_gear(1)
        elif dn > 0.05 and up < 0.05:
            if vf > 1.5:
                brk = dn
            else:
                thr = dn
                if self.gear >= 0 and self.auto:
                    self.set_gear(-1)
        elif up > 0.05 and dn > 0.05:
            brk = dn
        elif abs(vf) < 0.6:
            brk = 0.3  # parking hold
        if not self.auto and self.gear != -1 and dn > 0.05 and up < 0.05:
            thr, brk = 0.0, dn
        self.throttle += (thr - self.throttle) * min(1.0, dt * 12)
        self.brake_out += (brk - self.brake_out) * min(1.0, dt * 25)
        self.shift_t = max(0.0, self.shift_t - dt)
        self.since_shift += dt
        gears = c['gears']
        if self.auto and self.gear >= 1 and self.shift_t <= 0:
            wb = (self.wheels[0].om + self.wheels[1].om) * 0.5
            rpm_d = self.ratio * wb * 30 / math.pi
            th = self.throttle
            up_r = 3600 + 2500 * th
            dn_r = 2900 if th > 0.85 else 1500 + 1000 * th
            if self.since_shift > 0.7 and self.gear < 5 and rpm_d > up_r:
                if rpm_d * gears[self.gear] / gears[self.gear - 1] > 2300:
                    self.set_gear(self.gear + 1)
            elif self.since_shift > 0.5 and self.gear > 1 and rpm_d < dn_r:
                if rpm_d * gears[self.gear - 2] / gears[self.gear - 1] < 5600:
                    self.set_gear(self.gear - 1)
        if not self.auto:
            if shift_up and self.gear < 5:
                self.set_gear(self.gear + 1)
            if shift_dn and self.gear > -1:
                self.set_gear(self.gear - 1)
        self.hand = hand
        self.lean = lean

    def engine_torque(self, rpm, thr):
        c = self.cfg
        cut = clamp((c['redline'] + 200 - rpm) / 200, 0, 1)
        self.limiter = rpm > c['redline'] and thr > 0.1
        t = thr * cut * torque_at(rpm) * c['torque_scale'] - (1 - thr) * (14 + 0.014 * rpm)
        if rpm < c['idle']:
            t += clamp((c['idle'] - rpm) * 0.4, 0, 160)
        return t

    # ------------------------------------------------------------ physics
    def substep(self, dt):
        c, tr = self.cfg, self.t
        M, R, Iw, mw = c['mass'], c['wheel_r'], c['wheel_i'], c['wheel_mass']
        ca, sa = math.cos(self.a), math.sin(self.a)
        fx, fy = ca, sa          # chassis forward
        dxn, dyn = sa, -ca       # chassis down
        Fx, Fy, Tq = 0.0, -M * G, 0.0
        W = self.wheels
        pr = self.pressure
        l0, lmin, lmax = c['l0'], c['lmin'], c['lmax']
        sqrt, atan, sin, cos = math.sqrt, math.atan, math.sin, math.cos
        px_, py_, vx_, vy_, om_ = self.x, self.y, self.vx, self.vy, self.w
        mount_y = c['mount_y']
        pen_max = c['pen_max']

        # ---- suspension + tyre normal load, per wheel
        for w in W:
            lx = w.mx * ca - mount_y * sa
            ly = w.mx * sa + mount_y * ca
            rx = w.hx - (px_ + lx)
            ry = w.hy - (py_ + ly)
            l = rx * dxn + ry * dyn
            lat = rx * fx + ry * fy
            hrx = w.hx - px_
            hry = w.hy - py_
            rvx = w.vx - (vx_ - om_ * hry)
            rvy = w.vy - (vy_ + om_ * hrx)
            ldot = rvx * dxn + rvy * dyn
            latv = rvx * fx + rvy * fy
            w.l = l

            comp = l0 - l
            Fs = c['k'] * comp
            if comp > 0:
                Fs += c['k_prog'] * comp * comp * comp
            vv = abs(ldot)
            dc = c['c_bump'] if ldot < 0 else c['c_reb']
            vb = c['v_blow']
            fd = dc * vv if vv < vb else dc * (vb + c['blow'] * (vv - vb))
            Fax = Fs - (-fd if ldot < 0 else fd)
            if l < lmin:
                Fax += c['k_stop'] * (lmin - l) + c['c_stop'] * max(0.0, -ldot)
            elif l > lmax:
                Fax += c['k_stop'] * (lmax - l) - c['c_stop'] * max(0.0, ldot)
            Flat = -(c['k_lat'] * lat + c['c_lat'] * latv)

            Fhx = Fax * dxn + Flat * fx
            Fhy = Fax * dyn + Flat * fy - mw * G
            bx = -(Fax * dxn + Flat * fx)
            by = -(Fax * dyn + Flat * fy)
            Fx += bx
            Fy += by
            Tq += lx * by - ly * bx

            # ---- tyre
            con = w.con
            w.touching = tr.contact_circle(w.hx, w.hy, R, con)
            w.Fn = w.G = w.g = w.pen = 0.0
            if w.touching:
                pen, nx, ny = con[0], con[1], con[2]
                vn = w.vx * nx + w.vy * ny
                q = pen / pen_max
                Fn = c['tire_k'] * pr * pen * (1 + 1.4 * q * q) - c['tire_c'] * sqrt(pr) * vn
                if pen > pen_max:
                    Fn += c['k_rim'] * (pen - pen_max)
                if Fn < 0:
                    Fn = 0.0
                w.Fn = Fn
                w.pen = pen
                Fhx += Fn * nx
                Fhy += Fn * ny
                tx, ty = ny, -nx
                w.tx, w.ty = tx, ty
                w.vt = w.vx * tx + w.vy * ty
                sf = tr.surface(con[3])
                w.mat = sf['mat']
                w.loose = sf['loose']
                w.crr = sf['crr']
                w.drag = sf['drag']
                mu = sf['mu'] * (1 + c['patch_gain'] * (1 - pr) * sf['loose'])
                mu *= 1 - 0.1 * max(0.0, pr - 1.1)
                w.mu_e = mu
                w.slip = w.om * R - w.vt
                vref = max(abs(w.vt), c['v_min'])
                xs = c['B'] * w.slip / vref
                ax = atan(xs)
                mF = mu * Fn
                w.G = mF * sin(c['C'] * ax)
                gp = mF * c['C'] * cos(c['C'] * ax) * c['B'] / (vref * (1 + xs * xs))
                w.g = max(gp, 0.03 * mF * c['B'] / vref)
            else:
                w.slip = w.vt = w.Fx = 0.0
            w.Fhx, w.Fhy = Fhx, Fhy

        # ---- drivetrain
        w0, w1 = W
        r, eta = self.ratio, c['eta']
        rpm = self.we * 30 / math.pi
        self.rpm = rpm
        eng = clamp((rpm - 1100) / 900, 0, 1)
        eng = eng * eng * (3 - 2 * eng)
        if self.gear != 0:
            eng = max(eng, 0.04)
        if self.shift_t > 0.16:
            eng = 0.0
        elif self.shift_t > 0:
            eng *= 1 - self.shift_t / 0.16
        self.engage = eng
        thr_e = self.throttle
        if self.shift_t > 0.16:
            thr_e *= 0.1
        Te = self.engine_torque(rpm, thr_e)
        if self.shift_t > 0 and r != 0:   # rev-match while the clutch is open
            target = abs(r * (w0.om + w1.om) * 0.5)
            Te += clamp((target - self.we) * 1.0, -120, 220)
        T0 = T1 = 0.0
        I0 = I1 = Iw
        locked = False
        Tc = 0.0
        Ie = c['engine_i']
        if r != 0:
            wbar = (w0.om + w1.om) * 0.5
            win = r * wbar
            slip = self.we - win
            cap = c['clutch_cap'] * eng
            A = eta * r * r / (2 * Iw)
            gavg = -R * (w0.G + w1.G) * 0.5 / Iw
            Tlock = (slip / dt + Te / Ie - r * gavg) / (1 / Ie + A)
            if win >= 0 and abs(Tlock) <= cap:
                locked = True
                T0 = T1 = eta * r * Te * 0.5
                I0 = I1 = Iw + eta * Ie * r * r * 0.5
            else:
                Tc = cap if slip >= 0 else -cap
                T0 = T1 = eta * r * Tc * 0.5
            bias = clamp(c['lsd_k'] * (w1.om - w0.om), -c['lsd_max'], c['lsd_max'])
            T0 += bias
            T1 -= bias
        self.locked = locked

        # ---- tyre friction (linearised implicit) + wheel spin
        mq = M * 0.5 + mw
        brake, hand = self.brake_out, self.hand
        reaction = 0.0
        for i in (0, 1):
            w = W[i]
            Ti, Iei = (T0, I0) if i == 0 else (T1, I1)
            Fxt = 0.0
            if w.touching:
                Fxt = (w.G + w.g * R * dt * Ti / Iei) / (1 + w.g * dt * (1 / mq + R * R / Iei))
                crr = w.crr * (1 + 1.4 * max(0.0, 1 - pr))
                rr = -crr * w.Fn * clamp(w.vt / 0.4, -1, 1) - w.drag * w.vt
                w.Fhx += (Fxt + rr) * w.tx
                w.Fhy += (Fxt + rr) * w.ty
                w.Fx = Fxt
            om = w.om + dt * (Ti - R * Fxt) / Iei
            Tb = brake * c['brake_t'] * (0.6 if i == 0 else 0.4) + (hand * c['brake_t'] * 1.6 if i == 1 else 0.0)
            if Tb > 0:
                dm = Tb * dt / Iei
                if abs(om) <= dm:
                    om = 0.0
                else:
                    om -= math.copysign(dm, om)
            w.om = om
            w.ang += om * dt
            reaction += Ti
        if r == 0:
            self.we += dt * Te / Ie
        elif locked:
            self.we = r * (w0.om + w1.om) * 0.5
        else:
            self.we += dt * (Te - Tc) / Ie
        if self.we < 40:
            self.we = 40.0
        Tq += reaction  # driveline torque reacts on the chassis (nose lifts on acceleration)

        # ---- chassis vs terrain (bumpers, roof, skid plate)
        hit_f = 0.0
        hit = hit_v = None
        for lx, ly in BODY_PTS:
            rx = lx * ca - ly * sa
            ry = lx * sa + ly * ca
            px = px_ + rx
            py = py_ + ry
            gh = tr.h(px)
            if py >= gh:
                continue
            sl = tr.slope(px)
            il = 1 / sqrt(1 + sl * sl)
            nx, ny = -sl * il, il
            pen = (gh - py) * ny
            vx = vx_ - om_ * ry
            vy = vy_ + om_ * rx
            Fn = c['body_k'] * pen - c['body_c'] * (vx * nx + vy * ny)
            if Fn < 0:
                Fn = 0.0
            tx, ty = ny, -nx
            Ft = -c['body_mu'] * Fn * clamp((vx * tx + vy * ty) / 0.6, -1, 1)
            fxk, fyk = Fn * nx + Ft * tx, Fn * ny + Ft * ty
            Fx += fxk
            Fy += fyk
            Tq += rx * fyk - ry * fxk
            if Fn > hit_f:
                hit_f, hit, hit_v = Fn, (px, py), (vx, vy)
        if hit_f > self.hit_f:
            self.hit_f, self.hit, self.hit_v = hit_f, hit, hit_v

        # ---- aero drag, player pitch control, angular damping
        sp = math.hypot(vx_, vy_)
        Fx -= c['drag'] * sp * vx_
        Fy -= c['drag'] * sp * vy_
        grounded = w0.touching or w1.touching
        Tq += self.lean * (c['ground_torque'] if grounded else c['air_torque'])
        Tq -= c['ang_damp'] * om_ * (1.0 if grounded else 1.5)
        self.airborne = not grounded and hit_f <= 0

        # ---- integrate (semi-implicit Euler)
        for w in W:
            w.vx += w.Fhx / mw * dt
            w.vy += w.Fhy / mw * dt
            w.hx += w.vx * dt
            w.hy += w.vy * dt
        self.vx += Fx / M * dt
        self.vy += Fy / M * dt
        self.w += Tq / c['inertia'] * dt
        self.x += self.vx * dt
        self.y += self.vy * dt
        self.a += self.w * dt

    def step(self, dt):
        """Advance by dt seconds using fixed 960 Hz sub-steps."""
        self.acc += dt
        self.hit_f = 0.0
        n = 0
        while self.acc >= SUBSTEP and n < 40:
            self.substep(SUBSTEP)
            self.acc -= SUBSTEP
            n += 1
        self.odo += abs(self.vx) * dt
        if not math.isfinite(self.x + self.y + self.a):
            self.reset(0.0)
