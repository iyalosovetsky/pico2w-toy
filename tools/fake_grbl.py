"""A pretend grblHAL on TCP for recording the GIFs: answers, a position that follows the G-code, a delay."""
import re, socket, threading, time
class Fake:
    def __init__(self, port, delay=0.02):
        self.srv = socket.socket(); self.srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.srv.bind(("127.0.0.1", port)); self.srv.listen(1)
        self.pos = [0.0, 0.0, 5.0]; self.delay = delay; self.ov = [100, 100, 100]; self.n = 0; self.spin = False
        threading.Thread(target=self.run, daemon=True).start()
    def run(self):
        c, _ = self.srv.accept(); self.c = c; self.lock = threading.Lock()
        self.send("GrblHAL 1.1f ['$' or '$HELP' for help]")
        buf = b""
        while True:
            d = c.recv(1000)
            if not d: break
            for b in d:
                if b == ord("?"):
                    self.n += 1
                    st = "Run" if time.time() - getattr(self, "last", 0) < 0.3 else "Idle"
                    extra = "|WCO:0.000,0.000,0.000" if self.n % 10 == 1 else ""
                    if self.n % 5 == 1: extra += "|Ov:%d,%d,%d" % tuple(self.ov)
                    acc = "|A:S" if self.spin else ""
                    self.send("<%s|MPos:%.3f,%.3f,%.3f|FS:600,%d%s%s>" % (st, *self.pos, 12000 if self.spin else 0, acc, extra))
                elif b in (0x91, 0x92, 0x90):
                    self.ov[0] = {0x91: self.ov[0] + 10, 0x92: self.ov[0] - 10, 0x90: 100}[b]
                elif b == 10:
                    line = buf.decode(errors="replace"); buf = b""; self.answer(line)
                elif b != 13 and b < 0x80:
                    buf += bytes([b])
    def send(self, s):
        with self.lock:
            self.c.sendall((s + "\r\n").encode())
    def answer(self, line):
        out = []
        if line == "$$":
            out = ["$22=1", "$23=0", "$110=3000.000", "$111=3000.000", "$112=1000.000", "$130=375.000", "$131=600.000", "$132=130.000"]
        u = line.upper()
        if re.match(r"^(G[0123]\b|G1|G0|X|Y|Z)", u) or re.search(r"\b[XYZ]-?[\d.]", u):
            for i, a in enumerate("XYZ"):
                m = re.search(a + r"(-?[\d.]+)", u)
                if m: self.pos[i] = float(m.group(1))
            self.last = time.time()
            time.sleep(self.delay)
        if "M3" in u: self.spin = True
        if "M5" in u: self.spin = False
        for o in out: self.send(o)
        self.send("ok")
