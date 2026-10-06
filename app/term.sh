#!/bin/sh
# Console tools started from the menu on the PicoCalc (lcd-term@<tool>.service on tty7):
#   python  bpython REPL in ~/code          (exit: Ctrl+D)
#   basic   MMBasic for Linux in ~/basic    (exit: QUIT; EDIT opens nano with MMBasic highlighting)
#   edit    micro editor on ~/code          (exit: Ctrl+Q; Ctrl+O opens another file)
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
    *)
        echo "usage: $0 python|basic|edit" >&2; exit 2 ;;
esac
