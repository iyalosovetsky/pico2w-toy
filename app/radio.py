"""RADIO: internet radio for the PicoCalc's speaker.

Stations come from the community database radio-browser.info: the most popular Ukrainian ones,
by genre, or found by name; favourites are kept in ~/.config/lcdtoy/radio.json. This app reads
the stream itself (so it sees the ICY "now playing" titles) and feeds it to ffmpeg, which decodes
MP3 / AAC / OGG to the sound card; HLS (.m3u8) streams go to ffmpeg directly. A dropped stream
reconnects. Volume is the sound card's PCM control (put back on exit).

Keys: LEFT / RIGHT - list (favourites, Ukraine, genres, search), UP / DOWN / PgUp / PgDn - station,
Enter - play (in genres: open; in search: search), Space - stop / play again, f - favourite,
+ / - - volume, Esc - back / exit.
"""
import json
import os
import re
import subprocess
import sys
import threading
import time
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
os.environ["LCD_SOUND"] = "0"   # the sound card goes to ffmpeg; pygame must not hold it

import pygame  # noqa: E402
import lcd  # noqa: E402

UA = "pico2w-toy/1.0 (PicoCalc internet radio)"
MIRRORS = ["de1", "fi1", "at1", "nl1"]
CONFIG = os.path.expanduser("~/.config/lcdtoy/radio.json")
CACHE = os.path.expanduser("~/.cache/lcdtoy")
TABS = ["Обране", "Україна", "Жанри", "Пошук"]
T_FAV, T_UA, T_GENRES, T_SEARCH = range(4)
GENRES = [("Українське", "ukrainian"), ("Поп", "pop"), ("Рок", "rock"), ("Джаз", "jazz"),
          ("Класика", "classical"), ("Новини", "news"), ("Електроніка", "electronic"), ("Денс", "dance"),
          ("Чіл-аут", "chillout"), ("Ембієнт", "ambient"), ("Лаунж", "lounge"), ("Lo-fi", "lofi"),
          ("Метал", "metal"), ("Хіп-хоп", "hiphop"), ("Блюз", "blues"), ("Кантрі", "country"),
          ("Регі", "reggae"), ("Олдіс", "oldies"), ("80-ті", "80s"), ("90-ті", "90s"), ("Ретро", "retro"),
          ("Розмовне", "talk")]

BG, FG, DIM = (0, 0, 0), (235, 235, 235), (140, 140, 140)
ACCENT, GREEN, RED, BLUE = (255, 200, 0), (90, 220, 110), (240, 90, 80), (110, 170, 255)
FONT_DIR = "/usr/share/fonts/truetype/dejavu/"


# ---------------------------------------------------------------- the station database

def api(path, params):
    """GET a radio-browser.info endpoint (mirrors in turn); the answer cached for offline use."""
    query = urllib.parse.urlencode(params)
    key = re.sub(r"[^\w]+", "_", path + "_" + query)[:120]
    cache = os.path.join(CACHE, "radio-%s.json" % key)
    for m in MIRRORS:
        try:
            req = urllib.request.Request("https://%s.api.radio-browser.info%s?%s" % (m, path, query),
                                         headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=8) as r:
                data = json.load(r)
            os.makedirs(CACHE, exist_ok=True)
            with open(cache, "w", encoding="utf-8") as f:
                json.dump(data, f)
            return data, False
        except (OSError, ValueError):
            continue
    try:
        with open(cache, encoding="utf-8") as f:
            return json.load(f), True
    except (OSError, ValueError):
        raise OSError("немає зв'язку з radio-browser.info")


def station(s):
    return {"name": (s.get("name") or "?").strip(), "url": s.get("url_resolved") or s.get("url"),
            "codec": s.get("codec") or "", "bitrate": s.get("bitrate") or 0,
            "country": s.get("countrycode") or "", "uuid": s.get("stationuuid") or ""}


def search(**kw):
    params = {"order": "clickcount", "reverse": "true", "limit": 80, "hidebroken": "true"}
    params.update(kw)
    data, stale = api("/json/stations/search", params)
    seen, out = set(), []
    for s in data:
        st = station(s)
        if st["url"] and st["url"] not in seen:
            seen.add(st["url"])
            out.append(st)
    return out, stale


# ---------------------------------------------------------------- the player

class Player:
    """Reads a stream (ICY titles), pipes it into ffmpeg -> ALSA; reconnects when it drops."""

    def __init__(self):
        self.station = None
        self.title = ""
        self.status = ""
        self.error = False
        self.stop_flag = threading.Event()
        self.thread = None
        self.proc = None

    def play(self, st):
        self.stop()
        self.station, self.title, self.status, self.error = st, "", "з'єднання…", False
        self.stop_flag = threading.Event()
        self.thread = threading.Thread(target=self._run, args=(st, self.stop_flag), daemon=True)
        self.thread.start()

    def stop(self):
        self.stop_flag.set()
        self._kill()
        if self.thread:
            self.thread.join(3)
        self.thread = None

    def _kill(self):
        p, self.proc = self.proc, None
        if p:
            try:
                p.stdin and p.stdin.close()
            except OSError:
                pass
            p.terminate()
            try:
                p.wait(2)
            except subprocess.TimeoutExpired:
                p.kill()

    def _ffmpeg(self, src):
        quiet = ["-nostdin"] if src != "pipe:0" else []
        return subprocess.Popen(["ffmpeg", "-hide_banner", "-loglevel", "error"] + quiet +
                                ["-i", src, "-vn", "-ac", "1", "-f", "alsa", "default"],
                                stdin=subprocess.PIPE if src == "pipe:0" else subprocess.DEVNULL,
                                stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)

    def _run(self, st, stop):
        tries = 0
        while not stop.is_set():
            try:
                self._stream(st, stop)
                tries = 0
            except Exception as e:      # network, decoder - try again a few times
                if stop.is_set():
                    break
                tries += 1
                self.error = True
                self.status = "обрив (%s), знову…" % (str(e)[:40] or type(e).__name__)
            finally:
                self._kill()
            if stop.is_set():
                break
            if tries >= 6:
                self.status = "станція не відповідає"
                self.error = True
                break
            stop.wait(min(10, 1 + 2 * tries))

    def _stream(self, st, stop):
        url = st["url"]
        if re.search(r"\.m3u8(\?|$)", url):            # HLS: ffmpeg fetches it itself (no titles)
            self.proc = self._ffmpeg(url)
            self.status, self.error = "грає (HLS)", False
            while not stop.is_set() and self.proc.poll() is None:
                stop.wait(0.5)
            if not stop.is_set():
                raise OSError("потік закінчився")
            return
        req = urllib.request.Request(url, headers={"User-Agent": UA, "Icy-MetaData": "1"})
        resp = urllib.request.urlopen(req, timeout=10)
        try:
            ctype = (resp.headers.get("Content-Type") or "").lower()
            if "mpegurl" in ctype or "scpls" in ctype or "x-scpls" in ctype:   # a playlist: its first URL
                body = resp.read(65536).decode("utf-8", "replace")
                links = re.findall(r"(https?://[^\s\"']+)", body)
                if not links:
                    raise OSError("порожній плейлист")
                st = dict(st, url=links[0])
                resp.close()
                return self._stream(st, stop)
            metaint = int(resp.headers.get("icy-metaint") or 0)
            self.proc = self._ffmpeg("pipe:0")
            self.status, self.error = "грає", False
            while not stop.is_set():
                audio = resp.read(metaint if metaint else 8192)
                if not audio:
                    raise OSError("потік закінчився")
                try:
                    self.proc.stdin.write(audio)
                except (BrokenPipeError, ValueError, AttributeError):
                    err = self.proc.stderr.read(300).decode("utf-8", "replace").strip() if self.proc else ""
                    raise OSError("декодер: " + (err.splitlines()[-1] if err else "зупинився"))
                if metaint:
                    n = resp.read(1)
                    if n and n[0]:
                        meta = resp.read(n[0] * 16).rstrip(b"\0")
                        m = re.search(rb"StreamTitle='(.*?)';", meta, re.S)
                        if m:
                            raw = m.group(1)
                            try:
                                self.title = raw.decode("utf-8").strip()
                            except UnicodeDecodeError:
                                self.title = raw.decode("cp1251", "replace").strip()
        finally:
            resp.close()


# ---------------------------------------------------------------- volume (ALSA PCM)

def get_volume():
    try:
        out = subprocess.run(["amixer", "-c", "Headphones", "get", "PCM"], capture_output=True, text=True,
                             timeout=3).stdout
        m = re.search(r"\[(\d+)%\]", out)
        return int(m.group(1)) if m else None
    except (OSError, subprocess.TimeoutExpired):
        return None


def set_volume(v):
    try:
        subprocess.run(["amixer", "-q", "-c", "Headphones", "set", "PCM", "%d%%" % v], timeout=3)
    except (OSError, subprocess.TimeoutExpired):
        pass


# ---------------------------------------------------------------- screen

screen = lcd.init()
clock = pygame.time.Clock()


def font(name, px):
    size = px / lcd.S if lcd.S != 1 else int(px)
    try:
        return pygame.font.Font(FONT_DIR + name, size)
    except (FileNotFoundError, OSError):
        return pygame.font.Font(None, size)


BIG = lcd.S > 1
f_name = font("DejaVuSans-Bold.ttf", 16 if BIG else 8)
f_title = font("DejaVuSans.ttf", 14 if BIG else 7)
f_small = font("DejaVuSans.ttf", 12 if BIG else 7)
f_tab = font("DejaVuSans-Bold.ttf", 12 if BIG else 7)
f_list = font("DejaVuSans.ttf", 14 if BIG else 8)


def text(s, pos, color, f, right=False, center=False):
    img = f.render(s, True, color)
    x, y = pos
    if right:
        x -= img.get_width()
    elif center:
        x -= img.get_width() / 2
    screen.blit(img, (x, y))


def fit(s, f, width):
    if f.size(s)[0] <= width:
        return s
    while s and f.size(s + "…")[0] > width:
        s = s[:-1]
    return s + "…"


def marquee(s, f, x, y, width, color, t0):
    """A line that scrolls when it does not fit."""
    w = f.size(s)[0]
    if w <= width:
        text(s, (x, y), color, f)
        return
    gap = 20
    off = ((time.monotonic() - t0) * 12) % (w + gap)
    clip = screen.get_clip()
    screen.set_clip(pygame.Rect(lcd.sc(x), lcd.sc(y), lcd.sc(width), lcd.sc(f.get_linesize() + 1)))
    text(s, (x - off, y), color, f)
    text(s, (x - off + w + gap, y), color, f)
    screen.set_clip(clip)


def draw(ui, player, vol):
    screen.fill(BG)
    # now playing
    st = player.station
    pygame.draw.rect(screen, (25, 25, 35), (0, 0, 128, 31))
    if st:
        playing = player.thread is not None and not player.error and player.status.startswith("грає")
        text("♪" if playing else "·", (2, 1), GREEN if playing else DIM, f_name)
        marquee(st["name"], f_name, 11, 1, 115, FG, ui["t0"])
        marquee(player.title or "", f_title, 2, 11, 124, ACCENT, ui["t0"])
        info = "%s %s" % (st["codec"], ("%d кбіт/с" % st["bitrate"]) if st["bitrate"] else "")
        text(fit(player.status if player.status != "грає" else info.strip(), f_small, 90), (2, 21),
             RED if player.error else DIM, f_small)
    else:
        text("RADIO", (64, 3), ACCENT, f_name, center=True)
        text("виберіть станцію, Enter", (64, 16), DIM, f_small, center=True)
    text("%d%%" % vol if vol is not None else "", (126, 21), DIM, f_small, right=True)
    # tabs
    x = 1
    w = 126 / len(TABS)
    for i, name in enumerate(TABS):
        sel = i == ui["tab"]
        if sel:
            pygame.draw.rect(screen, ACCENT, (x + i * w, 32, w - 1, 9), border_radius=2)
        text(name, (x + i * w + w / 2, 32), BG if sel else DIM, f_tab, center=True)
    y = 43
    lh = f_list.get_linesize()
    # the search box
    if ui["tab"] == T_SEARCH and ui["view"] != "results":
        pygame.draw.rect(screen, (40, 40, 40), (2, y, 124, lh + 1))
        cur = "_" if int(time.monotonic() * 2) % 2 else " "
        text(fit("пошук: " + ui["query"] + cur, f_list, 120), (4, y), FG, f_list)
        y += lh + 3
    rows = ui["rows"]
    room = int((116 - y) // lh)
    if ui["loading"]:
        text("завантажую…", (64, y + 10), ACCENT, f_small, center=True)
    elif ui["msg"]:
        for k, line in enumerate(ui["msg"].split("\n")):
            text(line, (64, y + 6 + k * 9), DIM, f_small, center=True)
    else:
        sel = ui["sel"]
        ui["top"] = min(max(ui["top"], sel - room + 1), sel)
        favs = {f["url"] for f in ui["favs"]}
        for i in range(ui["top"], min(len(rows), ui["top"] + room)):
            r = rows[i]
            yy = y + (i - ui["top"]) * lh
            if i == sel:
                pygame.draw.rect(screen, (60, 50, 10), (1, yy, 126, lh))
            if isinstance(r, tuple):                 # a genre
                label, color = r[0], FG
            else:
                mark = "♪ " if st and r["url"] == st["url"] else ("★ " if r["url"] in favs else "")
                label, color = mark + r["name"], ACCENT if mark.startswith("♪") else FG
            text(fit(label, f_list, 122), (3, yy), color, f_list)
        if len(rows) > room:
            pos = ui["top"] / max(1, len(rows) - room)
            pygame.draw.rect(screen, (70, 70, 70), (126, y + pos * (room * lh - 6), 2, 6))
    hint = {T_GENRES: "Enter - відкрити  ←→ списки  Esc"}.get(ui["tab"], "Enter грати  Space стоп  f обране  +-")
    if ui["tab"] == T_SEARCH and ui["view"] != "results":
        hint = "назва + Enter - шукати  ←→ списки"
    text(hint, (64, 118), (150, 150, 150), f_small, center=True)
    lcd.flip()


# ---------------------------------------------------------------- state

def load_config():
    try:
        with open(CONFIG, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save_config(cfg):
    try:
        os.makedirs(os.path.dirname(CONFIG), exist_ok=True)
        with open(CONFIG, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=1)
    except OSError:
        pass


def main():
    if lcd.DEVICE != "picocalc":   # (not lcd.sound_available(): LCD_SOUND=0 above turns that off)
        screen.fill(BG)
        text("RADIO", (64, 4), ACCENT, f_name, center=True)
        text("тут немає динаміка", (64, 50), RED, f_small, center=True)
        lcd.flip()
        time.sleep(3)
        return
    cfg = load_config()
    vol0 = get_volume()
    vol = cfg.get("volume", vol0 if vol0 is not None else 70)
    set_volume(vol)
    ui = {"tab": T_FAV if cfg.get("favorites") else T_UA, "rows": [], "sel": 0, "top": 0, "loading": False,
          "msg": "", "query": "", "view": "", "favs": cfg.get("favorites", []), "t0": time.monotonic(),
          "genre": None}
    player = Player()
    loader = {"job": None}

    def load(fn, view=""):
        """Run a database query in the background; its rows replace the list."""
        job = object()
        loader["job"] = job
        ui.update(loading=True, msg="", rows=[], sel=0, top=0, view=view)

        def work():
            try:
                rows, stale = fn()
                msg = "" if rows else "нічого не знайдено"
                if stale and rows:
                    msg = ""
            except OSError as e:
                rows, msg = [], str(e) + "\n(перевірте Wi-Fi)"
            if loader["job"] is job:
                ui.update(rows=rows, msg=msg, loading=False)
        threading.Thread(target=work, daemon=True).start()

    def show_tab():
        ui["genre"] = None
        if ui["tab"] == T_FAV:
            ui.update(rows=list(ui["favs"]), sel=0, top=0, loading=False, view="",
                      msg="" if ui["favs"] else "тут порожньо\nf на станції - додати в обране")
        elif ui["tab"] == T_UA:
            load(lambda: search(countrycode="UA"))
        elif ui["tab"] == T_GENRES:
            ui.update(rows=list(GENRES), sel=0, top=0, loading=False, msg="", view="genres")
        else:
            ui.update(rows=[], sel=0, top=0, loading=False, view="", msg="наберіть частину назви\nлатиницею, Enter")

    show_tab()
    last = cfg.get("last")
    if last:
        player.play(last)
    try:
        while True:
            for ev in pygame.event.get():
                if ev.type == pygame.QUIT:
                    return
                if ev.type != pygame.KEYDOWN:
                    continue
                k = ev.key
                ch = getattr(ev, "unicode", "") if not getattr(ev, "hat", False) else ""
                typing = ui["tab"] == T_SEARCH and ui["view"] != "results"
                if k == pygame.K_ESCAPE or (getattr(ev, "hat", False) and k == pygame.K_3):
                    if ui["tab"] == T_GENRES and ui["genre"]:
                        show_tab()
                        continue
                    if ui["tab"] == T_SEARCH and ui["view"] == "results":
                        ui.update(view="", rows=[], msg="")
                        continue
                    return
                if typing and k == pygame.K_BACKSPACE:
                    ui["query"] = ui["query"][:-1]
                    continue
                if typing and ch and ch.isprintable() and k not in (pygame.K_RETURN, pygame.K_KP_ENTER):
                    ui["query"] = (ui["query"] + ch)[:40]
                    continue
                if k in (pygame.K_LEFT, pygame.K_RIGHT):
                    ui["tab"] = (ui["tab"] + (1 if k == pygame.K_RIGHT else -1)) % len(TABS)
                    show_tab()
                elif k == pygame.K_UP and ui["rows"]:
                    ui["sel"] = (ui["sel"] - 1) % len(ui["rows"])
                elif k == pygame.K_DOWN and ui["rows"]:
                    ui["sel"] = (ui["sel"] + 1) % len(ui["rows"])
                elif k == pygame.K_PAGEUP and ui["rows"]:
                    ui["sel"] = max(0, ui["sel"] - 8)
                elif k == pygame.K_PAGEDOWN and ui["rows"]:
                    ui["sel"] = min(len(ui["rows"]) - 1, ui["sel"] + 8)
                elif k in (pygame.K_RETURN, pygame.K_KP_ENTER):
                    if typing:
                        q = ui["query"].strip()
                        if q:
                            load(lambda q=q: search(name=q), view="results")
                    elif ui["rows"]:
                        r = ui["rows"][ui["sel"]]
                        if isinstance(r, tuple):                    # a genre: its stations
                            ui["genre"] = r
                            load(lambda tag=r[1]: search(tag=tag, tagExact="true"), view="stations")
                        else:
                            player.play(r)
                            ui["t0"] = time.monotonic()
                            cfg["last"] = r
                            save_config(cfg)
                elif k == pygame.K_SPACE:
                    if player.thread is not None:
                        player.stop()
                        player.status = "зупинено"
                    elif player.station:
                        player.play(player.station)
                elif ch in ("f", "F", "*") and ui["rows"] and not isinstance(ui["rows"][ui["sel"]], tuple):
                    r = ui["rows"][ui["sel"]]
                    favs = [f for f in ui["favs"] if f["url"] != r["url"]]
                    if len(favs) == len(ui["favs"]):
                        favs.append(r)
                    ui["favs"] = cfg["favorites"] = favs
                    save_config(cfg)
                    if ui["tab"] == T_FAV:
                        show_tab()
                elif ch == "+" or k in (pygame.K_EQUALS, pygame.K_KP_PLUS):
                    vol = min(100, vol + 5)
                    set_volume(vol)
                    cfg["volume"] = vol
                elif ch == "-" or k in (pygame.K_MINUS, pygame.K_KP_MINUS):
                    vol = max(0, vol - 5)
                    set_volume(vol)
                    cfg["volume"] = vol
            draw(ui, player, vol)
            clock.tick(15)
    finally:
        player.stop()
        save_config(cfg)
        if vol0 is not None:
            set_volume(vol0)


if __name__ == "__main__":
    try:
        main()
    finally:
        screen.fill(BG)
        lcd.flip()
        lcd.quit()
