# HyperMix — главное окно приложения
# ЭТАП 1: интерфейс | ЭТАП 2: воспроизведение + хоткеи
# ЭТАП 3: минимализм (без эмодзи) | ЭТАП 4: темы | ЭТАП 5: матрица

import hashlib
import sys

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QAction, QActionGroup, QKeySequence
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QDialog,
    QToolBar, QTableWidget, QTableWidgetItem, QSlider,
    QPushButton, QLabel, QProgressBar, QFileDialog,
    QHeaderView, QAbstractItemView, QKeySequenceEdit,
    QInputDialog, QHBoxLayout, QMenu, QSizePolicy,
)

from ..audio.engine import AudioEngine, SoundItem, format_time, PlaybackTracker
from ..audio.hotkeys import HotkeyManager
from ..audio import evdev_hotkeys
from .themes import (
    MatrixWidget, get_theme, load_theme_name, save_theme_name, THEMES,
    load_config, save_config,
)


# Поддерживаемые форматы аудио
AUDIO_FILTER = "Аудио файлы (*.wav *.mp3 *.ogg *.flac);;Все файлы (*)"


def sound_uid(path: str) -> str:
    """Детерминированный uid звука по пути (совпадает с SoundItem.uid)."""
    return hashlib.sha1(path.encode("utf-8")).hexdigest()[:12]


HOTKEY_TOKEN_ROLE = Qt.ItemDataRole.UserRole + 1


class HotkeyCaptureDialog(QDialog):
    """Ожидает нажатия клавиши или кнопки мыши (нативный слушатель)."""

    def __init__(self, hotkeys, parent=None, timeout_ms: int = 6000):
        super().__init__(parent)
        self._hotkeys = hotkeys
        self.token = ""
        self.setWindowTitle("Назначение клавиши")
        self.setModal(True)
        self.setMinimumWidth(380)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        lay = QVBoxLayout(self)
        self._msg = QLabel(
            "Нажмите клавишу или кнопку мыши…\n"
            "Боковые кнопки мыши поддерживаются; ЛКМ/ПКМ не биндятся.")
        self._msg.setWordWrap(True)
        lay.addWidget(self._msg)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.reject)
        self._timer.start(timeout_ms)
        hotkeys.hotkey_captured.connect(self._on_captured)
        hotkeys.hotkey_capture_blocked.connect(self._on_blocked)
        self.finished.connect(self._cleanup)
        QTimer.singleShot(0, hotkeys.begin_capture)

    def _on_captured(self, token: str):
        self.token = token
        self.accept()

    def _on_blocked(self, *_):
        self._msg.setText(
            "Левая и правая кнопки мыши не поддерживаются.\n"
            "Нажмите другую клавишу или боковую кнопку.")
        if self._timer.isActive():
            self._timer.start()  # продлеваем ожидание

    def _cleanup(self, *_):
        for sig, slot in ((self._hotkeys.hotkey_captured, self._on_captured),
                          (self._hotkeys.hotkey_capture_blocked, self._on_blocked)):
            try:
                sig.disconnect(slot)
            except Exception:
                pass
        self._hotkeys.cancel_capture()


class MainWindow(QMainWindow):
    """Главное окно HyperMix: панель управления + таблица звуков + статус-бар."""

    def __init__(self, platform_manager=None):
        super().__init__()
        # --- Платформа (ЭТАП 3 старый / виртуальный микрофон) ---
        self.platform = platform_manager
        # --- Аудио-подсистема (ЭТАП 1: фикс драйвера) ---
        self.engine = AudioEngine()
        self._mixer_error = not self.engine.init()
        if self.platform is not None:
            self.platform.attach_engine(self.engine)
        if sys.platform.startswith("win") and self.engine.ready:
            try:
                saved_mic = load_config().get("windows_voice_source", "")
                if saved_mic:
                    self.engine.set_voice_source(saved_mic)
            except Exception:
                pass
        self.tracker = PlaybackTracker(self.engine)
        self.engine.on_finished = self._on_playback_finished
        self.hotkeys = HotkeyManager()

        # --- Тема (ЭТАП 4) ---
        self.theme_name = load_theme_name()

        # Таймер прогресса
        self._progress_timer = QTimer(self)
        self._progress_timer.setInterval(100)
        self._progress_timer.timeout.connect(self._update_progress)

        self._editing_row = -1
        self._key_edit = None
        self._current_item: SoundItem | None = None

        self._setup_window()
        self._build_toolbar()      # сначала тулбар (нужен для меню «Вид»)
        self._build_menu()
        self._build_central()
        self._build_statusbar()
        self._connect_signals()
        self.apply_theme(self.theme_name)

        # ЭТАП 6: восстановление библиотеки звуков и горячих клавиш
        self._restore_library()

        if self._mixer_error:
            self.notify("Ошибка: аудио-микшер недоступен")
        else:
            self.notify("Готово. Добавьте звуковые файлы.")
        if not self.hotkeys.available:
            self.notify("Глобальные клавиши недоступны (нет KGlobalAccel)")

    # ------------------------------------------------------------------
    # ЭТАП 1: базовая настройка окна
    # ------------------------------------------------------------------

    def _setup_window(self):
        self.setWindowTitle("HyperMix — by hypermarket")
        self.resize(1000, 700)
        self.setMinimumSize(800, 500)

    # ------------------------------------------------------------------
    # ЭТАП 4: меню «Настройки» -> «Тема»
    # ------------------------------------------------------------------

    def _build_menu(self):
        menubar = self.menuBar()
        # Запрещаем скрытие меню-бара через правый клик
        menubar.setContextMenuPolicy(Qt.ContextMenuPolicy.NoContextMenu)

        # Меню «Вид» — восстановление панели инструментов (если скрыли)
        view_menu = menubar.addMenu("Вид")
        # toggleViewAction() — готовое действие Qt: чекбокс «Панель инструментов»
        self._toolbar_action = self.toolbar.toggleViewAction()
        self._toolbar_action.setText("Панель инструментов")
        view_menu.addAction(self._toolbar_action)

        # Пункт «Восстановить всё» — показать все панели сразу
        restore_act = QAction("Восстановить всё\tCtrl+Shift+H", self)
        restore_act.triggered.connect(self.restore_ui)
        view_menu.addAction(restore_act)

        # Меню «Настройки»
        settings_menu = menubar.addMenu("Настройки")

        # Подменю «Тема» (радиогруппа)
        theme_menu = settings_menu.addMenu("Тема")
        self._theme_group = QActionGroup(self)
        self._theme_group.setExclusive(True)
        self._theme_actions: dict[str, QAction] = {}
        for name in THEMES:
            act = QAction(name, self, checkable=True)
            act.triggered.connect(lambda checked, n=name: self.apply_theme(n))
            self._theme_group.addAction(act)
            theme_menu.addAction(act)
            self._theme_actions[name] = act

        # Глобальная горячая клавиша приложения: Ctrl+Shift+H
        # Всегда вернёт панель инструментов, меню и поднимет окно
        from PyQt6.QtGui import QShortcut
        sc = QShortcut(QKeySequence("Ctrl+Shift+H"), self)
        sc.setContext(Qt.ShortcutContext.WindowShortcut)
        sc.activated.connect(self.restore_ui)

    def restore_ui(self):
        """Восстанавливает все панели и поднимает окно на передний план."""
        self.toolbar.show()
        self.menuBar().show()
        self.statusBar().show()
        self.raise_()
        self.activateWindow()
        self.notify("Панели восстановлены (Ctrl+Shift+H)")

    def apply_theme(self, name: str):
        """Применяет тему: QSS + видимость матрицы (ЭТАП 4 + 5)."""
        self.theme_name = name
        from PyQt6.QtWidgets import QApplication
        qapp = QApplication.instance()
        if qapp is not None:
            qapp.setStyleSheet(get_theme(name))
        # Отметка в меню
        act = self._theme_actions.get(name)
        if act is not None:
            act.setChecked(True)
        # Матрица — только для Hacker (ЭТАП 5.4)
        self.matrix.set_active(name == "Hacker")
        # Сохраняем выбор в config.json (ЭТАП 4.3)
        save_theme_name(name)

    # ------------------------------------------------------------------
    # ЭТАП 3: тулбар без эмодзи, компактные кнопки
    # ------------------------------------------------------------------

    def _build_toolbar(self):
        tb = QToolBar("Основная панель")
        tb.setMovable(False)
        tb.setFloatable(False)
        # Запрещаем скрытие через правый клик — случайно спрятанную панель
        # сложно вернуть; показ/скрытие только через меню «Вид»
        tb.setContextMenuPolicy(Qt.ContextMenuPolicy.NoContextMenu)
        tb.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        self.toolbar = tb
        self.addToolBar(tb)

        # --- Запись ---
        self.btn_record = QPushButton("[REC]")
        self.btn_record.setObjectName("btnRecord")
        self.btn_record.setCheckable(True)
        self.btn_record.setToolTip("Записать звук с микрофона")
        self.btn_record.clicked.connect(self._on_record_clicked)
        tb.addWidget(self.btn_record)
        tb.addSeparator()

        # --- Режимы (компактные) ---
        self.btn_speakers = QPushButton("[SPK]")
        self.btn_speakers.setCheckable(True)
        self.btn_speakers.setChecked(True)
        self.btn_speakers.setToolTip("Воспроизведение через динамики")

        self.btn_mic = QPushButton("[MIC]")
        self.btn_mic.setCheckable(True)
        self.btn_mic.setToolTip("Направлять звук в виртуальный микрофон")

        self.btn_both = QPushButton("[BOTH]")
        self.btn_both.setCheckable(True)
        self.btn_both.setToolTip("В динамики и микрофон одновременно")

        tb.addWidget(self.btn_speakers)
        tb.addWidget(self.btn_mic)
        tb.addWidget(self.btn_both)
        tb.addSeparator()

        # --- Выбор микрофона (источник голоса) ---
        self.btn_pick_mic = QPushButton("[Источник]")
        self.btn_pick_mic.setToolTip(
            "Выбрать микрофон, из которого берётся голос")
        self.btn_pick_mic.clicked.connect(self._on_pick_mic_clicked)
        tb.addWidget(self.btn_pick_mic)
        tb.addSeparator()

        # --- Управление ---
        self.btn_stop = QPushButton("[STOP]")
        self.btn_stop.setToolTip("Остановить воспроизведение")
        self.btn_play = QPushButton("[PLAY]")
        self.btn_play.setToolTip("Запустить выбранный звук")
        tb.addWidget(self.btn_stop)
        tb.addWidget(self.btn_play)

        # --- Громкость ---
        tb.addWidget(QLabel(" Vol:"))
        self.volume_slider = QSlider(Qt.Orientation.Horizontal)
        self.volume_slider.setRange(0, 100)
        self.volume_slider.setValue(80)
        self.volume_slider.setFixedWidth(100)
        tb.addWidget(self.volume_slider)

        self.lbl_volume_val = QLabel("80%")
        self.lbl_volume_val.setObjectName("volumeLabel")
        tb.addWidget(self.lbl_volume_val)
        tb.addSeparator()

        # --- Прогресс и время ---
        self.progress = QProgressBar()
        self.progress.setRange(0, 1000)
        self.progress.setValue(0)
        self.progress.setFixedWidth(200)
        tb.addWidget(self.progress)

        self.lbl_time = QLabel("00:00 / 00:00")
        self.lbl_time.setObjectName("timeLabel")
        tb.addWidget(self.lbl_time)
        tb.addSeparator()

        self.mode = "speakers"

    # ------------------------------------------------------------------
    # ЭТАП 5: центральная часть — матрица ПОД таблицей
    # ------------------------------------------------------------------

    def _build_central(self):
        from PyQt6.QtWidgets import QGridLayout
        central = QWidget()
        layout = QVBoxLayout(central)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(0)

        # Сетка с наложением: матрица (фон) + таблица (поверх)
        self._stack = QWidget()
        grid = QGridLayout(self._stack)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(0)

        # Матрица — ПОД таблицей (ЭТАП 5.2)
        self.matrix = MatrixWidget(self._stack)
        grid.addWidget(self.matrix, 0, 0)

        # Таблица — поверх матрицы
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["№", "Название", "Длительность", "Клавиша"])
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setAlternatingRowColors(True)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)

        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)
        self.table.setColumnWidth(0, 40)
        self.table.setColumnWidth(2, 100)
        self.table.setColumnWidth(3, 120)

        self.table.cellDoubleClicked.connect(self._on_cell_double_clicked)
        self.table.setContextMenuPolicy(
            Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._show_table_menu)
        grid.addWidget(self.table, 0, 0)  # поверх матрицы

        # Крупные кнопки над таблицей — всегда видны в оконном режиме
        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 2)
        top.setSpacing(4)
        self.btn_add = QPushButton("[+ ДОБАВИТЬ ЗВУК]")
        self.btn_add.setObjectName("btnAddMain")
        self.btn_add.setToolTip("Добавить звуковые файлы")
        self.btn_add.setMinimumHeight(36)
        self.btn_add.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.btn_del = QPushButton("[УДАЛИТЬ]")
        self.btn_del.setObjectName("btnDelMain")
        self.btn_del.setToolTip(
            "Удалить выбранный звук (или через правый клик по таблице)")
        self.btn_del.setMinimumHeight(36)
        top.addWidget(self.btn_add, 1)
        top.addWidget(self.btn_del, 0)
        layout.addLayout(top)

        layout.addWidget(self._stack)
        self.setCentralWidget(central)

    # ------------------------------------------------------------------
    # Статус-бар
    # ------------------------------------------------------------------

    def _build_statusbar(self):
        from PyQt6.QtWidgets import QStatusBar
        sb = QStatusBar()
        self.setStatusBar(sb)

        self.lbl_mode = QLabel("Mode: [SPK]")
        self.lbl_mode.setObjectName("modeIndicator")
        sb.addWidget(self.lbl_mode)

        self.lbl_mic_text = QLabel("MIC:")
        sb.addPermanentWidget(self.lbl_mic_text)

        self.mic_level_bar = QProgressBar()
        self.mic_level_bar.setRange(0, 100)
        self.mic_level_bar.setValue(0)
        self.mic_level_bar.setFixedWidth(120)
        self.mic_level_bar.setFixedHeight(10)
        self.mic_level_bar.setTextVisible(False)
        self.mic_level_bar.setObjectName("micLevel")
        sb.addPermanentWidget(self.mic_level_bar)

        self.lbl_notify = QLabel("—")
        self.lbl_notify.setObjectName("notificationLabel")
        sb.addPermanentWidget(self.lbl_notify)

    def _connect_signals(self):
        self.btn_speakers.clicked.connect(lambda: self._set_mode("speakers"))
        self.btn_mic.clicked.connect(lambda: self._set_mode("mic"))
        self.btn_both.clicked.connect(lambda: self._set_mode("both"))
        self.volume_slider.valueChanged.connect(self._on_volume_changed)
        self.btn_add.clicked.connect(self._on_add_clicked)
        self.btn_del.clicked.connect(self._delete_selected_sound)
        self.btn_play.clicked.connect(self._on_play_clicked)
        self.btn_stop.clicked.connect(self._on_stop_clicked)

    # ------------------------------------------------------------------
    # ЭТАП 2: воспроизведение
    # ------------------------------------------------------------------

    def _on_add_clicked(self):
        files, _ = QFileDialog.getOpenFileNames(
            self, "Добавить звуки", "", AUDIO_FILTER)
        if not files:
            return
        added = 0
        for path in files:
            if self._add_sound_row(path) is not None:
                added += 1
        if added:
            self.notify(f"Добавлено: {added}")
            self.table.selectRow(self.table.rowCount() - 1)
            self._save_library()
        else:
            self.notify("Не удалось загрузить файлы")

    def _add_sound_row(self, path: str, hotkey: str = ""):
        """Добавляет звук в таблицу. Возвращает SoundItem или None."""
        item = self.engine.add_file(path)
        if item is None:
            return None
        row = self.table.rowCount()
        self.table.insertRow(row)
        self.table.setItem(row, 0, QTableWidgetItem(str(row + 1)))
        self.table.setItem(row, 1, QTableWidgetItem(item.name))
        self.table.setItem(row, 2, QTableWidgetItem(format_time(item.duration)))
        key_cell = QTableWidgetItem(
            evdev_hotkeys.label_for(hotkey) if hotkey else "—")
        key_cell.setData(HOTKEY_TOKEN_ROLE, hotkey or "")
        self.table.setItem(row, 3, key_cell)
        self.table.item(row, 0).setData(Qt.ItemDataRole.UserRole, item)
        if hotkey:
            item.hotkey = hotkey
            self.hotkeys.bind(
                hotkey, lambda s=item: self.play_sound(s),
                sound_id=item.uid, name=item.name)
        return item

    def _save_library(self):
        """Сохраняет список путей звуков в config.json."""
        cfg = load_config()
        cfg["sounds"] = [s.path for s in self.engine.sounds]
        # чистим привязки удалённых звуков и запрещённые ЛКМ/ПКМ
        valid = {s.uid for s in self.engine.sounds}
        cfg["hotkeys"] = {
            k: v for k, v in cfg.get("hotkeys", {}).items()
            if k in valid and not str(v).startswith(("Mouse:Left", "Mouse:Right"))
        }
        save_config(cfg)

    def _renumber_rows(self):
        for r in range(self.table.rowCount()):
            cell = self.table.item(r, 0)
            if cell is not None:
                cell.setText(str(r + 1))

    def _delete_selected_sound(self):
        """Удаляет выбранный звук: строку, привязку и запись в config.json."""
        self._commit_key_editor()
        row = self.table.currentRow()
        if row < 0:
            self.notify("Сначала выберите звук в таблице")
            return
        cell = self.table.item(row, 0)
        item = cell.data(Qt.ItemDataRole.UserRole) if cell else None
        if item is None:
            return
        self.engine.stop(item)
        self.hotkeys.unbind(item.uid)
        try:
            self.engine.sounds.remove(item)
        except ValueError:
            pass
        self.table.removeRow(row)
        self._renumber_rows()
        self._save_library()
        self.notify(f"Удалён: {item.name}")

    def _show_table_menu(self, pos):
        row = self.table.rowAt(pos.y())
        if row >= 0:
            self.table.selectRow(row)
        menu = QMenu(self)
        act_key = menu.addAction("Назначить клавишу")
        act_unbind = menu.addAction("Удалить привязку")
        menu.addSeparator()
        act_del = menu.addAction("Удалить звук")
        chosen = menu.exec(self.table.viewport().mapToGlobal(pos))
        if chosen is None or row < 0:
            return
        if chosen is act_key:
            self._on_cell_double_clicked(row, 3)
        elif chosen is act_unbind:
            self._apply_hotkey(row, "")
        elif chosen is act_del:
            self._delete_selected_sound()

    def _restore_library(self):
        """Загружает звуки из config.json и восстанавливает горячие клавиши."""
        cfg = load_config()
        paths = cfg.get("sounds", [])
        hotkeys = cfg.get("hotkeys", {})
        if not paths:
            return
        restored = 0
        for path in paths:
            item = self._add_sound_row(
                path, hotkey=hotkeys.get(sound_uid(path), ""))
            if item is not None:
                restored += 1
        if restored:
            self.notify(f"Восстановлено звуков: {restored}")

    def _selected_item(self) -> SoundItem | None:
        row = self.table.currentRow()
        if row < 0:
            return None
        it = self.table.item(row, 0)
        return it.data(Qt.ItemDataRole.UserRole) if it else None

    def _on_play_clicked(self):
        item = self._selected_item()
        if item is None:
            self.notify("Выберите звук")
            return
        self.play_sound(item)

    def play_sound(self, item: SoundItem):
        """
        Проигрывает звук с учётом режима.
        ФИКС «нет звука»: PipeWire сам кидал pygame-потоки в HyperMix_Mic.
        Теперь ЯВНО маршрутизируем после play (ретраи):
          speakers -> sink по умолчанию (колонки)
          mic      -> HyperMix_Mic
          both     -> HyperMix_Combine (combine-sink: колонки + микрофон)
        Один SDL-поток на процесс — достаточно одного канала.
        """
        if not self.engine.ready:
            self.notify("Микшер недоступен")
            return
        self.engine.set_output_mode(self.mode)
        vol = self.volume_slider.value() / 100.0
        self.engine.stop_all()
        self.tracker.clear()

        if not self.engine.play(item, volume=vol, channel_index=0):
            self.notify(f"Не удалось воспроизвести: {item.name}")
            return

        self.tracker.start_track(item, channel=0)

        # Linux: маршрутизация с ретраями (sink-input появляется не мгновенно).
        # Windows: движок сам выводит звук на нужные устройства.
        if sys.platform.startswith("linux"):
            self._schedule_route(attempt=0)

        self._current_item = item
        self.progress.setValue(0)
        self.lbl_time.setText(f"00:00 / {format_time(item.duration)}")
        self._progress_timer.start()
        self.notify(f"PLAY: {item.name}")

    def _schedule_route(self, attempt: int = 0, max_attempts: int = 15):
        """
        Повторяет route_app_streams: sink-input появляется с задержкой
        после play (100 мс между попытками, до 1.5 с).
        Маршрутизация идempotentна — можно повторять.
        """
        from ..audio.engine import route_app_streams
        ok = route_app_streams(self.mode)
        if ok:
            return
        if attempt < max_attempts:
            QTimer.singleShot(100, lambda: self._schedule_route(attempt + 1, max_attempts))

    def _on_stop_clicked(self):
        self.engine.stop_all()
        self.tracker.clear()
        self._progress_timer.stop()
        self._current_item = None
        self.progress.setValue(0)
        self.lbl_time.setText("00:00 / 00:00")
        self.notify("STOP")

    def _update_progress(self):
        item = self._current_item
        if item is None or not self.engine.is_playing():
            if self._current_item is not None:
                self._on_playback_finished()
            return
        pos = self.tracker.position(item)
        if item.duration > 0:
            self.progress.setValue(int(1000 * min(pos / item.duration, 1.0)))
        self.lbl_time.setText(f"{format_time(pos)} / {format_time(item.duration)}")

    def _on_playback_finished(self):
        QTimer.singleShot(0, self._finish_in_gui)

    def _finish_in_gui(self):
        self._progress_timer.stop()
        self._current_item = None
        self.progress.setValue(1000)
        self.notify("Готово")

    # ------------------------------------------------------------------
    # Горячие клавиши (ЭТАП 2)
    # ------------------------------------------------------------------

    def _on_cell_double_clicked(self, row: int, col: int):
        if col != 3:
            return
        self._commit_key_editor()
        if self.hotkeys.backend in ("evdev", "windows"):
            dlg = HotkeyCaptureDialog(self.hotkeys, self)
            if dlg.exec() == QDialog.DialogCode.Accepted and dlg.token:
                self._apply_hotkey(row, dlg.token)
            return
        self._editing_row = row
        if sys.platform.startswith("win"):
            self.notify("Глобальные клавиши недоступны: установите pynput")
        else:
            self.notify("Только клавиатура: для мыши нужен доступ к /dev/input "
                        "(sudo usermod -aG input $USER)")
        item = self.table.item(row, 3)
        current = item.data(HOTKEY_TOKEN_ROLE) if item else ""
        if not current:
            current = ""
        editor = QKeySequenceEdit()
        if current:
            editor.setKeySequence(QKeySequence(current))
        self.table.setCellWidget(row, 3, editor)
        self._key_edit = editor
        editor.editingFinished.connect(self._commit_key_editor)
        editor.setFocus()

    def _commit_key_editor(self):
        if self._key_edit is None or self._editing_row < 0:
            return
        row = self._editing_row
        seq = self._key_edit.keySequence().toString()
        self.table.removeCellWidget(row, 3)
        self._key_edit = None
        self._editing_row = -1
        self._apply_hotkey(row, seq)

    def _apply_hotkey(self, row: int, token: str):
        cell = self.table.item(row, 3)
        sound = self.table.item(row, 0).data(Qt.ItemDataRole.UserRole)
        if cell is None:
            cell = QTableWidgetItem()
            self.table.setItem(row, 3, cell)

        if evdev_hotkeys.is_blocked(token):
            self.notify("ЛКМ/ПКМ зарезервированы — выберите другую кнопку")
            return

        old = cell.data(HOTKEY_TOKEN_ROLE) or ""
        if old and sound is not None:
            self.hotkeys.unbind(sound.uid)

        if not token:
            cell.setText("—")
            cell.setData(HOTKEY_TOKEN_ROLE, "")
            if sound is not None:
                sound.hotkey = ""
            self.notify("Клавиша сброшена")
            return

        cell.setText(evdev_hotkeys.label_for(token))
        cell.setData(HOTKEY_TOKEN_ROLE, token)
        if sound is not None:
            sound.hotkey = token
        sound_name = sound.name if sound is not None else token
        if sound is not None and self.hotkeys.bind(
                token, lambda s=sound: self.play_sound(s),
                sound_id=sound.uid, name=sound_name):
            self.notify(f"Клавиша: {evdev_hotkeys.label_for(token)}")
        elif sys.platform.startswith("win"):
            self.notify("Не удалось назначить: установите pynput")
        elif evdev_hotkeys.is_mouse_token(token):
            self.notify("Мышь требует доступа к /dev/input (группа input)")
        else:
            self.notify(f"Клавиша {token} записана (глобальный перехват недоступен)")

    # ------------------------------------------------------------------
    # Прочие слоты
    # ------------------------------------------------------------------

    def _on_pick_mic_clicked(self):
        """Диалог выбора реального микрофона (источника голоса)."""
        if self.platform is None:
            self.notify("Платформа недоступна")
            return
        mics = self.platform.list_capture_mics()
        if not mics:
            self.notify("Реальные микрофоны не найдены")
            return
        current = self.platform.current_voice_source()
        if current not in mics:
            current = mics[0]
        dlg = QInputDialog()
        dlg.setWindowTitle("Источник голоса")
        dlg.setLabelText("Микрофон, из которого берётся ваш голос:")
        dlg.setComboBoxItems(mics)
        dlg.setComboBoxEditable(False)
        dlg.setCurrentText(current)
        if dlg.exec() != QInputDialog.DialogCode.Accepted:
            return
        chosen = dlg.currentText()
        if self.platform.select_voice_source(chosen):
            self.notify(f"Голос берётся с: {chosen}")
            self.update_platform_status()
        else:
            self.notify(f"Не удалось переключить источник на {chosen}")

    def _set_mode(self, mode: str, persist: bool = True, notify: bool = True):
        if mode in ("mic", "both") and self.platform is not None:
            if not self.platform.mic_mode_available():
                self.notify("Виртуальный микрофон недоступен")
                return
        self.mode = mode
        self.engine.set_output_mode(mode)
        self.btn_speakers.setChecked(mode == "speakers")
        self.btn_mic.setChecked(mode == "mic")
        self.btn_both.setChecked(mode == "both")
        labels = {"speakers": "[SPK]", "mic": "[MIC]", "both": "[BOTH]"}
        self.lbl_mode.setText(f"Mode: {labels[mode]}")
        if persist:
            cfg = load_config()
            cfg["output_mode"] = mode
            save_config(cfg)
        if notify:
            self.notify(f"Mode: {labels[mode]}")

    def restore_mode(self):
        """Восстанавливает режим вывода из config.json после startup платформы."""
        mode = load_config().get("output_mode", "speakers")
        if mode not in ("speakers", "mic", "both"):
            mode = "speakers"
        if mode in ("mic", "both") and (
            self.platform is None or not self.platform.mic_mode_available()
        ):
            mode = "speakers"
        self._set_mode(mode, persist=False, notify=False)

    def _on_volume_changed(self, value: int):
        self.lbl_volume_val.setText(f"{value}%")
        vol = value / 100.0
        self.engine.set_channel_volume(0, vol)
        self.engine.set_channel_volume(1, vol)

    def _on_record_clicked(self, checked: bool):
        if checked:
            self.notify("[REC] — в разработке")
            QTimer.singleShot(0, lambda: self.btn_record.setChecked(False))

    def notify(self, text: str):
        self.lbl_notify.setText(text)

    def set_mic_level(self, value: int):
        self.mic_level_bar.setValue(max(0, min(100, value)))

    def update_platform_status(self):
        if self.platform is None:
            return
        self.lbl_mic_text.setText(self.platform.status_text())
        available = (self.platform.mic_mode_available()
                     and self.engine.supports_routing)
        self.btn_mic.setEnabled(available)
        self.btn_both.setEnabled(available)
        if not available and self.mode in ("mic", "both"):
            self._set_mode("speakers")

    # ------------------------------------------------------------------
    # Завершение
    # ------------------------------------------------------------------

    def closeEvent(self, event):
        self.hotkeys.shutdown()
        self.tracker.stop()
        self.engine.stop_all()
        # Выгружаем combine-sink (если создавали для режима BOTH)
        if sys.platform.startswith("linux"):
            from ..audio.engine import destroy_combine_sink
            destroy_combine_sink()
        self.engine.shutdown()
        if self.platform is not None:
            self.platform.shutdown()
        super().closeEvent(event)
