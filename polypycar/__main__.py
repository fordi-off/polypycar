import argparse
import os

from .app import App
from .settings import Settings


def main():
    ap = argparse.ArgumentParser(description='PolyPyCar - low-poly 2D snow & mud offroad')
    ap.add_argument('--reset-settings', action='store_true', help='ignore and overwrite the saved settings')
    ap.add_argument('--windowed', action='store_true', help='force windowed mode for this run')
    a = ap.parse_args()
    st = Settings()
    if a.reset_settings:
        st.reset_all()
    if a.windowed:
        st['display_mode'] = 'windowed'
    App(st).run()


if __name__ == '__main__':
    main()
