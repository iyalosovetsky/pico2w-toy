#!/bin/sh
# Console tools started from the menu on the PicoCalc (lcd-term@<tool>.service on tty7):
#   python  bpython REPL in ~/code          (exit: Ctrl+D)
#   basic   MMBasic for Linux in ~/basic    (exit: QUIT; EDIT opens nano with MMBasic highlighting)
#   edit    micro editor on ~/code          (exit: Ctrl+Q; Ctrl+O opens another file)
#   minicom minicom on the SERIAL item's port and speed (~/.config/lcdtoy/serial.json; exit: Ctrl+A X)
printf '\033[2J\033[H'
case "$1" in
    python)
        mkdir -p "$HOME/code" && cd "$HOME/code"
        echo "bpython - Ctrl+D: back to the menu"
        exec bpython ;;
    basic)
        mkdir -p "$HOME/basic"
        exec mmbasic -d "$HOME/basic" ;;
    edit)
        mkdir -p "$HOME/code" && cd "$HOME/code"
        exec micro "${2:-scratch.py}" ;;
    minicom)
        cfg="$HOME/.config/lcdtoy/serial.json"
        port=$(python3 -c "import json; print(json.load(open('$cfg')).get('port') or '')" 2>/dev/null)
        baud=$(python3 -c "import json; print(json.load(open('$cfg')).get('baud') or 115200)" 2>/dev/null)
        [ -n "$port" ] || port=$(ls /dev/ttyACM* /dev/ttyUSB* 2>/dev/null | head -1)
        echo "minicom $port ${baud:-115200} - Ctrl+A X: back to the menu"
        exec minicom -D "$port" -b "${baud:-115200}" ;;
    *)
        echo "usage: $0 python|basic|edit|minicom" >&2; exit 2 ;;
esac
