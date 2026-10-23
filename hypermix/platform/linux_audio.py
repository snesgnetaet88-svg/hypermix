# HyperMix — модуль Linux-подсистемы
# ЭТАП 3: автоматический виртуальный микрофон через PipeWire/PulseAudio
#
# Принцип:
#   1. Проверяем наличие sink'а "HyperMix_Mic" (pactl list short sinks).
#   2. Если нет — создаём: pactl load-module module-null-sink sink_name=HyperMix_Mic
#   3. Подмешиваем РЕАЛЬНЫЙ микрофон в HyperMix_Mic (module-loopback),
#      чтобы в виртуальном микрофоне был слышен голос говорящего + звуки панели.
#   4. Делаем HyperMix_Mic.monitor источником (микрофоном) по умолчанию,
#      чтобы программы автоматически его использовали при запуске.
#   5. При закрытии приложения выгружаем созданные модули (pactl unload-module).
#   6. Режим «Микрофон» направляет канал воспроизведения в HyperMix_Mic
#      через перемещение sink-input (патч-пайплайн PulseAudio/PipeWire).

import os
import shutil
import subprocess
from pathlib import Path

# Имя виртуального sink'а (null-sink) — микрофон для остальных программ
VIRTUAL_SINK = "HyperMix_Mic"
# Источник (source) виртуального микрофона, который слушают программы
VIRTUAL_SOURCE = "HyperMix_Mic.monitor"
SINK_DESCRIPTION = "HyperMix Virtual Microphone"
# Файл, где запоминаем РЕАЛЬНЫЙ микрофон пользователя: после перезапуска
# default source уже указывает на виртуальный мик, и без этого мы
# подмешали бы произвольный микрофон вместо того, в который говорят.
VOICE_SOURCE_FILE = Path(
    os.environ.get("XDG_CONFIG_HOME") or (Path.home() / ".config")
) / "hypermix" / "voice-source"


def is_linux() -> bool:
    return os.name == "posix" and not sys_is_darwin()


def sys_is_darwin() -> bool:
    return shutil.mac_ver()[0] != ""


def _run(args: list[str], timeout: float = 10.0) -> subprocess.CompletedProcess:
    """Запуск внешней команды (pactl) с подавлением исключений."""
    try:
        return subprocess.run(args, capture_output=True, text=True, timeout=timeout)
    except (FileNotFoundError, subprocess.TimeoutExpired) as e:
        return subprocess.CompletedProcess(args, returncode=127, stdout="", stderr=str(e))


def _module_args(line: str) -> str:
    """
    Достаёт аргументы модуля из строки `pactl list short modules`.
    Формат строки: id \\t имя-модуля \\t аргументы \\t
    """
    parts = line.split("\t")
    return parts[2] if len(parts) >= 3 else ""


def pactl_available() -> bool:
    """Есть ли pactl в PATH (PipeWire с pulse-совместимостью или PulseAudio)."""
    return shutil.which("pactl") is not None


def list_sinks() -> list[str]:
    """Возвращает список имён всех sink'ов системы."""
    if not pactl_available():
        return []
    res = _run(["pactl", "list", "short", "sinks"])
    if res.returncode != 0:
        return []
    sinks = []
    for line in res.stdout.splitlines():
        parts = line.split("\t")
        if len(parts) >= 2:
            sinks.append(parts[1])
    return sinks


def virtual_sink_exists() -> bool:
    """Проверяет, существует ли уже HyperMix_Mic."""
    return VIRTUAL_SINK in list_sinks()


def create_virtual_sink() -> bool:
    """
    Создаёт виртуальный sink HyperMix_Mic (модуль module-null-sink).
    Возвращает True, если sink создан или уже существовал.
    """
    if virtual_sink_exists():
        return True
    if not pactl_available():
        return False
    res = _run([
        "pactl", "load-module", "module-null-sink",
        f"sink_name={VIRTUAL_SINK}",
        f"sink_properties=device.description={SINK_DESCRIPTION}",
    ])
    if res.returncode != 0:
        # Повторная проверка: возможно, создали параллельно
        return virtual_sink_exists()
    return True


def destroy_virtual_sink() -> bool:
    """
    Выгружает модуль null-sink, созданный нами.
    Ищем id модуля по имени sink'а и вызываем pactl unload-module.
    """
    if not pactl_available():
        return False
    # Метод 1: найти sink и определить, каким модульным id он создан
    res = _run(["pactl", "list", "short", "modules"])
    module_id = None
    if res.returncode == 0:
        for line in res.stdout.splitlines():
            if "module-null-sink" in line and f"sink_name={VIRTUAL_SINK}" in _module_args(line):
                module_id = line.split("\t")[0].strip()
                break
    if module_id is not None:
        unload = _run(["pactl", "unload-module", module_id])
        return unload.returncode == 0
    # Метод 2 (запасной): уничтожить сам sink, если модуль найти не удалось
    _run(["pactl", "unload-module", "module-null-sink"])
    return not virtual_sink_exists()


# ----------------------------------------------------------------------
# Источники (микрофоны) и подмешивание голоса
# ----------------------------------------------------------------------

def list_sources() -> list[str]:
    """Возвращает список имён всех источников (микрофонов)."""
    if not pactl_available():
        return []
    res = _run(["pactl", "list", "short", "sources"])
    if res.returncode != 0:
        return []
    out = []
    for line in res.stdout.splitlines():
        parts = line.split("\t")
        if len(parts) >= 2:
            out.append(parts[1])
    return out


def get_default_source() -> str:
    """Имя текущего микрофона по умолчанию ('' если нет)."""
    if not pactl_available():
        return ""
    res = _run(["pactl", "get-default-source"])
    return res.stdout.strip() if res.returncode == 0 else ""


def real_capture_sources() -> list[str]:
    """
    Реальные микрофоны (без .monitor) — источники, с которых можно
    снимать голос говорящего.
    """
    return [s for s in list_sources() if not s.endswith(".monitor")]


def is_real_capture_source(name: str) -> bool:
    """Проверяет, что источник — реальный микрофон (а не monitor/виртуальный)."""
    if not name or name.endswith(".monitor"):
        return False
    # наш собственный виртуальный микрофон исключаем (иначе петля)
    if name.startswith(VIRTUAL_SINK):
        return False
    return name in real_capture_sources()


def voice_loopback_exists() -> bool:
    """Есть ли уже загруженный module-loopback в HyperMix_Mic."""
    return bool(voice_loopback_source())


def voice_loopback_source() -> str:
    """Источник, из которого сейчас заливается голос в HyperMix_Mic ('' — нет)."""
    if not pactl_available():
        return ""
    res = _run(["pactl", "list", "short", "modules"])
    if res.returncode != 0:
        return ""
    for line in res.stdout.splitlines():
        if "module-loopback" in line and f"sink={VIRTUAL_SINK}" in _module_args(line):
            args = _module_args(line)
            for part in args.split():
                if part.startswith("source="):
                    return part[len("source="):].strip()
    return ""


def pick_voice_source() -> str:
    """
    Выбирает РЕАЛЬНЫЙ микрофон, голос из которого нужно подмешать в
    виртуальный HyperMix_Mic.

    Порядок приоритета:
      1) текущий микрофон по умолчанию, если он реальный (пользователь выбрал сам);
      2) микрофон, сохранённый при прошлом запуске (после перезапуска
         default уже указывает на виртуальный мик);
      3) любой доступный реальный микрофон.
    """
    cur = get_default_source()
    if is_real_capture_source(cur):
        _save_voice_source(cur)
        return cur
    saved = _load_saved_voice_source()
    if saved and is_real_capture_source(saved):
        print(f"VOICE: используем сохранённый микрофон {saved}")
        return saved
    real = real_capture_sources()
    if real:
        print(f"VOICE: fallback на реальный микрофон {real[0]}")
        return real[0]
    return ""


def _load_saved_voice_source() -> str:
    try:
        if VOICE_SOURCE_FILE.exists():
            s = VOICE_SOURCE_FILE.read_text(encoding="utf-8").strip()
            return s
    except Exception:
        pass
    return ""


def _save_voice_source(source: str) -> None:
    try:
        VOICE_SOURCE_FILE.parent.mkdir(parents=True, exist_ok=True)
        VOICE_SOURCE_FILE.write_text(source.strip(), encoding="utf-8")
    except Exception:
        pass


def clear_saved_voice_source() -> None:
    try:
        if VOICE_SOURCE_FILE.exists():
            VOICE_SOURCE_FILE.unlink()
    except Exception:
        pass


def ensure_voice_loopback(source: str = "") -> bool:
    """
    Подмешивает РЕАЛЬНЫЙ микрофон в виртуальный HyperMix_Mic, чтобы
    в нём был слышен голос говорящего ВМЕСТЕ со звуками панели.

    source: имя реального микрофона; если пусто — берётся сохранённый
    или текущий реальный микрофон.
    """
    if not pactl_available() or not virtual_sink_exists():
        return False
    if not source:
        source = _load_saved_voice_source() or get_default_source()
    if not is_real_capture_source(source):
        print(f"VOICE: источник '{source}' не является реальным микрофоном — пробуем поиск")
        real = real_capture_sources()
        if not real:
            print("VOICE: нет реальных микрофонов для подмешивания")
            return False
        source = real[0]
        print(f"VOICE: fallback на {source}")
    if voice_loopback_exists():
        current = voice_loopback_source()
        if current == source:
            _save_voice_source(source)
            return True
        # loopback уже есть, но из другого микрофона — переподключаем
        print(f"VOICE: loopback переключается {current} -> {source}")
        destroy_voice_loopback()
    res = _run([
        "pactl", "load-module", "module-loopback",
        f"source={source}",
        f"sink={VIRTUAL_SINK}",
        # 20 мс вместо дефолтных 200 — иначе голос в микрофоне запаздывает
        "latency_msec=20",
        # не даём loopback «убежать» за default-устройством (им станет
        # наш же HyperMix_Mic.monitor — получилась бы петля без голоса)
        "source_dont_move=true",
        "sink_dont_move=true",
    ])
    ok = res.returncode == 0 or voice_loopback_exists()
    print(f"VOICE: loopback {source} -> {VIRTUAL_SINK}: {'OK' if ok else 'FAIL'}")
    if ok:
        _save_voice_source(source)
    return ok


def destroy_voice_loopback() -> bool:
    """Выгружает module-loopback, который подмешивал голос в HyperMix_Mic."""
    if not pactl_available():
        return False
    res = _run(["pactl", "list", "short", "modules"])
    if res.returncode != 0:
        return False
    removed = False
    for line in res.stdout.splitlines():
        if "module-loopback" in line and f"sink={VIRTUAL_SINK}" in _module_args(line):
            module_id = line.split("\t")[0].strip()
            _run(["pactl", "unload-module", module_id])
            removed = True
    if removed:
        print("VOICE: loopback выгружен")
    return removed


def set_default_source(source: str) -> bool:
    """Делает источник (микрофон) текущим по умолчанию."""
    if not pactl_available() or not source:
        return False
    res = _run(["pactl", "set-default-source", source])
    ok = res.returncode == 0
    if ok:
        print(f"DEFAULT-SOURCE: {source}")
    else:
        print(f"DEFAULT-SOURCE: не удалось переключить на {source}: {res.stderr.strip()}")
    return ok


def get_default_sink() -> str:
    """Имя текущего устройства вывода по умолчанию."""
    if not pactl_available():
        return ""
    res = _run(["pactl", "get-default-sink"])
    return res.stdout.strip() if res.returncode == 0 else ""


def list_sink_inputs() -> dict[int, str]:
    """Возвращает {sink_input_id: sink_name} — какие потоки куда направлены."""
    if not pactl_available():
        return {}
    res = _run(["pactl", "list", "short", "sink-inputs"])
    inputs: dict[int, str] = {}
    if res.returncode != 0:
        return inputs
    for line in res.stdout.splitlines():
        parts = line.split("\t")
        if len(parts) >= 3:
            try:
                inputs[int(parts[0])] = parts[2]  # текущий sink
            except ValueError:
                continue
    return inputs


def move_to_virtual_sink(input_id: int) -> bool:
    """Перемещает sink-input на виртуальный sink HyperMix_Mic."""
    if not pactl_available() or not virtual_sink_exists():
        return False
    res = _run(["pactl", "move-sink-input", str(input_id), VIRTUAL_SINK])
    return res.returncode == 0


def move_all_app_inputs_to_virtual(app_pattern: str = "HyperMix") -> int:
    """
    Перемещает все sink-input, принадлежащие приложению (по app.name
    или application.process.id), на виртуальный микрофон HyperMix_Mic.
    Возвращает число перемещённых потоков.
    """
    if not pactl_available():
        return 0
    res = _run(["pactl", "list", "sink-inputs"])
    if res.returncode != 0:
        return 0
    import os
    my_pid = str(os.getpid())
    moved = 0
    current_id = None
    is_ours = False
    for line in res.stdout.splitlines():
        line_s = line.strip()
        if line_s.startswith("Sink Input #"):
            # Завершаем предыдущий блок
            if is_ours and current_id is not None:
                if move_to_virtual_sink(current_id):
                    moved += 1
            try:
                current_id = int(line_s.split("#")[1])
            except (ValueError, IndexError):
                current_id = None
            is_ours = False
        elif "application.name" in line_s and app_pattern.lower() in line_s.lower():
            is_ours = True
        elif "application.process.id" in line_s and my_pid in line_s:
            # pygame/SDL может подписывать поток именем процесса (python3)
            is_ours = True
    # Последний блок
    if is_ours and current_id is not None:
        if move_to_virtual_sink(current_id):
            moved += 1
    return moved


def ensure_virtual_mic() -> bool:
    """Гарантирует наличие виртуального микрофона (вызывается при старте на Linux)."""
    if not pactl_available():
        return False
    if virtual_sink_exists():
        return True
    return create_virtual_sink()


def cleanup_virtual_mic():
    """Выгружает виртуальный микрофон (вызывается при закрытии приложения)."""
    if virtual_sink_exists():
        destroy_virtual_sink()


def set_default_sink_for_monitoring(sink: str | None = None):
    """
    (Опционально) Делает HyperMix_Mic основным sink'ом для записи.
    Не используется по умолчанию — режим «Микрофон» работает через move-sink-input.
    """
    if not pactl_available():
        return
    target = sink or VIRTUAL_SINK
    _run(["pactl", "set-default-sink", target])
