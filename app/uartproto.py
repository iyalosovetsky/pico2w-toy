"""Frames for the UART tester: checksums, the framing of a few device protocols, input parsing
and the check / decoding of replies.

PRESETS[i] = Preset(name, title, baud, fmt, line, build, check, hint, examples)
  build(payload) -> (frame bytes, number of checksum bytes at the end)
  check(rx bytes) -> list of (ok: True / False / None, text) lines about the reply

Input: hex bytes ("05 00 06", "0x05,0x00", "050006") and text in quotes ("AT\\r\\n" 0D 0A).
"""
import re
from collections import namedtuple


# ---------------------------------------------------------------- checksums

def sum8(data):
    return sum(data) & 0xFF


def xor8(data):
    x = 0
    for b in data:
        x ^= b
    return x


def crc8(data, poly=0x07, init=0x00):
    """CRC-8, MSB first, no reflection (CRC-8/SMBUS with 0x07, DVB-S2 with 0xD5)."""
    crc = init
    for b in data:
        crc ^= b
        for _ in range(8):
            crc = ((crc << 1) ^ poly) & 0xFF if crc & 0x80 else (crc << 1) & 0xFF
    return crc


def crc8_maxim(data):
    """CRC-8/MAXIM (Dallas 1-Wire): poly 0x31 reflected (0x8C), init 0."""
    crc = 0
    for b in data:
        crc ^= b
        for _ in range(8):
            crc = (crc >> 1) ^ 0x8C if crc & 1 else crc >> 1
    return crc


def crc8_tmc(data):
    """The TMC2209 / TMC2208 UART CRC: poly 0x07, each byte taken LSB first (datasheet code)."""
    crc = 0
    for b in data:
        for _ in range(8):
            if (crc >> 7) ^ (b & 1):
                crc = ((crc << 1) ^ 0x07) & 0xFF
            else:
                crc = (crc << 1) & 0xFF
            b >>= 1
    return crc


def crc16_modbus(data):
    crc = 0xFFFF
    for b in data:
        crc ^= b
        for _ in range(8):
            crc = (crc >> 1) ^ 0xA001 if crc & 1 else crc >> 1
    return crc


def crc16_msb(data, poly, init=0):
    """CRC-16 MSB first, no reflection: XMODEM (0x1021), Dynamixel / BUYPASS (0x8005)."""
    crc = init
    for b in data:
        crc ^= b << 8
        for _ in range(8):
            crc = ((crc << 1) ^ poly) & 0xFFFF if crc & 0x8000 else (crc << 1) & 0xFFFF
    return crc


# ---------------------------------------------------------------- input

class InputError(ValueError):
    pass


def parse_input(s):
    """'05 00 06', '0x05,0x00', '"AT\\r\\n" 0D' -> bytes."""
    out = bytearray()
    i = 0
    while i < len(s):
        c = s[i]
        if c in " ,;\t":
            i += 1
        elif c in "\"'":
            q, i = c, i + 1
            while i < len(s) and s[i] != q:
                if s[i] == "\\" and i + 1 < len(s):
                    e = s[i + 1]
                    if e == "x" and i + 3 < len(s) + 1:
                        try:
                            out.append(int(s[i + 2:i + 4], 16))
                        except ValueError:
                            raise InputError("\\x потребує двох hex-цифр")
                        i += 4
                        continue
                    out += {"r": b"\r", "n": b"\n", "t": b"\t", "0": b"\0"}.get(e, e.encode())
                    i += 2
                else:
                    out += s[i].encode()
                    i += 1
            if i >= len(s):
                raise InputError("не закрито лапки")
            i += 1
        else:
            m = re.match(r"(?:0[xX])?([0-9a-fA-F]+)", s[i:])
            if not m:
                raise InputError("не hex: «%s»" % s[i:i + 6])
            digits = m.group(1)
            if len(digits) % 2:
                if len(digits) == 1:
                    digits = "0" + digits
                else:
                    raise InputError("непарна кількість hex-цифр: %s" % digits)
            out += bytes.fromhex(digits)
            i += m.end()
    return bytes(out)


def hexs(data):
    return " ".join("%02X" % b for b in data)


def ascii_of(data):
    return "".join(chr(b) if 32 <= b < 127 else "." for b in data)


# ---------------------------------------------------------------- generic checks

def _tail_check(rx, n, fn, big_endian=False, label="сума"):
    if len(rx) <= n:
        return [(None, "%d байт - замало для перевірки суми" % len(rx))]
    body, tail = rx[:-n], rx[-n:]
    want = fn(body)
    got = tail[0] if n == 1 else (tail[0] << 8 | tail[1] if big_endian else tail[1] << 8 | tail[0])
    if got == want:
        return [(True, "%s %0*X вірна" % (label, 2 * n, got))]
    return [(False, "%s %0*X, має бути %0*X" % (label, 2 * n, got, 2 * n, want))]


def generic(name, n, fn, big_endian=False):
    def build(p):
        if n == 0:
            return p, 0
        v = fn(p)
        tail = bytes([v]) if n == 1 else (bytes([v >> 8, v & 0xFF]) if big_endian else bytes([v & 0xFF, v >> 8]))
        return p + tail, n

    def check(rx):
        if n == 0:
            return [(None, "«%s»" % ascii_of(rx))] if any(32 <= b < 127 for b in rx) else []
        return _tail_check(rx, n, fn, big_endian, name)
    return build, check


# ---------------------------------------------------------------- device protocols

def tmc_build(p):
    """TMC2209: payload = addr reg [d3 d2 d1 d0]; a write sets bit 7 of reg itself."""
    if len(p) not in (2, 6):
        raise InputError("TMC2209: адр рег (читання) або адр рег + 4 байти (запис)")
    if len(p) == 6:
        p = bytes([p[0], p[1] | 0x80]) + p[2:]
    f = b"\x05" + p
    return f + bytes([crc8_tmc(f)]), 1


TMC_REGS = {0x00: "GCONF", 0x01: "GSTAT", 0x02: "IFCNT", 0x06: "IOIN", 0x10: "IHOLD_IRUN",
            0x12: "TPOWERDOWN", 0x41: "SG_RESULT", 0x6A: "MSCNT", 0x6C: "CHOPCONF", 0x6F: "DRV_STATUS",
            0x70: "PWMCONF", 0x40: "SGTHRS", 0x14: "TCOOLTHRS", 0x22: "VACTUAL"}


def tmc_check(rx):
    out = []
    i = 0
    while i + 8 <= len(rx):
        f = rx[i:i + 8]
        if f[0] != 0x05 or f[1] != 0xFF:
            i += 1
            continue
        ok = crc8_tmc(f[:7]) == f[7]
        val = int.from_bytes(f[3:7], "big")
        out.append((ok, "%s 0x%02X = 0x%08X%s" % (TMC_REGS.get(f[2], "рег"), f[2], val,
                                                 "" if ok else ", CRC %02X ≠ %02X" % (f[7], crc8_tmc(f[:7])))))
        i += 8
    if not out and rx:
        out.append((None, "не кадр TMC (05 FF рег 4 байти CRC)"))
    return out


def feetech_build(p):
    """Feetech SCS / STS (ST3215, SC09, ...): payload = id instr [params]."""
    if len(p) < 2:
        raise InputError("Feetech: ID інструкція [параметри]")
    body = bytes([p[0], len(p)]) + p[1:]       # LEN = params + 2 = len(instr + params) + 1
    return b"\xFF\xFF" + body + bytes([~sum(body) & 0xFF]), 1


FEETECH_ERR = ["напруга", "кут", "перегрів", "діапазон", "", "перевантаж.", "", ""]


def feetech_check(rx):
    out = []
    i = rx.find(b"\xFF\xFF")
    while 0 <= i and i + 6 <= len(rx):
        n = rx[i + 3]
        f = rx[i:i + 4 + n]
        if len(f) < 4 + n:
            out.append((False, "кадр обірвано: %d з %d байт" % (len(f), 4 + n)))
            break
        ok = (~sum(f[2:-1]) & 0xFF) == f[-1]
        err = f[4]
        errs = ", ".join(e for b, e in enumerate(FEETECH_ERR) if err >> b & 1 and e) or ("0x%02X" % err if err else "")
        text = "ID %d%s%s" % (f[2], ": " + hexs(f[5:-1]) if n > 2 else "", ", помилка " + errs if err else "")
        if n == 4:   # two bytes: a 16-bit value, low byte first
            text += " (%d)" % (f[5] | f[6] << 8)
        out.append((ok, text + ("" if ok else ", сума %02X ≠ %02X" % (f[-1], ~sum(f[2:-1]) & 0xFF))))
        i = rx.find(b"\xFF\xFF", i + 4 + n)
    if not out and rx:
        out.append((None, "не кадр Feetech (FF FF ID LEN ...)"))
    return out


def modbus_build(p):
    if len(p) < 2:
        raise InputError("Modbus: адреса функція [дані]")
    c = crc16_modbus(p)
    return p + bytes([c & 0xFF, c >> 8]), 2


MODBUS_EXC = {1: "функція", 2: "адреса", 3: "значення", 4: "збій пристрою", 6: "зайнятий"}


def modbus_check(rx):
    if len(rx) < 4:
        return [(None, "%d байт - замало для Modbus" % len(rx))] if rx else []
    c = crc16_modbus(rx[:-2])
    ok = rx[-2] == c & 0xFF and rx[-1] == c >> 8
    addr, fn, data = rx[0], rx[1], rx[2:-2]
    if fn & 0x80:
        text = "адр %d: виняток функції %02X - %s" % (addr, fn & 0x7F, MODBUS_EXC.get(data[0] if data else 0, "?"))
    elif fn in (3, 4) and data and data[0] == len(data) - 1:
        regs = [data[1 + 2 * k] << 8 | data[2 + 2 * k] for k in range(data[0] // 2)]
        text = "адр %d ф%02X: %s" % (addr, fn, " ".join(str(r) for r in regs[:6]))
    else:
        text = "адр %d ф%02X: %s" % (addr, fn, hexs(data))
    return [(ok, text + ("" if ok else ", CRC %02X%02X ≠ %02X%02X" % (rx[-2], rx[-1], c & 0xFF, c >> 8)))]


def crsf_build(p):
    """CRSF: payload = type [data] -> C8 LEN type data CRC8(0xD5 over type + data)."""
    if not p:
        raise InputError("CRSF: тип [дані]")
    return bytes([0xC8, len(p) + 1]) + p + bytes([crc8(p, 0xD5)]), 1


CRSF_TYPES = {0x02: "GPS", 0x08: "батарея", 0x14: "зв'язок", 0x16: "канали RC", 0x1E: "положення",
              0x21: "режим", 0x28: "ping", 0x29: "про пристрій", 0x2B: "параметр", 0x3A: "радіо ID"}


def crsf_check(rx):
    out, i = [], 0
    while i + 4 <= len(rx):
        n = rx[i + 1]
        if not 2 <= n <= 62 or i + 2 + n > len(rx):
            i += 1
            continue
        f = rx[i:i + 2 + n]
        ok = crc8(f[2:-1], 0xD5) == f[-1]
        t = f[2]
        text = "%02X→ %s (0x%02X)" % (f[0], CRSF_TYPES.get(t, "тип"), t)
        if t == 0x29 and len(f) > 6:   # device info: the name after dest / origin
            name = bytes(f[5:-1]).split(b"\0")[0]
            text += " «%s»" % name.decode("ascii", "replace")
        out.append((ok, text if ok else text + ", CRC %02X ≠ %02X" % (f[-1], crc8(f[2:-1], 0xD5))))
        i += 2 + n
    if not out and rx:
        out.append((None, "не кадр CRSF (адр LEN тип ... CRC)"))
    return out


def ddsm_build(p):
    """Waveshare DDSM210 / DDSM115: 9 bytes (shorter - zeros added) + CRC-8/MAXIM."""
    if len(p) > 9:
        raise InputError("DDSM: до 9 байт (ID команда дані), 10-й - CRC")
    p = p + bytes(9 - len(p))
    return p + bytes([crc8_maxim(p)]), 1


def ddsm_check(rx):
    out = []
    for i in range(0, len(rx) - 9, 10):
        f = rx[i:i + 10]
        ok = crc8_maxim(f[:9]) == f[9]
        # feedback (Waveshare wiki): ID, mode, current, speed, position, error, CRC
        cur = int.from_bytes(f[2:4], "big", signed=True)
        speed = int.from_bytes(f[4:6], "big", signed=True)
        text = "ID %d реж %d I %d v %d поз %d%s" % (f[0], f[1], cur, speed, int.from_bytes(f[6:8], "big"),
                                                ", помилка %02X" % f[8] if f[8] else "")
        out.append((ok, text if ok else text + ", CRC %02X ≠ %02X" % (f[9], crc8_maxim(f[:9]))))
    if not out and rx:
        out.append((None, "%d байт, кадр DDSM - 10" % len(rx)))
    return out


def dxl2_build(p):
    """Dynamixel 2.0: payload = id instr [params]."""
    if len(p) < 2:
        raise InputError("Dynamixel: ID інструкція [параметри]")
    n = len(p) - 1 + 2       # instr + params + CRC
    f = bytes([0xFF, 0xFF, 0xFD, 0x00, p[0], n & 0xFF, n >> 8]) + p[1:]
    c = crc16_msb(f, 0x8005)
    return f + bytes([c & 0xFF, c >> 8]), 2


def dxl2_check(rx):
    i = rx.find(b"\xFF\xFF\xFD\x00")
    if i < 0 or i + 11 > len(rx):
        return [(None, "не кадр Dynamixel 2.0")] if rx else []
    n = rx[i + 5] | rx[i + 6] << 8
    f = rx[i:i + 7 + n]
    if len(f) < 7 + n:
        return [(False, "кадр обірвано")]
    c = crc16_msb(f[:-2], 0x8005)
    ok = f[-2] == c & 0xFF and f[-1] == c >> 8
    err = f[8]
    text = "ID %d%s: %s" % (f[4], " помилка %02X" % err if err else "", hexs(f[9:-2]) or "ok")
    return [(ok, text if ok else text + ", CRC ≠ %04X" % c)]


def nmea_build(p):
    body = p[1:] if p[:1] == b"$" else p
    body = body.split(b"*")[0].rstrip(b"\r\n")
    return b"$" + body + b"*" + ("%02X" % xor8(body)).encode() + b"\r\n", 5


def nmea_check(rx):
    out = []
    for line in bytes(rx).split(b"\n"):
        line = line.strip(b"\r")
        m = re.match(rb"\$(.*)\*([0-9A-Fa-f]{2})$", line)
        if not m:
            continue
        ok = int(m.group(2), 16) == xor8(m.group(1))
        out.append((ok, m.group(1)[:40].decode("ascii", "replace")))
    if not out and rx:
        out.append((None, "«%s»" % ascii_of(rx)[:40]))
    return out[-3:]


Preset = namedtuple("Preset", "name title baud fmt line build check hint examples")

PRESETS = [
    Preset("tmc2209", "TMC2209", 115200, "8N1", "half", tmc_build, tmc_check,
           "адр рег [4 байти - запис]",
           ["00 06", "00 00", "00 02", "00 6F", "00 00 00 00 01 C0", "00 10 00 01 1F 0A"]),
    Preset("feetech", "Feetech SCS/STS", 1000000, "8N1", "half", feetech_build, feetech_check,
           "ID інстр [параметри]",
           ["01 01", "01 02 38 02", "01 02 05 01", "FE 01", "01 03 2A 00 08", "01 03 28 01"]),
    Preset("modbus", "Modbus RTU", 9600, "8N1", "full", modbus_build, modbus_check,
           "адр функція [дані]",
           ["01 03 00 00 00 01", "01 06 00 00 00 01", "01 03 01 01", "01 03 01 08", "01 05 02 13 88",
            "01 03 01 00"]),
    Preset("crsf", "CRSF", 420000, "8N1", "full", crsf_build, crsf_check,
           "тип [дані]",
           ["28 00 EA", "2D EE EA 00 00", "16 " + " ".join(["00"] * 22)]),
    Preset("ddsm", "DDSM210/115", 115200, "8N1", "full", ddsm_build, ddsm_check,
           "ID команда [дані] (9 байт)",
           ["01 64 00 64", "01 64 00 00", "01 64 FF 9C", "01 74", "01 A0 02", "AA 55 53 01"]),
    Preset("dxl2", "Dynamixel 2.0", 57600, "8N1", "half", dxl2_build, dxl2_check,
           "ID інстр [параметри]",
           ["01 01", "FE 01", "01 02 84 00 04 00", "01 03 40 00 01"]),
    Preset("nmea", "NMEA", 9600, "8N1", "full", nmea_build, nmea_check,
           "текст між $ і *",
           ['"PMTK605"', '"PMTK220,1000"', '"PMTK251,115200"', '"PUBX,00"']),
    Preset("none", "без суми", 115200, "8N1", "full", *generic("", 0, None),
           "hex або \"текст\"", ['"AT\\r\\n"', '"Hi PicoCalc!"', "55 AA 01 02", '"help\\n"']),
    Preset("sum8", "SUM8", 115200, "8N1", "full", *generic("SUM8", 1, sum8),
           "дані - сума в кінці", ["01 02 03", "AA 55 01"]),
    Preset("xor8", "XOR8", 115200, "8N1", "full", *generic("XOR8", 1, xor8),
           "дані - XOR в кінці", ["01 02 03", "AA 55 01"]),
    Preset("crc8", "CRC-8", 115200, "8N1", "full", *generic("CRC-8", 1, crc8),
           "дані - CRC-8 (0x07)", ["01 02 03", '"123456789"']),
    Preset("crc8maxim", "CRC-8/MAXIM", 115200, "8N1", "full", *generic("CRC-8/MAXIM", 1, crc8_maxim),
           "дані - CRC-8/MAXIM", ["01 02 03", '"123456789"']),
    Preset("crc16", "CRC-16/MODBUS", 115200, "8N1", "full", *generic("CRC-16", 2, crc16_modbus),
           "дані - CRC16 (мол. байт перший)", ["01 02 03", '"123456789"']),
    Preset("xmodem", "CRC-16/XMODEM", 115200, "8N1", "full",
           *generic("CRC-16", 2, lambda d: crc16_msb(d, 0x1021), big_endian=True),
           "дані - CRC16 (ст. байт перший)", ["01 02 03", '"123456789"']),
]

BAUDS = [1200, 2400, 4800, 9600, 19200, 38400, 57600, 115200, 230400, 250000, 420000, 460800, 500000,
         921600, 1000000]
FORMATS = ["8N1", "8E1", "8O1", "8N2", "8E2"]
LINES = ["full", "half", "inv"]


def build(preset, text):
    """(frame, checksum length) for the typed text, or InputError."""
    payload = parse_input(text)
    if not payload and preset.name != "nmea":
        raise InputError("порожній кадр")
    return preset.build(payload)


def strip_echo(sent, rx):
    """1-wire: the board hears its own frame first."""
    return rx[len(sent):] if rx[:len(sent)] == sent else rx
