"""Copy files to a MicroPython board over its raw REPL (USB), then soft-reset it.

    python3 mpy_put.py /dev/ttyACM0 tools/siggen/rp2350.py:main.py [file[:name] ...]
"""
import sys
import time

import serial


_pending = [b""]  # bytes read past the last marker


def read_until(port, marker, timeout=5):
    """Bytes up to and including marker; what came after it is kept for the next call."""
    data, end = _pending[0], time.time() + timeout
    while marker not in data:
        if time.time() > end:
            raise TimeoutError("no %r, got %r" % (marker, data[-200:]))
        data += port.read(port.in_waiting or 1)
    i = data.index(marker) + len(marker)
    _pending[0] = data[i:]
    return data[:i]


def exec_raw(port, code):
    port.write(code.encode() + b"\x04")
    if read_until(port, b"OK")[-2:] != b"OK":
        raise RuntimeError("not accepted")
    out = read_until(port, b"\x04")[:-1]
    err = read_until(port, b"\x04")[:-1]
    read_until(port, b">")
    if err:
        raise RuntimeError(err.decode(errors="replace"))
    return out


port = serial.Serial(sys.argv[1], 115200, timeout=0.1, write_timeout=3)
port.write(b"\r\x03\x03")          # stop a running program
time.sleep(0.3)
port.reset_input_buffer()
_pending[0] = b""
port.write(b"\r\x01")              # raw REPL
read_until(port, b"raw REPL; CTRL-B to exit\r\n>")
print(exec_raw(port, "import sys; print(sys.implementation._machine, sys.version)").decode().strip())
for arg in sys.argv[2:]:
    path, _, name = arg.partition(":")
    name = name or path.rsplit("/", 1)[-1]
    data = open(path, "rb").read()
    exec_raw(port, "f = open(%r, 'wb')" % name)
    for i in range(0, len(data), 256):
        exec_raw(port, "f.write(%r)" % data[i:i + 256])
    exec_raw(port, "f.close()")
    size = int(exec_raw(port, "import os; print(os.stat(%r)[6])" % name))
    if size != len(data):
        sys.exit("%s: %d of %d bytes on the board" % (name, size, len(data)))
    print("wrote %s (%d bytes)" % (name, len(data)))
port.write(b"\x02")                # friendly REPL
time.sleep(0.2)
port.write(b"\x04")                # soft reset: runs main.py
time.sleep(1.5)
print(port.read(port.in_waiting).decode(errors="replace"))
