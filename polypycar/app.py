"""Application shell: window / display modes, FPS limiter, scene stack, screenshots, toasts."""
import os
import time
import pygame

from .settings import Settings, config_dir
from . import ui


class App:
    def __init__(self, settings=None):
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
        w, h = st['resolution']
        dw, dh = self.desktop
        flags = 0
        if mode == 'borderless':
            size = (dw, dh)
            flags = pygame.NOFRAME
            os.environ['SDL_VIDEO_WINDOW_POS'] = '0,0'
            os.environ.pop('SDL_VIDEO_CENTERED', None)
        elif mode == 'fullscreen':
            size = (min(w, dw), min(h, dh))
            flags = pygame.FULLSCREEN
        else:
            size = (w, h)
            flags = pygame.RESIZABLE
            os.environ.pop('SDL_VIDEO_WINDOW_POS', None)
            os.environ['SDL_VIDEO_CENTERED'] = '1'
        try:
            self.screen = pygame.display.set_mode(size, flags)
        except pygame.error:
            st['display_mode'] = 'windowed'
            self.screen = pygame.display.set_mode((1280, 720), pygame.RESIZABLE)

    def toggle_fullscreen(self):
        st = self.settings
        st['display_mode'] = 'windowed' if st['display_mode'] != 'windowed' else 'borderless'
        self.apply_display()

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
            pygame.image.save(self.screen, str(path))
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
                self.screenshot()
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

    def run(self):
        self.goto(None)
        while self.running:
            target = self.settings['fps_target']
            ms = self.clock.tick(target if target > 0 else 0)
            dt = min(ms / 1000.0, 1 / 20.0)
            self.fps = self.clock.get_fps() or self.fps
            self.step(dt)
            pygame.display.flip()
        self.settings.save()
        pygame.quit()
