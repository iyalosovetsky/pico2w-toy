#!/bin/sh
# Install the toy box on a Raspberry Pi Zero 2 W with one of:
#   hat       Waveshare 1.44" LCD HAT (128x128) - Raspberry Pi OS Bookworm
#   picocalc  ClockworkPi PicoCalc (320x320, keyboard, PWM sound) - Raspberry Pi OS Trixie;
#             install its display + keyboard first (github.com/ironat/picocalc_trixie, Steps 4-5)
#
#   git clone https://github.com/iyalosovetsky/pico2w-toy.git
#   cd pico2w-toy && ./install.sh                  # device auto-detected (or asked)
#   ./install.sh --device=picocalc                  # or choose it
#
# Run as the normal (sudo-capable) user the menu should run as. Safe to re-run:
# every system file that gets changed is backed up once as <file>.bak-lcd.
#   --device=hat|picocalc   which device to install for
#   --no-doom               skip building Doom
#   --keep-desktop          don't switch a desktop image to console boot
#   --hdmi-mode=WxH@R       HAT only: HDMI mode to force (default 1920x1080@60)
set -e

REPO=$(cd "$(dirname "$0")" && pwd)
APP_DIR="$REPO/app"
USER_NAME=$(id -un)
DEVICE=
BUILD_DOOM=1
KEEP_DESKTOP=0
HDMI_MODE=1920x1080@60
for arg in "$@"; do
    case "$arg" in
        --device=*) DEVICE=${arg#--device=} ;;
        --no-doom) BUILD_DOOM=0 ;;
        --keep-desktop) KEEP_DESKTOP=1 ;;
        --hdmi-mode=*) HDMI_MODE=${arg#--hdmi-mode=} ;;
        *) echo "unknown option: $arg"; exit 1 ;;
    esac
done
[ "$USER_NAME" = root ] && { echo "run as your normal user, not root"; exit 1; }

CONFIG=/boot/firmware/config.txt
CMDLINE=/boot/firmware/cmdline.txt
REBOOT=0

backup() {  # keep the original version of a system file once
    [ -e "$1" ] && [ ! -e "$1.bak-lcd" ] && sudo cp "$1" "$1.bak-lcd" || true
}

add_cmdline() {  # add_cmdline <key> <param>
    if ! grep -q "$1" "$CMDLINE"; then
        backup "$CMDLINE"
        sudo sed -i "1s|\$| $2|" "$CMDLINE"
        REBOOT=1
    fi
}

add_config() {  # add_config <line>
    if ! grep -qxF "$1" "$CONFIG"; then
        backup "$CONFIG"
        echo "$1" | sudo tee -a "$CONFIG" >/dev/null
        REBOOT=1
    fi
}

detect_device() {
    # PicoCalc: its keyboard driver or display overlay; HAT: our overlay or a 128x128 panel
    if grep -qs picocalc_kbd /sys/class/input/event*/device/name \
            || grep -qsE "^dtoverlay=picocalc_kbd|picomipi" "$CONFIG"; then
        echo picocalc
    elif grep -qs "Waveshare 1.44\" LCD HAT" "$CONFIG" \
            || grep -qsx "128,128" /sys/class/graphics/fb*/virtual_size; then
        echo hat
    fi
}

if [ -z "$DEVICE" ]; then
    DEVICE=$(detect_device)
    if [ -z "$DEVICE" ]; then
        if [ -t 0 ]; then
            echo "Which device is this?"
            echo "  1) Waveshare 1.44\" LCD HAT"
            echo "  2) ClockworkPi PicoCalc"
            printf "> "
            read -r answer
            case "$answer" in
                1|hat) DEVICE=hat ;;
                2|picocalc) DEVICE=picocalc ;;
            esac
        fi
        [ -n "$DEVICE" ] || { echo "can't tell the device: use --device=hat or --device=picocalc"; exit 1; }
    else
        echo "== device: $DEVICE (auto-detected; --device=... to override)"
    fi
fi
case "$DEVICE" in
    hat|picocalc) ;;
    *) echo "unknown device: $DEVICE (hat or picocalc)"; exit 1 ;;
esac
DEV_CONFIG="$REPO/config/$DEVICE"

# ---------------------------------------------------------------- device specific

install_hat() {
    echo "== display init file"
    python3 "$REPO/firmware/mkpanel.py" | sudo tee /lib/firmware/waveshare144.bin >/dev/null

    echo "== /boot/firmware/config.txt"
    if ! grep -q "Waveshare 1.44\" LCD HAT" "$CONFIG"; then
        backup "$CONFIG"
        sudo tee -a "$CONFIG" < "$DEV_CONFIG/boot-config.txt" >/dev/null
        REBOOT=1
    fi

    echo "== kernel command line: HDMI console + LCD console on tty7"
    # The kernel often misses HDMI hotplug on the Zero (the firmware boot screen
    # works, the console doesn't): force the connector on. fbcon=map puts tty1-6 on
    # fb0 (HDMI) and tty7 on fb1 (the LCD) - the AI chat and LCD console use tty7.
    add_cmdline "video=HDMI-A-1" "video=HDMI-A-1:${HDMI_MODE}D"
    add_cmdline "fbcon=map" "fbcon=map:0000001"

    echo "== console fonts"
    sudo cp "$REPO"/fonts/Uni2-Fixed*.psf.gz /usr/share/consolefonts/
    # the HDMI consoles keep the normal font; tty7 (LCD) gets 5x7 from lcd-console.service
    # (older versions of this script set 5x7 for all consoles - undo that)
    sudo sed -i '/^FONT="Uni2-Fixed5x7.psf.gz"/d' /etc/default/console-setup
}

install_picocalc() {
    echo "== checking the PicoCalc display and keyboard"
    grep -qs mipi /sys/class/graphics/fb*/name || {
        echo "LCD framebuffer not found: install the display first (picocalc_trixie, Step 4)"; exit 1; }
    grep -qs picocalc_kbd /sys/class/input/event*/device/name || \
        echo "warning: picocalc_kbd keyboard not found (picocalc_trixie, Step 5) - a USB keyboard still works"

    echo "== sound: PWM audio on GPIO 12/13"
    grep -q "^dtparam=audio=on" "$CONFIG" || add_config "dtparam=audio=on"
    add_config "dtoverlay=audremap,pins_12_13"
    backup /etc/asound.conf
    sudo cp "$DEV_CONFIG/asound.conf" /etc/asound.conf
    [ -e /etc/default/lcd-toy ] || sudo cp "$DEV_CONFIG/lcd-toy.env" /etc/default/lcd-toy
    sudo install -m 755 "$DEV_CONFIG/lcd-vt" /usr/local/bin/lcd-vt

    echo "== UART on GPIO 14/15 (/dev/serial0) for the ESP32-C6, without a login console"
    add_config "enable_uart=1"
    if grep -q "console=serial0" "$CMDLINE"; then
        backup "$CMDLINE"
        sudo sed -i "s/console=serial0,[0-9]* //" "$CMDLINE"
        REBOOT=1
    fi
    sudo install -m 755 "$REPO/tools/esp32c6/esp32c6" /usr/local/bin/esp32c6

    install_mmbasic
}

# MMBasic for Linux (MMB4L, github.com/thwill1000/mmb4l) - the BASIC of the PicoCalc's
# own PicoMite firmware; its armv6l build runs on the Zero 2 W's 32-bit OS
MMB4L_VERSION=0.8-alpha.1
install_mmbasic() {
    if mmbasic --version 2>/dev/null | grep -q "$MMB4L_VERSION"; then
        return
    fi
    echo "== MMBasic for Linux $MMB4L_VERSION"
    name="mmb4l-$MMB4L_VERSION-armv6l-glibc-2.29"
    tmp=$(mktemp -d)
    curl -fsSL -o "$tmp/m.tgz" \
        "https://github.com/thwill1000/mmb4l/releases/download/v$MMB4L_VERSION/$name.tgz"
    tar xzf "$tmp/m.tgz" -C "$tmp"
    sudo install -m 755 "$tmp/$name/mmbasic" /usr/local/bin/mmbasic
    sudo install -d /usr/local/share/doc/mmb4l
    sudo cp "$tmp/$name"/LICENSE* "$tmp/$name/README.md" /usr/local/share/doc/mmb4l/
    # nano as MMBasic's EDITor, with MMBasic highlighting (nano 4.8+ setup from its README)
    mkdir -p "$HOME/.mmbasic"
    for f in mmbasic.nanorc mmbasic.syntax.nanorc; do
        [ -e "$HOME/.mmbasic/$f" ] || cp "$tmp/$name/$f" "$HOME/.mmbasic/"
    done
    rm -rf "$tmp"
}

# ---------------------------------------------------------------- common

echo "== packages"
EXTRA=
# PicoCalc: SDL for Doom sound, console tools for the PYTHON / BASIC / EDIT menu items
[ "$DEVICE" = picocalc ] && EXTRA="libsdl2-dev libsdl2-mixer-dev console-setup micro bpython nano curl"
sudo apt-get update -q
sudo apt-get install -y python3-pygame python3-numpy python3-pil python3-pip \
    stockfish doom-wad-shareware git build-essential fonts-dejavu-core poppler-utils $EXTRA
mkdir -p "$HOME/books"  # the BOOKS reader's library (.epub / .fb2 / .zip)

echo "== python-chess (into app/vendor, not in the Raspbian repo)"
python3 -m pip install -q --upgrade --target "$APP_DIR/vendor" chess

"install_$DEVICE"

echo "== keyboard layout + AI chat settings"
backup /etc/default/keyboard
sudo cp "$DEV_CONFIG/keyboard" /etc/default/keyboard
sudo setupcon --save-only >/dev/null 2>&1 || true
[ -e /etc/default/lcd-ai-chat ] || sudo cp "$REPO/config/ai-chat.env" /etc/default/lcd-ai-chat

if [ "$BUILD_DOOM" = 1 ]; then
    echo "== Doom"
    "$REPO/doom/build.sh"
fi

echo "== services"
for unit in "$DEV_CONFIG"/systemd/*.service; do
    sed -e "s|@USER@|$USER_NAME|g" -e "s|@APP_DIR@|$APP_DIR|g" "$unit" |
        sudo tee "/etc/systemd/system/$(basename "$unit")" >/dev/null
done
sudo install -m 755 "$REPO/config/lcdmenu" /usr/local/bin/lcdmenu
sudo systemctl daemon-reload
sudo systemctl enable lcd-menu.service

# A desktop session would take over the LCD; the menu needs console boot like Raspberry Pi OS Lite.
if [ "$KEEP_DESKTOP" = 0 ] && [ "$(systemctl get-default)" = graphical.target ]; then
    echo "== switching boot to console (desktop off; --keep-desktop to skip)"
    sudo systemctl set-default multi-user.target
    REBOOT=1
fi

if [ "$REBOOT" = 1 ]; then
    echo "== done ($DEVICE) - reboot to apply the new boot settings: sudo reboot"
else
    sudo systemctl restart lcd-menu.service
    echo "== done ($DEVICE) - menu started"
fi
