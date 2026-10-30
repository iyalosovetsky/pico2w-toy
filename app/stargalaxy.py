"""ЗОРЯНИЙ ТОРГОВЕЦЬ: the galaxy - 256 star systems grown from one seed in two spiral arms (light years,
3D), their names, economies, governments, tech levels and planets; the goods and the market prices.

All our own tables: the names come from syllables, the prices from a base price and how much an
agricultural or an industrial world wants the thing.
"""
import math
import random

N_SYSTEMS = 256
RADIUS = 46.0                        # light years
JUMP_MAX = 7.0                       # a full tank
START = "Ортея"
GALAXIES = 8                          # the galactic hyperdrive takes us on to the next (and round to the first)

SYLL = ["ор", "те", "я", "ла", "ве", "ри", "са", "но", "ди", "ка", "ус", "ен", "ар", "ти", "бо", "ге", "за", "ми",
        "ру", "хо", "ле", "ан", "із", "ок", "ма", "ре", "ва", "ін", "ол", "ес", "ну", "дра", "кси", "тор", "лі",
        "ен", "аш", "уль", "ве", "ри", "он", "ет", "ів", "ам", "ко", "зе", "ця", "ба"]
ECONOMY = ["Багата промислова", "Середня промислова", "Бідна промислова", "Переважно промислова",
           "Переважно аграрна", "Багата аграрна", "Середня аграрна", "Бідна аграрна"]
GOVERNMENT = ["Анархія", "Феодальна", "Багатоурядова", "Диктатура", "Комуністична", "Конфедерація",
              "Демократія", "Корпоративна держава"]
KINDS = ["earth", "desert", "ice", "moon", "lava", "ocean"]
SUNS = [(255, 220, 140), (255, 160, 110), (235, 240, 255), (150, 190, 255), (255, 240, 200)]

PRAISE = ["древніми лісами", "безкраїми пустелями", "міцним місцевим вином", "небезпечними хижаками",
          "гарячими гейзерами", "повільними поетами", "святом місячного пилу", "любов'ю до бюрократії",
          "кам'яними містами", "шаленими ураганами", "хорами співочих грибів", "віковими руїнами",
          "смачною їжею з водоростей", "гостинними мешканцями", "нескінченними дощами", "кришталевими горами"]
WARN = ["але бійтеся місцевих податківців", "та частими землетрусами", "і дивною модою на капелюхи",
        "але тутешні пірати не сплять", "та найнуднішими новинами галактики", "і шаховими турнірами в невагомості",
        "але кава тут жахлива", "та рекордними врожаями", "і таємничими сигналами з полюса"]


class System:
    __slots__ = ("idx", "name", "x", "y", "z", "econ", "gov", "tech", "pop", "prod", "radius_km", "kind", "seed",
                 "desc", "sun")

    def dist(self, o):
        return math.sqrt((self.x - o.x) ** 2 + (self.y - o.y) ** 2 + (self.z - o.z) ** 2)

    @property
    def pos(self):
        return (self.x, self.y, self.z)


def make_name(rnd, used):
    while True:
        n = "".join(rnd.choice(SYLL) for _ in range(rnd.choice((2, 2, 3))))
        n = n[0].upper() + n[1:]
        if 3 < len(n) < 10 and n not in used and not n.endswith(("ьь",)):
            used.add(n)
            return n


def generate(number=0):
    """Galaxy `number`: the systems and the start's index (Ortea in the first; a central-ish system in the
    others); every system within reach of the main cluster. Each galaxy turns its spiral its own way."""
    seed = 1 + number * 7919
    rnd = random.Random(seed)
    twist = number * 0.9
    systems, used = [], set()
    for i in range(N_SYSTEMS):
        s = System()
        s.idx = i
        t = rnd.random() ** 0.7
        a = (i % 2) * math.pi + t * (5.2 - number * 0.25) + twist + rnd.gauss(0, 0.35)
        r = 4 + (RADIUS - 4) * t
        s.x, s.z = r * math.cos(a), r * math.sin(a)
        s.y = rnd.gauss(0, 2.2 * (1.2 - t))
        s.seed = rnd.randrange(1 << 30)
        sr = random.Random(s.seed)
        s.name = make_name(sr, used)
        s.gov = sr.randrange(8)
        s.econ = sr.randrange(8)
        if s.gov <= 1:                                   # anarchies and feudal worlds are never rich
            s.econ = max(s.econ, 2) if s.econ < 4 else s.econ
        s.tech = max(1, min(15, (7 - s.econ) + s.gov // 2 + sr.randrange(4) + 1))
        s.pop = round((s.tech * 4 + s.gov + s.econ + 1) / 10.0, 1)               # billions
        s.prod = (8 - s.econ) * (s.gov + 3) * 8 * (s.tech + 1) // 4               # M Cr
        s.radius_km = sr.randrange(2800, 7600)
        s.kind = sr.choice(KINDS)
        s.sun = sr.choice(SUNS)
        s.desc = "%s відома %s, %s." % (s.name, sr.choice(PRAISE), sr.choice(WARN))
        systems.append(s)
    connect(systems)
    start = min(systems, key=lambda s: abs(math.hypot(s.x, s.z) - RADIUS * 0.45) + abs(s.y))
    if number == 0:
        start.name = START
        start.econ, start.gov, start.tech, start.kind = 5, 6, 7, "earth"
        start.desc = "Ортея відома гостинними мешканцями, та рекордними врожаями."
    return systems, start.idx


def connect(systems, reach=JUMP_MAX * 0.92):
    """Pull lone groups of stars towards the main cluster until every system can be reached."""
    for _ in range(40):
        comp = components(systems, reach)
        if len(comp) == 1:
            return
        main = max(comp, key=len)
        ms = [systems[i] for i in main]
        for c in comp:
            if c is main:
                continue
            group = [systems[i] for i in c]
            a, b = min(((g, m) for g in group for m in ms), key=lambda p: p[0].dist(p[1]))
            d = a.dist(b)
            k = (d - reach * 0.9) / d
            dx, dy, dz = (b.x - a.x) * k, (b.y - a.y) * k, (b.z - a.z) * k
            for g in group:
                g.x, g.y, g.z = g.x + dx, g.y + dy, g.z + dz


def components(systems, reach):
    left = set(range(len(systems)))
    out = []
    while left:
        i = left.pop()
        comp, todo = [i], [i]
        while todo:
            a = systems[todo.pop()]
            near = [j for j in left if a.dist(systems[j]) <= reach]
            for j in near:
                left.discard(j)
                comp.append(j)
                todo.append(j)
        out.append(comp)
    return out


def within(systems, here, reach):
    return [s for s in systems if s is not here and here.dist(s) <= reach]


# ---------------------------------------------------------------- goods and prices

# name, unit, base price (Cr), agricultural (+: made on farm worlds, cheap there; -: made by industry),
# typical stock, the least tech level that makes it, legal
GOODS = [
    ("Їжа", "т", 4.6, 1.0, 22, 1, True),
    ("Тканини", "т", 6.6, 0.6, 18, 1, True),
    ("Радіоактиви", "т", 22.0, -0.4, 10, 3, True),
    ("Роботи-помічники", "т", 34.0, -0.8, 8, 6, True),
    ("Напої", "т", 26.0, 0.9, 14, 1, True),
    ("Предмети розкоші", "т", 92.0, -0.7, 7, 4, True),
    ("Стимулятори", "т", 60.0, 0.3, 5, 2, False),
    ("Комп'ютери", "т", 84.0, -1.0, 10, 8, True),
    ("Машини", "т", 58.0, -0.8, 12, 5, True),
    ("Сплави", "т", 40.0, -0.5, 14, 3, True),
    ("Зброя", "т", 72.0, -0.9, 6, 6, False),
    ("Хутро", "т", 54.0, 1.0, 9, 1, True),
    ("Мінерали", "т", 11.0, 0.5, 20, 1, True),
    ("Золото", "кг", 37.0, 0.1, 16, 1, True),
    ("Платина", "кг", 66.0, 0.3, 10, 1, True),
    ("Самоцвіти", "г", 16.0, 0.4, 12, 1, True),
]
FUEL_PRICE = 1.6                      # Cr a light year


def market(sys_, visit):
    """[(price, stock)] for each of GOODS - by the economy (0 rich industrial .. 7 poor agricultural), the
    tech level, the government (the strict ones keep illegal goods off the board) and this visit's luck."""
    rnd = random.Random(sys_.seed * 977 + visit * 131)
    e = (sys_.econ - 3.5) / 3.5                     # -1 industrial .. +1 agricultural
    out = []
    for name, unit, base, agri, stock, tech, legal in GOODS:
        k = agri * e
        price = base * (1 - 0.32 * k) * rnd.uniform(0.9, 1.1)
        qty = stock * (1 + 0.7 * k) * rnd.uniform(0.5, 1.4)
        if sys_.tech < tech:
            qty = 0
        if not legal and sys_.gov >= 5:
            qty = 0
            price *= 1.5                             # scarce where banned: the black market pays well
        out.append((round(max(0.4, price), 1), max(0, int(qty))))
    return out
