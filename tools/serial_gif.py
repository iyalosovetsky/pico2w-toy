"""python3 tools/serial_gif.py [app dir] [out dir] - record SERIAL's shape editor and toolpath view into GIFs: the real app, scripted keys, a pretend machine.
Runs in its own HOME (no real port, no real machine); frames are taken where lcd.flip() would write them."""
import json, os, shutil, sys, time
APP = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app")
OUT = sys.argv[2] if len(sys.argv) > 2 else "/tmp"
HOME = "/tmp/gifhome"
shutil.rmtree(HOME, ignore_errors=True)
os.makedirs(HOME + "/.config/lcdtoy"); os.makedirs(HOME + "/gcode")
json.dump({"profiles": [{"name": "3D-сканер", "kind": "scanner", "link": "serial", "port": "/dev/null-none"},
                        {"name": "Верстат", "kind": "cnc", "link": "tcp", "host": "127.0.0.1", "tcp_port": 18740,
                         "axes": "XYZ", "spindle": True,
                         "shape_params": {"width": 100.0, "height": 60.0, "tool": 1.0, "depth": 0.5, "step": 0.5,
                                          "stepover": 45.0, "safe_z": 5.0, "feed": 800.0, "plunge": 200.0,
                                          "spindle": 12000.0}}],
           "profile": 1, "show_full": False}, open(HOME + "/.config/lcdtoy/serial.json", "w"))
os.environ["HOME"] = HOME
os.environ["LCD_SOUND"] = "0"
sys.path.insert(0, APP); sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fake_grbl
F = fake_grbl.Fake(18740, delay=0.003)
import pygame
import lcd
frames = []
def grab():
    frames.append((time.monotonic(), pygame.image.tobytes(lcd._screen, "RGB"), pygame.Surface.get_size(lcd._screen)))
lcd.flip = grab
import serialterm as st
K = pygame
def kd(k, ch=""): return pygame.event.Event(pygame.KEYDOWN, key=k, unicode=ch, mod=0)
def ku(k): return pygame.event.Event(pygame.KEYUP, key=k, unicode="", mod=0)
S = []
def wait(t): S.append((t, []))
def key(k, ch="", t=0.25): S.append((t, [kd(k, ch)])); S.append((0.03, [ku(k)]))
def taps(k, n, dt=0.06):
    for _ in range(n): S.append((dt, [kd(k)])); S.append((0.02, [ku(k)]))
def typ(s, dt=0.13):
    for c in s: S.append((dt, [kd(0, c)]))
marks = {}
def mark(name): S.append((0, "mark:" + name))
# --- the editor
wait(1.0); mark("ed")
key(K.K_F1, t=0.4); key(K.K_DOWN, t=0.5); key(K.K_RETURN, t=0.4); wait(0.8)
key(0, "c"); taps(K.K_RIGHT, 12); taps(K.K_UP, 15); key(K.K_RETURN); taps(K.K_RIGHT, 6, 0.09); key(K.K_RETURN); key(K.K_ESCAPE, t=0.5)
key(0, "r"); taps(K.K_RIGHT, 13); taps(K.K_DOWN, 7); key(K.K_RETURN); taps(K.K_RIGHT, 20, 0.05); taps(K.K_UP, 15, 0.05)
key(K.K_RETURN); key(K.K_ESCAPE, t=0.4)
key(0, " ", t=0.5); taps(K.K_DOWN, 6, 0.15); typ("5"); key(K.K_DOWN, t=0.3)
taps(K.K_RIGHT, 3, 0.4); wait(0.6); key(0, "s", t=0.3); wait(1.2)
key(0, "t"); taps(K.K_LEFT, 41, 0.035); taps(K.K_UP, 2); key(K.K_RETURN); taps(K.K_RIGHT, 42, 0.035); taps(K.K_UP, 4)
key(K.K_RETURN, t=0.4); wait(0.4); typ("PicoCalc "); key(K.K_TAB, "\t", t=0.4); typ("Ghbdsn"); wait(0.6); key(K.K_RETURN)
wait(0.6); key(0, "s"); wait(0.8); key(0, "0", t=0.3); wait(2.5)
key(K.K_ESCAPE); key(K.K_ESCAPE, t=0.4); wait(1.5); mark("ed_end")
# --- the toolpath view, a run
mark("tp")
key(K.K_F4, t=0.4); taps(K.K_DOWN, 6, 0.15); key(K.K_RETURN, t=0.3); wait(1.2)
taps(K.K_LEFT, 10, 0.08); taps(K.K_DOWN, 4, 0.08); wait(0.8); key(K.K_TAB, "\t", t=0.4); taps(K.K_DOWN, 6, 0.25); wait(1.0)
key(0, "r", t=0.5); wait(1.2); key(K.K_DOWN, t=0.4); key(K.K_RETURN, t=0.4); wait(9.0)
key(0, " ", t=0.2); wait(1.5); key(0, " ", t=0.2); wait(2.0); mark("tp_end")
orig = pygame.event.get
t0 = [time.monotonic()]; idx = [0]
def get(*a, **k):
    orig()
    while idx[0] < len(S) and isinstance(S[idx[0]][1], str):
        marks[S[idx[0]][1][5:]] = time.monotonic(); idx[0] += 1
    if idx[0] < len(S) and time.monotonic() - t0[0] > S[idx[0]][0]:
        evs = S[idx[0]][1]; idx[0] += 1; t0[0] = time.monotonic(); return evs
    if idx[0] >= len(S):
        return [pygame.event.Event(pygame.QUIT)]
    return []
pygame.event.get = get
st.main()
from PIL import Image
def save(name, a, b, path):
    sel = [(t, d, s) for t, d, s in frames if marks[a] <= t <= marks[b]]
    out, durs = [], []
    for (t, d, s), nxt in zip(sel, [x[0] for x in sel[1:]] + [marks[b]]):
        ms = max(20, int((nxt - t) * 1000))
        if out and d == out[-1][0]:
            durs[-1] += ms; continue
        out.append((d, s)); durs.append(ms)
    imgs = [Image.frombytes("RGB", s, d).quantize(colors=128, dither=Image.Dither.NONE) for d, s in out]
    imgs[0].save(path, save_all=True, append_images=imgs[1:], duration=durs, loop=0, optimize=True)
    print("%s: %d frames, %.0f KB, %.1f s" % (path, len(imgs), os.path.getsize(path) / 1024, sum(durs) / 1000))
    Image.frombytes("RGB", out[-1][1], out[-1][0]).save(path.replace(".gif", "-last.png"))
save("editor", "ed", "ed_end", OUT + "/serial-editor.gif")
save("toolpath", "tp", "tp_end", OUT + "/serial-toolpath.gif")
