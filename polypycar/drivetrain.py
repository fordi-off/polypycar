"""Generic driveline: a tree of differentials over per-axle outputs.

The same object drives the physics (torque distribution) and the clickable schematic in the
transmission app, so whatever the player toggles really changes how the truck behaves.

A vehicle describes its driveline as a nested tuple tree:
    ('center', 0, ('inter', 1, 2))      # 6x6: front axle | rear bogie (mid axle, rear axle)
    ('center', ('front', 0, 1), ('rear', 2, 3))   # 8x8
    ('center', 0, 1)                    # 4x4
Leaves are axle indices. Each diff splits torque equally per connected axle and couples its two
outputs by mode:  OPEN (almost free), LSD (viscous limited slip), LOCK (rigid).
"""
OPEN, LSD, LOCK = 0, 1, 2
MODE_NAMES = ('OPEN', 'LSD', 'LOCK')
MODE_HELP = (
    'Open: torque splits equally, so the output with the least grip decides how much power you get.',
    'Limited slip: shifts torque toward the slower (gripping) side. A good everyday setting.',
    'Locked: both sides forced to the same speed - maximum traction, but it binds on hard ground.',
)
# (coupling stiffness N*m per rad/s, max bias torque N*m) at diff_scale = 1
MODE_K = {OPEN: (40.0, 300.0), LSD: (400.0, 2500.0), LOCK: (3500.0, 14000.0)}


def _members(node):
    if isinstance(node, int):
        return [node]
    out = []
    for ch in node[1:]:
        out += _members(ch)
    return out


class Diff:
    __slots__ = ('id', 'name', 'a', 'b', 'mode', 'modes', 'node')

    def __init__(self, node, modes):
        self.node = node
        self.id = node[0]
        self.name = node[0]
        self.a = _members(node[1])
        self.b = _members(node[2])
        self.modes = modes
        self.mode = LSD


class Drivetrain:
    def __init__(self, spec, n_axles, scale=1.0):
        self.n = n_axles
        self.tree = spec['tree']
        self.scale = scale
        self.low_mult = spec.get('low_mult', 2.3)
        self.has_range = spec.get('has_range', True)      # False: single-speed transfer (road/rally cars)
        self.disconnectable = set(spec.get('disconnectable', ()))
        self.default_modes = dict(spec.get('default', {}))
        self.low = False
        self.axle_on = [i not in spec.get('axles_off', ()) for i in range(n_axles)]
        self.diffs = []
        self._collect(self.tree, spec.get('modes', (OPEN, LSD, LOCK)))
        self.reset_modes()

    def _collect(self, node, modes):
        if isinstance(node, int):
            return
        for ch in node[1:]:
            self._collect(ch, modes)
        self.diffs.append(Diff(node, modes))       # post-order: leaves first

    # ------------------------------------------------------------ state
    def reset_modes(self):
        for d in self.diffs:
            d.mode = self.default_modes.get(d.id, LSD)

    def diff(self, did):
        for d in self.diffs:
            if d.id == did:
                return d
        return None

    def set_mode(self, did, mode):
        d = self.diff(did)
        if d and mode in d.modes:
            d.mode = mode

    def cycle_mode(self, did):
        d = self.diff(did)
        if d:
            i = d.modes.index(d.mode) if d.mode in d.modes else 0
            d.mode = d.modes[(i + 1) % len(d.modes)]

    @property
    def all_locked(self):
        return all(d.mode == LOCK for d in self.diffs if LOCK in d.modes)

    def set_all_locked(self, on):
        if on:
            for d in self.diffs:
                if LOCK in d.modes:
                    d.mode = LOCK
        else:
            self.reset_modes()

    def toggle_axle(self, i):
        if i in self.disconnectable:
            others = sum(1 for k, on in enumerate(self.axle_on) if on and k != i)
            if self.axle_on[i] and others == 0:
                return
            self.axle_on[i] = not self.axle_on[i]

    @property
    def n_on(self):
        return sum(1 for on in self.axle_on if on)

    def drive_name(self):
        return '%dx%d' % (self.n * 2, self.n_on * 2)

    # ------------------------------------------------------------ physics
    def distribute(self, each, om, out):
        """Fill out[i] (torque per axle wheel) from `each` N*m per connected axle plus the
        coupling torque of every differential. om[i] are the wheel speeds."""
        on = self.axle_on
        for i in range(self.n):
            out[i] = each if on[i] else 0.0
        sc = self.scale
        for d in self.diffs:
            A = [i for i in d.a if on[i]]
            B = [i for i in d.b if on[i]]
            if not A or not B:
                continue
            ma = sum(om[i] for i in A) / len(A)
            mb = sum(om[i] for i in B) / len(B)
            k, mx = MODE_K[d.mode]
            bias = k * sc * (mb - ma)
            mx *= sc
            if bias > mx:
                bias = mx
            elif bias < -mx:
                bias = -mx
            ba, bb = bias / len(A), bias / len(B)
            for i in A:
                out[i] += ba
            for i in B:
                out[i] -= bb
