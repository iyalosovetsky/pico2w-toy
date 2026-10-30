"""The menu's folders: a column of icons on the left, the chosen folder's items on the right.

A few folders (Улюблене, Ігри, Інструменти, Система by default) and «Інше» - the top level: whatever is in
no folder (a new item too) is there, and a removed folder's items go back to it. Kept in
~/.config/lcdtoy/menu-folders.json as {"folders": [{"name", "icon", "items": [item names]}], "current": n,
"launches": {item: score}, "hidden": [items]}.

The folder with the star is the favourites: shortcuts, the items stay in their own folders too, the most run
first. Pinned ones (moved there) and the ones run often: each run adds 1 to the item's score and takes 2 % off
all the others - three runs lately (a score of 2) bring it in, some 20 runs of others take it out. One
taken out of the favourites by hand is not brought back.

A long press of OK (the stick's centre, Enter, a gamepad's cross) opens the folder dialog: move the item to a
folder, create, rename or remove a folder. The icons are drawn in code.
"""
import json
import math
import os

import pygame
import lcd

FILE = os.path.expanduser("~/.config/lcdtoy/menu-folders.json")
OTHER = "Інше"
MAX_FOLDERS = 6                      # with «Інше»: what fits the column of icons
DEFAULT = [
    ("Улюблене", "star", []),
    ("Ігри", "games", ["PONG", "TETRIS", "POKER", "CHESS", "PREFERANS", "DOOM", "PICO RUSH", "STAR TRADER"]),
    ("Інструменти", "tools", ["GENERATOR", "SERIAL", "CALC", "SDR", "FLIPPER", "PYTHON", "BASIC", "EDIT",
                              "AI CHAT"]),
    ("Система", "gear", ["BLUETOOTH", "SOUND", "CONSOLE", "HDMI", "POWER OFF"]),
]
# icon -> its colour and the name a new folder with it gets (unless one is typed)
ICONS = {"star": ((255, 200, 0), "Улюблене"), "games": ((240, 90, 80), "Ігри"),
         "tools": ((90, 160, 255), "Інструменти"), "gear": ((175, 175, 185), "Система"),
         "heart": ((255, 110, 160), "Обране"), "music": ((110, 220, 130), "Музика"),
         "book": ((255, 160, 70), "Читання"), "flag": ((80, 220, 220), "Проєкти"),
         "folder": ((230, 190, 90), "Тека"), "other": ((200, 200, 200), OTHER)}
CHOICE = [k for k in ICONS if k != "other"]
FAV_ICON = "star"
FAV_SCORE = 2.0                      # an often-run item comes into the favourites
FAV_AUTO = 5                         # at most so many of them
DECAY = 0.98                         # each run takes this much off the others' scores
NO_AUTO = {"SOUND", "POWER OFF", "CONSOLE", "HDMI"}   # switches, not programs

BG, FG, DIM, ACCENT = (0, 0, 0), (220, 220, 220), (110, 110, 110), (255, 200, 0)


def _dejavu(name, px):
    size = px / lcd.S if lcd.S != 1 else int(px)
    try:
        return pygame.font.Font("/usr/share/fonts/truetype/dejavu/" + name, size)
    except (FileNotFoundError, OSError):
        return pygame.font.Font(None, size)


BIG = lcd.S > 1
f_head = _dejavu("DejaVuSans-Bold.ttf", 24 if BIG else 11)
f_text = _dejavu("DejaVuSans.ttf", 15 if BIG else 9)
f_bold = _dejavu("DejaVuSans-Bold.ttf", 15 if BIG else 9)
f_small = _dejavu("DejaVuSans.ttf", 12 if BIG else 7)


class Folders:
    def __init__(self, names):
        self.names = names                   # the menu's items here (in their order)
        self.folders = [{"name": n, "icon": i, "items": list(it)} for n, i, it in DEFAULT]
        self.current = 0
        self.launches = {}
        self.hidden = set()
        try:
            with open(FILE, encoding="utf-8") as f:
                data = json.load(f)
            folders = [{"name": str(d["name"]), "icon": d["icon"] if d.get("icon") in ICONS else "folder",
                        "items": [str(x) for x in d.get("items", [])]} for d in data["folders"]]
            self.folders = folders[:MAX_FOLDERS - 1]
            self.current = int(data.get("current", 0))
            self.launches = {str(k): float(v) for k, v in data.get("launches", {}).items()}
            self.hidden = set(map(str, data.get("hidden", [])))
        except (OSError, ValueError, KeyError, TypeError):
            pass
        self.current = max(0, min(self.current, len(self.folders)))

    def save(self):
        try:
            os.makedirs(os.path.dirname(FILE), exist_ok=True)
            with open(FILE + ".tmp", "w", encoding="utf-8") as f:
                json.dump({"folders": self.folders, "current": self.current,
                           "launches": {k: round(v, 3) for k, v in self.launches.items() if v > 0.05},
                           "hidden": sorted(self.hidden)}, f, ensure_ascii=False, indent=1)
            os.replace(FILE + ".tmp", FILE)
        except OSError:
            pass

    def count(self):
        return len(self.folders) + 1

    def name(self, i):
        return self.folders[i]["name"] if i < len(self.folders) else OTHER

    def icon(self, i):
        return self.folders[i]["icon"] if i < len(self.folders) else "other"

    def fav(self):
        """The favourites' index (the folder with the star), or None."""
        return next((i for i, f in enumerate(self.folders) if f["icon"] == FAV_ICON), None)

    def auto(self):
        """The often-run items not pinned: the best scores first."""
        pinned = set(self.folders[self.fav()]["items"]) if self.fav() is not None else set()
        best = sorted((v, n) for n, v in self.launches.items()
                      if v >= FAV_SCORE and n in self.names and n not in pinned and n not in self.hidden
                      and n not in NO_AUTO)
        return [n for v, n in reversed(best)][:FAV_AUTO]

    def items(self, i):
        """Indices (into the menu's items) of folder i, in the menu's order (the favourites - the pinned and
        the often run - the most run first)."""
        if i == self.fav():
            inside = set(self.folders[i]["items"]) | set(self.auto())
            fav = [k for k, n in enumerate(self.names) if n in inside]
            return sorted(fav, key=lambda k: -self.launches.get(self.names[k], 0.0))
        if i < len(self.folders):
            inside = set(self.folders[i]["items"])
            return [k for k, n in enumerate(self.names) if n in inside]
        anywhere = set(x for k, f in enumerate(self.folders) if k != self.fav() for x in f["items"])
        return [k for k, n in enumerate(self.names) if n not in anywhere]

    def launched(self, item):
        if item in NO_AUTO:
            return
        for n in self.launches:
            self.launches[n] *= DECAY
        self.launches[item] = self.launches.get(item, 0.0) + 1.0
        self.save()

    def move(self, item, dest):
        """To a folder; to the favourites - pinned there, still in its own folder."""
        if dest == self.fav():
            if item not in self.folders[dest]["items"]:
                self.folders[dest]["items"].append(item)
            self.hidden.discard(item)
            self.save()
            return
        for k, f in enumerate(self.folders):
            if k != self.fav() and item in f["items"]:
                f["items"].remove(item)
        if dest < len(self.folders):
            self.folders[dest]["items"].append(item)
        self.save()

    def unfav(self, item):
        """Out of the favourites, and not brought back by its runs."""
        f = self.fav()
        if f is not None and item in self.folders[f]["items"]:
            self.folders[f]["items"].remove(item)
        self.hidden.add(item)
        self.save()

    def create(self, name, icon):
        self.folders.append({"name": name, "icon": icon, "items": []})
        self.current = len(self.folders) - 1
        self.save()

    def remove(self, i):
        """The folder goes; its items are back at the top level («Інше»)."""
        if i < len(self.folders):
            del self.folders[i]
            self.current = min(self.current, len(self.folders))
            self.save()


# ---------------------------------------------------------------- icons

def draw_icon(surf, kind, cx, cy, color, bg=BG, k=1.0):
    """A 14 x 14 icon (times k) centred on (cx, cy), in the menu's 128-pixel coordinates."""
    d = pygame.draw

    def p(x, y):
        return (cx + x * k, cy + y * k)

    def poly(*pts, col=color):
        d.polygon(surf, col, [p(x, y) for x, y in pts])

    def circ(x, y, r, col=color):
        d.circle(surf, col, p(x, y), r * k)

    def rect(x, y, w, h, col=color, rad=0):
        d.rect(surf, col, (cx + x * k, cy + y * k, w * k, h * k), border_radius=round(rad * k))

    def line(x0, y0, x1, y1, w):
        d.line(surf, color, p(x0, y0), p(x1, y1), max(1, round(w * k)))

    if kind == "star":
        poly(*[((7 if i % 2 == 0 else 3) * math.cos(-math.pi / 2 + i * math.pi / 5),
                0.6 + (7 if i % 2 == 0 else 3) * math.sin(-math.pi / 2 + i * math.pi / 5)) for i in range(10)])
    elif kind == "games":
        rect(-7, -4, 14, 9, rad=3)
        circ(-4, 4, 3)
        circ(4, 4, 3)
        rect(-5.5, -1, 4, 1.4, bg)
        rect(-4.2, -2.3, 1.4, 4, bg)
        circ(3, -1.2, 1.1, bg)
        circ(5, 0.8, 1.1, bg)
    elif kind == "tools":
        line(-5, 5, 2, -2, 3)
        circ(3, -3, 4)
        circ(5, -5, 2, bg)
    elif kind == "gear":
        for i in range(8):
            ca, sa = math.cos(i * math.pi / 4), math.sin(i * math.pi / 4)
            poly(*[(ca * r - sa * w, sa * r + ca * w) for r, w in ((3, -1.4), (7, -1.2), (7, 1.2), (3, 1.4))])
        circ(0, 0, 5)
        circ(0, 0, 2, bg)
    elif kind == "heart":
        circ(-3, -2, 3.6)
        circ(3, -2, 3.6)
        poly((-6.5, -0.5), (6.5, -0.5), (0, 6.5))
    elif kind == "music":
        circ(-3, 4, 2.8)
        line(-0.8, 4, -0.8, -6, 2)
        poly((-0.8, -6.5), (5.5, -4), (5.5, -1.5), (-0.8, -3.8))
    elif kind == "book":
        poly((-7, -5), (-0.7, -4), (-0.7, 6), (-7, 5))
        poly((7, -5), (0.7, -4), (0.7, 6), (7, 5))
    elif kind == "flag":
        line(-5, -6, -5, 7, 2)
        poly((-5, -6.5), (6.5, -3.5), (-5, 1))
    elif kind == "folder":
        poly((-7, -5), (-2, -5), (0, -3), (7, -3), (7, 5), (-7, 5))
    else:                                                       # «Інше»: the grid of apps
        for dx in (-3.5, 3.5):
            for dy in (-3.5, 3.5):
                rect(dx - 2.6, dy - 2.6, 5.2, 5.2, rad=1)


def column(surf, folders, cur, y0, h):
    """The icons down the left edge, the current one framed."""
    n = folders.count()
    step = min(20, h / n)
    for i in range(n):
        cy = y0 + step * i + step / 2
        col = ICONS[folders.icon(i)][0]
        if i == cur:
            pygame.draw.rect(surf, (45, 40, 20), (1, cy - step / 2 + 1, 20, step - 2), border_radius=4)
            pygame.draw.rect(surf, ACCENT, (1, cy - step / 2 + 1, 20, step - 2), 1, border_radius=4)
            draw_icon(surf, folders.icon(i), 11, cy, col, (45, 40, 20))
        else:
            draw_icon(surf, folders.icon(i), 11, cy, tuple(c * 0.55 for c in col))


# ---------------------------------------------------------------- the dialog

def _fit(s, f, width):
    if f.size(s)[0] <= width:
        return s
    while s and f.size(s + "…")[0] > width:
        s = s[:-1]
    return s + "…"


def _keys(clock):
    """KEYDOWN events (a held key's release - the long press that opened us - is not one)."""
    clock.tick(20)
    out = []
    for ev in pygame.event.get():
        if ev.type == pygame.QUIT:
            pygame.event.post(ev)                # the menu sees it and ends
            out.append(None)
        elif ev.type == pygame.KEYDOWN:
            out.append(ev)
    return out


def _cancel(ev):
    hat = getattr(ev, "hat", False)
    return ev is None or ev.key == pygame.K_ESCAPE or ev.key == pygame.K_LEFT or (hat and ev.key == pygame.K_3)


def _ok(ev):
    return ev.key in (pygame.K_RETURN, pygame.K_KP_ENTER, pygame.K_SPACE, pygame.K_RIGHT)


def choose(screen, clock, title, options, icons=None):
    """A list to pick from: the index, or None (Esc / ← / KEY3)."""
    sel = 0
    lh = max(f_text.get_linesize() + 3, 17 if icons else 0)
    while True:
        screen.fill(BG)
        t = f_bold.render(_fit(title, f_bold, 124), True, ACCENT)
        screen.blit(t, ((128 - t.get_width()) / 2, 3))
        y0 = 6 + f_bold.get_linesize()
        pygame.draw.line(screen, DIM, (4, y0 - 2), (124, y0 - 2))
        top = max(0, min(sel - 3, len(options) - int((120 - y0) // lh)))
        for i in range(top, len(options)):
            y = y0 + (i - top) * lh
            if y + lh > 126:
                break
            x = 6
            if i == sel:
                pygame.draw.rect(screen, ACCENT, (2, y, 124, lh - 1), border_radius=3)
            if icons and icons[i]:
                draw_icon(screen, icons[i], 11, y + lh / 2, BG if i == sel else ICONS[icons[i]][0],
                          ACCENT if i == sel else BG)
                x = 22
            s = f_text.render(_fit(options[i], f_text, 124 - x), True, BG if i == sel else FG)
            screen.blit(s, (x, y + (lh - f_text.get_linesize()) / 2))
        lcd.flip()
        for ev in _keys(clock):
            if _cancel(ev):
                return None
            if ev.key == pygame.K_UP:
                sel = (sel - 1) % len(options)
                lcd.play("click")
            elif ev.key == pygame.K_DOWN:
                sel = (sel + 1) % len(options)
                lcd.play("click")
            elif _ok(ev) and ev.key != pygame.K_RIGHT:
                lcd.play("select")
                return sel


def edit(screen, clock, title, name=None, icon="folder"):
    """The folder's icon (← / →) and name (typed; the icon's own name until something is typed):
    (name, icon), or None."""
    typed = name is not None
    k = CHOICE.index(icon) if icon in CHOICE else 0
    name = name if typed else ICONS[CHOICE[k]][1]
    while True:
        screen.fill(BG)
        t = f_bold.render(title, True, ACCENT)
        screen.blit(t, ((128 - t.get_width()) / 2, 3))
        icon = CHOICE[k]
        col = ICONS[icon][0]
        pygame.draw.rect(screen, (40, 40, 40), (44, 22, 40, 34), border_radius=6)
        draw_icon(screen, icon, 64, 39, col, (40, 40, 40), 2.0)
        for x, ch in ((34, "‹"), (90, "›")):
            s = f_head.render(ch, True, DIM)
            screen.blit(s, (x - s.get_width() / 2, 30))
        s = f_head.render(_fit(name + ("_" if pygame.time.get_ticks() // 500 % 2 else " "), f_head, 124), True, FG)
        screen.blit(s, ((128 - s.get_width()) / 2, 64))
        for i, line in enumerate(("← → - значок", "літери - назва",
                                  "%s - готово, %s - скасувати" % (lcd.OK, lcd.BACK))):
            s = f_small.render(line, True, DIM)
            screen.blit(s, ((128 - s.get_width()) / 2, 90 + i * (f_small.get_linesize() + 1)))
        lcd.flip()
        for ev in _keys(clock):
            hat = ev is not None and getattr(ev, "hat", False)
            if ev is None or ev.key == pygame.K_ESCAPE or (hat and ev.key == pygame.K_3):
                return None
            if ev.key in (pygame.K_LEFT, pygame.K_RIGHT):
                k = (k + (1 if ev.key == pygame.K_RIGHT else -1)) % len(CHOICE)
                if not typed:
                    name = ICONS[CHOICE[k]][1]
                lcd.play("click")
            elif ev.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                if name.strip():
                    lcd.play("select")
                    return name.strip(), CHOICE[k]
            elif ev.key == pygame.K_BACKSPACE:
                name = name[:-1] if typed else ""
                typed = True
            elif not hat and ev.unicode and ev.unicode.isprintable() and len(name) < 16:
                name = (name if typed else "") + ev.unicode
                typed = True


def dialog(screen, clock, folders, item):
    """The long press: what to do with the item (its name, or None in an empty folder) and the folder."""
    cur = folders.current
    acts, labels = [], []
    if item is not None and cur == folders.fav():
        acts.append("unfav")
        labels.append("Прибрати з «%s»" % folders.name(cur))
    if item is not None:
        acts.append("move")
        labels.append("Перемістити в теку…")
    if folders.count() < MAX_FOLDERS:
        acts.append("create")
        labels.append("Створити теку")
    if cur < len(folders.folders):
        acts += ["rename", "remove"]
        labels += ["Перейменувати «%s»" % folders.name(cur), "Вилучити «%s»" % folders.name(cur)]
    acts.append("cancel")
    labels.append("Скасувати")
    i = choose(screen, clock, item or folders.name(cur), labels)
    act = acts[i] if i is not None else "cancel"
    if act == "unfav":
        folders.unfav(item)
    elif act == "move":
        dests = [k for k in range(folders.count()) if k != cur]
        j = choose(screen, clock, "%s →" % item, [folders.name(k) for k in dests], [folders.icon(k) for k in dests])
        if j is not None:
            folders.move(item, dests[j])
    elif act == "create":
        used = {f["icon"] for f in folders.folders}
        r = edit(screen, clock, "Нова тека", icon=next((c for c in CHOICE if c not in used), "folder"))
        if r:
            folders.create(*r)
            if item is not None:              # what was chosen goes in it, if wanted
                if choose(screen, clock, "Перемістити %s сюди?" % item, ["Так", "Ні"]) == 0:
                    folders.move(item, folders.current)
            folders.save()
    elif act == "rename":
        f = folders.folders[cur]
        r = edit(screen, clock, "Тека", f["name"], f["icon"])
        if r:
            f["name"], f["icon"] = r
            folders.save()
    elif act == "remove":
        n = len(folders.items(cur))
        what = "Вилучити «%s»?" % folders.name(cur)
        opts = ["Так" + (" (%d → %s)" % (n, OTHER) if n else ""), "Ні"]
        if choose(screen, clock, what, opts) == 0:
            folders.remove(cur)
