import argparse
import os

from .app import App
from .settings import Settings


def main():
    ap = argparse.ArgumentParser(description='PolyPyCar - low-poly 2D snow & mud offroad')
    ap.add_argument('--reset-settings', action='store_true', help='ignore and overwrite the saved settings')
    ap.add_argument('--windowed', action='store_true', help='force windowed mode for this run')
    ap.add_argument('--bench', action='store_true', help='print a frame-time breakdown for the current settings and exit')
    ap.add_argument('--renderer', choices=('auto', 'gpu', 'software'), help='override the renderer for this run')
    ap.add_argument('--quality', choices=('low', 'medium', 'high'), help='override the quality preset for this run')
    a = ap.parse_args()
    st = Settings()
    if a.reset_settings:
        st.reset_all()
    if a.windowed:
        st['display_mode'] = 'windowed'
    if a.renderer:
        st['renderer'] = a.renderer
    if a.quality:
        st['quality'] = a.quality
    app = App(st)
    if a.bench:
        from . import bench
        bench.run(app)
        return
    app.run()


if __name__ == '__main__':
    main()
