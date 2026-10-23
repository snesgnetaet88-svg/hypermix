# HyperMix — модуль Windows-подсистемы
# ЭТАП 4: работа с виртуальным кабелем VB-Audio Cable
#
# Принцип (безопасность — ничего не ставим скрытно):
#   1. При запуске проверяем наличие устройства "CABLE Input"
#      (через пакет sounddevice / ffmpeg / реестр — см. detect_cable_input).
#   2. Если устройства нет — НЕ устанавливаем ничего автоматически:
#      - открываем браузер на https://vb-audio.com/Cable/
#      - показываем диалог с инструкцией для пользователя.
#   3. Если устройство найдено — используем его как цель для режима «Микрофон».

import os
import sys
import shutil
import subprocess
import webbrowser

# Ссылка на официальный драйвер (легальный, бесплатный)
VB_CABLE_URL = "https://vb-audio.com/Cable/"
# Имя устройства, которое создаёт VB-Cable (вход = наш "микрофон" для приложений)
CABLE_INPUT_NAME = "CABLE Input"


def is_windows() -> bool:
    return sys.platform.startswith("win")


# ----------------------------------------------------------------------
# Обнаружение CABLE Input
# ----------------------------------------------------------------------

def _detect_via_sounddevice():
    """
    Проверка через sounddevice (PortAudio).
    True/False — пакет работает и дал ответ; None — проверить не удалось.
    """
    try:
        import sounddevice as sd
        for dev in sd.query_devices():
            name = str(dev.get("name", ""))
            if CABLE_INPUT_NAME.lower() in name.lower():
                return True
        return False
    except Exception:
        return None


def _detect_via_ffmpeg() -> bool:
    """Запасная проверка через ffmpeg -list_devices (dshow на Windows)."""
    if shutil.which("ffmpeg") is None:
        return False
    try:
        res = subprocess.run(
            ["ffmpeg", "-hide_banner", "-list_devices", "true", "-f", "dshow", "-i", "dummy"],
            capture_output=True, text=True, timeout=15,
        )
        output = (res.stdout or "") + (res.stderr or "")
        return CABLE_INPUT_NAME.lower() in output.lower()
    except Exception:
        return False


def _detect_via_registry() -> bool:
    """
    Проверка реестра Windows: наличие ключей драйвера VB-Audio.
    (Быстро и не требует внешних библиотек.)
    """
    if not is_windows():
        return False
    keys = [
        r"SYSTEM\CurrentControlSet\Services\CABLE",
        r"SOFTWARE\VB Audio\VBCABLE",
    ]
    try:
        import winreg
        for key_path in keys:
            try:
                with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, key_path):
                    return True
            except OSError:
                continue
    except Exception:
        pass
    return False


def detect_cable_input() -> bool:
    """Определяет, установлен ли VB-Audio Cable (устройство CABLE Input)."""
    if not is_windows():
        return False
    via_sd = _detect_via_sounddevice()
    if via_sd is not None:
        return via_sd
    return _detect_via_ffmpeg() or _detect_via_registry()


# ----------------------------------------------------------------------
# Открытие страницы драйвера + диалог (вызывается из UI)
# ----------------------------------------------------------------------

def open_vb_cable_page():
    """Открывает официальную страницу VB-Audio Cable в браузере пользователя."""
    try:
        webbrowser.open(VB_CABLE_URL)
    except Exception:
        # Если браузер не открылся — печатаем ссылку в консоль
        print(f"HyperMix: откройте вручную {VB_CABLE_URL}", file=sys.stderr)


def show_cable_required_dialog(parent=None):
    """
    Показывает диалог: «Для работы HyperMix нужен бесплатный драйвер VB-Audio Cable...»
    Возвращает QMessageBox (чтобы вызывающий код мог further настроить).
    """
    from PyQt6.QtWidgets import QMessageBox, QPushButton

    box = QMessageBox(parent)
    box.setWindowTitle("HyperMix — требуется VB-Audio Cable")
    box.setIcon(QMessageBox.Icon.Warning)
    box.setText(
        "Для работы HyperMix нужен бесплатный драйвер VB-Audio Cable.\n\n"
        "Скачайте, установите и перезапустите программу."
    )
    box.setInformativeText(
        f"Страница загрузки будет открыта в браузере:\n{VB_CABLE_URL}"
    )
    # Кнопка «Открыть страницу»
    btn_open = box.addButton("Открыть страницу", QMessageBox.ButtonRole.ActionRole)
    btn_cancel = box.addButton("Продолжить без микрофона", QMessageBox.ButtonRole.RejectRole)
    box.setDefaultButton(btn_open)

    # Открываем браузер при показе диалога (по ТЗ: «Открой браузер на странице...»)
    open_vb_cable_page()

    box.exec()
    clicked = box.clickedButton()
    return clicked


def ensure_cable(parent=None) -> bool:
    """
    Точка входа при старте на Windows (ЭТАП 4).
    True — устройство найдено, режим «Микрофон» доступен.
    False — устройства нет, показан диалог с инструкцией; режим «Микрофон»
    будет помечен как недоступный.
    """
    if not is_windows():
        return False
    if detect_cable_input():
        return True
    # Нет устройства — НЕ ставим ничего скрытно: браузер + диалог
    show_cable_required_dialog(parent)
    return False


def cable_available() -> bool:
    """Краткая проверка без показа диалогов (для индикатора в UI)."""
    if not is_windows():
        return False
    return detect_cable_input()
