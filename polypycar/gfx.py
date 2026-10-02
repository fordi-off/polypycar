"""Drawing layer shared by the software (pygame) and GPU (OpenGL via moderngl) renderers.

A *painter* draws flat-coloured polygons / lines in whatever coordinate space the caller uses:
  SurfacePainter  -> straight onto a pygame Surface (software renderer)
  Recorder        -> collects triangles into an array (static terrain meshes, GPU batches)
GLRenderer owns the OpenGL context: shaders, a dynamic vertex batch, static meshes and the compositing of
the pygame-drawn UI/HUD layer on top of the GPU-drawn world.
"""
import array
import math
import pygame

# ----------------------------------------------------------------------------- triangulation
_TRI_CACHE = {}


def _cross(o, a, b):
    return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])


def _in_tri(p, a, b, c):
    d1, d2, d3 = _cross(a, b, p), _cross(b, c, p), _cross(c, a, p)
    neg = d1 < -1e-12 or d2 < -1e-12 or d3 < -1e-12
    pos = d1 > 1e-12 or d2 > 1e-12 or d3 > 1e-12
    return not (neg and pos)


def _ear_clip(pts):
    n = len(pts)
    idx = list(range(n))
    area2 = sum(pts[i][0] * pts[(i + 1) % n][1] - pts[(i + 1) % n][0] * pts[i][1] for i in range(n))
    if area2 < 0:
        idx.reverse()
    out = []
    while len(idx) > 3:
        m = len(idx)
        for k in range(m):
            i0, i1, i2 = idx[k - 1], idx[k], idx[(k + 1) % m]
            a, b, c = pts[i0], pts[i1], pts[i2]
            if _cross(a, b, c) <= 1e-12:
                continue
            if any(_in_tri(pts[j], a, b, c) for j in idx if j != i0 and j != i1 and j != i2 and pts[j] != a and pts[j] != b and pts[j] != c):
                continue
            out += [i0, i1, i2]
            idx.pop(k)
            break
        else:
            break                                   # degenerate polygon: fan whatever is left
    for k in range(1, len(idx) - 1):
        out += [idx[0], idx[k], idx[k + 1]]
    return out


def triangulate(pts):
    """Flat index list [i0,i1,i2, ...] triangulating a simple polygon. Convex polygons fan; others ear-clip.
    Results for tuple-keyed polygons are cached (static art is re-submitted every frame)."""
    n = len(pts)
    if n < 3:
        return []
    if n == 3:
        return [0, 1, 2]
    key = None
    if n > 12:                                       # big polygons are static art: worth caching
        key = tuple(pts)
        got = _TRI_CACHE.get(key)
        if got is not None:
            return got
    sign = 0
    convex = True
    for i in range(n):
        c = _cross(pts[i - 1], pts[i], pts[(i + 1) % n])
        if abs(c) < 1e-12:
            continue
        s = 1 if c > 0 else -1
        if sign == 0:
            sign = s
        elif s != sign:
            convex = False
            break
    if convex:
        idx = []
        for i in range(1, n - 1):
            idx += [0, i, i + 1]
    else:
        idx = _ear_clip(pts)
    if key is not None:
        if len(_TRI_CACHE) > 4000:
            _TRI_CACHE.clear()
        _TRI_CACHE[key] = idx
    return idx


# ----------------------------------------------------------------------------- painters
class SurfacePainter:
    """Software painter: draws straight into a pygame Surface."""
    needs_tris = False

    def __init__(self, surf):
        self.surf = surf

    def fan(self, col, c, ring):                      # star-shaped polygon given by its centre and boundary ring
        pygame.draw.polygon(self.surf, col, ring)

    def poly(self, col, pts):
        pygame.draw.polygon(self.surf, col, pts)

    def tris(self, col, verts, idx):                  # the software path just draws the polygon itself
        pygame.draw.polygon(self.surf, col, verts)

    def tri(self, col, a, b, c):
        pygame.draw.polygon(self.surf, col, (a, b, c))

    def poly_mono(self, col, top, bl, br):
        pygame.draw.polygon(self.surf, col, list(top) + [br, bl])

    def rect(self, col, x, y, w, h):
        self.surf.fill(col, (x, y, w, h))

    def line(self, col, a, b, w):
        pygame.draw.line(self.surf, col, a, b, max(1, int(w)))

    def lines(self, col, pts, w):
        pygame.draw.lines(self.surf, col, False, pts, max(1, int(w)))


class Recorder:
    """Collects triangles as float32 (x, y, r, g, b, a) vertices. Bulk numpy arrays can be spliced in order."""
    needs_tris = True

    def __init__(self):
        self.data = array.array('f')
        self.chunks = []                 # sealed byte blocks, in draw order
        self._nsealed = 0                # vertices in sealed blocks

    def clear(self):
        del self.data[:]
        self.chunks = []
        self._nsealed = 0

    @property
    def count(self):
        return self._nsealed + len(self.data) // 6

    def to_bytes(self):
        self._seal()
        return b''.join(self.chunks)

    def _seal(self):
        if self.data:
            self.chunks.append(self.data.tobytes())
            self._nsealed += len(self.data) // 6
            del self.data[:]

    def add_array(self, arr):
        """Splice a float32 array shaped (N, 6) / flat (x,y,r,g,b,a per vertex) after everything drawn so far."""
        if arr is None or len(arr) == 0:
            return
        self._seal()
        self.chunks.append(arr.tobytes())
        self._nsealed += arr.size // 6

    @staticmethod
    def _c(col):
        return col[0] / 255.0, col[1] / 255.0, col[2] / 255.0, (col[3] / 255.0 if len(col) > 3 else 1.0)

    def grad_rect(self, x, y, w, h, top, bottom):
        """Vertical gradient between two (r,g,b[,a]) colours."""
        r0, g0, b0, a0 = self._c(top)
        r1, g1, b1, a1 = self._c(bottom)
        self.data.extend((x, y, r0, g0, b0, a0, x + w, y, r0, g0, b0, a0, x + w, y + h, r1, g1, b1, a1,
                          x, y, r0, g0, b0, a0, x + w, y + h, r1, g1, b1, a1, x, y + h, r1, g1, b1, a1))

    def fan(self, col, c, ring):
        r, g, bl, al = self._c(col)
        ext = self.data.extend
        cx, cy = c
        n = len(ring)
        for k in range(n):
            a, b = ring[k], ring[(k + 1) % n]
            ext((cx, cy, r, g, bl, al, a[0], a[1], r, g, bl, al, b[0], b[1], r, g, bl, al))

    def tri(self, col, a, b, c):
        r, g, bl, al = self._c(col)
        self.data.extend((a[0], a[1], r, g, bl, al, b[0], b[1], r, g, bl, al, c[0], c[1], r, g, bl, al))

    def tris(self, col, verts, idx):
        r, g, bl, al = self._c(col)
        ext = self.data.extend
        for k in range(0, len(idx), 3):
            a, b, c = verts[idx[k]], verts[idx[k + 1]], verts[idx[k + 2]]
            ext((a[0], a[1], r, g, bl, al, b[0], b[1], r, g, bl, al, c[0], c[1], r, g, bl, al))

    def poly(self, col, pts):
        pts = [tuple(p) for p in pts]
        self.tris(col, pts, triangulate(pts))

    def poly_mono(self, col, top, bl, br):
        """Polygon bounded above by an x-monotone polyline and below by a horizontal line."""
        by = bl[1]
        r, g, bl_, al = self._c(col)
        ext = self.data.extend
        for i in range(len(top) - 1):
            a, b = top[i], top[i + 1]
            ext((a[0], a[1], r, g, bl_, al, b[0], b[1], r, g, bl_, al, b[0], by, r, g, bl_, al,
                 a[0], a[1], r, g, bl_, al, b[0], by, r, g, bl_, al, a[0], by, r, g, bl_, al))

    def rect(self, col, x, y, w, h):
        self.tris(col, ((x, y), (x + w, y), (x + w, y + h), (x, y + h)), (0, 1, 2, 0, 2, 3))

    def line(self, col, a, b, w):
        dx, dy = b[0] - a[0], b[1] - a[1]
        ln = math.hypot(dx, dy)
        if ln < 1e-9:
            return
        h = max(0.5, w) * 0.5
        nx, ny = -dy / ln * h, dx / ln * h
        self.tris(col, ((a[0] + nx, a[1] + ny), (b[0] + nx, b[1] + ny), (b[0] - nx, b[1] - ny), (a[0] - nx, a[1] - ny)), (0, 1, 2, 0, 2, 3))

    def lines(self, col, pts, w):
        for i in range(len(pts) - 1):
            self.line(col, pts[i], pts[i + 1], w)


# ----------------------------------------------------------------------------- OpenGL
_VS = """
#version 330
uniform vec4 u_xf;                 // scale.xy, translate.xy  (input units -> clip space)
in vec2 in_pos;
in vec4 in_col;
out vec4 v_col;
void main() {
    gl_Position = vec4(in_pos.x * u_xf.x + u_xf.z, in_pos.y * u_xf.y + u_xf.w, 0.0, 1.0);
    v_col = in_col;
}
"""
_FS = """
#version 330
in vec4 v_col;
out vec4 f_col;
void main() { f_col = v_col; }
"""
_UI_VS = """
#version 330
in vec2 in_pos;
out vec2 v_uv;
void main() {
    gl_Position = vec4(in_pos, 0.0, 1.0);
    v_uv = vec2(in_pos.x * 0.5 + 0.5, 0.5 - in_pos.y * 0.5);
}
"""
_UI_FS = """
#version 330
uniform sampler2D u_tex;
in vec2 v_uv;
out vec4 f_col;
void main() { f_col = texture(u_tex, v_uv).bgra; }     // pygame SRCALPHA surfaces are BGRA in memory
"""


ACTIVE = None          # the GLRenderer in use (None = software rendering); set by the App


class Mesh:
    __slots__ = ('vbo', 'vao', 'n')

    def __init__(self, vbo, vao, n):
        self.vbo, self.vao, self.n = vbo, vao, n

    def release(self):
        self.vao.release()
        self.vbo.release()


class GLRenderer:
    """Owns the GL state. Usage per frame: begin(W,H) -> painter calls / draw_mesh -> flush() -> composite_ui(surface)."""

    def __init__(self, ctx, target=None):
        import moderngl
        self.mgl = moderngl
        self.ctx = ctx
        self.target = target or ctx.screen
        self.prog = ctx.program(vertex_shader=_VS, fragment_shader=_FS)
        self.ui_prog = ctx.program(vertex_shader=_UI_VS, fragment_shader=_UI_FS)
        self.cap = 1 << 18
        self.dyn = ctx.buffer(reserve=self.cap * 4)
        self.vao = ctx.vertex_array(self.prog, [(self.dyn, '2f 4f', 'in_pos', 'in_col')])
        quad = array.array('f', (-1, -1, 1, -1, -1, 1, 1, 1))
        self.ui_vbo = ctx.buffer(quad.tobytes())
        self.ui_vao = ctx.vertex_array(self.ui_prog, [(self.ui_vbo, '2f', 'in_pos')])
        self.ui_tex = None
        self.rec = Recorder()
        self.W = self.H = 0
        self.ctx.enable(moderngl.BLEND)
        self.ctx.blend_func = (moderngl.SRC_ALPHA, moderngl.ONE_MINUS_SRC_ALPHA)
        self.info = ctx.info.get('GL_RENDERER', '?')
        self.xf_screen = (1.0, 1.0, 0.0, 0.0)

    # -------------------------------------------------------------- frame
    def begin(self, W, H, clear=(0.08, 0.1, 0.14, 1.0)):
        self.W, self.H = W, H
        self.target.use()
        self.target.viewport = (0, 0, W, H)
        self.target.clear(*clear)
        self.rec.clear()
        self.xf_screen = (2.0 / W, -2.0 / H, -1.0, 1.0)

    @property
    def painter(self):
        return self.rec

    def flush(self):
        """Draw everything the painter has collected so far (screen-pixel coordinates)."""
        n = self.rec.count
        if n == 0:
            return
        blob = self.rec.to_bytes()
        need = len(blob) // 4
        if need > self.cap:
            self.cap = need * 2
            self.dyn.release()
            self.dyn = self.ctx.buffer(reserve=self.cap * 4)
            self.vao = self.ctx.vertex_array(self.prog, [(self.dyn, '2f 4f', 'in_pos', 'in_col')])
        self.dyn.orphan(self.cap * 4)
        self.dyn.write(blob)
        self.prog['u_xf'].value = self.xf_screen
        self.vao.render(self.mgl.TRIANGLES, vertices=n)
        self.rec.clear()

    # -------------------------------------------------------------- static meshes
    def make_mesh(self, rec):
        n = rec.count
        vbo = self.ctx.buffer(rec.to_bytes() or b'\0' * 24)
        vao = self.ctx.vertex_array(self.prog, [(vbo, '2f 4f', 'in_pos', 'in_col')])
        return Mesh(vbo, vao, n)

    def draw_mesh(self, mesh, xf):
        """xf = (sx, sy, tx, ty) mapping the mesh's own coordinates to clip space."""
        self.flush()
        if mesh.n:
            self.prog['u_xf'].value = xf
            mesh.vao.render(self.mgl.TRIANGLES, vertices=mesh.n)

    # -------------------------------------------------------------- UI layer
    def composite_ui(self, ui_surface):
        """Blend the pygame-drawn UI (straight alpha) over the world."""
        self.flush()
        W, H = ui_surface.get_size()
        if self.ui_tex is None or self.ui_tex.size != (W, H):
            if self.ui_tex is not None:
                self.ui_tex.release()
            self.ui_tex = self.ctx.texture((W, H), 4)
            self.ui_tex.filter = (self.mgl.NEAREST, self.mgl.NEAREST)
        self.ui_tex.write(ui_surface.get_buffer())
        self.ui_tex.use(0)
        self.ui_prog['u_tex'].value = 0
        self.ui_vao.render(self.mgl.TRIANGLE_STRIP)

    def grab(self):
        """Current framebuffer as a pygame Surface (screenshots)."""
        W, H = self.W, self.H
        raw = self.target.read(viewport=(0, 0, W, H), components=3)
        return pygame.transform.flip(pygame.image.frombuffer(raw, (W, H), 'RGB'), False, True)
