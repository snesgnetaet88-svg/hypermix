# HyperMix — единый модуль платформы
# При старте: Linux — создаёт виртуальный микрофон HyperMix_Mic;
#             Windows — проверяет VB-Cable (диалог, если нет).
# При закрытии: Linux — выгружает модуль null-sink.

import json
import sys

from ..paths import CONFIG_PATH
from . import linux_audio
from . import windows_cable


class PlatformManager:
    """
    Менеджер виртуального микрофона для текущей ОС.
    """

    def __init__(self):
        self.system = sys.platform
        self.virtual_mic_ready = False   # Linux: HyperMix_Mic создан
        self.cable_ready = False         # Windows: CABLE Input найден
        self._linux_module_loaded = False
        self._linux_source_loaded = False
        self._voice_loopback_loaded = False
        self._previous_default_source = ""
        self._voice_source = ""
        self.engine = None

    # ------------------------------------------------------------------
    # Старт
    # ------------------------------------------------------------------

    def startup(self, parent=None) -> str:
        """
        Инициализация при запуске приложения.
        Возвращает строку-статус для статус-бара / уведомления.
        """
        if self.system.startswith("linux"):
            return self._startup_linux()
        elif self.system.startswith("win"):
            return self._startup_windows(parent)
        else:
            return f"Платформа {self.system} — виртуальный микрофон не поддерживается"

    def _startup_linux(self) -> str:
        """ЭТАП 3: проверка/создание HyperMix_Mic через pactl."""
        if not linux_audio.pactl_available():
            return "PipeWire/PulseAudio (pactl) не найден — режим микрофона ограничен"
        if linux_audio.virtual_sink_exists():
            self.virtual_mic_ready = True
            self._linux_module_loaded = False  # существовал до нас — не выгружаем
        elif linux_audio.create_virtual_sink():
            self.virtual_mic_ready = True
            self._linux_module_loaded = True   # создали сами — выгрузим при выходе
        else:
            return "Не удалось создать виртуальный микрофон HyperMix_Mic"

        # --- Обычный источник для Discord (remap с monitor'а) ---
        source_preexisting = linux_audio.virtual_source_exists()
        source_ok = linux_audio.create_virtual_source()
        self._linux_source_loaded = source_ok and not source_preexisting
        if not source_ok:
            print("MIC: не удалось создать HyperMix_Microphone — fallback на monitor")

        # --- Подмешиваем голос говорящего в виртуальный микрофон ---
        # Сначала определяем РЕАЛЬНЫЙ микрофон — до переключения default
        # source на наш виртуальный. Если default уже указывает на виртуальный
        # (остался с прошлого запуска), pick_voice_source возьмёт сохранённый
        # ранее реальный микрофон, а не произвольный.
        voice_source = linux_audio.pick_voice_source()
        self._previous_default_source = voice_source
        voice_ok = False
        if voice_source:
            voice_ok = linux_audio.ensure_voice_loopback(voice_source)
        self._voice_loopback_loaded = voice_ok
        self._voice_source = voice_source

        # --- Делаем наш микрофон микрофоном по умолчанию ---
        default_ok = linux_audio.set_default_source(
            linux_audio.active_virtual_source())

        parts = []
        if self._linux_module_loaded:
            parts.append("Виртуальный микрофон HyperMix_Mic создан")
        else:
            parts.append("Виртуальный микрофон HyperMix_Mic уже существует")
        if voice_ok:
            parts.append(f"голос с «{voice_source}» подмешан")
        elif voice_source:
            parts.append(f"голос с «{voice_source}» подмешать не удалось")
        else:
            parts.append("реальный микрофон не найден — только звуки")
        if default_ok:
            parts.append(f"микрофон по умолчанию: {linux_audio.active_virtual_source()}")
        return "; ".join(parts)

    def _startup_windows(self, parent=None) -> str:
        """ЭТАП 4: проверка CABLE Input, диалог если нет (ничего не ставим скрытно)."""
        if windows_cable.detect_cable_input():
            self.cable_ready = True
            voice = (self.engine.voice_source_name()
                     if self.engine and self.engine.voice_active else "")
            if voice:
                return (f"VB-Audio Cable найден; голос: «{voice}»; "
                        "в Discord выберите микрофон CABLE Output")
            return ("VB-Audio Cable найден; микрофон не найден — только звуки; "
                    "в Discord выберите CABLE Output")
        # Нет устройства: открываем браузер + диалог с инструкцией
        windows_cable.show_cable_required_dialog(parent)
        return "VB-Audio Cable не найден — режим микрофона недоступен (см. диалог)"

    # ------------------------------------------------------------------
    # Выход
    # ------------------------------------------------------------------

    def shutdown(self):
        """Выгрузка ресурсов при закрытии приложения (ЭТАП 3: unload модуля)."""
        if self.system.startswith("linux"):
            # Возвращаем прежний микрофон по умолчанию, чтобы у остальных
            # программ не остался «мёртвый» виртуальный микрофон.
            if self._previous_default_source:
                linux_audio.set_default_source(self._previous_default_source)
                self._previous_default_source = ""
            if self._voice_loopback_loaded:
                linux_audio.destroy_voice_loopback()
                self._voice_loopback_loaded = False
            if self._linux_source_loaded:
                linux_audio.destroy_virtual_source()
                self._linux_source_loaded = False
            if self._linux_module_loaded:
                linux_audio.destroy_virtual_sink()
                self.virtual_mic_ready = False
                self._linux_module_loaded = False

    # ------------------------------------------------------------------
    # Доступность режима «Микрофон»
    # ------------------------------------------------------------------

    def mic_mode_available(self) -> bool:
        """Можно ли направлять звук в виртуальный микрофон."""
        if self.system.startswith("linux"):
            return self.virtual_mic_ready or linux_audio.virtual_sink_exists()
        if self.system.startswith("win"):
            return self.cable_ready or windows_cable.cable_available()
        return False

    def route_playback_to_mic(self, engine) -> bool:
        """
        Направляет потоки воспроизведения HyperMix в виртуальный микрофон.
        Linux: перемещает sink-input приложения на HyperMix_Mic.
        Windows: не используется — AudioEngine сам выводит звук на CABLE Input.
        """
        if self.system.startswith("linux"):
            if not self.mic_mode_available():
                return False
            moved = linux_audio.move_all_app_inputs_to_virtual("HyperMix")
            return moved > 0
        # Windows: маршрутизацией управляет AudioEngine (_play_windows).
        return self.mic_mode_available()

    def status_text(self) -> str:
        """Краткий статус для UI."""
        if self.system.startswith("linux"):
            if self.virtual_mic_ready:
                voice = " + голос" if self._voice_loopback_loaded else " (без голоса)"
                return f"Микрофон: {linux_audio.active_virtual_source()}{voice} ✔"
            return "Микрофон: —"
        if self.system.startswith("win"):
            if self.cable_ready:
                voice = (self.engine.voice_source_name()
                         if self.engine and self.engine.voice_active else "")
                if voice:
                    return "VB-Cable: CABLE Output + голос ✔"
                return "VB-Cable: CABLE Output (голос не найден) ✔"
            return "VB-Cable: не найден"
        return "Платформа не поддерживается"

    # ------------------------------------------------------------------
    # Управление источником микрофона
    # ------------------------------------------------------------------

    def attach_engine(self, engine):
        """Даёт платформе доступ к аудиодвижку (Windows: микрофон/голос)."""
        self.engine = engine

    def list_capture_mics(self) -> list[str]:
        """Список реальных микрофонов (без monitor и без нашего виртуального)."""
        if self.system.startswith("linux"):
            return linux_audio.real_capture_sources()
        if self.system.startswith("win"):
            return self.engine.list_input_devices() if self.engine else []
        return []

    def current_voice_source(self) -> str:
        """Текущий микрофон, с которого берётся голос."""
        if self.system.startswith("linux"):
            return self._voice_source or linux_audio._load_saved_voice_source()
        if self.system.startswith("win") and self.engine is not None:
            return self.engine.voice_source_name()
        return ""

    def select_voice_source(self, source: str) -> bool:
        """
        Меняет микрофон, из которого берётся голос говорящего, и заново
        подмешивает его в виртуальный микрофон.
        """
        if self.system.startswith("linux"):
            if not linux_audio.is_real_capture_source(source):
                return False
            # пересоздаём loopback с новым источником
            linux_audio.destroy_voice_loopback()
            ok = linux_audio.ensure_voice_loopback(source)
            self._voice_loopback_loaded = ok
            if ok:
                self._voice_source = source
            return ok
        if self.system.startswith("win"):
            if self.engine is None or not self.engine.set_voice_source(source):
                return False
            self._save_windows_voice_source(source)
            return True
        return False

    @staticmethod
    def _save_windows_voice_source(name: str):
        """Запоминает выбранный микрофон Windows в config.json."""
        try:
            cfg = {}
            if CONFIG_PATH.exists():
                with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                    cfg = json.load(f)
            cfg["windows_voice_source"] = name
            with open(CONFIG_PATH, "w", encoding="utf-8") as f:
                json.dump(cfg, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"WIN: не удалось сохранить микрофон: {e}")

    def activate_virtual_mic(self) -> bool:
        """Делает HyperMix_Mic.monitor микрофоном по умолчанию."""
        if not self.system.startswith("linux"):
            return False
        return linux_audio.set_default_source(linux_audio.active_virtual_source())
