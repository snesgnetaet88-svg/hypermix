# HyperMix — прямое чтение устройств ввода (/dev/input/event*)
#
# Зачем: KGlobalAccel/CommandShortcut не умеет боковые кнопки мыши, а запуск
# .desktop через systemd+fire.sh даёт заметную задержку. Прямое чтение
# event-устройств даёт срабатывание за единицы миллисекунд и любые кнопки мыши.
#
# Требуется доступ на чтение /dev/input/event* — пользователь должен быть
# в группе input (sudo usermod -aG input $USER + перелогин) либо udev-правило.
# Если доступа нет — available() вернёт False, и приложение откатится на
# KGlobalAccel (мышь в этом режиме недоступна).
#
# Реализовано на чистом stdlib (struct/select/fcntl), без python-evdev.

from __future__ import annotations

try:
    import fcntl
except ImportError:  # Windows: модуля нет, evdev-бэкенд недоступен
    fcntl = None

import glob
import os
import select
import struct
import threading
import time

EV_KEY = 1

# --- кнопки мыши ------------------------------------------------------
BTN_LEFT = 0x110
BTN_RIGHT = 0x111
BTN_MIDDLE = 0x112
BTN_SIDE = 0x113
BTN_EXTRA = 0x114
BTN_FORWARD = 0x115
BTN_BACK = 0x116
BTN_TASK = 0x117

# ЛКМ/ПКМ не биндятся: это обычные клики, их перехват ломает работу с окном
BLOCKED_MOUSE_CODES = frozenset({BTN_LEFT, BTN_RIGHT})

MOUSE_TOKENS = {
    "Mouse:Middle": BTN_MIDDLE,
    "Mouse:Side": BTN_SIDE,
    "Mouse:Extra": BTN_EXTRA,
    "Mouse:Forward": BTN_FORWARD,
    "Mouse:Back": BTN_BACK,
    "Mouse:Task": BTN_TASK,
}
MOUSE_CODE_TO_TOKEN = {c: t for t, c in MOUSE_TOKENS.items()}

MOUSE_LABELS = {
    "Mouse:Middle": "Мышь: средняя",
    "Mouse:Side": "Мышь: боковая",
    "Mouse:Extra": "Мышь: доп.",
    "Mouse:Back": "Мышь: назад",
    "Mouse:Forward": "Мышь: вперёд",
    "Mouse:Task": "Мышь: задача",
}

# --- клавиатура (linux/input-event-codes.h) ---------------------------
KEY_NAMES = {
    1: "Esc", 2: "1", 3: "2", 4: "3", 5: "4", 6: "5", 7: "6", 8: "7",
    9: "8", 10: "9", 11: "0", 12: "-", 13: "=", 14: "Backspace", 15: "Tab",
    16: "Q", 17: "W", 18: "E", 19: "R", 20: "T", 21: "Y", 22: "U", 23: "I",
    24: "O", 25: "P", 26: "[", 27: "]", 28: "Return", 29: "Ctrl",
    30: "A", 31: "S", 32: "D", 33: "F", 34: "G", 35: "H", 36: "J", 37: "K",
    38: "L", 39: ";", 40: "'", 41: "`", 42: "Shift", 43: "\\",
    44: "Z", 45: "X", 46: "C", 47: "V", 48: "B", 49: "N", 50: "M",
    51: ",", 52: ".", 53: "/", 54: "Shift", 55: "*", 56: "Alt", 57: "Space",
    58: "CapsLock",
    59: "F1", 60: "F2", 61: "F3", 62: "F4", 63: "F5", 64: "F6", 65: "F7",
    66: "F8", 67: "F9", 68: "F10", 69: "NumLock", 70: "ScrollLock",
    71: "Num7", 72: "Num8", 73: "Num9", 74: "Num-", 75: "Num4", 76: "Num5",
    77: "Num6", 78: "Num+", 79: "Num1", 80: "Num2", 81: "Num3", 82: "Num0",
    83: "Num.", 87: "F11", 88: "F12", 96: "NumEnter", 97: "Ctrl",
    98: "Num/", 99: "Print", 100: "Alt", 102: "Home", 103: "Up",
    104: "PageUp", 105: "Left", 106: "Right", 107: "End", 108: "Down",
    109: "PageDown", 110: "Insert", 111: "Delete", 113: "Mute",
    114: "VolumeDown", 115: "VolumeUp", 119: "Pause",
    121: "Num,", 122: "Hangul", 123: "Hanja", 124: "Yen", 125: "Meta",
    126: "Meta", 127: "Compose",
    128: "Stop", 129: "Again", 130: "Props", 131: "Undo", 132: "Front",
    133: "Copy", 134: "Open", 135: "Paste", 136: "Find", 137: "Cut",
    138: "Help", 139: "Menu", 140: "Calc", 141: "Setup", 142: "Sleep",
    143: "WakeUp", 144: "File", 145: "SendFile", 146: "DeleteFile",
    147: "Xfer", 148: "Prog1", 149: "Prog2", 150: "WWW", 151: "MSDOS",
    152: "Coffee", 153: "Direction", 154: "CycleWindows", 155: "Mail",
    156: "Bookmarks", 157: "Computer", 158: "Back", 159: "Forward",
    160: "CloseCD", 161: "EjectCD", 163: "NextSong", 164: "PlayPause",
    165: "PreviousSong", 166: "StopCD", 167: "Record", 168: "Rewind",
    169: "Phone", 171: "Config", 172: "HomePage", 173: "Refresh",
    174: "Exit", 175: "Move", 176: "Edit", 177: "ScrollUp",
    178: "ScrollDown", 179: "KPLeft", 180: "KPRight", 181: "KPEnter",
    182: "KPDelete", 183: "F13", 184: "F14", 185: "F15", 186: "F16",
    187: "F17", 188: "F18", 189: "F19", 190: "F20", 191: "F21",
    192: "F22", 193: "F23", 194: "F24", 200: "Play", 201: "Pause",
    212: "Camera", 217: "Search", 224: "BrightnessDown",
    225: "BrightnessUp", 226: "Media", 240: "Unknown",
}
NAME_TO_KEY = {v: k for k, v in KEY_NAMES.items()}
# "Enter" — привычное имя для Return
NAME_TO_KEY.setdefault("Enter", 28)
# Имена, которые возвращает QKeySequence.toString() (для переносимого config.json)
NAME_TO_KEY.setdefault("Escape", 1)
NAME_TO_KEY.setdefault("PgUp", 104)
NAME_TO_KEY.setdefault("PgDown", 109)
NAME_TO_KEY.setdefault("Ins", 110)
NAME_TO_KEY.setdefault("Del", 111)
NAME_TO_KEY.setdefault("Space", 57)

MODIFIER_CODES = {
    29: "Ctrl", 97: "Ctrl",
    56: "Alt", 100: "Alt",
    42: "Shift", 54: "Shift",
    125: "Meta", 126: "Meta",
}
MODIFIER_ORDER = ("Ctrl", "Alt", "Shift", "Meta")
MODIFIER_ALIASES = {
    "Control": "Ctrl", "Ctl": "Ctrl",
    "Super": "Meta", "Win": "Meta", "Cmd": "Meta", "Command": "Meta",
}

_EVENT_SIZE = struct.calcsize("llHHi")  # 24 байта на 64-bit


def _ioc_read(nr: int, size: int, typ: int = ord("E")) -> int:
    return (2 << 30) | (size << 16) | (typ << 8) | nr


def _has_key_events(fd: int) -> bool:
    """Есть ли у устройства события EV_KEY (кнопки/клавиши)."""
    if fcntl is None:
        return False
    try:
        buf = fcntl.ioctl(fd, _ioc_read(0x20 + 0, 8), bytes(8))  # EVIOCGBIT(0)
    except OSError:
        return False
    return bool(buf[0] & (1 << EV_KEY))


def is_mouse_token(text: str) -> bool:
    return text in MOUSE_TOKENS


def is_blocked(text: str) -> bool:
    """ЛКМ/ПКМ: биндить нельзя."""
    return text in ("Mouse:Left", "Mouse:Right")


def label_for(token: str) -> str:
    """Человекочитаемое имя привязки."""
    if token in MOUSE_LABELS:
        return MOUSE_LABELS[token]
    return token


def parse_binding(text: str):
    """
    'F9'        -> (67, frozenset(), False)
    'Ctrl+Alt+H'-> (35, {'Ctrl','Alt'}, False)
    'Mouse:Side'-> (275, frozenset(), True)
    """
    if not text:
        return None
    if text in MOUSE_TOKENS:
        return MOUSE_TOKENS[text], frozenset(), True
    parts = [p.strip() for p in text.split("+") if p.strip()]
    if not parts:
        return None
    mods = set()
    for p in parts[:-1]:
        p = MODIFIER_ALIASES.get(p, p)
        if p not in MODIFIER_ORDER:
            return None
        mods.add(p)
    code = NAME_TO_KEY.get(parts[-1])
    if code is None:
        return None
    return code, frozenset(mods), False


def _devices() -> list[str]:
    return sorted(glob.glob("/dev/input/event*"))


def available() -> bool:
    """True, если есть хотя бы одно читаемое устройство с клавишами/кнопками."""
    if fcntl is None:
        return False
    for path in _devices():
        try:
            fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
        except OSError:
            continue
        try:
            if _has_key_events(fd):
                return True
        finally:
            os.close(fd)
    return False


class Listener(threading.Thread):
    """
    Слушает все доступные /dev/input/event*, вызывает on_sound(sound_id)
    при нажатии привязанной клавиши/кнопки мыши.
    """

    def __init__(self, on_sound):
        super().__init__(daemon=True, name="hypermix-evdev")
        self._on_sound = on_sound
        self._on_capture = None
        self._on_blocked = None
        self._map: dict[str, str] = {}
        self._lock = threading.Lock()
        self._fds: dict[int, str] = {}
        self._mods: set[str] = set()
        self._last_key = None  # (code, monotonic) — защита от дублей с разных устройств
        self._stop = threading.Event()

    # -- управление ---------------------------------------------------
    def set_bindings(self, token_to_sound: dict[str, str]):
        with self._lock:
            self._map = dict(token_to_sound)

    def begin_capture(self, callback, on_blocked=None):
        with self._lock:
            self._on_capture = callback
            self._on_blocked = on_blocked

    def cancel_capture(self):
        with self._lock:
            self._on_capture = None
            self._on_blocked = None

    def stop(self):
        self._stop.set()
        try:
            self.join(1.0)
        except Exception:
            pass

    # -- устройства ---------------------------------------------------
    def _refresh_devices(self):
        for path in _devices():
            if path in self._fds.values():
                continue
            try:
                fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
            except OSError:
                continue
            if not _has_key_events(fd):
                os.close(fd)
                continue
            self._fds[fd] = path

    def _close_all(self):
        for fd in list(self._fds):
            try:
                os.close(fd)
            except OSError:
                pass
        self._fds.clear()

    # -- цикл ---------------------------------------------------------
    def run(self):
        while not self._stop.is_set():
            self._refresh_devices()
            if not self._fds:
                self._stop.wait(1.0)
                continue
            try:
                readable, _, _ = select.select(list(self._fds), [], [], 0.5)
            except (OSError, ValueError):
                self._close_all()
                self._stop.wait(0.5)
                continue
            for fd in readable:
                if not self._read_fd(fd):
                    try:
                        os.close(fd)
                    except OSError:
                        pass
                    self._fds.pop(fd, None)

    def _read_fd(self, fd: int) -> bool:
        try:
            data = os.read(fd, _EVENT_SIZE * 128)
        except OSError:
            return False
        if not data:
            return False
        n = len(data) // _EVENT_SIZE
        for i in range(n):
            _, _, etype, code, value = struct.unpack_from(
                "llHHi", data, i * _EVENT_SIZE)
            if etype == EV_KEY:
                self._handle_key(code, value)
        return True

    def _handle_key(self, code: int, value: int):
        if code in MODIFIER_CODES:
            mod = MODIFIER_CODES[code]
            if value == 1:
                self._mods.add(mod)
            elif value == 0:
                self._mods.discard(mod)
            return
        if value != 1:  # 2 — автоповтор, 0 — отпускание
            return

        # одна физическая кнопка может приходить с нескольких интерфейсов
        # устройства (например, side-кнопка мыши и как KEY_BACK) — гасим дубли
        now = time.monotonic()
        with self._lock:
            last = self._last_key
            if last is not None and last[0] == code and now - last[1] < 0.03:
                return
            self._last_key = (code, now)

        if code in BLOCKED_MOUSE_CODES:
            # ЛКМ/ПКМ: сообщаем диалогу, что кнопка не подходит
            with self._lock:
                blocked = self._on_blocked if self._on_capture is not None else None
            if blocked is not None:
                try:
                    blocked()
                except Exception:
                    pass
            return

        token = MOUSE_CODE_TO_TOKEN.get(code) or KEY_NAMES.get(code)
        if token is None:
            return

        with self._lock:
            cb = self._on_capture
            if cb is not None:
                self._on_capture = None
            mapping = self._map

        if cb is not None:
            try:
                cb(token)
            except Exception:
                pass
            return

        candidates = [token]
        if self._mods and token not in MOUSE_TOKENS:
            order = [m for m in MODIFIER_ORDER if m in self._mods]
            candidates.insert(0, "+".join(order + [token]))

        with self._lock:
            sid = None
            for cand in candidates:
                if cand in self._map:
                    sid = self._map[cand]
                    break
        if sid:
            try:
                self._on_sound(sid)
            except Exception:
                pass
