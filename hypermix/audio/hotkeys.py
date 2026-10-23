# HyperMix — модуль глобальных горячих клавиш
#
# Backend: KDE CommandShortcut .desktop (надёжно работает на KDE Wayland БЕЗ root).
#
# Почему так: KWin grab'ает глобальные клавиши для компонентов, известных
# KGlobalAccel. Runtime-регистрация через DBus работает, но вызов
# setForeignShortcutKeys НЕ активирует shortcut: в kglobalacceld он
# вызывает setShortcutKeys(..., NoAutoloading) без флага SetPresent,
# поэтому shortcut остаётся «неприсутствующим» (isPresent() == false),
# setActive() не вызывается и ключ не попадает в _active_keys —
# нажатие клавиши игнорируется.
#
# Поэтому: на каждый звук создаём .desktop вида hypermix-<sound>.desktop,
# Exec вызывает скрипт, который шлёт id звука в Unix-сокет приложения.
# Клавишу назначаем через KGlobalAccel setShortcutKeys с флагами
# SetPresent|NoAutoloading (2|4) — это активирует shortcut и сразу
# хватает клавишу, без перелогина.

import os
import socket
import json
import sys
import threading
import subprocess
import tempfile
from pathlib import Path
from typing import Callable

from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtGui import QKeySequence

try:
    from dbus_next.aio import MessageBus
    from dbus_next import Message, MessageType
    _DBUS_AVAILABLE = True
except Exception:
    _DBUS_AVAILABLE = False

try:
    import keyboard as _keyboard_lib
    _KEYBOARD_AVAILABLE = True
except Exception:
    _KEYBOARD_AVAILABLE = False

try:
    from . import evdev_hotkeys
except Exception:
    evdev_hotkeys = None

try:
    from . import windows_hotkeys
except Exception:
    windows_hotkeys = None

KGA_DEST = "org.kde.kglobalaccel"
KGA_PATH = "/kglobalaccel"
SOCK_PATH = os.path.join(
    os.environ.get("XDG_RUNTIME_DIR", tempfile.gettempdir()),
    "hypermix-hotkeys.sock")


def send_sound_id(sound_id: str) -> bool:
    """Отправляет id звука в сокет работающего HyperMix (для --send/fire.sh)."""
    if not sound_id:
        return False
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
            sock.settimeout(1.0)
            sock.connect(SOCK_PATH)
            sock.sendall(sound_id.encode("utf-8"))
        return True
    except OSError:
        return False
APPS_DIR = Path.home() / ".local/share/applications"
from ..paths import CONFIG_PATH
# префикс storageId .desktop (совпадает с именем файла)
DESKTOP_PREFIX = "hypermix-"


def _desktop_id(sound_id: str) -> str:
    """storageId .desktop-файла для звука."""
    return f"{DESKTOP_PREFIX}{sound_id}.desktop"


class HotkeyManager(QObject):
    """
    Глобальные горячие клавиши через KDE CommandShortcut + Unix-сокет.

    Приложение слушает сокет; .desktop-скрипты шлют в него sound_id;
    менеджер эмитит activated(sound_id) в GUI-поток.
    """

    activated = pyqtSignal(str)  # sound_id
    hotkey_captured = pyqtSignal(str)  # token новой привязки (evdev-захват)
    hotkey_capture_blocked = pyqtSignal()  # в захвате нажата ЛКМ/ПКМ

    def __init__(self, parent=None):
        super().__init__(parent)
        self._lock = threading.Lock()
        self._counter = 0
        self._keys: dict[str, str] = {}      # sound_id -> key_str
        self._callbacks: dict[str, Callable[[], None]] = {}  # sound_id -> cb
        self._desktop_ids: dict[str, str] = {}  # sound_id -> desktop_id

        self._script_path = ("" if sys.platform.startswith("win")
                             else self._write_fire_script())
        self._server = None
        self._backend = "none"
        self.available_ = False
        self._evdev = None
        self._windows = None

        # DBus подсистема (для назначения клавиш)
        self._loop = None
        self._dbus = None
        self._iface = None
        self._ready = threading.Event()

        # Windows: pynput (клавиатура + боковые кнопки мыши, без root)
        if sys.platform.startswith("win") and windows_hotkeys is not None:
            try:
                if windows_hotkeys.available():
                    self._windows = windows_hotkeys.Listener(self._on_evdev_sound)
                    self._windows.start()
                    self._backend = "windows"
                    print("HOTKEY: backend windows (pynput, клавиатура + мышь)")
            except Exception as e:
                print(f"HOTKEY: windows-бэкенд недоступен: {e}")

        # evdev: мгновенное срабатывание + кнопки мыши (если есть доступ)
        if self._backend == "none" and evdev_hotkeys is not None:
            try:
                if evdev_hotkeys.available():
                    self._evdev = evdev_hotkeys.Listener(self._on_evdev_sound)
                    self._evdev.start()
                    self._backend = "evdev"
                    print("HOTKEY: backend evdev (прямое /dev/input, мышь поддерживается)")
                    threading.Thread(
                        target=self._teardown_commandshortcut, daemon=True).start()
            except Exception as e:
                print(f"HOTKEY: evdev недоступен: {e}")

        if (self._backend == "none" and not sys.platform.startswith("win")
                and _DBUS_AVAILABLE):
            self._dbus_thread = threading.Thread(target=self._run_dbus, daemon=True)
            self._dbus_thread.start()
            self._ready.wait(5.0)
            if self._backend == "commandshortcut":
                print("HOTKEY: backend KGlobalAccel (CommandShortcut); "
                      "для мыши/мгновенного срабатывания нужен доступ к /dev/input")

        # Сокет-сервер нужен только Linux-бэкенду CommandShortcut.
        if not sys.platform.startswith("win"):
            self._start_socket_server()

        self.available_ = self._backend in ("evdev", "windows", "commandshortcut")
        self.activated.connect(self._dispatch)

    # ------------------------------------------------------------------

    @property
    def available(self) -> bool:
        return self.available_

    @property
    def backend(self) -> str:
        return self._backend

    # ------------------------------------------------------------------
    # Fire-скрипт (вызывается из .desktop)
    # ------------------------------------------------------------------

    def _write_fire_script(self) -> str:
        # Постоянный путь (не /tmp — переживает перезагрузку и нужен .desktop)
        script_dir = Path.home() / ".local/share/hypermix"
        try:
            script_dir.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass
        path = str(script_dir / "fire.sh")
        main_py = str(Path(__file__).resolve().parent.parent.parent / "main.py")
        if getattr(sys, "frozen", False):
            run = f'"{Path(sys.executable).resolve()}"'
        else:
            run = f'python3 "{main_py}"'
        content = (
            "#!/bin/bash\n"
            "# HyperMix: отправляет id звука в сокет; если приложение не\n"
            "# запущено — стартует его и повторяет попытку.\n"
            "# socat заметно быстрее, чем запуск приложения на каждое нажатие.\n"
            f'SOCK="{SOCK_PATH}"\n'
            f'RUN=({run})\n'
            'send() {\n'
            '  if command -v socat >/dev/null 2>&1; then\n'
            '    printf "%s" "$1" | socat - "UNIX-CONNECT:$SOCK" 2>/dev/null\n'
            '    return $?\n'
            '  fi\n'
            '  "${RUN[@]}" --send "$1" 2>/dev/null\n'
            '}\n'
            'if send "$1"; then exit 0; fi\n'
            '(setsid "${RUN[@]}" >/dev/null 2>&1 &)\n'
            'for i in $(seq 1 40); do\n'
            '  sleep 0.1\n'
            '  if send "$1"; then exit 0; fi\n'
            'done\n'
            'exit 1\n'
        )
        with open(path, "w") as f:
            f.write(content)
        os.chmod(path, 0o755)
        return path

    # ------------------------------------------------------------------
    # Unix-сокет сервер
    # ------------------------------------------------------------------

    def _start_socket_server(self):
        try:
            if os.path.exists(SOCK_PATH):
                os.unlink(SOCK_PATH)
            self._server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            self._server.bind(SOCK_PATH)
            self._server.listen(8)
        except Exception as e:
            print(f"HOTKEY: не удалось открыть сокет: {e}")
            return
        threading.Thread(target=self._socket_loop, daemon=True).start()

    def _socket_loop(self):
        while True:
            try:
                conn, _ = self._server.accept()
            except Exception:
                break
            try:
                data = conn.recv(256).decode().strip()
            except Exception:
                data = ""
            finally:
                conn.close()
            if data:
                self.activated.emit(data)

    # ------------------------------------------------------------------
    # DBus (назначение клавиш в kglobalaccel)
    # ------------------------------------------------------------------

    def _run_dbus(self):
        import asyncio
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_until_complete(self._async_init())
            self._backend = "commandshortcut"
            self._ready.set()
            self._loop.run_forever()
        except Exception as e:
            print(f"HOTKEY: KGlobalAccel недоступен: {e}")
        finally:
            self._ready.set()

    async def _async_init(self):
        self._dbus = await MessageBus().connect()
        intro = await self._dbus.introspect(KGA_DEST, KGA_PATH)
        obj = self._dbus.get_proxy_object(KGA_DEST, KGA_PATH, intro)
        self._iface = obj.get_interface("org.kde.KGlobalAccel")
        await self._iface.call_all_components()

    def _submit(self, coro):
        import asyncio
        if self._loop is None:
            return
        asyncio.run_coroutine_threadsafe(coro, self._loop)

    # ------------------------------------------------------------------
    # Управление .desktop
    # ------------------------------------------------------------------

    def _write_desktop(self, sound_id: str) -> str:
        did = _desktop_id(sound_id)
        path = APPS_DIR / did
        content = (
            "[Desktop Entry]\n"
            f"Exec={self._script_path} {sound_id}\n"
            f"Name=HyperMix: {sound_id}\n"
            "NoDisplay=true\n"
            "StartupNotify=false\n"
            "Type=Application\n"
            "X-KDE-GlobalAccel-CommandShortcut=true\n"
        )
        APPS_DIR.mkdir(parents=True, exist_ok=True)
        with open(path, "w") as f:
            f.write(content)
        os.chmod(path, 0o600)
        self._desktop_ids[sound_id] = did
        return did

    def _remove_desktop(self, sound_id: str):
        did = self._desktop_ids.pop(sound_id, None)
        if did:
            try:
                (APPS_DIR / did).unlink(missing_ok=True)
            except Exception:
                pass

    def _refresh_kservice(self):
        for exe in ("kbuildsycoca6", "kbuildsycoca5"):
            try:
                subprocess.run([exe], capture_output=True, timeout=15)
                return
            except FileNotFoundError:
                continue
            except Exception:
                return

    def _write_kglobalshortcutsrc(self, mapping: dict[str, str]):
        """
        Пишет привязки в kglobalshortcutsrc: KWin подхватывает CommandShortcut
        из конфига. Формат: [services][<desktop_id>] \n _launch=<key>
        """
        p = Path.home() / ".config/kglobalshortcutsrc"
        try:
            text = p.read_text()
        except FileNotFoundError:
            text = ""
        import re
        for did, key in mapping.items():
            section = f"[services][{did}]"
            block = f"{section}\n_launch={key}\n"
            pat = re.compile(re.escape(section) + r"\n(?:_launch=.*\n)?")
            if pat.search(text):
                text = pat.sub(block, text)
            else:
                text = text.rstrip("\n") + "\n\n" + block
        try:
            p.write_text(text)
        except Exception as e:
            print(f"HOTKEY: не записать kglobalshortcutsrc: {e}")

    def _teardown_commandshortcut(self):
        """
        При работе через evdev убираем наши .desktop и записи KGlobalAccel,
        иначе клавиша сработает дважды (evdev + CommandShortcut).
        """
        try:
            for p in APPS_DIR.glob(f"{DESKTOP_PREFIX}*.desktop"):
                try:
                    p.unlink()
                except OSError:
                    pass
            self._desktop_ids.clear()
        except Exception:
            pass
        p = Path.home() / ".config/kglobalshortcutsrc"
        try:
            import re
            text = p.read_text()
            new = re.sub(
                r"\[services\]\[hypermix-[^\]]*\]\n(?:_launch=[^\n]*\n)?",
                "", text)
            if new != text:
                p.write_text(new)
                print("HOTKEY: KGlobalAccel-привязки HyperMix удалены (используется evdev)")
        except Exception:
            pass
        self._refresh_kservice()

    def _on_evdev_sound(self, sound_id: str):
        # вызывается из потока слушателя — сигнал безопасно доставит в GUI-поток
        print(f"HOTKEY[{self._backend}]: {sound_id}")
        self.activated.emit(sound_id)

    # ------------------------------------------------------------------
    # Публичный API
    # ------------------------------------------------------------------

    def begin_capture(self):
        """Ждёт следующее нажатие клавиши/кнопки мыши (для назначения)."""
        if self._evdev is not None:
            self._evdev.begin_capture(
                self.hotkey_captured.emit,
                lambda: self.hotkey_capture_blocked.emit())
        elif self._windows is not None:
            self._windows.begin_capture(
                self.hotkey_captured.emit,
                lambda: self.hotkey_capture_blocked.emit())

    def cancel_capture(self):
        if self._evdev is not None:
            self._evdev.cancel_capture()
        elif self._windows is not None:
            self._windows.cancel_capture()

    def bind(self, key_str: str, callback: Callable[[], None],
             sound_id: str = "", name: str = "") -> bool:
        if not key_str or not sound_id:
            return False
        if sys.platform.startswith("win") and self._backend != "windows":
            print("HOTKEY: на Windows глобальные клавиши требуют pynput")
            return False
        if evdev_hotkeys is not None and evdev_hotkeys.is_blocked(key_str):
            print(f"HOTKEY: {key_str} зарезервирована, бинд отклонён")
            return False
        is_mouse = (evdev_hotkeys is not None
                    and evdev_hotkeys.is_mouse_token(key_str))
        if is_mouse:
            norm = key_str
        elif self._backend == "windows" and windows_hotkeys is not None:
            norm = windows_hotkeys.canonical(key_str)
            if not norm:
                return False
        else:
            norm = QKeySequence(key_str).toString()
            if not norm:
                return False

        with self._lock:
            self._keys[sound_id] = norm
            self._callbacks[sound_id] = callback
        self._save_config_hotkey(sound_id, norm)

        if self._backend in ("evdev", "windows"):
            self._sync_native()
            print(f"HOTKEY[{self._backend}]: {sound_id} -> {norm}")
            return True

        self._write_desktop(sound_id)
        self._refresh_kservice()
        # назначаем клавишу через DBus setForeignShortcutKeys
        self._submit(self._async_set_foreign(_desktop_id(sound_id), norm))
        # и дублируем в конфиг для надёжного grab при следующем старте
        self._write_kglobalshortcutsrc({_desktop_id(sound_id): norm})
        return True

    def _sync_native(self):
        """Передаёт текущие привязки активному нативному слушателю."""
        with self._lock:
            mapping = {tok: sid for sid, tok in self._keys.items() if tok}
            target = self._evdev or self._windows
        if target is not None:
            target.set_bindings(mapping)

    def _sync_evdev(self):
        """Совместимость со старыми вызовами."""
        self._sync_native()

    # ------------------------------------------------------------------
    # Персистентность hotkeys (config.json)
    # ------------------------------------------------------------------

    def _load_config(self) -> dict:
        try:
            if CONFIG_PATH.exists():
                with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                    return json.load(f)
        except Exception:
            pass
        return {}

    def _save_config_hotkey(self, sound_id: str, key_str: str):
        cfg = self._load_config()
        hk = cfg.get("hotkeys", {})
        hk[sound_id] = key_str
        cfg["hotkeys"] = hk
        try:
            with open(CONFIG_PATH, "w", encoding="utf-8") as f:
                json.dump(cfg, f, indent=2, ensure_ascii=False)
        except Exception:
            pass

    def _remove_config_hotkey(self, sound_id: str):
        cfg = self._load_config()
        hk = cfg.get("hotkeys", {})
        if sound_id in hk:
            hk.pop(sound_id, None)
            cfg["hotkeys"] = hk
            try:
                with open(CONFIG_PATH, "w", encoding="utf-8") as f:
                    json.dump(cfg, f, indent=2, ensure_ascii=False)
            except Exception:
                pass

    def load_persisted(self) -> dict:
        """Возвращает сохранённые привязки {sound_id: key}. Только чтение."""
        return self._load_config().get("hotkeys", {})

    async def _async_set_foreign(self, desktop_id: str, key_str: str):
        seq = QKeySequence(key_str)
        keys = [seq[i].toCombined() for i in range(min(seq.count(), 4))]
        combo = [[keys]]
        args = [desktop_id, "_launch", desktop_id, desktop_id]
        try:
            await self._iface.call_do_register(args)
        except Exception:
            pass
        try:
            # флаги: SetPresent(2) | NoAutoloading(4) — обязателен SetPresent,
            # иначе shortcut не активируется и KWin не реагирует на клавишу
            await self._iface.call_set_shortcut_keys(args, combo, 6)
            print(f"HOTKEY: {desktop_id} -> {key_str}")
        except Exception as e:
            print(f"HOTKEY: ошибка назначения {desktop_id}: {e}")

    def unbind(self, sound_id: str):
        if sound_id not in self._keys:
            return
        with self._lock:
            self._keys.pop(sound_id, None)
            self._callbacks.pop(sound_id, None)
        self._remove_config_hotkey(sound_id)
        if self._backend in ("evdev", "windows"):
            self._sync_native()
            return
        self._remove_desktop(sound_id)
        self._refresh_kservice()

    def unbind_all(self):
        with self._lock:
            ids = list(self._keys.keys())
        for sid in ids:
            self.unbind(sid)

    def shutdown(self):
        """
        Завершение работы: закрывает сокет, но СОХРАНЯЕТ .desktop-файлы,
        чтобы горячие клавиши пережили перезапуск приложения.
        """
        if self._server is not None:
            try:
                self._server.close()
            except Exception:
                pass
            try:
                os.unlink(SOCK_PATH)
            except Exception:
                pass
        if self._evdev is not None:
            self._evdev.stop()
        if self._windows is not None:
            self._windows.stop()

    def rebind_all(self, mapping: dict[str, Callable[[], None]]):
        self.unbind_all()
        for sound_id, cb in mapping.items():
            self.bind("", cb, sound_id=sound_id)

    # ------------------------------------------------------------------

    def _dispatch(self, sound_id: str):
        with self._lock:
            cb = self._callbacks.get(sound_id)
        if cb is not None:
            try:
                cb()
            except Exception as e:
                print(f"HOTKEY: ошибка callback: {e}")
