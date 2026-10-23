# HyperMix — глобальные горячие клавиши и кнопки мыши для Windows
#
# Бэкенд: pynput (без прав администратора, работает поверх Win32).
# Поддерживает клавиатуру (включая F1-F24 и модификаторы) и боковые
# кнопки мыши. ЛКМ/ПКМ намеренно не биндятся — как и в Linux-версии.
#
# Модуль можно импортировать на любой ОС: pynput требуется только для
# Listener/available(), поэтому парсер токенов тестируется отдельно.

from __future__ import annotations

import threading

from . import evdev_hotkeys as _tokens

MODIFIER_ORDER = _tokens.MODIFIER_ORDER
MODIFIER_ALIASES = _tokens.MODIFIER_ALIASES

# Имена pynput.Key -> токены в формате HyperMix (совместимы с Linux)
_KEY_NAME_MAP = {
    "space": "Space",
    "enter": "Return",
    "tab": "Tab",
    "esc": "Esc",
    "backspace": "Backspace",
    "delete": "Delete",
    "insert": "Insert",
    "home": "Home",
    "end": "End",
    "page_up": "PageUp",
    "page_down": "PageDown",
    "up": "Up",
    "down": "Down",
    "left": "Left",
    "right": "Right",
    "caps_lock": "CapsLock",
    "num_lock": "NumLock",
    "scroll_lock": "ScrollLock",
    "print_screen": "Print",
    "pause": "Pause",
    "menu": "Menu",
}
for _i in range(1, 25):
    _KEY_NAME_MAP[f"f{_i}"] = f"F{_i}"

# Модификаторы pynput -> канонические имена
_MODIFIER_NAMES = {
    "ctrl": "Ctrl", "ctrl_l": "Ctrl", "ctrl_r": "Ctrl",
    "alt": "Alt", "alt_l": "Alt", "alt_r": "Alt", "alt_gr": "Alt",
    "shift": "Shift", "shift_l": "Shift", "shift_r": "Shift",
    "cmd": "Meta", "cmd_l": "Meta", "cmd_r": "Meta",
}

# Windows Virtual-Key -> токен (для клавиш, у которых pynput не даёт name)
_VK_MAP = {
    0x08: "Backspace", 0x09: "Tab", 0x0D: "Return", 0x1B: "Esc",
    0x20: "Space", 0x21: "PageUp", 0x22: "PageDown", 0x23: "End",
    0x24: "Home", 0x25: "Left", 0x26: "Up", 0x27: "Right", 0x28: "Down",
    0x2D: "Insert", 0x2E: "Delete",
    # OEM-клавиши (раскладка US; для остальных сработает fallback по char)
    0xBA: ";", 0xBB: "=", 0xBC: ",", 0xBD: "-", 0xBE: ".",
    0xBF: "/", 0xC0: "`", 0xDB: "[", 0xDC: "\\", 0xDD: "]", 0xDE: "'",
    # Numpad
    0x60: "Num0", 0x61: "Num1", 0x62: "Num2", 0x63: "Num3",
    0x64: "Num4", 0x65: "Num5", 0x66: "Num6", 0x67: "Num7",
    0x68: "Num8", 0x69: "Num9",
    0x6A: "Num*", 0x6B: "Num+", 0x6D: "Num-", 0x6E: "Num.", 0x6F: "Num/",
}

# QKeySequence-имена -> канонические имена evdev
_BASE_ALIASES = {
    "PgUp": "PageUp",
    "PgDown": "PageDown",
    "Ins": "Insert",
    "Del": "Delete",
    "Enter": "Return",
    "Escape": "Esc",
    "Super": "Meta",
    "Win": "Meta",
}

# Кнопки мыши pynput -> токены HyperMix
_MOUSE_BUTTON_TOKENS = {
    "middle": "Mouse:Middle",
    "x1": "Mouse:Side",
    "x2": "Mouse:Extra",
}
_BLOCKED_BUTTONS = ("left", "right")


def available() -> bool:
    """Установлен ли pynput (на Windows обычно да)."""
    try:
        import pynput  # noqa: F401
        return True
    except Exception:
        return False


def _button_name(button) -> str:
    """pynput.mouse.Button -> короткое имя ('left', 'x1', ...)."""
    return str(button).split(".")[-1].lower()


def _key_token(key) -> str | None:
    """pynput-клавиша -> токен HyperMix (или None)."""
    name = getattr(key, "name", None)
    if name:
        if name in _MODIFIER_NAMES:
            return _MODIFIER_NAMES[name]
        if name in _KEY_NAME_MAP:
            return _KEY_NAME_MAP[name]

    vk = getattr(key, "vk", None)
    if isinstance(vk, int):
        if 0x41 <= vk <= 0x5A:       # A-Z
            return chr(vk)
        if 0x30 <= vk <= 0x39:       # 0-9
            return chr(vk)
        tok = _VK_MAP.get(vk)
        if tok:
            return tok

    ch = getattr(key, "char", None)
    if isinstance(ch, str) and len(ch) == 1 and ch.isprintable():
        return ch.upper() if ch.isalpha() else ch
    return None


def canonical(token: str) -> str:
    """
    Приводит токен к каноническому виду (как в Linux-конфиге).
    Возвращает "" для нераспознанной привязки.
    """
    if not token:
        return ""
    if _tokens.is_mouse_token(token) or _tokens.is_blocked(token):
        return token
    parts = [p.strip() for p in token.split("+") if p.strip()]
    if not parts:
        return ""
    mods: list[str] = []
    for p in parts[:-1]:
        p = MODIFIER_ALIASES.get(p, p)
        if p not in MODIFIER_ORDER:
            return ""
        if p not in mods:
            mods.append(p)
    base = _BASE_ALIASES.get(parts[-1], parts[-1])
    if base not in _tokens.NAME_TO_KEY:
        return ""
    ordered = [m for m in MODIFIER_ORDER if m in mods]
    return "+".join(ordered + [base])


def label_for(token: str) -> str:
    """Человекочитаемое имя привязки (общее с Linux)."""
    return _tokens.label_for(token)


class Listener:
    """
    Слушает клавиатуру и мышь через pynput.
    Вызывает on_sound(sound_id) при срабатывании привязки.
    """

    def __init__(self, on_sound):
        self._on_sound = on_sound
        self._on_capture = None
        self._on_blocked = None
        self._map: dict[str, str] = {}
        self._lock = threading.Lock()
        self._mods: set[str] = set()
        self._pressed: set[str] = set()
        self._kb = None
        self._ms = None
        self._started = False

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

    def start(self):
        if self._started:
            return
        from pynput import keyboard, mouse

        self._kb = keyboard.Listener(
            on_press=lambda key: self._handle_key(key, True),
            on_release=lambda key: self._handle_key(key, False),
        )
        self._kb.daemon = True
        self._kb.start()

        self._ms = mouse.Listener(
            on_click=lambda x, y, button, pressed: (
                self._handle_mouse(button) if pressed else None),
        )
        self._ms.daemon = True
        self._ms.start()
        self._started = True

    def stop(self):
        for listener in (self._kb, self._ms):
            if listener is not None:
                try:
                    listener.stop()
                except Exception:
                    pass
        self._kb = None
        self._ms = None
        self._started = False

    # -- обработка ----------------------------------------------------
    def _handle_key(self, key, down: bool):
        token = _key_token(key)
        if token is None:
            return

        if token in MODIFIER_ORDER:
            if down:
                self._mods.add(token)
            else:
                self._mods.discard(token)
            return

        if not down:
            self._pressed.discard(token)
            return
        if token in self._pressed:       # автоповтор Windows
            return
        self._pressed.add(token)

        with self._lock:
            mods = [m for m in MODIFIER_ORDER if m in self._mods]
            cb = self._on_capture
            if cb is not None:
                self._on_capture = None
            mapping = self._map

        combined = "+".join(mods + [token]) if mods else token
        if cb is not None:
            try:
                cb(combined)
            except Exception:
                pass
            return

        sid = mapping.get(combined) or mapping.get(token)
        if sid:
            self._sound(sid)

    def _handle_mouse(self, button):
        name = _button_name(button)
        with self._lock:
            blocked_cb = (self._on_blocked
                          if self._on_capture is not None else None)
        if name in _BLOCKED_BUTTONS:
            if blocked_cb is not None:
                try:
                    blocked_cb()
                except Exception:
                    pass
            return

        token = _MOUSE_BUTTON_TOKENS.get(name)
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

        sid = mapping.get(token)
        if sid:
            self._sound(sid)

    def _sound(self, sound_id: str):
        try:
            self._on_sound(sound_id)
        except Exception:
            pass
