# Changelog

## 1.0.0 — 2026-10-23

Первый публичный релиз HyperMix для Linux и Windows.

### Возможности
- Библиотека звуков WAV/MP3/OGG/FLAC и воспроизведение с горячих клавиш.
- Режимы вывода `[SPK]` / `[MIC]` / `[BOTH]`.
- Виртуальный микрофон:
  - Linux — `HyperMix_Mic` (PipeWire/PulseAudio, null-sink + loopback);
  - Windows — VB-Audio Cable (`CABLE Input` → `CABLE Output`).
- Автоматическое подмешивание голоса реального микрофона:
  - Linux — `module-loopback`;
  - Windows — встроенный микшер на `sounddevice`.
- Выбор микрофона кнопкой `[Источник]` на обеих ОС.
- Глобальные клавиши и боковые кнопки мыши:
  - Linux — `/dev/input` (evdev), резерв — KGlobalAccel;
  - Windows — `pynput`.
- Темы Light / Dark / Hacker, анимация «Матрица».
- Портативный `config.json` рядом с приложением.
- Портативные сборки: Linux tar.gz и Windows ZIP с exe.

### Известные требования
- Linux: `pactl`, права на `/dev/input` для глобальных клавиш.
- Windows: установленный VB-Audio Cable, разрешение доступа к микрофону.
