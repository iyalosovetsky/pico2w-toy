#!/bin/sh
# Build Doom for the LCD: doomgeneric + our backend (doomgeneric_lcd.c).
# Output: app/doom/doomlcd (started from the menu with the shareware WAD).
#   sudo apt install git build-essential doom-wad-shareware
# With SDL2 + SDL2_mixer installed (libsdl2-dev libsdl2-mixer-dev) it is built
# with sound; DOOM_SOUND=0 forces a silent build.
set -e
HERE=$(cd "$(dirname "$0")" && pwd)
OUT="$HERE/../app/doom"
SRC="$HERE/build/doomgeneric"
REV=dcb7a8dbc7a16ce3dda29382ac9aae9d77d21284  # tested doomgeneric revision

if [ ! -d "$SRC" ]; then
    git clone -q https://github.com/ozkl/doomgeneric.git "$SRC"
fi
git -C "$SRC" fetch -q origin "$REV" 2>/dev/null || true
git -C "$SRC" checkout -q "$REV"

cp "$HERE/doomgeneric_lcd.c" "$HERE/Makefile.lcd" "$SRC/doomgeneric/"
SOUND=0
if [ "${DOOM_SOUND:-auto}" != 0 ] && command -v sdl2-config >/dev/null \
        && [ -e /usr/include/SDL2/SDL_mixer.h ]; then
    SOUND=1
fi
# the object set differs with/without sound: rebuild from scratch if it changed
if [ "$(cat "$SRC/doomgeneric/.sound" 2>/dev/null)" != "$SOUND" ]; then
    make -C "$SRC/doomgeneric" -f Makefile.lcd clean >/dev/null
    echo "$SOUND" > "$SRC/doomgeneric/.sound"
fi
echo "building Doom (sound: $SOUND)"
make -C "$SRC/doomgeneric" -f Makefile.lcd -j"$(nproc)" SOUND=$SOUND
mkdir -p "$OUT"
cp "$SRC/doomgeneric/doomlcd" "$OUT/doomlcd.new"
mv -f "$OUT/doomlcd.new" "$OUT/doomlcd"  # works even while the old binary is running
echo "built $OUT/doomlcd"
