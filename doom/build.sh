#!/bin/sh
# Build Doom for the LCD HAT: doomgeneric + our backend (doomgeneric_lcd.c).
# Output: app/doom/doomlcd (started from the menu with the shareware WAD).
#   sudo apt install git build-essential doom-wad-shareware
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
make -C "$SRC/doomgeneric" -f Makefile.lcd -j"$(nproc)"
mkdir -p "$OUT"
cp "$SRC/doomgeneric/doomlcd" "$OUT/doomlcd"
echo "built $OUT/doomlcd"
