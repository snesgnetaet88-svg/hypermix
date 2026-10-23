# HyperMix — модуль аудио-движка (audio_engine)
# Linux: pygame.mixer + SDL_AUDIODRIVER=pulseaudio, роутинг через pactl.
# Windows: sounddevice/soundfile — вывод сразу на нужное устройство
#          (колонки / CABLE Input / оба) без смены системного default.

import os
import sys
# SDL_AUDIODRIVER=pulseaudio имеет смысл только в Linux. На Windows
# принудительный pulseaudio ломает инициализацию микшера.
if sys.platform.startswith("linux"):
    os.environ["SDL_AUDIODRIVER"] = "pulseaudio"

import hashlib
import subprocess
import tempfile
import threading
from dataclasses import dataclass, field
from pathlib import Path

os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
import pygame  # импорт строго ПОСЛЕ установки SDL_AUDIODRIVER

# Поддерживаемые форматы
AUDIO_EXTS = {".wav", ".mp3", ".ogg", ".flac"}


# ----------------------------------------------------------------------
# Вспомогательные функции
# ----------------------------------------------------------------------

def format_time(seconds: float) -> str:
    """Форматирует секунды в строку ММ:СС."""
    s = int(max(0, seconds))
    return f"{s // 60:02d}:{s % 60:02d}"


def probe_duration(path: str) -> float:
    """Определяет длительность аудиофайла через ffprobe (fallback: 0.0)."""
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", path],
            capture_output=True, text=True, timeout=10,
        )
        return float(out.stdout.strip())
    except Exception:
        return 0.0


def mp3_to_wav(mp3_path: str) -> str | None:
    """
    ЭТАП 1: конвертация MP3 во временный WAV через pydub.
    pygame плохо декодирует MP3 — поэтому готовим чистый WAV.
    Fallback: если pydub недоступен — конвертируем через ffmpeg.
    Возвращает путь к временному WAV или None при ошибке.
    """
    fd, wav_path = tempfile.mkstemp(suffix=".wav", prefix="hypermix_")
    os.close(fd)
    # Основной путь — pydub
    try:
        from pydub import AudioSegment
        seg = AudioSegment.from_mp3(mp3_path)
        seg.export(wav_path, format="wav")
        return wav_path
    except Exception as e:
        print(f"MP3->WAV (pydub) error: {e}, пробуем ffmpeg")
    # Fallback — ffmpeg
    try:
        res = subprocess.run(
            ["ffmpeg", "-y", "-i", mp3_path, "-ar", "44100", "-ac", "2", wav_path],
            capture_output=True, timeout=60,
        )
        if res.returncode == 0 and os.path.getsize(wav_path) > 0:
            return wav_path
    except Exception as e:
        print(f"MP3->WAV (ffmpeg) error: {e}")
    try:
        os.unlink(wav_path)
    except OSError:
        pass
    return None


# ----------------------------------------------------------------------
# Данные
# ----------------------------------------------------------------------

@dataclass
class SoundItem:
    """Описание одного звукового файла в библиотеке."""
    path: str                 # оригинальный путь (возможно .mp3)
    name: str                 # имя файла для отображения
    duration: float           # длительность в секундах
    hotkey: str = ""          # глобальная горячая клавиша
    play_path: str = ""       # путь, который реально играет (WAV после конвертации)
    sound: pygame.mixer.Sound | None = field(default=None, repr=False)
    uid: str = ""             # стабильный идентификатор для горячих клавиш
    pcm: object | None = field(default=None, repr=False)  # numpy-массив (Windows)
    samplerate: int = 44100   # частота дискретизации pcm


# ----------------------------------------------------------------------
# Маршрутизация потоков (ЭТАП 2 + фикс «нет звука»)
# ----------------------------------------------------------------------

def _pactl(args: list[str]) -> subprocess.CompletedProcess:
    """Запуск pactl с подавлением ошибок."""
    try:
        return subprocess.run(["pactl"] + args, capture_output=True,
                              text=True, timeout=10)
    except Exception as e:
        return subprocess.CompletedProcess(args, returncode=1, stdout="", stderr=str(e))


def _find_sink_id(sink_name: str) -> str | None:
    """Возвращает ID sink'а по имени (или None)."""
    res = _pactl(["list", "short", "sinks"])
    for line in res.stdout.splitlines():
        parts = line.split("\t")
        if len(parts) >= 2 and parts[1] == sink_name:
            return parts[0]
    return None


def _list_app_stream_ids() -> list[str]:
    """
    Возвращает ID всех sink-input, принадлежащих текущему процессу.
    PipeWire может сам направлять pygame-потоки в HyperMix_Mic
    (module-stream-restore помнит прошлое move-sink-input) — поэтому
    ищем именно СВОИ потоки, чтобы явно перенаправить их.
    """
    my_pid = str(os.getpid())
    res = _pactl(["list", "sink-inputs"])
    if res.returncode != 0:
        return []
    ids: list[str] = []
    current_id = None
    ours = False
    for line in res.stdout.splitlines():
        s = line.strip()
        if s.startswith("Sink Input #"):
            if ours and current_id is not None:
                ids.append(current_id)
            current_id = s.split("#")[1].strip()
            ours = False
        elif "application.process.id" in s and my_pid in s:
            ours = True
    if ours and current_id is not None:
        ids.append(current_id)
    return ids


def _move_stream(stream_id: str, sink_name: str) -> bool:
    """pactl move-sink-input <stream_id> <sink_name>."""
    move = _pactl(["move-sink-input", stream_id, sink_name])
    ok = move.returncode == 0
    print(f"ROUTE: sink-input {stream_id} -> {sink_name}: {'OK' if ok else 'FAIL'}")
    return ok


def route_to_virtual_mic() -> bool:
    """
    Направляет ПОСЛЕДНИЙ поток текущего процесса в HyperMix_Mic.
    """
    if _find_sink_id("HyperMix_Mic") is None:
        print("ROUTE: sink HyperMix_Mic не найден")
        return False
    streams = _list_app_stream_ids()
    if not streams:
        print("ROUTE: активных потоков нет")
        return False
    return _move_stream(streams[-1], "HyperMix_Mic")


def route_to_default_sink() -> bool:
    """
    ФИКС «нет звука»: PipeWire направляет pygame-потоки в HyperMix_Mic
    (stream-restore помнит прошлые перемещения). В режиме динамиков
    нужно ЯВНО вернуть поток в системный sink по умолчанию.
    """
    res = _pactl(["get-default-sink"])
    default_sink = res.stdout.strip()
    if not default_sink:
        print("ROUTE: sink по умолчанию не найден")
        return False
    streams = _list_app_stream_ids()
    if not streams:
        print("ROUTE: активных потоков нет")
        return False
    return _move_stream(streams[-1], default_sink)


def ensure_combine_sink() -> bool:
    """
    Режим BOTH: pygame создаёт ОДИН поток на процесс (все каналы SDL
    смешиваются в один stream) — поэтому обычный move-sink-input не может
    одновременно отправить звук в колонки И в микрофон.
    Решение: module-combine-sink — виртуальный sink, который дублирует
    звук в оба устройства (колонки + HyperMix_Mic).
    """
    if _find_sink_id("HyperMix_Combine") is not None:
        return True
    res = _pactl(["get-default-sink"])
    default = res.stdout.strip()
    if not default:
        return False
    r = _pactl([
        "load-module", "module-combine-sink",
        f"sinks={default},HyperMix_Mic",
        "sink_name=HyperMix_Combine",
        "sink_properties=device.description=HyperMixCombine",
    ])
    ok = r.returncode == 0 or _find_sink_id("HyperMix_Combine") is not None
    print(f"COMBINE: создание HyperMix_Combine ({default}+HyperMix_Mic): {'OK' if ok else 'FAIL'}")
    return ok


def destroy_combine_sink():
    """Выгружает combine-sink при выходе/смене режима."""
    sid = _find_sink_id("HyperMix_Combine")
    if sid is None:
        return
    res = _pactl(["list", "short", "modules"])
    for line in res.stdout.splitlines():
        parts = line.split("\t")
        # формат: id \t имя-модуля \t аргументы
        args = parts[2] if len(parts) >= 3 else ""
        if "module-combine-sink" in line and "HyperMix_Combine" in args:
            _pactl(["unload-module", parts[0].strip()])
            print("COMBINE: HyperMix_Combine выгружен")
            return


def route_app_streams(mode: str) -> bool:
    """
    Маршрутизация потоков процесса по режиму:
      "speakers" -> sink по умолчанию (колонки)
      "mic"      -> HyperMix_Mic
      "both"     -> HyperMix_Combine (combine-sink: колонки + микрофон)
    """
    streams = _list_app_stream_ids()
    if not streams:
        print(f"ROUTE[{mode}]: потоков нет")
        return False

    if mode == "speakers":
        destroy_combine_sink()  # убираем лишний combine-sink
        res = _pactl(["get-default-sink"])
        target = res.stdout.strip()
        ok = True
        for sid in streams:
            ok = _move_stream(sid, target) and ok
        return ok

    if mode == "mic":
        destroy_combine_sink()
        if _find_sink_id("HyperMix_Mic") is None:
            return False
        ok = True
        for sid in streams:
            ok = _move_stream(sid, "HyperMix_Mic") and ok
        return ok

    if mode == "both":
        # Один поток SDL — направляем в combine-sink (дубль в оба устройства)
        if not ensure_combine_sink():
            # Fallback: нет combine-sink — хотя бы в колонки
            res = _pactl(["get-default-sink"])
            target = res.stdout.strip()
            ok = True
            for sid in streams:
                ok = _move_stream(sid, target) and ok
            return ok
        ok = True
        for sid in streams:
            ok = _move_stream(sid, "HyperMix_Combine") and ok
        return ok

    return False


# ----------------------------------------------------------------------
# Движок
# ----------------------------------------------------------------------

class AudioEngine:
    """
    Движок воспроизведения.

    Linux  — pygame.mixer; маршрутизация SPK/MIC/BOTH через pactl.
    Windows — sounddevice/soundfile; звук сразу идёт на выбранные
              устройства (колонки / CABLE Input / оба).
    """

    NUM_CHANNELS = 8

    def __init__(self):
        self._initialized = False
        self.sounds: list[SoundItem] = []
        self.on_finished = None      # callback завершения
        self.output_mode = "speakers"

        # Windows-ветка
        self._win_audio = False
        self._np = None
        self._sd = None
        self._sf = None
        self._volume = 1.0
        self._streams: list = []
        self._stream_lock = threading.Lock()
        self._current_item: SoundItem | None = None
        self._play_token = 0

        # Windows: захват реального микрофона и подмешивание в CABLE Input
        self._voice_stream = None
        self._voice_ring = None
        self._voice_rate = 48000
        self._voice_written = 0
        self._voice_read = 0.0
        self._voice_lock = threading.Lock()
        self._voice_source = ""
        self._voice_active_name = ""

    # ------------------------------------------------------------------
    # Инициализация
    # ------------------------------------------------------------------

    def init(self) -> bool:
        """Инициализирует аудиоподсистему под текущую ОС."""
        if self._initialized:
            return True

        if sys.platform.startswith("win"):
            try:
                import numpy as np
                import sounddevice as sd
                self._np, self._sd = np, sd
                try:
                    import soundfile as sf
                    self._sf = sf
                except Exception:
                    self._sf = None
                self._win_audio = True
                self._initialized = True
                print("AudioEngine: Windows backend (sounddevice"
                      + ("/soundfile" if self._sf else "")
                      + ")")
                self._start_voice_capture()
                return True
            except Exception as e:
                print(f"AudioEngine: sounddevice недоступен ({e}), "
                      "использую pygame (только колонки)")

        try:
            pygame.mixer.init(frequency=44100, size=-16, channels=2, buffer=512)
            pygame.mixer.set_num_channels(self.NUM_CHANNELS)
            self._initialized = True
            print(f"AudioEngine: mixer init OK (driver={pygame.mixer.get_init()})")
            return True
        except pygame.error as e:
            print(f"AudioEngine: mixer init FAIL: {e}")
            self._initialized = False
            return False

    @property
    def ready(self) -> bool:
        return self._initialized

    @property
    def supports_routing(self) -> bool:
        """Может ли движок направлять звук в виртуальный микрофон."""
        if sys.platform.startswith("win"):
            return self._win_audio
        return True

    def set_output_mode(self, mode: str):
        """Режим вывода для Windows-ветки: speakers / mic / both."""
        if mode in ("speakers", "mic", "both"):
            self.output_mode = mode

    # ------------------------------------------------------------------
    # Windows: микрофон (голос) — захват и подмешивание в CABLE Input
    # ------------------------------------------------------------------

    def list_input_devices(self) -> list[str]:
        """Список реальных микрофонов Windows (без виртуального кабеля)."""
        if not self._win_audio:
            return []
        try:
            devices = self._sd.query_devices()
        except Exception:
            return []
        names: list[str] = []
        for dev in devices:
            try:
                if int(dev.get("max_input_channels", 0)) <= 0:
                    continue
            except Exception:
                continue
            name = str(dev.get("name", "")).strip()
            low = name.lower()
            if not name or "cable output" in low or "voicemeeter" in low:
                continue
            if name not in names:
                names.append(name)
        return names

    def _default_input_index(self):
        """Индекс микрофона по умолчанию (sounddevice отдаёт int или пару)."""
        try:
            dev = self._sd.default.device
            try:
                idx = dev[0]
            except (TypeError, IndexError, KeyError):
                idx = dev
            if idx is None:
                return None
            return int(idx)
        except Exception:
            return None

    def _default_input(self):
        """(индекс, имя) микрофона по умолчанию, если это не CABLE Output."""
        try:
            idx = self._default_input_index()
            if idx is None:
                return None, ""
            info = self._sd.query_devices(idx)
            name = str(info.get("name", "")).strip()
            if (int(info.get("max_input_channels", 0)) > 0
                    and "cable output" not in name.lower()):
                return idx, name
        except Exception:
            pass
        return None, ""

    def _pick_voice_device(self):
        """Выбирает выбранный пользователем микрофон или дефолтный."""
        try:
            devices = self._sd.query_devices()
        except Exception:
            devices = []
        if self._voice_source:
            for idx, dev in enumerate(devices):
                try:
                    if int(dev.get("max_input_channels", 0)) <= 0:
                        continue
                except Exception:
                    continue
                if str(dev.get("name", "")).strip() == self._voice_source:
                    return idx, self._voice_source
            return None, ""
        idx, name = self._default_input()
        if idx is not None:
            return idx, name
        for idx, dev in enumerate(devices):
            try:
                if int(dev.get("max_input_channels", 0)) <= 0:
                    continue
            except Exception:
                continue
            name = str(dev.get("name", "")).strip()
            if name and "cable output" not in name.lower():
                return idx, name
        return None, ""

    @property
    def voice_active(self) -> bool:
        """Открыт ли захват микрофона."""
        return self._voice_stream is not None

    def voice_source_name(self) -> str:
        """Имя активного микрофона (для UI)."""
        if self._voice_active_name:
            return self._voice_active_name
        if self._voice_source:
            return self._voice_source
        _idx, name = self._default_input()
        return name

    def set_voice_source(self, name: str) -> bool:
        """Меняет микрофон, голос с которого идёт в CABLE Input."""
        if not self._win_audio:
            return False
        name = (name or "").strip()
        if name:
            try:
                if name not in self.list_input_devices():
                    return False
            except Exception:
                return False
        self._voice_source = name
        self._stop_voice_capture()
        return self._start_voice_capture()

    def _start_voice_capture(self) -> bool:
        """Открывает InputStream и наполняет кольцевой буфер голосом."""
        if not self._win_audio:
            return False
        if self._voice_stream is not None:
            return True
        np = self._np
        try:
            idx, name = self._pick_voice_device()
            if idx is None:
                print("WIN: микрофон не найден — звуки без голоса")
                return False
            info = self._sd.query_devices(idx)
            channels = int(info.get("max_input_channels", 0))
            if channels <= 0:
                return False
            channels = min(2, channels)
            rate = int(info.get("default_samplerate") or 48000)
            if rate <= 0:
                rate = 48000
            ring_len = max(rate * 2, 4096)
            ring = np.zeros((ring_len, 2), dtype=np.float32)
            with self._voice_lock:
                self._voice_ring = ring
                self._voice_rate = rate
                self._voice_written = 0
                self._voice_read = 0.0

            def callback(indata, frames, _time_info, _status):
                data = np.asarray(indata, dtype=np.float32)
                if data.ndim == 1:
                    data = data.reshape(-1, 1)
                if data.shape[1] == 1:
                    data = np.repeat(data, 2, axis=1)
                elif data.shape[1] > 2:
                    data = data[:, :2]
                n = len(data)
                with self._voice_lock:
                    ring = self._voice_ring
                    if ring is None:
                        return
                    size = len(ring)
                    pos = self._voice_written % size
                    first = min(n, size - pos)
                    ring[pos:pos + first] = data[:first]
                    if n > first:
                        ring[:n - first] = data[first:]
                    self._voice_written += n
                    if self._voice_written - self._voice_read > size - 2048:
                        self._voice_read = float(self._voice_written - size // 2)

            stream = self._sd.InputStream(
                device=idx,
                channels=channels,
                samplerate=rate,
                dtype="float32",
                blocksize=0,
                callback=callback,
            )
            stream.start()
            self._voice_stream = stream
            self._voice_active_name = name
            print(f"WIN: голос с «{name}» подмешивается в CABLE Input "
                  f"({rate} Hz)")
            return True
        except Exception as e:
            print(f"WIN: микрофон недоступен: {e}")
            self._stop_voice_capture()
            return False

    def _stop_voice_capture(self):
        stream = self._voice_stream
        self._voice_stream = None
        if stream is not None:
            try:
                stream.stop()
            except Exception:
                pass
            try:
                stream.close()
            except Exception:
                pass
        with self._voice_lock:
            self._voice_ring = None
            self._voice_written = 0
            self._voice_read = 0.0
        self._voice_active_name = ""

    def _prime_voice(self):
        """Ставит чтение голоса почти на «живой» край буфера (малая задержка)."""
        with self._voice_lock:
            if self._voice_ring is None:
                return
            prefill = int(self._voice_rate * 0.03)
            self._voice_read = float(max(0, self._voice_written - prefill))

    def _mix_voice(self, outdata, frames: int, rate: int):
        """Подмешивает голос из кольцевого буфера в выходной блок."""
        np = self._np
        if np is None or frames <= 0:
            return
        with self._voice_lock:
            ring = self._voice_ring
            if ring is None:
                return
            size = len(ring)
            step = self._voice_rate / max(rate, 1)
            available = self._voice_written - self._voice_read
            needed = (frames - 1) * step + 2
            if available < needed:
                return
            idx = self._voice_read + step * np.arange(frames, dtype=np.float64)
            base = idx.astype(np.int64)
            frac = (idx - base).astype(np.float32)[:, None]
            i0 = (base % size).astype(np.int64)
            i1 = ((base + 1) % size).astype(np.int64)
            outdata[:frames] += ring[i0] * (1.0 - frac) + ring[i1] * frac
            self._voice_read = float(self._voice_read + frames * step)
        np.clip(outdata, -1.0, 1.0, out=outdata)

    # ------------------------------------------------------------------
    # Библиотека
    # ------------------------------------------------------------------

    def _load_pcm(self, path: str):
        """Читает файл в float32-массив (frames, 2) для Windows-вывода."""
        np = self._np
        if np is None:
            return None

        data, rate = None, None
        if self._sf is not None:
            try:
                data, rate = self._sf.read(path, dtype="float32", always_2d=True)
            except Exception as e:
                print(f"WIN: soundfile не прочитал {path}: {e}")
                data, rate = None, None

        # pygame умеет MP3/OGG/FLAC/WAV и всегда есть в сборке
        if data is None or len(data) == 0:
            data, rate = self._load_pcm_pygame(path)

        # Последний шанс — pydub/ffmpeg во временный WAV
        if data is None or len(data) == 0:
            wav = mp3_to_wav(path)
            if not wav:
                return None
            if self._sf is None:
                try:
                    os.unlink(wav)
                except OSError:
                    pass
                return None
            try:
                data, rate = self._sf.read(wav, dtype="float32", always_2d=True)
            except Exception as e:
                print(f"WIN: не удалось прочитать WAV {wav}: {e}")
                return None
            finally:
                try:
                    os.unlink(wav)
                except OSError:
                    pass

        if data is None or len(data) == 0:
            return None
        if data.shape[1] == 1:
            data = np.repeat(data, 2, axis=1)
        elif data.shape[1] > 2:
            data = data[:, :2]
        return np.ascontiguousarray(data, dtype=np.float32), int(rate)

    def _load_pcm_pygame(self, path: str):
        """Декодирует файл через pygame (без вывода звука на устройство)."""
        np = self._np
        inited_here = not pygame.mixer.get_init()
        try:
            if inited_here:
                pygame.mixer.init(frequency=44100, size=-16,
                                  channels=2, buffer=512)
            sound = pygame.mixer.Sound(path)
            arr = pygame.sndarray.array(sound)
            if arr.ndim == 1:
                arr = arr.reshape(-1, 1)
            rate = pygame.mixer.get_init()[0] if pygame.mixer.get_init() else 44100
            data = arr.astype(np.float32) / 32768.0
            print(f"WIN: {path} декодирован через pygame @ {rate} Hz")
            return data, int(rate)
        except Exception as e:
            print(f"WIN: pygame не смог декодировать {path}: {e}")
            return None, None
        finally:
            if inited_here:
                try:
                    pygame.mixer.quit()
                except pygame.error:
                    pass

    def add_file(self, path: str) -> SoundItem | None:
        """
        Загружает аудиофайл. MP3 конвертируется в WAV (Linux) либо
        декодируется soundfile/ffmpeg (Windows).
        Возвращает SoundItem или None.
        """
        if not self._initialized and not self.init():
            return None

        uid = hashlib.sha1(path.encode("utf-8")).hexdigest()[:12]
        ext = Path(path).suffix.lower()

        if self._win_audio:
            loaded = self._load_pcm(path)
            if loaded is None:
                print(f"add_file FAIL (win): {path}")
                return None
            pcm, rate = loaded
            duration = len(pcm) / max(rate, 1)
            item = SoundItem(
                path=path,
                name=Path(path).name,
                duration=duration,
                play_path=path,
                sound=None,
                uid=uid,
                pcm=pcm,
                samplerate=rate,
            )
            self.sounds.append(item)
            return item

        play_path = path
        # ЭТАП 1: MP3 -> WAV через pydub
        if ext == ".mp3":
            wav = mp3_to_wav(path)
            if wav:
                play_path = wav
            else:
                print(f"add_file: не удалось сконвертировать {path}, пробуем как есть")

        try:
            sound = pygame.mixer.Sound(play_path)
        except pygame.error as e:
            print(f"add_file FAIL: {path}: {e}")
            return None

        duration = sound.get_length()
        if duration <= 0:
            duration = probe_duration(path)

        item = SoundItem(
            path=path,
            name=Path(path).name,
            duration=duration,
            play_path=play_path,
            sound=sound,
            uid=uid,
        )
        self.sounds.append(item)
        return item

    # ------------------------------------------------------------------
    # Windows: выбор устройств и вывод
    # ------------------------------------------------------------------

    def _default_output(self):
        """Индекс устройства вывода по умолчанию (None = default PortAudio)."""
        try:
            dev = self._sd.default.device
            try:
                out = dev[1]
            except (TypeError, IndexError, KeyError):
                out = dev
            if out is None:
                return None
            return int(out)
        except Exception:
            return None

    def _device_index(self, substring: str):
        """Индекс output-устройства, в имени которого есть substring."""
        try:
            devices = self._sd.query_devices()
        except Exception:
            return None
        for idx, dev in enumerate(devices):
            try:
                if int(dev.get("max_output_channels", 0)) <= 0:
                    continue
            except Exception:
                continue
            if substring.lower() in str(dev.get("name", "")).lower():
                return idx
        return None

    def _device_samplerate(self, idx) -> int:
        try:
            info = self._sd.query_devices(idx)
            return int(info.get("default_samplerate") or 44100)
        except Exception:
            return 44100

    def _resample(self, data, src: int, dst: int):
        """Линейная передискретизация (numpy), если частота устройства иная."""
        np = self._np
        if src == dst or src <= 0 or data is None or len(data) == 0:
            return data
        n = max(1, int(round(len(data) * dst / src)))
        src_idx = np.arange(len(data), dtype=np.float64)
        dst_idx = np.linspace(0, len(data) - 1, n)
        out = np.empty((n, data.shape[1]), dtype=np.float32)
        for ch in range(data.shape[1]):
            out[:, ch] = np.interp(dst_idx, src_idx, data[:, ch])
        return out

    def _close_streams(self):
        with self._stream_lock:
            streams = self._streams
            self._streams = []
        for stream in streams:
            try:
                stream.stop()
            except Exception:
                pass
            try:
                stream.close()
            except Exception:
                pass

    def _play_windows(self, item: SoundItem, volume: float, loops: int) -> bool:
        self.stop_all()
        if item.pcm is None:
            print(f"PLAY: нет PCM для {item.name}")
            return False

        mode = self.output_mode
        targets: list = []
        cable_flags: list[bool] = []

        def add(idx, is_cable: bool = False):
            if idx in targets:
                i = targets.index(idx)
                cable_flags[i] = cable_flags[i] or is_cable
                return
            targets.append(idx)
            cable_flags.append(is_cable)

        cable = self._device_index("CABLE Input")
        if mode == "mic":
            if cable is None:
                print("WIN: CABLE Input не найден — микрофонный режим недоступен")
                return False
            add(cable, True)
        elif mode == "both":
            add(self._default_output(), False)
            if cable is None:
                print("WIN: CABLE Input не найден — только колонки")
            else:
                add(cable, True)
        else:
            add(self._default_output(), False)

        if not targets:
            print("WIN: не найдено ни одного устройства вывода")
            return False

        self._volume = max(0.0, min(1.0, volume))
        token = self._play_token + 1
        self._play_token = token
        self._current_item = item

        positions = [0] * len(targets)
        bufs: list = []
        lock = threading.Lock()

        def make_callback(buf, index, with_voice: bool, rate: int):
            def callback(outdata, frames, _time_info, _status):
                with lock:
                    pos = positions[index]
                    chunk = buf[pos:pos + frames]
                    n = len(chunk)
                    if n:
                        outdata[:n] = chunk
                        if self._volume != 1.0:
                            outdata[:n] *= self._volume
                    if n < frames:
                        outdata[n:] = 0
                    positions[index] = min(pos + n, len(buf))
                if with_voice:
                    self._mix_voice(outdata, frames, rate)
                return (0, 0)
            return callback

        streams = []
        try:
            for i, device in enumerate(targets):
                stream_device = None if (device is None or device < 0) else device
                rate = self._device_samplerate(stream_device)
                data = self._resample(item.pcm, item.samplerate, rate)
                bufs.append(data)
                stream = self._sd.OutputStream(
                    samplerate=rate,
                    channels=data.shape[1],
                    dtype="float32",
                    device=stream_device,
                    callback=make_callback(data, i, cable_flags[i], rate),
                )
                streams.append(stream)
            with self._stream_lock:
                self._streams = streams
            if any(cable_flags):
                self._prime_voice()
            for stream in streams:
                stream.start()
        except Exception as e:
            print(f"WIN: ошибка запуска вывода: {e}")
            for stream in streams:
                try:
                    stream.stop()
                except Exception:
                    pass
                try:
                    stream.close()
                except Exception:
                    pass
            self._close_streams()
            self._current_item = None
            return False

        def watch():
            while True:
                if token != self._play_token:
                    return
                with lock:
                    done = all(positions[i] >= len(bufs[i])
                               for i in range(len(bufs)))
                    if done:
                        break
                import time
                time.sleep(0.05)
            if token == self._play_token:
                self._close_streams()
                if self._current_item is item:
                    self._current_item = None

        threading.Thread(target=watch, daemon=True,
                         name="hypermix-win-watch").start()

        has_cable = cable is not None and cable in targets
        print(f"PLAY: {item.name} (win: "
              f"{'CABLE Input' if has_cable else 'speakers'}"
              f"{' + speakers' if has_cable and len(targets) > 1 else ''})")
        return True

    # ------------------------------------------------------------------
    # Воспроизведение
    # ------------------------------------------------------------------

    def play(self, item: SoundItem, volume: float = 1.0,
             loops: int = 0, channel_index: int = 0) -> bool:
        """
        Запускает звук. Linux: pygame + внешняя маршрутизация pactl.
        Windows: sounddevice сразу на нужные устройства.
        """
        if not self._initialized:
            print(f"PLAY: движок не готов ({item.name})")
            return False

        if self._win_audio:
            return self._play_windows(item, volume, loops)

        if item.sound is None:
            print(f"PLAY: звук не загружен ({item.name})")
            return False
        try:
            ch = pygame.mixer.Channel(channel_index)
            ch.set_volume(max(0.0, min(1.0, volume)))
            ch.play(item.sound, loops=loops)
            # ЭТАП 1: обязательное логирование
            print(f"PLAY: {item.name}")
            return True
        except pygame.error as e:
            print(f"PLAY FAIL: {item.name}: {e}")
            return False

    def stop(self, item: SoundItem | None = None):
        """Останавливает звук (или всё, если item is None)."""
        if not self._initialized:
            return
        if self._win_audio:
            if item is None or item is self._current_item:
                self.stop_all()
            return
        try:
            if item is not None and item.sound is not None:
                item.sound.stop()
            else:
                pygame.mixer.stop()
        except pygame.error:
            pass

    def stop_all(self):
        if not self._initialized:
            return
        if self._win_audio:
            self._play_token += 1
            self._current_item = None
            self._close_streams()
            return
        try:
            pygame.mixer.stop()
        except pygame.error:
            pass

    def set_channel_volume(self, channel_index: int, volume: float):
        if not self._initialized:
            return
        self._volume = max(0.0, min(1.0, volume))
        if self._win_audio:
            return
        try:
            pygame.mixer.Channel(channel_index).set_volume(self._volume)
        except pygame.error:
            pass

    def is_playing(self, item: SoundItem | None = None) -> bool:
        if not self._initialized:
            return False
        if self._win_audio:
            if item is not None and item is not self._current_item:
                return False
            with self._stream_lock:
                return bool(self._streams)
        if item is not None and item.sound is not None:
            return item.sound.get_num_channels() > 0
        return pygame.mixer.get_busy()

    def shutdown(self):
        if not self._initialized:
            return
        if self._win_audio:
            self.stop_all()
            self._stop_voice_capture()
            try:
                if pygame.mixer.get_init():
                    pygame.mixer.quit()
            except pygame.error:
                pass
            self._initialized = False
            return
        try:
            pygame.mixer.quit()
        except pygame.error:
            pass
        self._initialized = False


class PlaybackTracker:
    """Отслеживает прогресс воспроизведения (оценка по времени старта)."""

    def __init__(self, engine: AudioEngine):
        self.engine = engine
        self._active: dict[int, tuple[SoundItem, float, int]] = {}
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._running = False

    def start_track(self, item: SoundItem, channel: int, loops: int = 0):
        import time
        with self._lock:
            self._active[channel] = (item, time.monotonic(), loops)
        self._ensure_thread()

    def clear(self, channel: int | None = None):
        with self._lock:
            if channel is None:
                self._active.clear()
            else:
                self._active.pop(channel, None)

    def position(self, item: SoundItem) -> float:
        import time
        with self._lock:
            for _ch, (it, t0, loops) in self._active.items():
                if it is item:
                    pos = time.monotonic() - t0
                    if loops == -1:
                        return pos % max(item.duration, 0.001)
                    return min(pos, item.duration)
        return 0.0

    def _ensure_thread(self):
        if self._thread is not None and self._thread.is_alive():
            return
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def _loop(self):
        import time
        while self._running:
            finished = []
            with self._lock:
                for ch, (item, t0, loops) in list(self._active.items()):
                    if loops == -1:
                        continue
                    if not self.engine.is_playing(item):
                        finished.append(ch)
                        self._active.pop(ch, None)
            if finished and self.engine.on_finished:
                for _ in finished:
                    self.engine.on_finished()
            time.sleep(0.05)

    def stop(self):
        self._running = False
        self.clear()
