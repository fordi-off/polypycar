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
from . import vehicles as V
from .drivetrain import Drivetrain

G = 9.81
TAU = math.tau
SUBSTEP = 1.0 / 960.0


class Wheel:
    __slots__ = ('mx', 'k', 'kp', 'hx', 'hy', 'vx', 'vy', 'om', 'ang', 'con', 'touching', 'Fn', 'slip', 'vt',
                 'Fx', 'l', 'mat', 'loose', 'mu_e', 'G', 'g', 'tx', 'ty', 'crr', 'drag', 'pen', 'Fhx', 'Fhy',
                 'z', 'soft', 'dens', 'ratio', 'Tdrv')

    def __init__(self, mx, k, kp):
        self.mx, self.k, self.kp = mx, k, kp
        self.hx = self.hy = self.vx = self.vy = self.om = self.ang = 0.0
        self.con = [0.0, 0.0, 1.0, 0.0, 0.0]  # pen, nx, ny, px, py
        self.touching = False
        self.Fn = self.slip = self.vt = self.Fx = self.l = 0.0
        self.mat = 0
        self.loose = self.mu_e = self.G = self.g = self.crr = self.drag = self.pen = 0.0
        self.z = self.soft = self.dens = self.ratio = self.Tdrv = 0.0
        self.tx, self.ty = 1.0, 0.0
        self.Fhx = self.Fhy = 0.0


class Car:
    def __init__(self, terrain, spec=None):
        self.t = terrain
        self.spec = spec or V.LOGGER
        self.cfg = c = V.phys(self.spec)
        eng = self.spec.engine
        self.engine = eng
        c.update(idle=eng.idle, redline=eng.redline, engine_i=eng.inertia, gears=self.spec.gears,
                 reverse=self.spec.reverse, final=self.spec.final)
        self.n = len(c['mount_x'])
        self.body_pts = list(self.spec.body_pts)
        self.drive = Drivetrain(self.spec.drivetrain, self.n, self.spec.diff_scale)
        self.pressure = 1.0       # ratio vs nominal (~30 psi)
        self.auto = True
        self.throttle_ramp = 0.9  # keyboard: how fast holding the gas builds power (1/s)
        self.wheels = [Wheel(x, c['k'][i], c['k_prog'][i]) for i, x in enumerate(c['mount_x'])]
        self.hit_f = 0.0
        self.hit = (0.0, 0.0)
        self.hit_v = (0.0, 0.0)
        self.hand = 0.0
        self.lean = 0.0
        self.acc = 0.0
        self.tick = 0
        self.reset(0.0)

    # drivetrain switches used by keys / the transmission app
    @property
    def low(self):
        return self.drive.low

    @low.setter
    def low(self, v):
        self.drive.low = bool(v)
        self._update_ratio()

    @property
    def diff_lock(self):
        return self.drive.all_locked

    @diff_lock.setter
    def diff_lock(self, v):
        self.drive.set_all_locked(bool(v))

    # ------------------------------------------------------------------ state
    def reset(self, x):
        c, t = self.cfg, self.t
        half = max(abs(m) for m in c['mount_x']) + 0.5
        a = math.atan2(t.h(x + half) - t.h(x - half), 2 * half)
        ground = max(t.h(x + dx * 0.2) for dx in range(-int(half * 5), int(half * 5) + 1))
        self.x, self.y, self.a = x, ground + c['wheel_r'] + c['l0'] + 0.9, a * 0.5
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
        self.Te = 0.0

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
        self.ratio = base * c['final'] * (self.drive.low_mult if self.drive.low else 1.0)

    def set_gear(self, g):
        if g == self.gear:
            return
        self.gear = g
        self._update_ratio()
        self.shift_t = 0.4
        self.since_shift = 0.0

    def toggle_low(self):
        self.low = not self.low

    def toggle_diff_lock(self):
        self.diff_lock = not self.diff_lock

    def shift_to(self, g):
        top = len(self.cfg['gears'])
        self.set_gear(max(-1, min(top, g)))

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
            self.throttle = min(thr, self.throttle + dt * self.throttle_ramp * thr)   # keyboard: hold to build power
        else:
            self.throttle = max(thr, self.throttle - dt * 4.0)
        self.brake_out += (brk - self.brake_out) * min(1.0, dt * 14)
        self.shift_t = max(0.0, self.shift_t - dt)
        self.since_shift += dt
        gears = self.cfg['gears']
        n = len(self.wheels)
        top = len(gears)
        rl = self.cfg['redline']
        if self.auto and self.gear >= 1 and self.shift_t <= 0:
            gs = max(0.0, vf) / self.cfg['wheel_r']        # ground-speed based, ignores wheelspin
            on = [w.om for w, e in zip(self.wheels, self.drive.axle_on) if e] or [0.0]
            wb = min(gs, sum(on) / len(on))
            rpm_d = self.ratio * wb * 30 / math.pi
            th = self.throttle
            up_r = rl * (0.61 + 0.29 * th)
            dn_r = rl * 0.53 if th > 0.85 else rl * (0.35 + 0.18 * th)
            if self.since_shift > 1.0 and self.gear < top and rpm_d > up_r:
                if rpm_d * gears[self.gear] / gears[self.gear - 1] > 0.43 * rl:
                    self.set_gear(self.gear + 1)
            elif self.since_shift > 0.7 and self.gear > 1 and rpm_d < dn_r:
                if rpm_d * gears[self.gear - 2] / gears[self.gear - 1] < 0.9 * rl:
                    self.set_gear(self.gear - 1)
        if not self.auto:
            if shift_up and self.gear < top:
                self.set_gear(self.gear + 1)
            if shift_dn and self.gear > -1:
                self.set_gear(self.gear - 1)
        self.hand = hand
        self.lean = lean

    def engine_torque(self, rpm, thr):
        c, e = self.cfg, self.engine
        cut = clamp((c['redline'] + 0.06 * c['redline'] - rpm) / (0.06 * c['redline']), 0, 1)
        self.limiter = rpm > c['redline'] and thr > 0.1
        t = thr * cut * e.torque_at(rpm) - (1 - thr) * (e.brake0 + e.brake1 * rpm)
        if rpm < c['idle']:
            t += clamp((c['idle'] - rpm) * 3.0 * c['engine_i'] / 1.6, 0, 500 * c['engine_i'] / 1.6 + 120)
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

        # ---- drivetrain (engine -> clutch -> gearbox -> range -> differential tree -> connected axles)
        dr = self.drive
        on = dr.axle_on
        n_on = dr.n_on
        r, eta = self.ratio, c['eta']
        rpm = self.we * 30 / math.pi
        self.rpm = rpm
        rl, idle = c['redline'], c['idle']
        eng = clamp((rpm - (idle + 150)) / (0.2 * rl), 0, 1)
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
        om = [w.om for w in W]
        wbar = 0.0
        for i in range(N):
            if on[i]:
                wbar += om[i]
        wbar /= n_on
        Te = self.engine_torque(rpm, thr_e)
        Ie = c['engine_i']
        if self.shift_t > 0 and r != 0:   # rev-match while the clutch is open
            Te += clamp((abs(r * wbar) - self.we) * 8.0 * Ie / 1.6, -400 * Ie / 1.6, 700 * Ie / 1.6)
        self.Te = Te
        Ti = [0.0] * N
        Ii = [Iw] * N
        locked = False
        Tc = 0.0
        if r != 0:
            win = r * wbar
            slip = self.we - win
            cap = c['clutch_cap'] * eng
            A = eta * r * r / (n_on * Iw)
            gsum = 0.0
            for i in range(N):
                if on[i]:
                    gsum += W[i].G
            gavg = -R * gsum / (n_on * Iw)
            Tlock = (slip / dt + Te / Ie - r * gavg) / (1 / Ie + A)
            if win >= 0 and abs(slip) < 2.5 + 0.02 * self.we and abs(Tlock) <= cap:   # clutch only sticks once speeds match
                locked = True
                each = eta * r * Te / n_on
                Ieff = Iw + eta * Ie * r * r / n_on
                for i in range(N):
                    if on[i]:
                        Ii[i] = Ieff
            else:
                # slipping: transmit only the torque that would close the slip this step (implicit, so it
                # can't overshoot and chatter with big ratios), limited by the clutch capacity
                Tc = clamp((slip / dt + Te / Ie) / (1 / Ie + A), -cap, cap)
                each = eta * r * Tc / n_on
            dr.distribute(each, om, Ti)
        self.locked = locked

        # ---- tyre friction (linearised implicit) + wheel spin
        mq = M / N + mw
        brake, hand = self.brake_out, self.hand
        reaction = 0.0
        for i, w in enumerate(W):
            Tdrv = Ti[i]
            Iei = Ii[i]
            Fxt = 0.0
            if w.touching:
                Fxt = (w.G + w.g * R * dt * Tdrv / Iei) / (1 + w.g * dt * (1 / mq + R * R / Iei))
                rr = -w.crr * w.Fn * clamp(w.vt / 0.4, -1, 1) - w.drag * w.vt
                w.Fhx += (Fxt + rr) * w.tx
                w.Fhy += (Fxt + rr) * w.ty
                w.Fx = Fxt
            w.Tdrv = Tdrv
            omi = w.om + dt * (Tdrv - R * Fxt) / Iei
            Tb = brake * c['brake_t'] + (hand * c['brake_t'] * 1.3 if w.mx < 0 else 0.0)
            if Tb > 0:
                dm = Tb * dt / Iei
                if abs(omi) <= dm:
                    omi = 0.0
                else:
                    omi -= math.copysign(dm, omi)
            w.om = omi
            w.ang += omi * dt
            reaction += Tdrv
        if r == 0:
            self.we += dt * Te / Ie
        elif locked:
            sm = 0.0
            for i in range(N):
                if on[i]:
                    sm += W[i].om
            self.we = r * sm / n_on
        else:
            self.we += dt * (Te - Tc) / Ie
        if self.we < 40:
            self.we = 40.0
        Tq += reaction  # driveline torque reacts on the chassis (nose lifts on acceleration)

        # ---- chassis vs terrain
        hit_f = 0.0
        hit = hit_v = None
        for lx, ly in self.body_pts:
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
