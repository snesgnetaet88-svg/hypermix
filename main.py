#!/usr/bin/env python3
# HyperMix — точка входа приложения
# Аудио-микшер с функциями звуковой панели
# by hypermarket

import os
import signal
import socket
import sys
import platform

from hypermix import __version__, __author__


def main() -> int:
    """Запуск HyperMix."""
    if "--version" in sys.argv or "-V" in sys.argv:
        print(f"HyperMix {__version__} by {__author__}")
        return 0

    if "--send" in sys.argv:
        idx = sys.argv.index("--send")
        if idx + 1 >= len(sys.argv):
            print("HyperMix: --send требует id звука", file=sys.stderr)
            return 2
        from hypermix.audio.hotkeys import send_sound_id
        return 0 if send_sound_id(sys.argv[idx + 1]) else 1

    if "--check" in sys.argv:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PyQt6.QtWidgets import QApplication
        QApplication(sys.argv[:1])
        from hypermix.audio.engine import AudioEngine  # noqa: F401
        from hypermix.ui.main_window import MainWindow  # noqa: F401
        print(f"HyperMix {__version__}: check OK")
        return 0

    from PyQt6.QtCore import QSocketNotifier, QTimer
    from PyQt6.QtWidgets import QApplication

    from hypermix.ui.main_window import MainWindow
    from hypermix.ui.themes import get_theme, load_theme_name
    from hypermix.platform.manager import PlatformManager

    app = QApplication(sys.argv)
    app.setApplicationName("HyperMix")
    app.setApplicationVersion(__version__)
    app.setOrganizationName("hypermarket")
    from PyQt6.QtGui import QIcon
    from hypermix.paths import resource_path
    icon_path = resource_path("assets/hypermix.png")
    if icon_path.exists():
        app.setWindowIcon(QIcon(str(icon_path)))

    # ЭТАП 4: загрузка темы из config.json (по умолчанию Dark)
    theme_name = load_theme_name()
    app.setStyleSheet(get_theme(theme_name))

    # Платформенная подсистема (виртуальный микрофон)
    platform_mgr = PlatformManager()

    # Главное окно (тема применится повторно внутри — безвредно)
    window = MainWindow(platform_manager=platform_mgr)
    window.show()

    # Виртуальный микрофон (после show, чтобы диалог имел parent)
    status = platform_mgr.startup(parent=window)
    window.notify(status)
    window.update_platform_status()

    if sys.platform.startswith("win"):
        # Windows: set_wakeup_fd недоступен; очистка идёт из closeEvent.
        def _win_quit(signum, _frame):
            QTimer.singleShot(0, app.quit)

        for _sig in (signal.SIGINT, signal.SIGTERM):
            try:
                signal.signal(_sig, _win_quit)
            except Exception:
                pass
    else:
        # Корректное завершение по SIGTERM/SIGINT (иначе модули PipeWire
        # остаются висеть, а микрофон по умолчанию — переключённым).
        # Python не выполняет обработчики сигналов, пока главный поток
        # заблокирован в event loop Qt — поэтому используем self-pipe
        # (signal.set_wakeup_fd) + QSocketNotifier.
        sig_r, sig_w = socket.socketpair()
        # set_wakeup_fd требует неблокирующий файловый дескриптор
        os.set_blocking(sig_w.fileno(), False)
        signal.set_wakeup_fd(sig_w.fileno())

        def _on_signal_ready():
            try:
                sig_r.recv(4096)
            except OSError:
                pass
            app.quit()

        notifier = QSocketNotifier(sig_r.fileno(), QSocketNotifier.Type.Read)
        notifier.activated.connect(_on_signal_ready)

        def _handle_signal(signum, _frame):
            try:
                os.write(sig_w.fileno(), b"\x00")
            except OSError:
                pass

        signal.signal(signal.SIGTERM, _handle_signal)
        signal.signal(signal.SIGINT, _handle_signal)

    # На случай закрытия окна — выгружаем модули
    app.aboutToQuit.connect(platform_mgr.shutdown)

    print(f"HyperMix запущен на {platform.system()} ({platform.platform()})")
    print(f"Тема: {theme_name}")
    print(f"Платформа: {status}")

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
