"""Heavy 6x6 truck simulation (side-view, 2D).

 * Chassis: rigid body with mass + pitch inertia (~7 t loaded).
 * Three axles. Each wheel is its own sprung particle ("hub") tied to the chassis by a
   spring/damper along the chassis' down axis (progressive spring, bump/rebound damping with
   blow-off, bump stops) and a very stiff lateral constraint.
 * Tyre: radial spring/damper in series with the soil, slip-based friction curve, rolling
   resistance that grows with sinkage, viscous drag in mud/snow.
 * Soil: soft layers (snow / mud / dirt) over a hard pan. If wheel load exceeds the bearing
   capacity of the soil (which grows with sinkage, compaction and tyre footprint = low pressure)
   the soil yields and the wheel sinks. Spinning wheels dig. Wheels pack the soil behind them.
 * Drivetrain: diesel torque curve + inertia, idle governor, slipping clutch (implicit),
   6 gears + reverse, low range, AWD with an inter-wheel coupling that can be locked.
 * Friction is a linearised implicit step so it stays stable with huge gear ratios at 960 Hz.
"""
import math
from .util import clamp

G = 9.81
TAU = math.tau
SUBSTEP = 1.0 / 960.0

CFG = dict(
    mass=6500.0, inertia=42000.0,
    wheel_mass=140.0, wheel_r=0.62, wheel_i=38.0,
    mount_x=(3.0, -0.7, -2.4), mount_y=0.35,
    # suspension (per axle)
    l0=0.98, lmin=0.30, lmax=0.98,
    k=(85000.0, 105000.0, 105000.0), k_prog=(260000.0, 320000.0, 320000.0),
    c_bump=8000.0, c_reb=12500.0, v_blow=0.8, blow=0.35,
    k_stop=1.1e6, c_stop=35000.0, k_lat=8.0e6, c_lat=45000.0,
    # tyre
    tire_k=480000.0, tire_c=4500.0, soil_c=14000.0, pen_max=0.26, k_rim=5.0e6, patch_gain=0.35, tire_w=1.3,
    # friction curve
    B=7.0, C=1.3, v_min=0.5,
    # drivetrain
    engine_i=1.6, idle=650.0, redline=2450.0, torque_scale=0.85, eta=0.9,
    final=7.2, gears=(7.0, 4.7, 3.2, 2.2, 1.5, 1.0), reverse=6.0, low_mult=2.3,
    clutch_cap=2600.0, brake_t=16000.0,
    # coupling between the driven wheels
    cpl_k=400.0, cpl_max=2000.0, lock_k=3500.0, lock_max=14000.0,
    # aero / misc
    drag=3.8, air_torque=30000.0, ground_torque=6000.0, ang_damp=2500.0,
    body_k=500000.0, body_c=25000.0, body_mu=0.6,
)

# full-throttle torque (Nm) vs rpm
TORQUE = [(0, 900), (600, 1300), (1000, 1750), (1400, 1900), (1900, 1800), (2300, 1450), (2600, 900), (2900, 0)]


def torque_at(rpm):
    if rpm <= 0:
        return TORQUE[0][1]
    for i in range(1, len(TORQUE)):
        if rpm <= TORQUE[i][0]:
            a, b = TORQUE[i - 1], TORQUE[i]
            return a[1] + (b[1] - a[1]) * ((rpm - a[0]) / (b[0] - a[0]))
    return 0.0


# chassis collision points (chassis-local): bumpers, cab, deck, frame
BODY_PTS = [(3.95, -0.15), (3.95, 0.9), (3.5, 2.55), (1.9, 2.6), (1.8, 1.0), (-1.0, 1.0), (-4.0, 1.0),
            (-4.1, -0.2), (-3.0, -0.5), (-1.0, -0.5), (1.0, -0.5)]


class Wheel:
    __slots__ = ('mx', 'k', 'kp', 'hx', 'hy', 'vx', 'vy', 'om', 'ang', 'con', 'touching', 'Fn', 'slip', 'vt',
                 'Fx', 'l', 'mat', 'loose', 'mu_e', 'G', 'g', 'tx', 'ty', 'crr', 'drag', 'pen', 'Fhx', 'Fhy',
                 'z', 'soft', 'dens', 'ratio')

    def __init__(self, mx, k, kp):
        self.mx, self.k, self.kp = mx, k, kp
        self.hx = self.hy = self.vx = self.vy = self.om = self.ang = 0.0
        self.con = [0.0, 0.0, 1.0, 0.0, 0.0]  # pen, nx, ny, px, py
        self.touching = False
        self.Fn = self.slip = self.vt = self.Fx = self.l = 0.0
        self.mat = 0
        self.loose = self.mu_e = self.G = self.g = self.crr = self.drag = self.pen = 0.0
        self.z = self.soft = self.dens = self.ratio = 0.0
        self.tx, self.ty = 1.0, 0.0
        self.Fhx = self.Fhy = 0.0


class Car:
    def __init__(self, terrain):
        self.t = terrain
        self.cfg = dict(CFG)
        c = self.cfg
        self.pressure = 1.0       # ratio vs nominal (~30 psi)
        self.auto = True
        self.low = False          # low range
        self.diff_lock = False
        self.wheels = [Wheel(x, c['k'][i], c['k_prog'][i]) for i, x in enumerate(c['mount_x'])]
        self.hit_f = 0.0
        self.hit = (0.0, 0.0)
        self.hit_v = (0.0, 0.0)
        self.hand = 0.0
        self.lean = 0.0
        self.acc = 0.0
        self.tick = 0
        self.reset(0.0)

    # ------------------------------------------------------------------ state
    def reset(self, x):
        c, t = self.cfg, self.t
        a = math.atan2(t.h(x + 3.0) - t.h(x - 3.0), 6.0)
        ground = max(t.h(x + dx * 0.2) for dx in range(-25, 26))
        self.x, self.y, self.a = x, ground + 2.2, a * 0.5
        self.vx = self.vy = self.w = 0.0
        ca, sa = math.cos(self.a), math.sin(self.a)
        for w in self.wheels:
            mx = self.x + w.mx * ca - c['mount_y'] * sa
            my = self.y + w.mx * sa + c['mount_y'] * ca
            l = c['l0'] - 0.25
            w.hx, w.hy = mx + sa * l, my - ca * l
            w.vx = w.vy = w.om = w.ang = w.Fn = 0.0
            w.touching = False
        self.we = c['idle'] * TAU / 60
        self.gear = 1
        self._update_ratio()
        self.shift_t = 0.0
        self.since_shift = 1.0
        self.engage = 0.06
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
        return self.pressure * 30

    def adjust_pressure(self, d):
        self.pressure = clamp(self.pressure + d, 0.3, 1.4)

    def _update_ratio(self):
        c, g = self.cfg, self.gear
        if g == 0:
            self.ratio = 0.0
            return
        base = -c['reverse'] if g < 0 else c['gears'][g - 1]
        self.ratio = base * c['final'] * (c['low_mult'] if self.low else 1.0)

    def set_gear(self, g):
        if g == self.gear:
            return
        self.gear = g
        self._update_ratio()
        self.shift_t = 0.4
        self.since_shift = 0.0

    def toggle_low(self):
        self.low = not self.low
        self._update_ratio()

    def toggle_diff_lock(self):
        self.diff_lock = not self.diff_lock

    # --------------------------------------------- per-frame driver logic
    def control(self, dt, up, dn, hand, lean, shift_up=False, shift_dn=False):
        vf = self.vx * math.cos(self.a) + self.vy * math.sin(self.a)
        self.speed = vf
        thr = brk = 0.0
        if up > 0.05 and dn < 0.05:
            if vf < -1.0:
                brk = up
            else:
                thr = up
                if self.gear <= 0 and self.auto:
                    self.set_gear(1)
        elif dn > 0.05 and up < 0.05:
            if vf > 1.0:
                brk = dn
            else:
                thr = dn
                if self.gear >= 0 and self.auto:
                    self.set_gear(-1)
        elif up > 0.05 and dn > 0.05:
            brk = dn
        elif abs(vf) < 0.4:
            brk = 0.35  # parking hold
        if not self.auto and self.gear != -1 and dn > 0.05 and up < 0.05:
            thr, brk = 0.0, dn
        if thr > self.throttle:
            self.throttle = min(thr, self.throttle + dt * 0.9 * thr)   # keyboard: hold W to build power
        else:
            self.throttle = max(thr, self.throttle - dt * 4.0)
        self.brake_out += (brk - self.brake_out) * min(1.0, dt * 14)
        self.shift_t = max(0.0, self.shift_t - dt)
        self.since_shift += dt
        gears = self.cfg['gears']
        n = len(self.wheels)
        if self.auto and self.gear >= 1 and self.shift_t <= 0:
            gs = max(0.0, vf) / self.cfg['wheel_r']        # ground-speed based, ignores wheelspin
            wb = min(gs, sum(w.om for w in self.wheels) / n)
            rpm_d = self.ratio * wb * 30 / math.pi
            th = self.throttle
            up_r = 1500 + 700 * th
            dn_r = 1300 if th > 0.85 else 850 + 450 * th
            if self.since_shift > 1.0 and self.gear < 6 and rpm_d > up_r:
                if rpm_d * gears[self.gear] / gears[self.gear - 1] > 1050:
                    self.set_gear(self.gear + 1)
            elif self.since_shift > 0.7 and self.gear > 1 and rpm_d < dn_r:
                if rpm_d * gears[self.gear - 2] / gears[self.gear - 1] < 2200:
                    self.set_gear(self.gear - 1)
        if not self.auto:
            if shift_up and self.gear < 6:
                self.set_gear(self.gear + 1)
            if shift_dn and self.gear > -1:
                self.set_gear(self.gear - 1)
        self.hand = hand
        self.lean = lean

    def engine_torque(self, rpm, thr):
        c = self.cfg
        cut = clamp((c['redline'] + 150 - rpm) / 150, 0, 1)
        self.limiter = rpm > c['redline'] and thr > 0.1
        t = thr * cut * torque_at(rpm) * c['torque_scale'] - (1 - thr) * (60 + 0.06 * rpm)
        if rpm < c['idle']:
            t += clamp((c['idle'] - rpm) * 3.0, 0, 500)
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
        N = len(W)
        pr = self.pressure
        l0, lmin, lmax = c['l0'], c['lmin'], c['lmax']
        sqrt, atan, sin, cos = math.sqrt, math.atan, math.sin, math.cos
        px_, py_, vx_, vy_, om_ = self.x, self.y, self.vx, self.vy, self.w
        mount_y = c['mount_y']
        pen_max = c['pen_max']
        self.tick += 1
        area_k = clamp(pr, 0.35, 1.5) ** -0.8

        # ---- suspension + tyre/soil normal load, per wheel
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
            Fs = w.k * comp
            if comp > 0:
                Fs += w.kp * comp * comp * comp
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

            # ---- tyre on soil
            con = w.con
            w.touching = tr.contact_circle(w.hx, w.hy, R, con)
            w.Fn = w.G = w.g = w.pen = w.z = w.soft = w.ratio = 0.0
            if w.touching:
                pen, nx, ny = con[0], con[1], con[2]
                vn = w.vx * nx + w.vy * ny
                sf = tr.surface(con[3])
                soft = sf['soft']
                kt = c['tire_k'] * pr
                keff = 1.0 / (1.0 / kt + soft / sf['ks'])        # tyre and soil springs in series
                pen_lim = pen_max + 0.22 * soft
                q = pen / pen_lim
                Fn = keff * pen * (1 + 1.4 * q * q) - (c['tire_c'] * sqrt(pr) + soft * c['soil_c']) * vn
                if pen > pen_lim:
                    Fn += c['k_rim'] * (pen - pen_lim)
                if Fn < 0:
                    Fn = 0.0
                w.Fn = Fn
                w.pen = pen
                w.soft = soft
                Fhx += Fn * nx
                Fhy += Fn * ny
                tx, ty = ny, -nx
                w.tx, w.ty = tx, ty
                w.vt = w.vx * tx + w.vy * ty
                w.mat = sf['mat']
                w.loose = sf['loose']
                w.slip = w.om * R - w.vt
                # sinkage below the original surface
                z = sf['h0'] - (w.hy - R)
                if z < 0.0:
                    z = 0.0
                w.z = z
                dens = sf['dens']
                w.dens = dens
                if soft > 0.02:
                    zc = z if z < 0.8 * R else 0.8 * R
                    chord = 2 * sqrt(max(0.0, 2 * R * zc - zc * zc)) + 0.2
                    Fy_ = sf['pb'] * (1 + 3 * dens) * chord * area_k * c['tire_w']
                    ratio = Fn / Fy_
                    w.ratio = ratio
                    spin = abs(w.slip) - 0.8
                    if spin < 0:
                        spin = 0.0
                    if (self.tick + id(w)) & 1 == 0:
                        tr.disturb(w.hx, w.hy, R, con[3], ratio, spin * soft, -1 if w.slip > 0 else 1, dt * 2)
                mu = sf['mu'] * (1 + 0.8 * dens * soft) * (1 + c['patch_gain'] * (1 - pr) * sf['loose'])
                mu += 0.12 * clamp(z / 0.25, 0, 1) * soft
                w.mu_e = mu
                w.crr = sf['crr'] * (1 + 1.4 * max(0.0, 1 - pr)) + 0.65 * sqrt(z / R) * soft * (1 - 0.6 * dens)
                w.drag = sf['drag'] * soft
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
        r, eta = self.ratio, c['eta']
        rpm = self.we * 30 / math.pi
        self.rpm = rpm
        eng = clamp((rpm - 800) / 500, 0, 1)
        eng = eng * eng * (3 - 2 * eng)
        if self.gear != 0:
            eng = max(eng, 0.06)
        if self.shift_t > 0.25:
            eng = 0.0
        elif self.shift_t > 0:
            eng *= 1 - self.shift_t / 0.25
        self.engage = eng
        thr_e = self.throttle
        if self.shift_t > 0.25:
            thr_e *= 0.1
        wbar = 0.0
        for w in W:
            wbar += w.om
        wbar /= N
        Te = self.engine_torque(rpm, thr_e)
        if self.shift_t > 0 and r != 0:   # rev-match while the clutch is open
            Te += clamp((abs(r * wbar) - self.we) * 8.0, -400, 700)
        Ie = c['engine_i']
        Ti = [0.0] * N
        Iei = Iw
        locked = False
        Tc = 0.0
        if r != 0:
            win = r * wbar
            slip = self.we - win
            cap = c['clutch_cap'] * eng
            A = eta * r * r / (N * Iw)
            gsum = 0.0
            for w in W:
                gsum += w.G
            gavg = -R * gsum / (N * Iw)
            Tlock = (slip / dt + Te / Ie - r * gavg) / (1 / Ie + A)
            if win >= 0 and abs(Tlock) <= cap:
                locked = True
                each = eta * r * Te / N
                Iei = Iw + eta * Ie * r * r / N
            else:
                Tc = cap if slip >= 0 else -cap
                each = eta * r * Tc / N
            ck, cm = (c['lock_k'], c['lock_max']) if self.diff_lock else (c['cpl_k'], c['cpl_max'])
            for i, w in enumerate(W):
                Ti[i] = each + clamp(ck * (wbar - w.om), -cm, cm)
        self.locked = locked

        # ---- tyre friction (linearised implicit) + wheel spin
        mq = M / N + mw
        brake, hand = self.brake_out, self.hand
        reaction = 0.0
        for i, w in enumerate(W):
            Tdrv = Ti[i]
            Fxt = 0.0
            if w.touching:
                Fxt = (w.G + w.g * R * dt * Tdrv / Iei) / (1 + w.g * dt * (1 / mq + R * R / Iei))
                rr = -w.crr * w.Fn * clamp(w.vt / 0.4, -1, 1) - w.drag * w.vt
                w.Fhx += (Fxt + rr) * w.tx
                w.Fhy += (Fxt + rr) * w.ty
                w.Fx = Fxt
            om = w.om + dt * (Tdrv - R * Fxt) / Iei
            Tb = brake * c['brake_t'] + (hand * c['brake_t'] * 1.3 if i > 0 else 0.0)
            if Tb > 0:
                dm = Tb * dt / Iei
                if abs(om) <= dm:
                    om = 0.0
                else:
                    om -= math.copysign(dm, om)
            w.om = om
            w.ang += om * dt
            reaction += Tdrv
        if r == 0:
            self.we += dt * Te / Ie
        elif locked:
            self.we = r * sum(w.om for w in W) / N
        else:
            self.we += dt * (Te - Tc) / Ie
        if self.we < 40:
            self.we = 40.0
        Tq += reaction  # driveline torque reacts on the chassis (nose lifts on acceleration)

        # ---- chassis vs terrain
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
        grounded = any(w.touching for w in W)
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
