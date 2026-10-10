*[English version](README.en.md)*

# pico2w-toy

Кишенькова ігрова консоль / AI-термінал на **Raspberry Pi Zero 2 W** для двох пристроїв:

- **Waveshare 1.44" LCD HAT** - 128×128, джойстик + 3 кнопки, Raspberry Pi OS Bookworm (основний опис нижче);
- **[ClockworkPi PicoCalc](https://www.clockworkpi.com/picocalc)** із Zero 2 W замість Pico (zero mod) -
  320×320, клавіатура, PWM-звук, Raspberry Pi OS Trixie (розділ [PicoCalc](#picocalc)).

Код програм спільний: `app/lcd.py` сам визначає дисплей. `install.sh` визначає пристрій або бере
його з `--device=hat|picocalc`; конфігурація для кожного - у `config/hat/` і `config/picocalc/`.

Після ввімкнення запускається меню: Pong, тетріс, покер (техаський холдем), шахи проти Stockfish,
Doom, чат з локальною LLM, текстова консоль і вимкнення. Керування - джойстиком і кнопками HAT або
маленькою USB-клавіатурою.

![Прототип у надрукованому корпусі](docs/prototype.jpg)

| Меню | Pong | Тетріс | Покер |
|:---:|:---:|:---:|:---:|
| ![menu](docs/gif/menu.gif) | ![pong](docs/gif/pong.gif) | ![tetris](docs/gif/tetris.gif) | ![poker](docs/gif/poker.gif) |
| **Шахи** | **Преферанс** | **Doom** | **AI-чат** |
| ![chess](docs/gif/chess.gif) | ![preferans](docs/gif/preferans.gif) | ![doom](docs/gif/doom.gif) | ![aichat](docs/gif/aichat.gif) |
| **Книжки** | **PDF** | | |
| ![reader](docs/gif/reader.gif) | ![pdf](docs/gif/pdf.gif) | | |

*(GIF записані прямо з фреймбуфера дисплея скриптом `tools/record_gif.py`, збільшені вдвічі.)*

## PicoCalc

<img src="docs/picocalc.jpg" width="360" alt="PicoCalc із меню pico2w-toy">

| Меню | Pong | Тетріс | Покер |
|:---:|:---:|:---:|:---:|
| ![menu](docs/gif-picocalc/menu.gif) | ![pong](docs/gif-picocalc/pong.gif) | ![tetris](docs/gif-picocalc/tetris.gif) | ![poker](docs/gif-picocalc/poker.gif) |
| **Шахи** | **Преферанс** | **Doom** | **AI-чат** |
| ![chess](docs/gif-picocalc/chess.gif) | ![preferans](docs/gif-picocalc/preferans.gif) | ![doom](docs/gif-picocalc/doom.gif) | ![aichat](docs/gif-picocalc/aichat.gif) |
| **Книжки** | **PDF** | **GENERATOR** | **Вольтметр** |
| ![reader](docs/gif-picocalc/reader.gif) | ![pdf](docs/gif-picocalc/pdf.gif) | ![generator](docs/gif-picocalc/generator.gif) | ![voltmeter](docs/gif-picocalc/voltmeter.gif) |
| **Осцилограф** | **Логічний аналізатор** | | |
| ![oscilloscope](docs/gif-picocalc/oscilloscope.gif) | ![logic](docs/gif-picocalc/logic.gif) | | |

*(GIF записані з фреймбуфера PicoCalc 1:1, 320×320, скриптом `tools/record_gif.py`.)*

Ті самі програми на PicoCalc із Zero 2 W під Raspberry Pi OS **Trixie** Lite (32-bit):

- **Дисплей 320×320** (ST7365P, той самий драйвер `panel-mipi-dbi`). Ігри далі рахують у
  координатах 128×128, а `app/lcd.py` малює все в рідній роздільності: прямокутники, лінії, кола
  й шрифти множаться на `lcd.S` = 2.5, тож текст і графіка чіткі, а не розтягнуті. На HAT
  (S = 1) нічого не змінюється.
- **Клавіатура** PicoCalc (драйвер `picocalc_kbd`) працює як звичайна: стрілки, Enter, Esc,
  цифри. Підказки на екрані пишуть «Enter / 2 / Esc» замість «PRESS / KEY2 / KEY3».
  **CapsLock перемикає розкладку US ↔ UA** у консолі та AI-чаті (світлодіод Caps = UA,
  Shift+CapsLock - звичайний Caps Lock).
  **Права Shift** у драйвері PicoCalc вмикає/вимикає режим миші: стрілки тоді рухають курсор і не
  доходять до ігор (ігри й Doom відпускають затиснуті стрілки, щоб нічого не «залипало»). Якщо
  стрілки перестали працювати - натисніть праву Shift ще раз. Бігти в Doom - лівою Shift.
- **Звук** - PWM на GPIO 12/13 (`dtoverlay=audremap,pins_12_13`) у динаміки PicoCalc: ефекти в
  Pong, тетрісі, покері, шахах, преферансі й меню; пункт меню **SOUND** вмикає/вимикає їх, гучність -
  `LCD_VOLUME` у `/etc/default/lcd-toy`. Doom збирається зі звуком через SDL2_mixer.
- **Doom** показує кадр 320×200 один до одного (без зменшення), по центру екрана.
- **AI-чат** - на tty7 шрифтом Terminus 8×16 (40×20 символів).
- **PYTHON / BASIC / EDIT** - консольні інструменти на tty7 шрифтом Terminus 12×6 (53×26 символів),
  після виходу - назад у меню:
  - **PYTHON** - [bpython](https://bpython-interpreter.org/): REPL з підсвіткою, підказками й автодоповненням,
    робоча тека `~/code`; вихід - Ctrl+D;
  - **BASIC** - [MMBasic для Linux](https://github.com/thwill1000/mmb4l) - BASIC рідної прошивки PicoCalc
    (PicoMite), тека `~/basic`; `EDIT` відкриває nano з підсвіткою MMBasic; вихід - `QUIT`;
  - **EDIT** - редактор [micro](https://micro-editor.github.io/) (Ctrl+S, Ctrl+Q, Ctrl+O - відкрити файл),
    за замовчуванням `~/code/scratch.py`.
- **Консолі:** меню працює на tty8 у графічному режимі (щоб ядро нічого не малювало поверх),
  **CONSOLE** відкриває звичайну tty1 з автологіном, `lcdmenu` повертає меню. Пункту HDMI
  немає - він з'являється лише там, де є HDMI-фреймбуфер.

### Встановлення на PicoCalc

1. Raspberry Pi OS Trixie Lite 32-bit, дисплей і клавіатура - за кроками 4-5
   [picocalc_trixie](https://github.com/ironat/picocalc_trixie) (`picomipi.bin`, `picocalc_kbd`).
2. Далі:

```bash
git clone https://github.com/iyalosovetsky/pico2w-toy.git
cd pico2w-toy
./install.sh --device=picocalc   # --no-doom - не збирати Doom
```

`install.sh` перевіряє дисплей і клавіатуру, ставить пакети (разом із SDL2 для звуку Doom),
додає звук у `config.txt`, кладе `/etc/asound.conf` (вихід PWM), `/etc/default/lcd-toy`, збирає
Doom і вмикає сервіси. Що має бути в `config.txt` - див. [`config/picocalc/boot-config.txt`](config/picocalc/boot-config.txt).

### Підводні камені звуку на PicoCalc

- **`dmix` не годиться:** на картці bcm2835 він зависає при закритті пристрою. Тому
  `/etc/asound.conf` дає прямий доступ (`plug` → `hw:Headphones`), а меню звільняє звук на час гри.
- **Не вбивати процес зі звуком:** якщо процес убито, поки звук відкритий, драйвер
  `bcm2835-audio` хвилинами закриває пристрій («failed to close VCHI service connection»).
  Усі програми виходять штатно по SIGTERM, Doom теж (власний обробник → `I_Quit()`).
- **Буфер 2048 семплів на 44100 Гц:** з меншим буфером Python не встигає і сиплються underrun.

### Задня кришка для Zero 2 W

![Задня кришка PicoCalc під Zero 2 W](docs/picocalc-back.png)

Задня кришка PicoCalc 172×103×20 мм під zero mod (Zero 2 W замість Pico):

| Файл | Що це |
|---|---|
| [`case/myPicoCalcZero2wV2.FCStd`](case/myPicoCalcZero2wV2.FCStd) | Модель FreeCAD (тіло `backCase`) |
| [`case/picocalc-zero2w-back.stl`](case/picocalc-zero2w-back.stl) | STL для друку (вивантажено з моделі, точність 0.02 мм) |

## 1. Опис

| Пункт меню | Що це |
|---|---|
| **PONG** | Pong проти комп'ютера, 3 рівні складності, гра до 7 |
| **TETRIS** | Тетріс 10×20: тінь фігури, поворот біля стіни, «мішок» із 7 фігур, рівні, рекорд зберігається |
| **POKER** | Техаський холдем один на один проти AI (Монте-Карло), блайнди ростуть |
| **CHESS** | Шахи проти Stockfish 15 (8 рівнів), відкат ходу, вибір фігури при перетворенні, автозбереження |
| **PREFERANS** | Преферанс проти двох AI: Сочинка (за замовчуванням) або Ленінградка - вибір на старті нової пульки, пулька до 20, автозбереження пульки. Рушій і AI - [Python Pref](https://python-pref.sourceforge.io/index_ru.html) (той самий, що був для Nokia/Symbian), портований на Python 3 |
| **BOOKS** | Читалка книжок EPUB / FB2 / TXT (і в ZIP) та PDF з теки `~/books`: картинки, зміст, розмір шрифту, світла/темна тема; PDF - збільшені фрагменти сторінки й плавна прокрутка; позиція в кожній книжці зберігається |
| **DOOM** | Doom (shareware, 1-й епізод) на [doomgeneric](https://github.com/ozkl/doomgeneric), зменшений до 128×80 |
| **GENERATOR** | Генератор сигналів на окремій платі (PicoCalc, через UART або USB): форма (меандр, синус, трикутник, пила), частота, скважність, увімк/вимк, а також вольтметр і осцилограф на АЦП, логічний аналізатор і декодер I2C / SPI / UART на J703; світлодіод плати показує скважність і частоту - див. [генератор](#компоненти-picocalc) |
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
| `install.sh` | Встановлення «в один крок» (пакети, драйвер, шрифти, сервіси) для HAT або PicoCalc |
| `app/lcd.py` | Спільний шар дисплея та вводу для всіх програм на pygame |
| `app/menu.py` | Меню запуску (список із прокручуванням) |
| `app/pong.py`, `app/tetris.py`, `app/poker.py`, `app/chessgame.py` | Ігри |
| `app/preferans.py` | Інтерфейс преферансу 128×128 для рушія PyPref |
| `app/reader.py`, `app/books.py`, `app/pdfdoc.py` | Читалка: інтерфейс, розбір EPUB / FB2 / TXT / ZIP (FB2 і TXT у будь-якому кодуванні), сторінки PDF через `pdftoppm` |
| `app/prefgame/` | Рушій і AI [Python Pref](https://sourceforge.net/projects/python-pref/) 2.34, портовані на Python 3 (GPL-3.0) |
| `app/ai_chat.py` | Клієнт чату з потоковою відповіддю для llama.cpp / OpenAI-сумісного сервера |
| `app/demo.py` | Мінімальний приклад на pygame: намалювати щось і прочитати кнопки |
| `app/term.sh` | Запуск консольних інструментів PicoCalc: PYTHON (bpython), BASIC (MMBasic), EDIT (micro) |
| `doom/doomgeneric_lcd.c` | Backend для doomgeneric: 320×200 → 128×80 зі згладжуванням, RGB565, кнопки HAT + клавіатура |
| `doom/Makefile.lcd`, `doom/build.sh` | Збирає `app/doom/doomlcd` із зафіксованої версії doomgeneric |
| `firmware/mkpanel.py` | Генерує файл ініціалізації дисплея (`waveshare144.bin`, готова копія теж є) |
| `fonts/` | Консольні шрифти 5×7 (консоль, 25×18 символів) і 6×10 (AI-чат, 21×12) + `build-fonts.sh` |
| `config/` | Усе, що встановлюється в систему: `hat/`, `picocalc/` і спільне - див. [Конфігурація](#6-конфігурація) |
| `tools/` | `vkeys.py` - віртуальна клавіатура, `snap.py` - скриншот, `record_gif.py` - запис GIF |
| `case/` | Корпус: модель FreeCAD (`pico-toy.FCStd`) і STL для друку |
| `docs/` | GIF, фото, схема підключення, перегляд корпусу |

## 2. Керування

| Дія | HAT | USB-клавіатура |
|---|---|---|
| Рух / вибір | джойстик | стрілки |
| Підтвердити / почати | натиск джойстика або KEY1 | Enter / Space |
| Додаткова дія (пауза, складність, ва-банк, меню гри) | KEY2 | 2 |
| Назад у меню | KEY3 | Esc |
| Довідка до пункту головного меню (керування, команди) | KEY1 | F1 |

По іграх:

| Програма | Керування |
|---|---|
| Pong | вгору/вниз - ракетка, Enter - старт/пауза, 2 - складність |
| Тетріс | ←/→ рух, ↓ прискорити, ↑ або Enter поворот, KEY1/Space скинути, 2 пауза |
| Покер | ←/→ вибір FOLD / CHECK-CALL / BET-RAISE, ↑/↓ розмір ставки, 2 - ва-банк |
| Шахи | джойстик рухає курсор, Enter бере / ставить фігуру, 2 - меню (відкат, нова гра) |
| Преферанс | ←/→ карта або заявка, ↑/↓ заявка на рівень вище / нижче, Enter - підтвердити; при зносі Enter відкладає карту, ↓ повертає, Enter ще раз - знести; 2 - запис пульки |
| Книжки | ←/→ (↑/↓, PgUp/PgDn, Space) - сторінки, KEY2 / 2 / Tab - меню (зміст, шрифт, тема), KEY3 / Esc - до бібліотеки; з клавіатури + / - шрифт, Home / End - початок / кінець розділу. PDF: ↑/↓ - сторінка, ←/→ - фрагменти, + / - (KEY1 / KEY2) - масштаб, Enter / натиск - плавна прокрутка стрілками, Esc / KEY3 - назад до фрагментів |
| Doom | HAT: джойстик рух, натиск - постріл (+Enter), KEY1 двері (+«y»), KEY2 наступна зброя, KEY3 меню. Клавіатура: стрілки, Enter або Ctrl постріл (Enter у меню - вибір), Space двері, Alt боком, ліва Shift біг, 1-7 зброя, Tab карта, Esc меню |
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

### Компоненти PicoCalc

| Компонент | Фото | Опис | Документація / магазин |
|---|---|---|---|
| **ClockworkPi PicoCalc** | <img src="docs/picocalc.jpg" width="200"> | Кишеньковий комп’ютер: екран 320×320, клавіатура, динаміки, відсік для акумуляторів; Zero 2 W стоїть замість Pico (zero mod) | [clockworkpi.com](https://www.clockworkpi.com/picocalc) |
| **Raspberry Pi Zero 2 W** | <img src="https://arduino.ua/products_pictures/usa146/large_usa146-1.jpg" width="200"> | Той самий Zero 2 W, що й у версії з HAT | [raspberrypi.com](https://www.raspberrypi.com/products/raspberry-pi-zero-2-w/) |
| **Pololu U3V40F5** | <img src="https://arduino.ua/products_pictures/usa138/large_USA138-8.jpg" width="200"> | Підвищувальний DC-DC перетворювач на 5 В: вхід 1.3-5 В (старт від 2.7 В), до 4 А вхідного струму, 15×15 мм | [arduino.ua](https://arduino.ua/prod5037-povishaushhii-dc-dc-preobrazovatel-5v-u3v40f5-ot-pololu), [pololu.com](https://www.pololu.com/product/4012) |
| **Модуль USB 2.0 Hub FE1.1S** | <img src="https://images.prom.ua/7505726655_w640_h640_modul-usb-20.jpg" width="200"> | USB-хаб 1→4 порти на FE1.1S | [ekran.in.ua](https://ekran.in.ua/ua/p3100872448-modul-usb-hub.html) |
| **Pimoroni Tiny 2350** | <img src="https://cdn.shopify.com/s/files/1/0174/1800/files/tiny2350-oak-1.jpg?v=1723049735" width="200"> | RP2350A (2 ядра 150 МГц, PIO, DMA), 520 КБ SRAM, 4 МБ Flash, 12 GPIO (4 АЦП), RGB-світлодіод, USB Type-C - плата генератора сигналів, вольтметра й осцилографа | [pimoroni.com](https://shop.pimoroni.com/products/tiny-2350) |

**UART до Tiny 2350.** На Zero це стандартний UART `/dev/serial0` (mini UART `ttyS0`, Bluetooth лишається на PL011).
`install.sh --device=picocalc` вмикає його (`enable_uart=1` у `config.txt`) і прибирає з
`cmdline.txt` консоль `console=serial0,115200`, щоб порт був вільний для програм.

**Генератор сигналів** ([`tools/siggen/`](tools/siggen)) - плата Pimoroni Tiny 2350 з MicroPython
([`rp2350.py`](tools/siggen/rp2350.py)), з'єднана із Zero через UART (`/dev/serial0`) або USB
(`/dev/ttyACM*`; команда й застосунок самі знаходять, де вона відповідає). Форми: меандр зі
скважністю, синус, трикутник, пила; вихід **GP6**. ЦАП в RP2350 немає, тож аналоговий сигнал - після
RC-фільтра на виході.

Меандр - апаратний ШІМ, 10 Гц - 10 МГц (нижче - через DMA, від 1 Гц); синус, трикутник і пила - 1 Гц -
20 кГц: ШІМ 586 кГц (8 біт), скважність якого канал DMA бере з таблиці форми, тактований таймером
DMA (150 МГц·X/Y) - частота точна, процесор вільний. Фільтр, напр. 1 кОм + 4,7 нФ. Ніжки - у таблиці
нижче. Світлодіод RGB (GP18-20) показує частоту кольором і скважність яскравістю. На RP2350A GP16-31
ділять слайси ШІМ із GP0-15 (світлодіод - слайси 1 і 2), тому вихід на GP6 (слайс 3).

**Розводка Tiny 2350 у PicoCalc.** UART - до Zero, решта - на зовнішній роз'єм **J703** PicoCalc.
Роз'єм - на **лівому** боці корпусу (якщо дивитися на екран), на рівні екрана: верхній із двох рядів
по 8 контактів (нижній - J702: UART0/UART1/USB головної плати); пін 1 (3V3_OUT) - найвищий, пін 8 (GND) -
найнижчий (за шовкографією Gerber-файлів головної плати V2.0). Його лінії йдуть на гніздо Pico головної плати (номери RP2040 і пінів Pico - за
[схемою PicoCalc V2.0](https://github.com/clockworkpi/PicoCalc/blob/master/clockwork_Mainboard_V2.0_Schematic.pdf));
у zero mod вони не з'єднані із Zero (перевірте тестером у своїй розводці).

| Tiny 2350 | Куди | RP2040 (Pico) за схемою PicoCalc | Призначення |
|---|---|---|---|
| GP0 (UART0 TX) | Zero GPIO 15 / RXD, пін 10 | — | UART до Zero (`/dev/serial0`) |
| GP1 (UART0 RX) | Zero GPIO 14 / TXD, пін 8 | — | UART до Zero |
| GND | Zero GND, пін 6 | — | спільна земля |
| 5V (VBUS) | 5 В від Pololu U3V40F5 | — | живлення |
| USB-C | порт 3 USB-хаба FE1.1S | — | USB (`/dev/ttyACM0`): заливка програми, запасний канал |
| — | J703.1 | 3V3_OUT (AXP2101) | 3,3 В для зовнішніх модулів |
| **GP6** | J703.2 | **GP2**, пін 4 (J302) · PSRAM SIO0 | вихід генератора |
| GP3 | J703.3 | **GP3**, пін 5 (J302) · PSRAM SIO1 | SPI0 TX (MOSI) |
| GP4 | J703.4 | **GP4**, пін 6 (J302) · PSRAM SIO2 | SPI0 RX (MISO) / I2C0 SDA / UART1 TX |
| GP5 | J703.5 | **GP5**, пін 7 (J302) · PSRAM SIO3 | SPI0 CS / I2C0 SCL / UART1 RX |
| GP2 | J703.6 | **GP21**, пін 27 (J301) · PSRAM SCLK | SPI0 SCK |
| GP26 | J703.7 | **GP28**, пін 34 (J301) | АЦП, 0-3,3 В |
| GND | J703.8 | GND | земля |

На лініях GP2-GP5 і GP21 сидить PSRAM головної плати (U301); її вибір CE - GP20 (пін 26) з
підтяжкою 10 кОм до 3,3 В, тож поки GP20 ні до чого не під'єднаний, PSRAM неактивна і лініям не
заважає. Логіка лише 3,3 В; на сигнальні лінії J703 варто поставити послідовні резистори 100-220 Ом.
Через PIO будь-яку з ліній можна перепризначити (I2S, UART, 1-Wire…).

Живлення: VSYS гнізда Pico (пін 39) → підвищувальний Pololu U3V40F5 → 5 В на Zero (пін 2/4), на
USB-хаб FE1.1S і на пін 5V Tiny 2350; хаб сидить на USB Zero, на його порту 1 - приймач клавіатури, на порту 3 - Tiny 2350.

![Схема: Zero 2 W, Tiny 2350, Pololu, USB-хаб і J703 PicoCalc](docs/wiring-picocalc.svg)

У пункті меню GENERATOR є ще три режими (перший рядок «Режим»). Вольтметр і осцилограф - на вході АЦП
плати (J703.7):
- **вольтметр** - напруга, мін / макс і графік за 10 с;
- **осцилограф** (RP2350) - 256 точок за розгортку, від 100 мкс до 50 мс на поділку, синхронізація по
  фронту через заданий рівень, частота й розмах, пауза. АЦП працює на ~500 тис. вимірів/с, а кожна точка -
  середнє вимірів за свій інтервал (як режим «high-res»), тож ШІМ синуса / трикутника видно як форму й
  без RC-фільтра.

і **логічний аналізатор** - шість ліній J703 (2-7 = GP6 GP3 GP4 GP5 GP2 GP26, J703.2 - вихід самого
генератора): автомат PIO RP2350 щотакту знімає всі GPIO, DMA пише їх у пам'ять (до 25 млн вибірок/с),
512 вибірок за розгортку, від 5 мкс до 20 мс на поділку, синхронізація по фронту обраної лінії, її
частота і скважність, пауза; а **декодер I2C / SPI / UART** - плата чекає на перший фронт протоколу,
знімає 32768 вибірок тими ж PIO + DMA і сама їх розбирає: UART 8N1 (RX - J703.4), I2C (SDA - J703.4,
SCL - J703.5: START, адреса R/W, байти, ACK/NACK, STOP), SPI режими 0-3 (SCK .6, MOSI .3, MISO .4,
CS .5). Джерело «тест» - плата сама шле трафік своїми апаратними UART / I2C / SPI на ці ж лінії.

Генератор тим часом працює, тож його вихід можна подати на вхід і побачити форму.

Керування із Zero - пункт меню GENERATOR або команда `siggen` (її ставить `install.sh`):

```bash
siggen shape sine freq 2.5k  # форма (square sine triangle saw) і частота (Гц, k, M)
siggen shape square duty 25  # меандр, скважність (%)
siggen off                   # вимкнути вихід; on - увімкнути
siggen get                   # ok board=rp2350 shape=square freq=2500 duty=25 out=on fmin=1 fmax=10000000
siggen probe                 # плата читає свій вихід: середній рівень у десяти відрізках по 0,1 с
siggen adc                   # напруга на входах АЦП (RP2350: GP26 = J703.7, GP27-29)
siggen scope 25.6k 1.6       # одне захоплення осцилографа: частота вибірок, рівень синхронізації (В)
siggen logic 1M 0            # одне захоплення логічного аналізатора: частота вибірок, канал синхронізації
siggen decode uart 9600 test # декодер UART / I2C / SPI (test - плата сама шле трафік)
siggen flash tools/siggen/rp2350.py   # оновити програму на платі через UART або USB
```

Перший раз - через USB: на RP2350 спершу MicroPython (затиснути BOOT, підключити - з'явиться диск
RP2350, скопіювати на нього UF2 з [micropython.org](https://micropython.org/download/RPI_PICO2/)), далі
`python3 tools/siggen/mpy_put.py /dev/ttyACM0 tools/siggen/rp2350.py:main.py`.

## 4. Схема

![Схема](docs/wiring.svg)

LCD HAT використовує SPI0 (CE0) і GPIO 25/27/24 для DC/reset/підсвітки; джойстик і кнопки - на
GPIO 6, 19, 5, 26, 13, 21, 20, 16 (активний низький рівень, внутрішня підтяжка). Вручну паяти треба
лише живлення.

### Корпус

![Корпус](docs/case.png)

Корпус для друку - у папці [`case/`](case):

| Файл | Що це |
|---|---|
| `pico-toy.FCStd` | Модель FreeCAD (V2, без сітки-скану пристрою, з якої робився корпус) |
| `pico-toy-base.stl` | Основа: коробка 37×40×68 мм, у яку ставиться стек плат |
| `pico-toy-leftFall.stl` | Бічна рамка 39×40×14 мм |

Кришки для дисплея ще немає - вона в розробці. STL вивантажені з моделі FreeCAD (точність 0.02 мм). Перша версія без корпусу:
[`docs/prototype-v1.jpg`](docs/prototype-v1.jpg).

## 5. Встановлення

Для HAT нижче; для PicoCalc - [Встановлення на PicoCalc](#встановлення-на-picocalc).
Перевірено на Raspbian 12 (Bookworm) armhf, ядро 6.12, Pi Zero 2 W.

```bash
git clone https://github.com/iyalosovetsky/pico2w-toy.git
cd pico2w-toy
./install.sh --device=hat   # без --device пристрій визначається сам (або спитає)
                            # --no-doom - не збирати Doom, --keep-desktop - не вимикати робочий стіл,
                            # --hdmi-mode=1280x720@60 - інший режим HDMI
sudo reboot           # лише при першому встановленні: завантажити драйвер дисплея
```

`install.sh` запускається від звичайного користувача (із sudo), від якого працюватиме меню. Він:

1. ставить `python3-pygame python3-numpy python3-pil stockfish doom-wad-shareware git build-essential`;
2. кладе [python-chess](https://github.com/niklasf/python-chess) в `app/vendor` (у репозиторії Raspbian її немає);
3. записує `/lib/firmware/waveshare144.bin` і дописує `config/hat/boot-config.txt` у `/boot/firmware/config.txt`;
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

Уся системна конфігурація лежить у [`config/`](config): спільні `ai-chat.env` і `lcdmenu`, а файли
пристроїв - у [`config/hat/`](config/hat) (таблиця нижче) і [`config/picocalc/`](config/picocalc)
(`boot-config.txt` для довідки, `keyboard` з перемиканням CapsLock, `asound.conf`, `lcd-toy.env`,
`lcd-vt` і сервіси під tty1/tty7/tty8).

Файли HAT (`config/hat/`):

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
