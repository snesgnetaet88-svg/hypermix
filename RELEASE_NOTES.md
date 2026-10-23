# HyperMix 1.0.1

Исправляющий релиз. Дата: 23 октября 2026.

Главное изменение: на Linux Discord теперь видит обычный микрофон
**HyperMix_Microphone**, а не monitor-источник. Это исправляет выбор
устройства ввода и передачу звуков панели вместе с голосом.

HyperMix — портативная звуковая панель с глобальными горячими клавишами и
виртуальным микрофоном. Звуки панели и голос с реального микрофона
смешиваются автоматически — в Discord или игре достаточно выбрать один
виртуальный микрофон.

## Артефакты

| Файл | Назначение |
|------|------------|
| `HyperMix-1.0.1-Linux-x86_64.tar.gz` | готовый Linux-бинарник |
| `HyperMix-1.0.1-Windows-x86_64.zip` | готовый Windows exe |
| `HyperMix-1.0.1-source.tar.gz` | исходники релиза |
| `HyperMix-1.0.1-Windows-build-kit.zip` | опционально: сборка exe на Windows |
| `SHA256SUMS` | контрольные суммы |

Проверка:
```bash
sha256sum -c SHA256SUMS
```

## Linux

```bash
tar -xzf HyperMix-1.0.1-Linux-x86_64.tar.gz
cd HyperMix-1.0.1-Linux-x86_64
./HyperMix
```

- Установка не требуется; Python внутри сборки.
- Нужен `pactl` (PipeWire или PulseAudio).
- Глобальные клавиши читают `/dev/input/event*`: добавьте пользователя в
  группу `input` или установите udev-правило. Без доступа используется
  KGlobalAccel.
- Виртуальный микрофон `HyperMix_Microphone` (внутри `HyperMix_Mic`)
  создаётся при запуске и удаляется при закрытии.
- В Discord выберите вход **HyperMix_Microphone** (не `Monitor of HyperMix`).
- Сборка сделана в GitHub Actions на Ubuntu 22.04 (glibc 2.35).
  На Ubuntu 20.04 и старше используйте исходники и `./build_linux.sh`.

## Windows

1. Скачайте `HyperMix-1.0.1-Windows-x86_64.zip` и распакуйте в любую папку.
2. Запустите `HyperMix.exe` — Python и установка не нужны.

Сборка автоматизирована в GitHub Actions; локально на Windows можно
запустить `build_windows.bat`.

Для работы:
- установите VB-Audio Cable: https://vb-audio.com/Cable/
- перезагрузите Windows;
- в Discord/игре выберите микрофон **CABLE Output**;
- при необходимости разрешите доступ к микрофону в параметрах Windows.

Голос подмешивается в `CABLE Input` встроенным микшером HyperMix;
включать «Прослушивать с данного устройства» не нужно — будет эхо.

## Что нового в 1.0.1

- Добавлен обычный capture-источник `HyperMix_Microphone` (`module-remap-source`).
- Discord на Linux корректно выбирает его как микрофон; звуки панели и голос
  идут в него, системный звук не захватывается.
- `[Источник]` показывает реальный микрофон, а не виртуальный источник.

## Возможности

- Звуковая панель: WAV, MP3, OGG, FLAC; глобальные клавиши и боковые кнопки мыши.
- Режимы `[SPK]` / `[MIC]` / `[BOTH]`.
- Linux: `HyperMix_Mic` + loopback + `HyperMix_Microphone` для Discord,
  evdev с откатом на KGlobalAccel.
- Windows: VB-Cable, `sounddevice`, автоматический микс голоса, выбор микрофона.
- Темы Light / Dark / Hacker с анимацией «Матрица».
- Портативный `config.json` рядом с приложением.
- `HyperMix --version`, `--check`, `--send` для диагностики и интеграций.

## Известные ограничения

- Windows-сборка не подписана сертификатом: SmartScreen может показать
  предупреждение. Выберите «Подробнее» → «Выполнить в любом случае».
- Windows exe прошёл автоматический smoke-тест (`--check`), но не проверялся
  на реальном VB-Cable и микрофоне в этом окружении.
- Для Linux-бинарника нужна glibc 2.35 или новее (Ubuntu 22.04+, Debian 12+,
  Arch, Fedora 36+).

## Лицензия

MIT. См. `LICENSE`.
