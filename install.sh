#!/bin/sh
# Install the toy box on a PicoCalc with a Raspberry Pi Zero 2 W
# (Raspberry Pi OS Trixie Lite, 32-bit), branch "picocalc".
#
# The display and keyboard drivers come first, from
# https://github.com/ironat/picocalc_trixie (Steps 4-5). Then:
#
#   git clone -b picocalc https://github.com/iyalosovetsky/pico2w-toy.git
#   cd pico2w-toy && ./install.sh
#
# Run as the normal (sudo-capable) user the menu should run as. Safe to re-run:
# every system file that gets changed is backed up once as <file>.bak-lcd.
#   --no-doom        skip building Doom
#   --keep-desktop   don't switch a desktop image to console boot
set -e

REPO=$(cd "$(dirname "$0")" && pwd)
APP_DIR="$REPO/app"
USER_NAME=$(id -un)
BUILD_DOOM=1
KEEP_DESKTOP=0
for arg in "$@"; do
    case "$arg" in
        --no-doom) BUILD_DOOM=0 ;;
        --keep-desktop) KEEP_DESKTOP=1 ;;
        *) echo "unknown option: $arg"; exit 1 ;;
    esac
done
[ "$USER_NAME" = root ] && { echo "run as your normal user, not root"; exit 1; }

backup() {  # keep the original version of a system file once
    [ -e "$1" ] && [ ! -e "$1.bak-lcd" ] && sudo cp "$1" "$1.bak-lcd" || true
}

echo "== checking the PicoCalc display and keyboard"
grep -qs mipi /sys/class/graphics/fb*/name || {
    echo "LCD framebuffer not found: install the display first (picocalc_trixie, Step 4)"; exit 1; }
grep -qs picocalc_kbd /sys/class/input/event*/device/name || \
    echo "warning: picocalc_kbd keyboard not found (picocalc_trixie, Step 5) - a USB keyboard still works"

echo "== packages"
sudo apt-get update -q
sudo apt-get install -y python3-pygame python3-numpy python3-pil python3-pip \
    stockfish doom-wad-shareware git build-essential libsdl2-dev libsdl2-mixer-dev \
    console-setup

echo "== python-chess (into app/vendor, not in the Raspbian repo)"
python3 -m pip install -q --upgrade --target "$APP_DIR/vendor" chess

echo "== sound: PWM audio on GPIO 12/13"
CONFIG=/boot/firmware/config.txt
REBOOT=0
add_config() {  # add_config <line>
    if ! grep -qxF "$1" "$CONFIG"; then
        backup "$CONFIG"
        echo "$1" | sudo tee -a "$CONFIG" >/dev/null
        REBOOT=1
    fi
}
grep -q "^dtparam=audio=on" "$CONFIG" || add_config "dtparam=audio=on"
add_config "dtoverlay=audremap,pins_12_13"
backup /etc/asound.conf
sudo cp "$REPO/config/asound.conf" /etc/asound.conf
[ -e /etc/default/lcd-toy ] || sudo cp "$REPO/config/lcd-toy.env" /etc/default/lcd-toy

echo "== keyboard layout + AI chat settings"
backup /etc/default/keyboard
sudo cp "$REPO/config/keyboard" /etc/default/keyboard
sudo setupcon --save-only >/dev/null 2>&1 || true
[ -e /etc/default/lcd-ai-chat ] || sudo cp "$REPO/config/ai-chat.env" /etc/default/lcd-ai-chat

if [ "$BUILD_DOOM" = 1 ]; then
    echo "== Doom"
    "$REPO/doom/build.sh"
fi

echo "== services"
for unit in "$REPO"/config/systemd/*.service; do
    sed -e "s|@USER@|$USER_NAME|g" -e "s|@APP_DIR@|$APP_DIR|g" "$unit" |
        sudo tee "/etc/systemd/system/$(basename "$unit")" >/dev/null
done
sudo install -m 755 "$REPO/config/lcdmenu" /usr/local/bin/lcdmenu
sudo install -m 755 "$REPO/config/lcd-vt" /usr/local/bin/lcd-vt
sudo systemctl daemon-reload
sudo systemctl enable lcd-menu.service

# A desktop session would take over the LCD; the menu needs console boot.
if [ "$KEEP_DESKTOP" = 0 ] && [ "$(systemctl get-default)" = graphical.target ]; then
    echo "== switching boot to console (desktop off; --keep-desktop to skip)"
    sudo systemctl set-default multi-user.target
    REBOOT=1
fi

if [ "$REBOOT" = 1 ]; then
    echo "== done - reboot to apply the new boot settings: sudo reboot"
else
    sudo systemctl restart lcd-menu.service
    echo "== done - menu started"
fi
