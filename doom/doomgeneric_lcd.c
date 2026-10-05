// doomgeneric backend for the Waveshare 1.44" LCD HAT (128x128 RGB565 fb via
// panel-mipi-dbi) with the HAT buttons exposed as gpio-key evdev devices.
//
// Buttons: joystick = move/turn, joystick press = fire (+Enter in menus),
//          KEY1 = use/open (+"y" to confirm), KEY2 = next weapon, KEY3 = menu (Esc)
// USB keyboard: arrows, Ctrl = fire, Space = use, Alt = strafe, Shift = run,
//          Enter, Esc, Tab = map, 1-7 = weapons, y/n, letters for cheats/save names

#include "doomgeneric.h"
#include "doomkeys.h"
#include "i_system.h"

#include <dirent.h>
#include <errno.h>
#include <fcntl.h>
#include <linux/input.h>
#include <stdio.h>
#include <string.h>
#include <time.h>
#include <unistd.h>
#include <sys/ioctl.h>

#define LCD_W 128
#define LCD_H 128
#define OUT_H (DOOMGENERIC_RESY * LCD_W / DOOMGENERIC_RESX)  // 80, keeps aspect
#define OUT_Y ((LCD_H - OUT_H) / 2)

#define NEXT_WEAPON_KEY 0x5d  // ]
// linux/input.h redefines KEY_ENTER as 28; Doom expects 13
#define DOOM_KEY_ENTER 13
// same for these doomkeys.h names, so use Doom's values directly
#define DOOM_KEY_TAB 9
#define DOOM_KEY_BACKSPACE 0x7f
#define DOOM_KEY_MINUS 0x2d
#define DOOM_KEY_EQUALS 0x3d
#define DOOM_KEY_F1 (0x80 + 0x3b)

extern int key_nextweapon;

static int fbFd = -1;
static uint16_t frame[LCD_W * LCD_H];
static int srcX[LCD_W + 1], srcY[OUT_H + 1];

#define MAX_INPUTS 16
static int inputFds[MAX_INPUTS];
static int inputIsKeyboard[MAX_INPUTS];
static int numInputFds;

#define KEYQUEUE_SIZE 64
static unsigned short keyQueue[KEYQUEUE_SIZE];
static unsigned int keyQueueWrite, keyQueueRead;

static struct timespec startTime;

static void addKey(int pressed, unsigned char key)
{
	keyQueue[keyQueueWrite] = (pressed << 8) | key;
	keyQueueWrite = (keyQueueWrite + 1) % KEYQUEUE_SIZE;
}

static void handleButton(int code, int pressed)
{
	switch (code) {
	case KEY_UP:    addKey(pressed, KEY_UPARROW); break;
	case KEY_DOWN:  addKey(pressed, KEY_DOWNARROW); break;
	case KEY_LEFT:  addKey(pressed, KEY_LEFTARROW); break;
	case KEY_RIGHT: addKey(pressed, KEY_RIGHTARROW); break;
	case KEY_ENTER: addKey(pressed, KEY_FIRE); addKey(pressed, DOOM_KEY_ENTER); break;
	case KEY_1:     addKey(pressed, KEY_USE); addKey(pressed, 0x79); break;  // y
	case KEY_2:     addKey(pressed, NEXT_WEAPON_KEY); break;
	case KEY_3:     addKey(pressed, KEY_ESCAPE); break;
	}
}

// Full USB keyboard: Linux keycode -> Doom key (0 = ignore)
static unsigned char keyboardKey(int code)
{
	static const char row1[] = "qwertyuiop", row2[] = "asdfghjkl", row3[] = "zxcvbnm";

	switch (code) {
	case KEY_UP:        return KEY_UPARROW;
	case KEY_DOWN:      return KEY_DOWNARROW;
	case KEY_LEFT:      return KEY_LEFTARROW;
	case KEY_RIGHT:     return KEY_RIGHTARROW;
	case KEY_ENTER:
	case KEY_KPENTER:   return DOOM_KEY_ENTER;
	case KEY_ESC:       return KEY_ESCAPE;
	case KEY_LEFTCTRL:
	case KEY_RIGHTCTRL: return KEY_FIRE;
	case KEY_SPACE:     return KEY_USE;
	case KEY_LEFTALT:
	case KEY_RIGHTALT:  return KEY_RALT;
	case KEY_LEFTSHIFT:
	case KEY_RIGHTSHIFT: return KEY_RSHIFT;
	case KEY_TAB:       return DOOM_KEY_TAB;
	case KEY_BACKSPACE: return DOOM_KEY_BACKSPACE;
	case KEY_MINUS:     return DOOM_KEY_MINUS;
	case KEY_EQUAL:     return DOOM_KEY_EQUALS;
	case KEY_F1 ... KEY_F10: return DOOM_KEY_F1 + (code - KEY_F1);
	case KEY_1 ... KEY_9: return 0x31 + (code - KEY_1);
	case KEY_0:         return 0x30;
	case KEY_Q ... KEY_P: return row1[code - KEY_Q];
	case KEY_A ... KEY_L: return row2[code - KEY_A];
	case KEY_Z ... KEY_M: return row3[code - KEY_Z];
	}
	return 0;
}

static void pollButtons(void)
{
	struct input_event ev[16];

	for (int i = 0; i < numInputFds; i++) {
		ssize_t n;
		while ((n = read(inputFds[i], ev, sizeof(ev))) > 0) {
			for (size_t j = 0; j < n / sizeof(ev[0]); j++) {
				if (ev[j].type != EV_KEY || ev[j].value == 2)  // ignore autorepeat
					continue;
				if (inputIsKeyboard[i]) {
					unsigned char k = keyboardKey(ev[j].code);
					if (k)
						addKey(ev[j].value, k);
				} else {
					handleButton(ev[j].code, ev[j].value);
				}
			}
		}
	}
}

// a real keyboard has Enter and letter keys
static int isKeyboard(const char *event)
{
	char path[300], buf[512];
	unsigned long words[32];
	int n = 0;

	snprintf(path, sizeof(path), "/sys/class/input/%s/device/capabilities/key", event);
	FILE *f = fopen(path, "r");
	if (!f)
		return 0;
	if (fgets(buf, sizeof(buf), f)) {
		for (char *tok = strtok(buf, " \n"); tok && n < 32; tok = strtok(NULL, " \n"))
			words[n++] = strtoul(tok, NULL, 16);
	}
	fclose(f);

	int bpw = sizeof(unsigned long) * 8;
	const int need[] = { KEY_ENTER, KEY_A, KEY_Z };
	for (int i = 0; i < 3; i++) {
		int w = n - 1 - need[i] / bpw;  // the last word holds the lowest bits
		if (w < 0 || !(words[w] >> (need[i] % bpw) & 1))
			return 0;
	}
	return 1;
}

static void openButtons(void)
{
	DIR *dir = opendir("/sys/class/input");
	struct dirent *de;
	char path[300], name[64];

	if (!dir)
		I_Error("Cannot open /sys/class/input: %s", strerror(errno));
	while ((de = readdir(dir)) && numInputFds < MAX_INPUTS) {
		if (strncmp(de->d_name, "event", 5))
			continue;
		snprintf(path, sizeof(path), "/sys/class/input/%s/device/name", de->d_name);
		FILE *f = fopen(path, "r");
		if (!f)
			continue;
		int button = fgets(name, sizeof(name), f) && !strncmp(name, "button@", 7);
		int keyboard = !button && isKeyboard(de->d_name);
		if (button || keyboard) {
			snprintf(path, sizeof(path), "/dev/input/%s", de->d_name);
			int fd = open(path, O_RDONLY | O_NONBLOCK);
			if (fd >= 0) {
				ioctl(fd, EVIOCGRAB, 1);  // keys must not also reach the HDMI console
				inputIsKeyboard[numInputFds] = keyboard;
				inputFds[numInputFds++] = fd;
			}
		}
		fclose(f);
	}
	closedir(dir);
	if (numInputFds == 0)
		I_Error("No HAT buttons found (gpio-key overlay not loaded?)");
}

static int openLcd(void)
{
	char path[64], name[64];

	for (int i = 0; i < 8; i++) {
		snprintf(path, sizeof(path), "/sys/class/graphics/fb%d/name", i);
		FILE *f = fopen(path, "r");
		if (!f)
			continue;
		int found = fgets(name, sizeof(name), f) && strstr(name, "mipi");
		fclose(f);
		if (found) {
			snprintf(path, sizeof(path), "/dev/fb%d", i);
			return open(path, O_WRONLY);
		}
	}
	return -1;
}

void DG_Init()
{
	fbFd = openLcd();
	if (fbFd < 0)
		I_Error("LCD framebuffer not found");

	// source pixel ranges for box-filter downscaling 320x200 -> 128x80
	for (int x = 0; x <= LCD_W; x++)
		srcX[x] = x * DOOMGENERIC_RESX / LCD_W;
	for (int y = 0; y <= OUT_H; y++)
		srcY[y] = y * DOOMGENERIC_RESY / OUT_H;

	openButtons();
	clock_gettime(CLOCK_MONOTONIC, &startTime);
}

void DG_DrawFrame()
{
	for (int y = 0; y < OUT_H; y++) {
		uint16_t *out = &frame[(OUT_Y + y) * LCD_W];
		for (int x = 0; x < LCD_W; x++) {
			unsigned r = 0, g = 0, b = 0, n = 0;
			for (int sy = srcY[y]; sy < srcY[y + 1]; sy++) {
				const pixel_t *row = &DG_ScreenBuffer[sy * DOOMGENERIC_RESX];
				for (int sx = srcX[x]; sx < srcX[x + 1]; sx++) {
					uint32_t p = row[sx];
					r += (p >> 16) & 0xff;
					g += (p >> 8) & 0xff;
					b += p & 0xff;
					n++;
				}
			}
			r /= n; g /= n; b /= n;
			out[x] = ((r >> 3) << 11) | ((g >> 2) << 5) | (b >> 3);
		}
	}
	pwrite(fbFd, frame, sizeof(frame), 0);
	pollButtons();
}

void DG_SleepMs(uint32_t ms)
{
	usleep(ms * 1000);
}

uint32_t DG_GetTicksMs()
{
	struct timespec now;

	clock_gettime(CLOCK_MONOTONIC, &now);
	return (now.tv_sec - startTime.tv_sec) * 1000 +
	       (now.tv_nsec - startTime.tv_nsec) / 1000000;
}

int DG_GetKey(int *pressed, unsigned char *doomKey)
{
	pollButtons();
	if (keyQueueRead == keyQueueWrite)
		return 0;
	unsigned short k = keyQueue[keyQueueRead];
	keyQueueRead = (keyQueueRead + 1) % KEYQUEUE_SIZE;
	*pressed = k >> 8;
	*doomKey = k & 0xff;
	return 1;
}

void DG_SetWindowTitle(const char *title)
{
}

int main(int argc, char **argv)
{
	doomgeneric_Create(argc, argv);
	key_nextweapon = NEXT_WEAPON_KEY;

	for (;;)
		doomgeneric_Tick();
	return 0;
}
