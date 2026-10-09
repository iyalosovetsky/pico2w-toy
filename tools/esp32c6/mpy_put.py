"""Copy files to a MicroPython board over its raw REPL, then soft-reset it.

    python3 mpy_put.py /dev/ttyACM0 main.py [more.py ...]
"""
import sys
import time

import serial


def read_until(port, marker, timeout=5):
    data, end = b"", time.time() + timeout
    while time.time() < end:
        data += port.read(port.in_waiting or 1)
        if data.endswith(marker):
            return data
    raise TimeoutError("no %r, got %r" % (marker, data[-200:]))


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


port = serial.Serial(sys.argv[1], 115200, timeout=0.1)
port.write(b"\r\x03\x03")          # stop a running program
time.sleep(0.3)
port.reset_input_buffer()
port.write(b"\r\x01")              # raw REPL
read_until(port, b"raw REPL; CTRL-B to exit\r\n>")
print(exec_raw(port, "import sys; print(sys.implementation._machine, sys.version)").decode().strip())
for path in sys.argv[2:]:
    name = path.rsplit("/", 1)[-1]
    data = open(path, "rb").read()
    exec_raw(port, "f = open(%r, 'wb')" % name)
    for i in range(0, len(data), 256):
        exec_raw(port, "f.write(%r)" % data[i:i + 256])
    exec_raw(port, "f.close()")
    print("wrote %s (%d bytes)" % (name, len(data)))
port.write(b"\x02")                # friendly REPL
time.sleep(0.2)
port.write(b"\x04")                # soft reset: runs main.py
time.sleep(1.5)
print(port.read(port.in_waiting).decode(errors="replace"))
