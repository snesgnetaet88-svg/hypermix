<p align="center">
  <img src="assets/hypermix.png" width="112" alt="HyperMix">
</p>

<h1 align="center">HyperMix</h1>

<p align="center">
  <b>Портативная звуковая панель с виртуальным микрофоном и глобальными горячими клавишами для Linux и Windows.</b>
</p>

<p align="center">
  <a href="https://github.com/snesgnetaet88-svg/hypermix/releases/latest">
    <img alt="Последний релиз" src="https://img.shields.io/github/v/release/snesgnetaet88-svg/hypermix?style=flat-square&label=release">
  </a>
  <img alt="Платформы" src="https://img.shields.io/badge/platform-Linux%20%7C%20Windows-2ea44f?style=flat-square">
  <a href="LICENSE">
    <img alt="Лицензия MIT" src="https://img.shields.io/github/license/snesgnetaet88-svg/hypermix?style=flat-square">
  </a>
</p>

**HyperMix** — программа для быстрого воспроизведения звуков с горячими клавишами
и маршрутизацией звука в виртуальный микрофон (для стримов, Discord и т.д.).
Работает портативно: без установки, настройки хранятся рядом с приложением.

> Название **HyperMix** выбрано специально, чтобы избежать ложных срабатываний антивирусов.

**[Скачать последний релиз](https://github.com/snesgnetaet88-svg/hypermix/releases/latest)** ·
[Linux](#linux--запуск) · [Windows](#windows--запуск) · [Сборка](#сборка-из-исходников)

---

## Релиз 1.0.0

| ОС | Файл | Что внутри |
|----|------|------------|
| Linux x86_64 | `HyperMix-1.0.0-Linux-x86_64.tar.gz` | готовый бинарник, `config.json`, README |
| Windows 10/11 x86_64 | `HyperMix-1.0.0-Windows-x86_64.zip` | готовый `HyperMix.exe`, `config.json`, README |
| Исходники | `HyperMix-1.0.0-source.tar.gz` | весь код и скрипты сборки |
| Windows build-kit | `HyperMix-1.0.0-Windows-build-kit.zip` | опционально: сборка exe на Windows |

Windows `.exe` собирается автоматически в GitHub Actions (workflow
**Build release**) и проверяется smoke-тестом. Локальная сборка на Windows:
`build_windows.bat` → `release\HyperMix-1.0.0-Windows-x86_64.zip`.

Проверка целостности:
```bash
sha256sum -c SHA256SUMS
```

### Linux — запуск

```bash
tar -xzf HyperMix-1.0.0-Linux-x86_64.tar.gz
cd HyperMix-1.0.0-Linux-x86_64
./HyperMix
```

Нужны `pactl` (PipeWire/PulseAudio) и права на `/dev/input` для глобальных
клавиш. Установка не требуется. Для автозапуска можно скопировать
`hypermix.desktop` в `~/.local/share/applications/` (при необходимости
поправьте путь в `Exec=`).

На Debian/Ubuntu могут понадобиться системные библиотеки Qt:
```bash
sudo apt install libxcb-cursor0 libxkbcommon-x11-0 libegl1 libgl1 libpulse0
```

### Windows — запуск

1. Скачайте `HyperMix-1.0.0-Windows-x86_64.zip` из последнего релиза.
2. Распакуйте в любую папку.
3. Установите **VB-Cable**: https://vb-audio.com/Cable/ и перезагрузитесь.
4. Запустите `HyperMix.exe`.
5. В Discord/игре выберите микрофон **CABLE Output**.

`HyperMix.exe` не требует Python и установки. SmartScreen может показать
предупреждение об неизвестном издателе — нажмите «Подробнее» → «Выполнить
в любом случае» (сборка не подписана платным сертификатом).

### Сборка из исходников

Linux:
```bash
./build_linux.sh
# → release/HyperMix-1.0.0-Linux-x86_64.tar.gz
```

Windows (собирать **на Windows**):
```bat
build_windows.bat
:: → release\HyperMix-1.0.0-Windows-x86_64.zip
```

---

## Возможности

- Библиотека звуков: WAV, MP3 (конвертируется в WAV), OGG, FLAC
- Глобальные горячие клавиши для мгновенного запуска звуков
- Режимы вывода: **[SPK]** динамики / **[MIC]** микрофон / **[BOTH]** оба
- Голос с микрофона автоматически подмешивается в виртуальный микрофон
  (Linux — loopback, Windows — встроенный микшер)
- 3 темы оформления: **Light**, **Dark** (оранжевый акцент), **Hacker** (зелёный + матрица)
- Анимация «Матрица» (падающие 0/1) на фоне — только в теме Hacker
- Компактный минималистичный интерфейс, моноширинный шрифт
- Выбор темы: меню **Настройки → Тема** (сохраняется в `config.json`)

---

## Установка

### Linux — ничего устанавливать не нужно

Виртуальный микрофон **HyperMix_Mic** создаётся автоматически при запуске
через `pactl` (PipeWire/PulseAudio) и выгружается при закрытии.

```bash
# Запуск
./run.sh

# Или вручную
python3 main.py
```

Зависимости:
```bash
pip install -r requirements-linux.txt
# PyQt6, pygame-ce, pydub, dbus-next, audioop-lts (Python 3.13+)
```

Глобальные горячие клавиши на Linux работают через прямое чтение
`/dev/input/event*` (нужен доступ: группа `input` или udev-правило).
Если доступа нет — автоматический откат на KGlobalAccel.

### Windows — нужен бесплатный драйвер VB-Audio Cable

1. Скачайте и установите **VB-Cable**: https://vb-audio.com/Cable/
   (страница откроется автоматически при первом запуске, если драйвера нет).
2. Перезапустите Windows.
3. Запустите HyperMix — устройство **CABLE Input** будет обнаружено автоматически.
4. В Discord/игре выберите микрофон **CABLE Output (VB-Audio Virtual Cable)**.

Звук панели выводится напрямую: `[SPK]` — в колонки, `[MIC]` — в
`CABLE Input`, `[BOTH]` — одновременно в колонки и `CABLE Input`.
Системное устройство по умолчанию при этом не меняется.

Горячие клавиши и боковые кнопки мыши работают через `pynput`
(без прав администратора). ЛКМ/ПКМ не биндятся.

Зависимости для запуска из исходников:
```bat
pip install PyQt6 pygame-ce sounddevice soundfile numpy pynput pydub
python main.py
```

Сборка exe:
```bat
build_windows.bat
```
Скрипт сам установит зависимости и соберёт
`release\HyperMix-1.0.0-Windows-x86_64.zip` (внутри — `HyperMix.exe`).

> **Важно:** HyperMix **не устанавливает** драйверы скрытно.

---

## Использование

1. **[+ ADD]** — добавьте аудиофайлы.
2. Выберите строку → **[PLAY]** (или двойной клик по строке).
3. Горячая клавиша: **двойной клик по колонке «Клавиша»** → ввод.
4. Режим вывода: **[SPK]** / **[MIC]** / **[BOTH]**.
5. Микрофон для голоса: **[Источник]** (Linux и Windows).
6. Тема: меню **Настройки → Тема → Light / Dark / Hacker**.
7. **[STOP]** — остановить.

Настройки (тема, библиотека, горячие клавиши) сохраняются в `config.json`
рядом с `main.py`, а в собранном Windows-exe — рядом с `HyperMix.exe`.

В консоль при воспроизведении выводится `PLAY: <имя файла>` —
если лог есть, а звука нет, проблема в аудиодрайвере.

---

## Структура проекта

```
hypermix/
├── main.py                      # точка входа
├── config.json                  # тема, звуки, горячие клавиши (не входит в релиз)
├── VERSION                      # версия релиза
├── build_linux.sh               # сборка Linux tar.gz
├── build_windows.bat            # сборка Windows ZIP с exe
├── run.sh                       # запуск Linux
├── packaging/                   # config.default.json, version_info, desktop
└── hypermix/
    ├── paths.py                 # путь к config.json (рядом с exe в сборке)
    ├── ui/
    │   ├── main_window.py       # главное окно
    │   └── themes.py            # 3 темы + MatrixWidget
    ├── audio/
    │   ├── engine.py            # Linux: pygame + pactl; Windows: sounddevice
    │   ├── hotkeys.py           # выбор бэкенда глобальных клавиш
    │   ├── evdev_hotkeys.py     # Linux: /dev/input (клавиши + мышь)
    │   └── windows_hotkeys.py   # Windows: pynput (клавиши + мышь)
    └── platform/
        ├── linux_audio.py       # виртуальный микрофон HyperMix_Mic
        ├── windows_cable.py     # VB-Audio Cable
        └── manager.py           # менеджер платформ
```

---

## Виртуальный микрофон

| ОС | Механизм | Устройство |
|----|----------|------------|
| Linux | `pactl load-module module-null-sink sink_name=HyperMix_Mic` | `HyperMix_Mic.monitor` |
| Windows | VB-Audio Cable, вывод через `sounddevice` | `CABLE Input` → `CABLE Output` |

Настройка Discord:

- **Микрофон (вход):** `Monitor of HyperMix` на Linux или `CABLE Output` на Windows.
- **Устройство вывода:** ваши наушники/колонки. **Не выбирайте** `HyperMix`
  или `CABLE Input` как выход — иначе звук Discord/демонстрации экрана
  попадёт обратно в виртуальный микрофон.
- **Режим HyperMix:** `[MIC]` или `[BOTH]`. В режиме `[SPK]` звуки панели
  идут только в колонки и в Discord не передаются.

Linux: в режиме **[MIC]** / **[BOTH]** звук направляется через
`pactl move-sink-input <stream_id> <virtual_id>` сразу после `.play()`.

Windows: звук сразу выводится на `CABLE Input`; в Discord выберите
**CABLE Output** как микрофон.

### Голос на Windows

HyperMix сам захватывает системный микрофон и подмешивает ваш голос в
`CABLE Input` — вместе со звуками панели. В Discord достаточно выбрать
**CABLE Output**; отдельное «прослушивание» в Windows не нужно.

- Другой микрофон: кнопка **[Источник]** — выбор сохраняется в
  `config.json` (`windows_voice_source`).
- Если статус показывает «голос не найден», разрешите доступ:
  **Параметры → Конфиденциальность → Микрофон → Разрешить классическим
  приложениям доступ к микрофону**.

> Не включайте одновременно **«Прослушивать с данного устройства»** в
> свойствах микрофона — голос попадёт в кабель дважды (эхо).

Альтернатива для сложного микса — VoiceMeeter, но для Discord достаточно
встроенного микшера HyperMix.

---

## Лицензия

MIT License. Бесплатно для личного и коммерческого использования.
