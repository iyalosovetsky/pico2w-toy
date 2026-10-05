*[English version](README.en.md)*

# pico2w-toy

Кишенькова ігрова консоль / AI-термінал на **Raspberry Pi Zero 2 W** і **Waveshare 1.44" LCD HAT**
(128×128, джойстик + 3 кнопки) під звичайною Raspberry Pi OS Bookworm.

Після ввімкнення запускається меню: Pong, тетріс, покер (техаський холдем), шахи проти Stockfish,
Doom, чат з локальною LLM, текстова консоль і вимкнення. Керування - джойстиком і кнопками HAT або
маленькою USB-клавіатурою.

![Прототип: AI-чат на екрані](docs/prototype.jpg)

| Меню | Pong | Тетріс | Покер |
|:---:|:---:|:---:|:---:|
| ![menu](docs/gif/menu.gif) | ![pong](docs/gif/pong.gif) | ![tetris](docs/gif/tetris.gif) | ![poker](docs/gif/poker.gif) |
| **Шахи** | **Преферанс** | **Doom** | **AI-чат** |
| ![chess](docs/gif/chess.gif) | ![preferans](docs/gif/preferans.gif) | ![doom](docs/gif/doom.gif) | ![aichat](docs/gif/aichat.gif) |

*(GIF записані прямо з фреймбуфера дисплея скриптом `tools/record_gif.py`, збільшені вдвічі.)*

## 1. Опис

| Пункт меню | Що це |
|---|---|
| **PONG** | Pong проти комп'ютера, 3 рівні складності, гра до 7 |
| **TETRIS** | Тетріс 10×20: тінь фігури, поворот біля стіни, «мішок» із 7 фігур, рівні, рекорд зберігається |
| **POKER** | Техаський холдем один на один проти AI (Монте-Карло), блайнди ростуть |
| **CHESS** | Шахи проти Stockfish 15 (8 рівнів), відкат ходу, вибір фігури при перетворенні, автозбереження |
| **PREFERANS** | Преферанс проти двох AI, Сочинка, пулька до 20, автозбереження пульки. Рушій і AI - [Python Pref](https://python-pref.sourceforge.io/index_ru.html) (той самий, що був для Nokia/Symbian), портований на Python 3 |
| **DOOM** | Doom (shareware, 1-й епізод) на [doomgeneric](https://github.com/ozkl/doomgeneric), зменшений до 128×80 |
| **AI CHAT** | Чат з локальною LLM (llama.cpp або будь-який OpenAI-сумісний сервер) у текстовій консолі, розкладка US/UA |
| **CONSOLE** | Закриває меню і відкриває текстову консоль на LCD (tty7) з логіном; команда `lcdmenu` повертає меню |
| **HDMI** | Віддає USB-клавіатуру консолі на моніторі (tty1); кнопки HAT лишаються в меню, KEY3 повертає клавіатуру меню |
| **POWER OFF** | Коректне вимкнення з підтвердженням |

Як це влаштовано:

- **Дисплей** - DRM-драйвер ядра [panel-mipi-dbi](https://github.com/notro/panel-mipi-dbi/wiki)
  керує ST7735S по SPI і створює `/dev/fb0` (без `fbcp`, який на Bookworm під KMS не працює).
  Послідовність ініціалізації - `/lib/firmware/waveshare144.bin`, її генерує `firmware/mkpanel.py`.
- **Кнопки** - overlay `gpio-key` перетворює джойстик і KEY1-3 на звичайні клавіші (стрілки, Enter,
  1/2/3), тому вони працюють усюди, навіть у текстовій консолі.
- **Програми** - pygame малює у поверхню 128×128 в пам'яті, `app/lcd.py` перетворює її в RGB565,
  пише у фреймбуфер, а натискання кнопок HAT і будь-якої USB-клавіатури (і під'єднаної пізніше теж)
  перетворює на події клавіатури pygame.
- **HDMI** - звичайна консоль Linux (tty1 з логіном). LCD має власну консоль tty7 (`fbcon=map`), тож
  монітор і LCD працюють одночасно. Поки відкрите меню чи гра, вони перехоплюють кнопки й клавіатуру
  (`EVIOCGRAB`), щоб натискання не потрапляли в консоль на HDMI. Щоб друкувати на моніторі, є пункт
  меню **HDMI**.
- **Меню** - `lcd-menu.service` стартує при завантаженні; ігри запускаються як його дочірні процеси
  і повертаються в нього. AI-чат працює на tty7 (консоль LCD) через окремий сервіс, щоб мати справжній термінал
  (редагування рядка, кирилиця).

### Файли проєкту

| Файл / папка | Призначення |
|---|---|
| `install.sh` | Встановлення «в один крок» на чисту Raspberry Pi OS Bookworm (пакети, драйвер, шрифти, сервіси) |
| `app/lcd.py` | Спільний шар дисплея та вводу для всіх програм на pygame |
| `app/menu.py` | Меню запуску (список із прокручуванням) |
| `app/pong.py`, `app/tetris.py`, `app/poker.py`, `app/chessgame.py` | Ігри |
| `app/preferans.py` | Інтерфейс преферансу 128×128 для рушія PyPref |
| `app/prefgame/` | Рушій і AI [Python Pref](https://sourceforge.net/projects/python-pref/) 2.34, портовані на Python 3 (GPL-3.0) |
| `app/ai_chat.py` | Клієнт чату з потоковою відповіддю для llama.cpp / OpenAI-сумісного сервера |
| `app/demo.py` | Мінімальний приклад на pygame: намалювати щось і прочитати кнопки |
| `doom/doomgeneric_lcd.c` | Backend для doomgeneric: 320×200 → 128×80 зі згладжуванням, RGB565, кнопки HAT + клавіатура |
| `doom/Makefile.lcd`, `doom/build.sh` | Збирає `app/doom/doomlcd` із зафіксованої версії doomgeneric |
| `firmware/mkpanel.py` | Генерує файл ініціалізації дисплея (`waveshare144.bin`, готова копія теж є) |
| `fonts/` | Консольні шрифти 5×7 (консоль, 25×18 символів) і 6×10 (AI-чат, 21×12) + `build-fonts.sh` |
| `config/` | Усе, що встановлюється в систему - див. [Конфігурація](#6-конфігурація) |
| `tools/` | `vkeys.py` - віртуальна клавіатура, `snap.py` - скриншот, `record_gif.py` - запис GIF |
| `docs/` | GIF і схема підключення |

## 2. Керування

| Дія | HAT | USB-клавіатура |
|---|---|---|
| Рух / вибір | джойстик | стрілки |
| Підтвердити / почати | натиск джойстика або KEY1 | Enter / Space |
| Додаткова дія (пауза, складність, ва-банк, меню гри) | KEY2 | 2 |
| Назад у меню | KEY3 | Esc |

По іграх:

| Програма | Керування |
|---|---|
| Pong | вгору/вниз - ракетка, Enter - старт/пауза, 2 - складність |
| Тетріс | ←/→ рух, ↓ прискорити, ↑ або Enter поворот, KEY1/Space скинути, 2 пауза |
| Покер | ←/→ вибір FOLD / CHECK-CALL / BET-RAISE, ↑/↓ розмір ставки, 2 - ва-банк |
| Шахи | джойстик рухає курсор, Enter бере / ставить фігуру, 2 - меню (відкат, нова гра) |
| Преферанс | ←/→ карта або заявка, ↑/↓ заявка на рівень вище / нижче, Enter - підтвердити; при зносі Enter відкладає карту, ↓ повертає, Enter ще раз - знести; 2 - запис пульки |
| Doom | HAT: джойстик рух, натиск - постріл (+Enter), KEY1 двері (+«y»), KEY2 наступна зброя, KEY3 меню. Клавіатура: стрілки, Ctrl постріл, Space двері, Alt боком, Shift біг, 1-7 зброя, Tab карта, Esc меню |
| AI-чат | пишете й Enter; `/new`, `/think` (міркування моделі), `/quit` або Ctrl+D; Ctrl+C зупиняє відповідь; Alt+Shift - US/UA |

## 3. Компоненти

| Компонент | Фото | Опис | Документація / магазин |
|---|---|---|---|
| **Raspberry Pi Zero 2 W** | <img src="https://arduino.ua/products_pictures/usa146/large_usa146-1.jpg" width="200"> | 4 ядра Cortex-A53, 512 МБ RAM, Wi-Fi/BT | [arduino.ua](https://arduino.ua/prod6668-raspberry-pi-zero-2-w), [raspberrypi.com](https://www.raspberrypi.com/products/raspberry-pi-zero-2-w/) |
| **Waveshare 1.44" LCD HAT** | <img src="https://www.waveshare.com/media/catalog/product/cache/1/image/800x800/9df78eab33525d08d6e5fb8d27136e95/1/_/1.44inch-lcd-hat-1.jpg" width="200"> | Дисплей ST7735S 128×128 SPI, 5-позиційний джойстик, 3 кнопки | [Waveshare Wiki](https://www.waveshare.com/wiki/1.44inch_LCD_HAT), [магазин](https://www.waveshare.com/1.44inch-lcd-hat.htm) |
| **Waveshare USB HUB HAT (B)** | <img src="https://www.waveshare.com/media/catalog/product/cache/1/image/800x800/9df78eab33525d08d6e5fb8d27136e95/u/s/usb-hub-hat-b-1_2.jpg" width="200"> | Хаб 4× USB-A для Zero, кріпиться знизу на пружинних контактах (pogo pins), USB-UART на платі | [Waveshare Wiki](https://www.waveshare.com/wiki/USB_HUB_HAT_(B)), [магазин](https://www.waveshare.com/usb-hub-hat-b.htm) |
| **Li-Po 2000 мА·год 103450** | <img src="https://arduino.ua/products_pictures/usa231/large_rac139_1.jpg" width="200"> | 1S 3.7 В, плаский, 34×50×10 мм, з платою захисту | [arduino.ua](https://arduino.ua/prod3075-akkymylyator-li-po-2000mach-3-7v-formata-103450) |
| **Модуль заряду Type-C + підвищення до 9 В** | <img src="https://content2.rozetka.com.ua/goods/images/big/650937112.jpg" width="200"> | Міні-модуль живлення (для мультиметрів): заряджає акумулятор від USB-C, видає 9 В | [Rozetka](https://rozetka.com.ua/ua/573636100/p573636100/) |
| **Понижувальний CA-1235** | <img src="https://gadgetpcb.com/wp-content/uploads/ca-1235-dc-dc-step-down-buck-converter.webp" width="200"> | Перетворювач на MP1495, вхід 5-16 В, вихід 1.25-5 В на вибір, 3 А - виставлений на 5 В | [приклад](https://www.aliexpress.us/item/3256802445813752.html) |
| **Міні-клавіатура** | <img src="docs/keyboard.jpg" width="160"> | Бездротова міні-клавіатура з тачпадом (типу Rii i8), USB-приймач 2.4 ГГц у хабі; підійде будь-яка USB-клавіатура | — |

## 4. Схема

![Схема](docs/wiring.svg)

LCD HAT використовує SPI0 (CE0) і GPIO 25/27/24 для DC/reset/підсвітки; джойстик і кнопки - на
GPIO 6, 19, 5, 26, 13, 21, 20, 16 (активний низький рівень, внутрішня підтяжка). Вручну паяти треба
лише живлення.

## 5. Встановлення

Перевірено на Raspbian 12 (Bookworm) armhf, ядро 6.12, Pi Zero 2 W.

```bash
git clone https://github.com/iyalosovetsky/pico2w-toy.git
cd pico2w-toy
./install.sh          # --no-doom - не збирати Doom, --keep-desktop - не вимикати робочий стіл,
                      # --hdmi-mode=1280x720@60 - інший режим HDMI
sudo reboot           # лише при першому встановленні: завантажити драйвер дисплея
```

`install.sh` запускається від звичайного користувача (із sudo), від якого працюватиме меню. Він:

1. ставить `python3-pygame python3-numpy python3-pil stockfish doom-wad-shareware git build-essential`;
2. кладе [python-chess](https://github.com/niklasf/python-chess) в `app/vendor` (у репозиторії Raspbian її немає);
3. записує `/lib/firmware/waveshare144.bin` і дописує `config/boot-config.txt` у `/boot/firmware/config.txt`;
4. дописує в `/boot/firmware/cmdline.txt` `video=HDMI-A-1:1920x1080@60D` (примусово вмикає HDMI - ядро на Zero
   часто не бачить монітор, хоча екран завантаження є) і `fbcon=map:0000001` (tty1-6 на HDMI, tty7 на LCD);
   встановлює консольні шрифти, розкладку US+UA, створює `/etc/default/lcd-ai-chat`;
5. збирає Doom (`doom/build.sh`);
6. встановлює й вмикає systemd-сервіси (шляхи й користувач підставляються автоматично);
7. на образі з робочим столом перемикає завантаження в консоль (`multi-user.target`), бо робочий стіл
   захопив би LCD як дисплей.

Кожен системний файл, який він змінює, один раз зберігається як `<файл>.bak-lcd`; запускати повторно
безпечно. Оновлення - `git pull && ./install.sh`.

## 6. Конфігурація

Уся системна конфігурація лежить у [`config/`](config):

| Файл | Куди встановлюється | Що робить |
|---|---|---|
| `boot-config.txt` | дописується в `/boot/firmware/config.txt` | SPI, overlay дисплея `mipi-dbi-spi` (розмір, зміщення, піни DC/RST/BL), `gpio-key` для 8 кнопок |
| `systemd/lcd-menu.service` | `/etc/systemd/system/` | Меню при старті; закриває консоль LCD (tty7) і повертає на передній план HDMI (tty1) |
| `systemd/lcd-console.service` | `/etc/systemd/system/` | Відкриває консоль на LCD (tty7, шрифт 5×7), коли меню закривається |
| `systemd/ai-chat.service` | `/etc/systemd/system/` | AI-чат на tty7 (LCD) зі шрифтом 6×10, після виходу - назад у меню |
| `lcdmenu` | `/usr/local/bin/` | Команда, щоб повернутися з консолі LCD (або з SSH) в меню |
| `keyboard` | `/etc/default/keyboard` | Розкладки US + українська, Alt+Shift перемикає, світлодіод Scroll Lock = UA |
| `ai-chat.env` | `/etc/default/lcd-ai-chat` | `AI_URL` сервера LLM (тут - llama.cpp у локальній мережі) |

Консолі на HDMI мають звичайний шрифт; шрифт 5×7 ставиться лише на tty7 (LCD) у `lcd-console.service`.
`/boot/firmware/cmdline.txt` отримує `video=HDMI-A-1:<режим>D` і `fbcon=map:0000001`.

**Поворот дисплея.** Орієнтацію задає MADCTL у `firmware/mkpanel.py` (`0x68` - поворот на 90°,
`0x08` - без повороту). Під час повороту міняються місцями зміщення в `boot-config.txt`
(`x-offset=1,y-offset=2` для 0x68, `2,1` для 0x08).

**AI-сервер.** Підійде будь-який сервер з OpenAI-сумісним `/v1/chat/completions`, наприклад
[llama.cpp](https://github.com/ggml-org/llama.cpp) `llama-server`. Моделі з міркуваннями підтримуються:
поки модель думає, видно «(думаю...)»; за замовчуванням міркування вимкнені (`/think` вмикає).

## 7. Нотатки та підводні камені

- **`fbcp` на Bookworm не працює** (KMS прибрав dispmanx). Тут дисплей - справжній DRM/fbdev-пристрій,
  тому консоль, pygame і Doom малюють прямо у фреймбуфер LCD. Програми шукають його за назвою драйвера
  (`panel-mipi-dbi`), бо з HDMI він `fb1`, а без - `fb0`.
- **HDMI на Zero.** Прошивка показує екран завантаження, а ядро може не помітити монітор (hotplug) і
  не створити для нього консоль - тоді вся консоль опиняється на LCD. `video=HDMI-A-1:...D` вмикає
  HDMI примусово.
- **Конфлікт `KEY_ENTER` у Doom.** `linux/input.h` визначає `KEY_ENTER`, `KEY_TAB`, `KEY_F1`... з
  кодами Linux і перекриває однойменні значення з `doomkeys.h` doomgeneric - Doom отримує 28 замість 13
  для Enter, і його меню перестає працювати. `doomgeneric_lcd.c` використовує явні коди Doom.
- **Кольори в підказці readline** треба обгортати в `\001...\002`, інакше довгий рядок вводу не
  переноситься.
- **SDL і SIGTERM.** SDL перетворює SIGTERM на подію `QUIT`; усі програми її обробляють, тому
  `systemctl stop` спрацьовує одразу.
- **Тестування без рук.** `tools/vkeys.py` створює віртуальну клавіатуру
  (`sudo python3 tools/vkeys.py "down down enter"`), `tools/snap.py` робить скриншот,
  `tools/record_gif.py` записує GIF, як вище.

## 8. Використане ПЗ

| Компонент | Для чого | Ліцензія |
|---|---|---|
| [pygame](https://www.pygame.org/) | Малювання та ввід у всіх програмах | LGPL |
| [panel-mipi-dbi](https://github.com/notro/panel-mipi-dbi/wiki) | Драйвер дисплея в ядрі + формат файлу ініціалізації | GPL (ядро) |
| [doomgeneric](https://github.com/ozkl/doomgeneric) | Портативний Doom; `doom/doomgeneric_lcd.c` - його backend | GPL-2.0 |
| Doom shareware WAD ([doom-wad-shareware](https://packages.debian.org/bookworm/doom-wad-shareware)) | Дані гри, 1-й епізод | shareware-ліцензія id Software |
| [Stockfish](https://stockfishchess.org/) | Шаховий рушій | GPL-3.0 |
| [python-chess](https://github.com/niklasf/python-chess) | Правила шахів, керування рушієм по UCI | GPL-3.0 |
| [Python Pref](https://python-pref.sourceforge.io/index_ru.html) 2.34 (amigo, Вадим Заплетін; на основі kpref і OpenPref) | Рушій і AI преферансу в `app/prefgame/` | GPL-3.0 |
| Шрифти X11 misc-fixed ([xfonts-base](https://packages.debian.org/bookworm/xfonts-base)) | Джерело консольних шрифтів 5×7 і 6×10 | Public domain |
| [llama.cpp](https://github.com/ggml-org/llama.cpp) | LLM-сервер для AI-чату (працює на іншій машині) | MIT |

## 9. Ліцензія

[GPL-3.0-or-later](LICENSE). Backend для Doom походить від doomgeneric / Chocolate Doom
(GPL-2.0-or-later), а шахи використовують python-chess (GPL-3.0), а преферанс - рушій Python Pref (GPL-3.0), тож проєкт
загалом - під GPL-3.0.
Shareware WAD для Doom не входить у репозиторій: він встановлюється з пакета `doom-wad-shareware`
за shareware-ліцензією id Software.
