#!/bin/sh
# Rebuild the console fonts in this folder from the X11 "misc-fixed" bitmap
# fonts (public domain): 5x7 for the console (25x18 chars on the LCD) and
# 6x10 for the AI chat (21x12 chars). Uni2 = Latin + Cyrillic.
#   sudo apt install xfonts-base pcf2bdf bdf2psf
set -e
cd "$(dirname "$0")"
B=/usr/share/bdf2psf
tmp=$(mktemp -d)
for size in 5x7 6x10; do
    zcat /usr/share/fonts/X11/misc/$size.pcf.gz > "$tmp/$size.pcf"
    pcf2bdf -o "$tmp/$size.bdf" "$tmp/$size.pcf"
    bdf2psf --fb "$tmp/$size.bdf" $B/standard.equivalents \
        $B/ascii.set+$B/linux.set+$B/fontsets/Uni2.512+:$B/useful.set 512 \
        "$tmp/Uni2-Fixed$size.psf" 2>/dev/null
    gzip -9 -c "$tmp/Uni2-Fixed$size.psf" > "Uni2-Fixed$size.psf.gz"
    echo "built Uni2-Fixed$size.psf.gz"
done
rm -rf "$tmp"
