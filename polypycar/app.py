"""Application shell: window / display modes, FPS limiter, scene stack, screenshots, toasts."""
import os
import sys
import time
import pygame

from .settings import Settings, config_dir
from . import ui, gfx


def _make_dpi_aware():
    """On Windows, an app that isn't DPI-aware is told a *scaled* desktop size (e.g. 1536x864 on a 1080p
    screen at 125%) and gets bitmap-stretched. Opt in so desktop / borderless sizes are the real pixels."""
    if sys.platform != 'win32':
        return
    try:
        import ctypes
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)      # per-monitor
        except (AttributeError, OSError):
            ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass


class App:
    def __init__(self, settings=None):
        _make_dpi_aware()
        pygame.init()
        pygame.font.init()
        self.settings = settings or Settings()
        pygame.display.set_caption('PolyPyCar')
        self.scenes = []
        self.backdrop = None
        self.running = True
        self.clock = pygame.time.Clock()
        self.fps = 60.0
        self.toasts = []
        self.screen = None
        self.gl = None
        self.ui_surf = None
        self.gl_note = ''
        self.want_shot = False
        self.desktop = self._desktop()
        self.apply_display()
        pygame.key.start_text_input()

    # ------------------------------------------------------------------ display
    @staticmethod
    def _desktop():
        try:
            sizes = pygame.display.get_desktop_sizes()
            if sizes:
                return tuple(sizes[0])
        except pygame.error:
            pass
        return (1920, 1080)

    def apply_display(self):
        st = self.settings
        mode = st['display_mode']
        self.desktop = self._desktop()
        w, h = st['resolution']
        dw, dh = self.desktop
        if mode == 'borderless':
            # always the true desktop resolution; the saved windowed size is left alone
            size, flags = (dw, dh), pygame.NOFRAME
            os.environ['SDL_VIDEO_WINDOW_POS'] = '0,0'
            os.environ.pop('SDL_VIDEO_CENTERED', None)
        elif mode == 'fullscreen':
            size, flags = (min(w, dw), min(h, dh)), pygame.FULLSCREEN
        else:
            size, flags = (min(w, dw), min(h, dh)), pygame.RESIZABLE
            os.environ.pop('SDL_VIDEO_WINDOW_POS', None)
            os.environ['SDL_VIDEO_CENTERED'] = '1'
        self.gl = None
        gfx.ACTIVE = None
        if st['renderer'] != 'software' and not os.environ.get('POLYPYCAR_SOFTWARE'):
            self.screen = self._try_gl(size, flags)
        if self.gl is None:
            try:
                if self.ui_surf is not None or self.gl_note == 'gl-failed':
                    pygame.display.quit()
                    pygame.display.init()
                    pygame.display.set_caption('PolyPyCar')
                self.screen = pygame.display.set_mode(size, flags)
            except pygame.error:
                st['display_mode'] = 'windowed'
                self.screen = pygame.display.set_mode((1280, 720), pygame.RESIZABLE)
                return
            self.ui_surf = None
        if mode == 'borderless':
            try:                                   # an existing window keeps its old position otherwise
                pygame.display.set_window_position((0, 0))
            except (pygame.error, AttributeError):
                pass
        pygame.key.start_text_input()

    def _try_gl(self, size, flags):
        """Open an OpenGL window and the moderngl renderer; on any problem leave self.gl None (software fallback)."""
        st = self.settings
        try:
            import moderngl
        except ImportError:
            self.gl_note = 'moderngl is not installed - using the software renderer'
            return None
        try:
            if self.ui_surf is not None or self.gl_note == 'gl-failed':
                pygame.display.quit()
                pygame.display.init()
                pygame.display.set_caption('PolyPyCar')
            if os.environ.get('POLYPYCAR_GL_STANDALONE'):         # offscreen GL (tests / benchmarks without a window system)
                pygame.display.set_mode(size)
                ctx = moderngl.create_standalone_context(backend='egl')
                fbo = ctx.simple_framebuffer(size)
                gl = gfx.GLRenderer(ctx, target=fbo)
                self.gl, gfx.ACTIVE, self.gl_note = gl, gl, ''
                self.ui_surf = pygame.Surface(size, pygame.SRCALPHA)
                return self.ui_surf
            ga = pygame.display.gl_set_attribute
            ga(pygame.GL_CONTEXT_MAJOR_VERSION, 3)
            ga(pygame.GL_CONTEXT_MINOR_VERSION, 3)
            ga(pygame.GL_CONTEXT_PROFILE_MASK, pygame.GL_CONTEXT_PROFILE_CORE)
            ga(pygame.GL_MULTISAMPLEBUFFERS, 1 if st['msaa'] > 0 else 0)
            ga(pygame.GL_MULTISAMPLESAMPLES, int(st['msaa']))
            pygame.display.set_mode(size, flags | pygame.OPENGL | pygame.DOUBLEBUF, vsync=1 if st['vsync'] else 0)
            ctx = moderngl.create_context()
            gl = gfx.GLRenderer(ctx)
            name = gl.info.lower()
            if st['renderer'] == 'auto' and any(k in name for k in ('llvmpipe', 'software', 'gdi generic', 'swrast')):
                raise RuntimeError('software OpenGL (%s)' % gl.info)
        except Exception as ex:                       # no GL 3.3, driver trouble, ...
            self.gl_note = 'gl-failed'
            self.gl_error = str(ex)
            return None
        self.gl = gl
        gfx.ACTIVE = gl
        self.gl_note = ''
        self.ui_surf = pygame.Surface(pygame.display.get_window_size(), pygame.SRCALPHA)
        return self.ui_surf

    def toggle_fullscreen(self):
        st = self.settings
        st['display_mode'] = 'windowed' if st['display_mode'] != 'windowed' else 'borderless'
        self.rebuild_display()

    def rebuild_display(self):
        """Re-create the window (and, on the GPU path, every GL object); sessions rebuild their meshes on demand."""
        self.apply_display()
        self.backdrop = None
        for sc in self.scenes:
            if type(sc).__name__ == 'MainMenu':
                sc.on_enter()

    @property
    def renderer_name(self):
        return ('GPU - ' + self.gl.info) if self.gl else 'Software (CPU)'

    @property
    def u(self):
        return self.screen.get_height() / 720.0 * self.settings['ui_scale']

    # ------------------------------------------------------------------ scenes
    @property
    def top(self):
        return self.scenes[-1] if self.scenes else None

    def push(self, scene):
        self.scenes.append(scene)
        scene.on_enter()

    def pop(self):
        if self.scenes:
            s = self.scenes.pop()
            s.on_exit()
        if self.top:
            if hasattr(self.top, 'on_resume'):
                self.top.on_resume()
            else:
                self.top.on_enter()

    def goto(self, scene):
        """Replace the whole stack with the main menu (and optionally one scene on top of it)."""
        from .scenes import MainMenu
        for s in reversed(self.scenes):
            s.on_exit()
        self.scenes = []
        self.push(MainMenu(self))
        if scene is not None:
            self.push(scene)

    def start_drive(self, cfg=None):
        from .scenes import MainMenu, DriveScene
        st = self.settings
        c = dict(cfg or st['last'])
        if cfg is not None:
            st['last'].update({k: c[k] for k in c if k in st['last']})
        st.save()
        for s in reversed(self.scenes):
            s.on_exit()
        self.scenes = []
        self.push(MainMenu(self))
        self.push(DriveScene(self, c))

    def quit(self):
        self.running = False

    def toast(self, msg, secs=2.4):
        self.toasts.append([msg, secs])

    # ------------------------------------------------------------------ screenshots
    def screenshot(self):
        d = config_dir() / 'screenshots'
        try:
            d.mkdir(parents=True, exist_ok=True)
            path = d / ('polypycar_%s.png' % time.strftime('%Y%m%d_%H%M%S'))
            pygame.image.save(self.gl.grab() if self.gl else self.screen, str(path))
            self.toast('Screenshot saved: %s' % path.name)
        except OSError:
            self.toast('Could not save screenshot')

    # ------------------------------------------------------------------ main loop
    def handle_event(self, e):
        st = self.settings
        if e.type == pygame.QUIT:
            self.running = False
            return
        if e.type == pygame.VIDEORESIZE and st['display_mode'] == 'windowed':
            st['resolution'] = [max(640, e.w), max(360, e.h)]
        if e.type == pygame.KEYDOWN:
            if e.key == pygame.K_F12:
                self.want_shot = True
                return
            if e.key in st.keys('fullscreen') and not getattr(self.top, 'capturing', False):
                self.toggle_fullscreen()
                return
        if self.top:
            self.top.event(e)

    def step(self, dt):
        for e in pygame.event.get():
            self.handle_event(e)
        if not self.scenes:
            self.running = False
            return
        if self.gl:
            size = pygame.display.get_window_size()
            if self.ui_surf.get_size() != tuple(size):
                self.ui_surf = pygame.Surface(size, pygame.SRCALPHA)
            self.ui_surf.fill((0, 0, 0, 0))
            self.screen = self.ui_surf
            self.gl.begin(*size)
        else:
            self.screen = pygame.display.get_surface() or self.screen
        top = self.top
        # an overlay (pause, settings) is drawn over the scene beneath it
        i = len(self.scenes) - 1
        while i > 0 and self.scenes[i].overlay:
            i -= 1
        if self.backdrop is not None and type(self.scenes[i]).__name__ == 'MainMenu':
            self.backdrop.update(dt)
        top.update(dt)
        for s in self.scenes[i:]:
            s.draw(self.screen)
        self._draw_overlays(dt)
        if self.gl:
            self.gl.composite_ui(self.ui_surf)
        if self.want_shot:
            self.want_shot = False
            self.screenshot()

    def _draw_overlays(self, dt):
        u = self.u
        W, H = self.screen.get_size()
        if self.settings['show_fps']:
            ui.text(self.screen, '%d fps' % round(self.fps), (W - 14 * u, 12 * u), int(24 * u), ui.OK if self.fps >= 50 else ui.WARN, 'tr')
        y = H - 70 * u
        for t in list(self.toasts):
            t[1] -= dt
            if t[1] <= 0:
                self.toasts.remove(t)
                continue
            ui.text(self.screen, t[0], (W / 2, y), int(24 * u), ui.TEXT, 'c')
            y -= 30 * u

    def _limit(self, frame_start):
        """Frame limiter: sleep most of the remaining time, spin the last ~1.5 ms (Clock.tick is too coarse on Windows)."""
        target = self.settings['fps_target']
        if target <= 0:
            return
        end = frame_start + 1.0 / target
        while True:
            left = end - time.perf_counter()
            if left <= 0:
                return
            if left > 0.002:
                time.sleep(left - 0.0015)

    def run(self):
        self.goto(None)
        last = frame_start = time.perf_counter()
        while self.running:
            now = time.perf_counter()
            dt = min(now - last, 1 / 20.0)
            last = now
            self.fps += (1.0 / max(dt, 1e-4) - self.fps) * 0.08
            self.step(dt)
            pygame.display.flip()
            self._limit(frame_start)
            frame_start = time.perf_counter()
        self.settings.save()
        pygame.quit()
