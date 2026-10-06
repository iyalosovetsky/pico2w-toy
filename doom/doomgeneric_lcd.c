// doomgeneric backend for small RGB565 framebuffer LCDs (panel-mipi-dbi):
// the Waveshare 1.44" LCD HAT (128x128, the HAT buttons exposed as gpio-key
// evdev devices) and the PicoCalc (320x320, I2C keyboard). The 320x200 frame
// is box-filtered down to the LCD width (1:1 on the PicoCalc) and centred.
//
// Buttons: joystick = move/turn, joystick press = fire (+Enter in menus),
//          KEY1 = use/open (+"y" to confirm), KEY2 = next weapon, KEY3 = menu (Esc)
// Keyboard: arrows, Enter or Ctrl = fire (Enter also selects in menus), Space = use,
//          Alt = strafe, left Shift = run, Esc, Tab = map, 1-7 = weapons, y/n,
//          letters for cheats/save names. (The PicoCalc's right Shift toggles its
//          driver's mouse mode: arrows stop being keys - see pollButtons.)

#include "doomgeneric.h"
#include "doomkeys.h"
#include "i_system.h"

#include <dirent.h>
#include <stdlib.h>
#include <errno.h>
#include <fcntl.h>
#include <linux/input.h>
#include <stdio.h>
#include <string.h>
#include <signal.h>
#include <time.h>
#include <unistd.h>
#include <sys/ioctl.h>

static int lcdW = 128, lcdH = 128;  // read from the framebuffer in DG_Init
static int outH, outY;              // height of the picture (keeps aspect) and its top row

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
static uint16_t *frame;
static size_t frameBytes;
static int *srcX, *srcY;

#define MAX_INPUTS 16
static int inputFds[MAX_INPUTS];
static char inputNames[MAX_INPUTS][16];  // "eventN", to skip devices already open
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

static void openButtons(int required);

static unsigned arrowsDown;  // bit (doomkey & 3) per arrow key held on a keyboard

static void releaseArrows(void)
{
	static const unsigned char arrows[] = { KEY_UPARROW, KEY_DOWNARROW, KEY_LEFTARROW, KEY_RIGHTARROW };

	for (int a = 0; a < 4; a++)
		if (arrowsDown & (1 << (arrows[a] & 3)))
			addKey(0, arrows[a]);
	arrowsDown = 0;
}

static void dropInput(int i)
{
	close(inputFds[i]);
	numInputFds--;
	inputFds[i] = inputFds[numInputFds];
	inputIsKeyboard[i] = inputIsKeyboard[numInputFds];
	memcpy(inputNames[i], inputNames[numInputFds], sizeof(inputNames[i]));
}

static void pollButtons(void)
{
	struct input_event ev[16];
	static uint32_t lastScan;

	if (DG_GetTicksMs() - lastScan > 2000) {  // pick up keyboards plugged in later
		lastScan = DG_GetTicksMs();
		openButtons(0);
	}
	for (int i = 0; i < numInputFds; i++) {
		ssize_t n;
		while ((n = read(inputFds[i], ev, sizeof(ev))) > 0) {
			for (size_t j = 0; j < n / sizeof(ev[0]); j++) {
				if (ev[j].type == EV_REL && inputIsKeyboard[i]) {
					// keyboard in mouse mode (PicoCalc: right Shift): arrows now move
					// a pointer and their key-up never comes - don't leave them held
					releaseArrows();
					continue;
				}
				if (ev[j].type != EV_KEY || ev[j].value == 2)  // ignore autorepeat
					continue;
				if (inputIsKeyboard[i]) {
					if (ev[j].code == KEY_ENTER || ev[j].code == KEY_KPENTER) {
						// Enter: fire in the game, select in the menus
						addKey(ev[j].value, KEY_FIRE);
						addKey(ev[j].value, DOOM_KEY_ENTER);
						continue;
					}
					unsigned char k = keyboardKey(ev[j].code);
					if (k == KEY_UPARROW || k == KEY_DOWNARROW || k == KEY_LEFTARROW || k == KEY_RIGHTARROW)
						arrowsDown = ev[j].value ? arrowsDown | (1 << (k & 3)) : arrowsDown & ~(1 << (k & 3));
					if (k)
						addKey(ev[j].value, k);
				} else {
					handleButton(ev[j].code, ev[j].value);
				}
			}
		}
		if (n < 0 && errno == ENODEV) {  // unplugged
			dropInput(i);
			i--;
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

static void openButtons(int required)
{
	DIR *dir = opendir("/sys/class/input");
	struct dirent *de;
	char path[300], name[64];

	if (!dir)
		I_Error("Cannot open /sys/class/input: %s", strerror(errno));
	while ((de = readdir(dir)) && numInputFds < MAX_INPUTS) {
		if (strncmp(de->d_name, "event", 5))
			continue;
		int known = 0;
		for (int i = 0; i < numInputFds; i++)
			known |= !strcmp(inputNames[i], de->d_name);
		if (known)
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
				snprintf(inputNames[numInputFds], sizeof(inputNames[0]), "%s", de->d_name);
				inputFds[numInputFds++] = fd;
			}
		}
		fclose(f);
	}
	closedir(dir);
	if (required && numInputFds == 0)
		I_Error("No HAT buttons or keyboard found");
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
			snprintf(path, sizeof(path), "/sys/class/graphics/fb%d/virtual_size", i);
			f = fopen(path, "r");
			if (f) {
				if (fscanf(f, "%d,%d", &lcdW, &lcdH) != 2)
					lcdW = lcdH = 128;
				fclose(f);
			}
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

	outH = DOOMGENERIC_RESY * lcdW / DOOMGENERIC_RESX;  // 80 on 128, 200 on 320
	if (outH > lcdH)
		outH = lcdH;
	outY = (lcdH - outH) / 2;
	frameBytes = (size_t)lcdW * lcdH * 2;
	frame = calloc(lcdW * lcdH, 2);
	srcX = malloc((lcdW + 1) * sizeof(int));
	srcY = malloc((outH + 1) * sizeof(int));
	if (!frame || !srcX || !srcY)
		I_Error("out of memory");

	// source pixel ranges for box-filter downscaling 320x200 -> lcdW x outH
	for (int x = 0; x <= lcdW; x++)
		srcX[x] = x * DOOMGENERIC_RESX / lcdW;
	for (int y = 0; y <= outH; y++)
		srcY[y] = y * DOOMGENERIC_RESY / outH;

	openButtons(1);
	clock_gettime(CLOCK_MONOTONIC, &startTime);
}

void DG_DrawFrame()
{
	for (int y = 0; y < outH; y++) {
		uint16_t *out = &frame[(outY + y) * lcdW];
		for (int x = 0; x < lcdW; x++) {
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
			if (n == 0) {  // LCD wider than 320: nearest source pixel
				uint32_t p = DG_ScreenBuffer[srcY[y] * DOOMGENERIC_RESX + srcX[x]];
				r = (p >> 16) & 0xff; g = (p >> 8) & 0xff; b = p & 0xff; n = 1;
			}
			r /= n; g /= n; b /= n;
			out[x] = ((r >> 3) << 11) | ((g >> 2) << 5) | (b >> 3);
		}
	}
	pwrite(fbFd, frame, frameBytes, 0);
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

// SIGTERM (systemctl stop, poweroff) must end in a normal I_Quit(): being
// killed while the sound device is open leaves the PicoCalc's bcm2835 PWM audio
// driver stuck closing it for minutes.
static volatile sig_atomic_t quitRequested;

static void onSignal(int sig)
{
	(void)sig;
	quitRequested = 1;
}

int main(int argc, char **argv)
{
	signal(SIGTERM, onSignal);
	signal(SIGINT, onSignal);
	signal(SIGHUP, onSignal);
	doomgeneric_Create(argc, argv);
	key_nextweapon = NEXT_WEAPON_KEY;

	for (;;) {
		doomgeneric_Tick();
		if (quitRequested)
			I_Quit();
	}
	return 0;
}
