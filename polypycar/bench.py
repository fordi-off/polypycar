"""`python -m polypycar --bench`: drive a few seconds with the current settings and print where the time goes,
so a slow machine can be diagnosed (CPU simulation vs. drawing vs. presenting the frame)."""
import time
import pygame


def run(app, frames=300):
    from .scenes import DriveScene
    st = app.settings
    app.goto(None)
    app.start_drive({'vehicle': st['last']['vehicle'], 'paint': 0, 'map': 'snowfield', 'difficulty': 'normal', 'seed': 5, 'snowfall': True})
    drive = app.top
    assert isinstance(drive, DriveScene)
    drive.hud_hide = False
    sess = drive.session
    names = ('update (physics)', 'world draw (CPU)', 'GPU wait', 'hud + overlays', 'present')
    acc = [0.0] * 5
    pc = time.perf_counter
    from .session import Controls
    c = Controls()
    c.up = 0.8
    for i in range(frames + 30):
        pygame.event.pump()
        t0 = pc()
        sess.update(1 / 60, c)
        t1 = pc()
        if app.gl:
            app.screen = app.ui_surf
            app.ui_surf.fill((0, 0, 0, 0))
            app.gl.begin(*app.ui_surf.get_size())
        else:
            app.screen = pygame.display.get_surface()
        sess.draw(app.screen)
        ta = pc()
        if app.gl:
            app.gl.ctx.finish()
        t2 = pc()
        drive.hud.draw(app.screen, drive)
        app._draw_overlays(0.0)
        t3 = pc()
        if app.gl:
            app.gl.composite_ui(app.ui_surf)
        pygame.display.flip()
        if app.gl:
            app.gl.ctx.finish()
        t4 = pc()
        if i >= 30:
            for k, v in enumerate((t1 - t0, ta - t1, t2 - ta, t3 - t2, t4 - t3)):
                acc[k] += v
    tot = sum(acc) / frames * 1000
    print('renderer : %s' % app.renderer_name)
    if app.gl and 'llvmpipe' in app.gl.info:
        print('(software OpenGL: the GPU-wait row is CPU rasterisation here, not a real GPU)')
    print('size     : %dx%d   quality %s' % (app.screen.get_width(), app.screen.get_height(), st['quality']))
    for n, a in zip(names, acc):
        print('%-15s %6.2f ms' % (n, a / frames * 1000))
    print('%-15s %6.2f ms   (~%d fps uncapped)' % ('total', tot, 1000 / tot))
    # the real loop: events, scene update (incl. audio), draw, HUD, present - no frame limiter
    app.settings['fps_target'] = 0
    app.settings['show_fps'] = False
    t0 = pc()
    n = 240
    for _ in range(n):
        app.step(1 / 60)
        pygame.display.flip()
    print('%-15s %6.2f ms   (~%d fps) <- what the game really runs at, uncapped' % ('full game step', (pc() - t0) / n * 1000, n / (pc() - t0)))
