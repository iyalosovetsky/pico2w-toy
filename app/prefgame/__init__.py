"""Python Pref (PyPref) 2.34 preferans engine - https://sourceforge.net/projects/python-pref/

Based on kpref by Azarniy I.V. and OpenPref. Author (2.0): Alexander aka amigo;
versions 2.1-2.34: Vadim Zapletin. License: GNU GPL v3 (see LICENSE.txt).

Modified for pico2w-toy (2026-10): ported from Python 2 to Python 3 - tabs
expanded, cp1251 comments converted to UTF-8, cmp-style sorts replaced with key
functions, integer division (//) restored in the scoring code, TCard.__hash__
added, a None comparison guarded in desktop.py, package renamed game -> prefgame.
The game logic and AI are unchanged; the Tkinter GUI is replaced by ../preferans.py.
"""
__all__ = [
        'cardlist',
        'card',
        'coloda',
        'ctlist',
        'desktop',
        'gamer',
        'ncounter',
        'plscore',
        'prfconst',
]
