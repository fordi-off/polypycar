"""Map types and difficulty levels. A WorldConfig is everything the terrain generator needs to know
beyond the seed: which biomes appear, how hilly it is, how deep the soft stuff is, how hard it ramps."""
from dataclasses import dataclass, field

TAIGA, MUDLANDS, HIGHLAND, WHITEOUT, SUNBELT = range(5)
HARDPACK = 9      # material id (see terrain.MATERIALS)


@dataclass
class MapType:
    id: str
    name: str
    tagline: str
    description: str
    biomes: tuple                 # biome ids that can appear (a single one => fixed)
    start_biome: int = -1         # -1: first biome in `biomes` order is chosen by the generator
    relief: float = 1.0           # hill height multiplier
    soft: float = 1.0             # soft-layer depth multiplier (snow / mud)
    surf: dict = None             # optional {biome: {material: weight}} override
    sequence: tuple = ()          # forced biome order for the first segments (index 0 = start)
    preview: int = 0              # biome whose look is used on the card
    themes: tuple = None          # restrict zone themes (terrain.THEMES keys); None = the default mix
    start_surface: int = None     # material of the opening zones
    gaps: float = 1.0             # obstacle spacing multiplier
    fast: bool = False            # tuned for high speed (hint only)


@dataclass
class Difficulty:
    id: str
    name: str
    description: str
    start: float                  # obstacle difficulty at the start (0..1)
    span: float                   # metres until full difficulty
    soft: float                   # extra soil depth multiplier
    gaps: float                   # obstacle spacing multiplier (<1 = denser)


@dataclass
class WorldConfig:
    map: MapType
    diff: Difficulty
    snowfall: bool = True

    @property
    def biomes(self):
        return self.map.biomes


MAPS = [
    MapType('endless', 'Endless Trail', 'Every kind of ground, one long road',
            'Starts on easy dirt, then drifts into snowy taiga, mudlands, highland and whiteout. '
            'Everything the game has, in one endless trail.',
            (HIGHLAND, TAIGA, MUDLANDS, WHITEOUT), sequence=(HIGHLAND, TAIGA), preview=TAIGA),
    MapType('snowfield', 'Snowfield', 'Pines, drifts and ice',
            'Deep snow, packed trails and slick ice patches under a grey winter sky. Low tyre pressure is your friend.',
            (TAIGA, WHITEOUT), sequence=(TAIGA,), preview=TAIGA),
    MapType('mudbog', 'Mud Bog', 'Wet, sticky and relentless',
            'Rain-soaked lowlands full of mud holes and fallen timber. Heavy drag, little grip - lock your diffs.',
            (MUDLANDS,), sequence=(MUDLANDS,), soft=1.2, preview=MUDLANDS,
            surf={MUDLANDS: {2: 0.0, 3: 0.60, 0: 0.20, 4: 0.12, 5: 0.0, 7: 0.08}}),
    MapType('highland', 'Highland Pass', 'Steep dirt climbs and gravel',
            'Autumn hills with long climbs, rock ledges and firm gravel. A drivers test of power and gearing, '
            'not of flotation.',
            (HIGHLAND,), sequence=(HIGHLAND,), relief=1.5, soft=0.7, preview=HIGHLAND),
    MapType('whiteout', 'Whiteout', 'Deep snow and nothing else',
            'A blizzard-wrapped plateau with the deepest snow in the game. Every metre is a negotiation.',
            (WHITEOUT,), sequence=(WHITEOUT,), soft=1.25, preview=WHITEOUT),
    MapType('rally', 'Rally Stage', 'Full gas on gravel and tarmac',
            'No mud, no snow: hard-packed road, loose gravel and asphalt under a clear sky. Long crests, '
            'rhythm sections and jumps - flat out is the point. A rally car belongs here.',
            (SUNBELT,), sequence=(SUNBELT,), relief=0.8, soft=0.5, preview=SUNBELT, fast=True,
            themes=('rally_flow', 'rally_jumps', 'rally_rough', 'rally_clear'), start_surface=HARDPACK, gaps=1.1),
]
DIFFICULTIES = [
    Difficulty('easy', 'Easy', 'Shallower soil, fewer obstacles, slow ramp-up', 0.0, 6000.0, 0.8, 1.35),
    Difficulty('normal', 'Normal', 'The intended experience', 0.0, 3200.0, 1.0, 1.0),
    Difficulty('hard', 'Hard', 'Deeper soil, denser obstacles, faster ramp', 0.2, 1800.0, 1.15, 0.8),
    Difficulty('brutal', 'Brutal', 'Deep and dense from the first metre', 0.55, 900.0, 1.3, 0.62),
]
MAP_BY_ID = {m.id: m for m in MAPS}
DIFF_BY_ID = {d.id: d for d in DIFFICULTIES}


def make(map_id='endless', diff_id='normal', snowfall=True):
    return WorldConfig(MAP_BY_ID.get(map_id, MAPS[0]), DIFF_BY_ID.get(diff_id, DIFFICULTIES[1]), snowfall)
