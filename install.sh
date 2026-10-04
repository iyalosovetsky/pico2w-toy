#!/bin/sh
# Install the LCD HAT toy box on Raspberry Pi OS Bookworm (Pi Zero 2 W).
#
#   git clone https://github.com/iyalosovetsky/pico2w-toy.git
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

echo "== packages"
sudo apt-get update -q
sudo apt-get install -y python3-pygame python3-numpy python3-pil python3-pip \
    stockfish doom-wad-shareware git build-essential

echo "== python-chess (into app/vendor, not in the Raspbian repo)"
python3 -m pip install -q --upgrade --target "$APP_DIR/vendor" chess

echo "== display init file"
python3 "$REPO/firmware/mkpanel.py" | sudo tee /lib/firmware/waveshare144.bin >/dev/null

echo "== /boot/firmware/config.txt"
CONFIG=/boot/firmware/config.txt
REBOOT=0
if ! grep -q "Waveshare 1.44\" LCD HAT" "$CONFIG"; then
    backup "$CONFIG"
    sudo tee -a "$CONFIG" < "$REPO/config/boot-config.txt" >/dev/null
    REBOOT=1
fi

echo "== console font + keyboard layout"
sudo cp "$REPO"/fonts/Uni2-Fixed*.psf.gz /usr/share/consolefonts/
backup /etc/default/console-setup
if grep -q "^FONT=" /etc/default/console-setup; then
    sudo sed -i 's|^FONT=.*|FONT="Uni2-Fixed5x7.psf.gz"|' /etc/default/console-setup
else
    echo 'FONT="Uni2-Fixed5x7.psf.gz"' | sudo tee -a /etc/default/console-setup >/dev/null
fi
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
sudo systemctl daemon-reload
sudo systemctl enable lcd-menu.service

# The desktop (lightdm + Wayland) would take over the LCD as a display;
# the menu needs console boot like Raspberry Pi OS Lite.
if [ "$KEEP_DESKTOP" = 0 ] && [ "$(systemctl get-default)" = graphical.target ]; then
    echo "== switching boot to console (desktop off; --keep-desktop to skip)"
    sudo systemctl set-default multi-user.target
    REBOOT=1
fi

if [ "$REBOOT" = 1 ]; then
    echo "== done - reboot to load the display driver: sudo reboot"
else
    sudo systemctl restart lcd-menu.service
    echo "== done - menu restarted"
fi
