import argparse
import random
from .game import Game


def main():
    ap = argparse.ArgumentParser(description='PolyPyCar - a chill low-poly 2D offroad sandbox')
    ap.add_argument('--seed', type=int, default=None, help='world seed (default: random)')
    ap.add_argument('--no-sound', action='store_true')
    ap.add_argument('--size', default='1280x720')
    ap.add_argument('--fullscreen', action='store_true')
    a = ap.parse_args()
    w, h = (int(v) for v in a.size.lower().split('x'))
    seed = a.seed if a.seed is not None else random.randrange(1, 10 ** 6)
    Game(seed, sound=not a.no_sound, size=(w, h), fullscreen=a.fullscreen).run()


if __name__ == '__main__':
    main()
