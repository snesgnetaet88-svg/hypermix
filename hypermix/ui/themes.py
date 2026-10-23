# HyperMix — система тем (ЭТАП 4)
# Три темы: "Light" (белый), "Dark" (чёрный/оранжевый), "Hacker" (чёрный/зелёный)
# + виджет MatrixWidget (ЭТАП 5) для темы Hacker

import json
import os

from PyQt6.QtCore import Qt, QTimer, QRect
from PyQt6.QtGui import QPainter, QColor, QFont, QPen
from PyQt6.QtWidgets import QWidget

# Файл конфигурации (рядом с main.py или с собранным exe)
from ..paths import CONFIG_PATH

# Доступные темы
THEMES = ("Light", "Dark", "Hacker")
DEFAULT_THEME = "Dark"


# ----------------------------------------------------------------------
# Конфигурация (config.json)
# ----------------------------------------------------------------------

def load_config() -> dict:
    """Загружает config.json (или возвращает пустой dict)."""
    try:
        if CONFIG_PATH.exists():
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        pass
    return {}


def save_config(cfg: dict):
    """Сохраняет config.json."""
    try:
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2, ensure_ascii=False)
    except Exception:
        pass


def load_theme_name() -> str:
    """Читает имя темы из config.json (по умолчанию Dark)."""
    name = load_config().get("theme", DEFAULT_THEME)
    return name if name in THEMES else DEFAULT_THEME


def save_theme_name(name: str):
    """Сохраняет выбранную тему в config.json."""
    cfg = load_config()
    cfg["theme"] = name
    save_config(cfg)


# ----------------------------------------------------------------------
# QSS-стили тем
# ----------------------------------------------------------------------

def _base_qss(bg: str, bg_alt: str, bg_widget: str, border: str,
              text: str, accent: str, accent_dim: str, accent_dark: str,
              table_bg: str = "", table_alt: str = "") -> str:
    """Базовый QSS-шаблон, параметризованный цветами темы."""
    t_bg = table_bg or bg_alt
    t_alt = table_alt or bg
    return f"""
    QWidget {{
        background-color: {bg};
        color: {text};
        font-family: 'Consolas', 'Courier New', 'DejaVu Sans Mono', 'Monospace';
        font-size: 12px;
    }}
    QMainWindow, QDialog {{ background-color: {bg}; }}

    /* Панель инструментов */
    QToolBar {{
        background-color: {bg_alt};
        border: none;
        border-bottom: 1px solid {border};
        padding: 3px 6px;
        spacing: 4px;
    }}
    QToolBar::separator {{ background-color: {border}; width: 1px; margin: 2px 4px; }}

    /* Компактные кнопки (ЭТАП 3) */
    QPushButton {{
        background-color: {bg_widget};
        color: {accent};
        border: 1px solid {border};
        border-radius: 3px;
        padding: 3px 8px;
        font-weight: bold;
        font-size: 11px;
        min-height: 20px;
    }}
    QPushButton:hover {{ border-color: {accent}; }}
    QPushButton:pressed {{ background-color: {accent_dark}; }}
    QPushButton:checked {{ background-color: {accent_dark}; border-color: {accent}; }}
    QPushButton:disabled {{ color: {border}; background-color: {bg_alt}; }}

    QPushButton#btnRecord {{ color: #ff4444; border-color: #ff4444; }}
    QPushButton#btnRecord:checked {{ background-color: #4a0000; border-color: #ff4444; }}
    QPushButton#btnRecord:hover {{ background-color: #4a0000; }}

    /* Крупные кнопки над таблицей */
    QPushButton#btnAddMain {{
        font-size: 13px;
        border: 2px solid {accent};
        color: {accent};
        padding: 6px 12px;
    }}
    QPushButton#btnAddMain:hover {{ background-color: {accent_dark}; border-color: {accent}; }}
    QPushButton#btnDelMain {{
        font-size: 12px;
        color: #ff6666;
        border-color: #ff6666;
        padding: 6px 12px;
    }}
    QPushButton#btnDelMain:hover {{ background-color: #4a0000; border-color: #ff6666; }}

    /* Слайдер */
    QSlider::groove:horizontal {{
        height: 4px; background-color: {bg_widget}; border-radius: 2px;
    }}
    QSlider::handle:horizontal {{
        background-color: {accent}; width: 12px; margin: -4px 0; border-radius: 6px;
    }}
    QSlider::sub-page:horizontal {{ background-color: {accent_dark}; border-radius: 2px; }}

    /* Прогресс */
    QProgressBar {{
        background-color: {bg_widget}; border: 1px solid {border};
        border-radius: 3px; text-align: center; color: {accent};
        min-height: 16px; font-size: 10px;
    }}
    QProgressBar::chunk {{ background-color: {accent_dark}; border-radius: 2px; }}

    /* Таблица */
    QTableWidget {{
        background-color: {t_bg};
        alternate-background-color: {t_alt};
        gridline-color: {border};
        border: 1px solid {border};
        selection-background-color: {accent_dark};
        selection-color: {text};
    }}
    QTableWidget::item {{ padding: 2px 4px; }}
    QHeaderView::section {{
        background-color: {bg_widget};
        color: {accent};
        border: 1px solid {border};
        padding: 3px;
        font-weight: bold;
        font-size: 11px;
    }}

    /* Метки */
    QLabel {{ background-color: transparent; }}
    QLabel#timeLabel {{ color: {accent}; font-size: 12px; font-weight: bold; padding: 0 6px; }}
    QLabel#modeIndicator {{ color: {accent}; font-weight: bold; }}
    QLabel#micLevel {{ color: {accent_dim}; }}
    QLabel#notificationLabel {{ color: {text}; }}
    QLabel#volumeLabel {{ color: {accent}; min-width: 36px; }}

    /* Статус-бар */
    QStatusBar {{
        background-color: {bg_alt};
        border-top: 1px solid {border};
        color: {text};
        font-size: 11px;
    }}
    QStatusBar QLabel {{ padding: 1px 8px; }}

    /* Меню */
    QMenuBar {{
        background-color: {bg_alt};
        color: {text};
        border-bottom: 1px solid {border};
        padding: 1px 4px;
    }}
    QMenuBar::item:selected {{ background-color: {accent_dark}; }}
    QMenu {{ background-color: {bg_widget}; color: {text}; border: 1px solid {border}; }}
    QMenu::item:selected {{ background-color: {accent_dark}; }}

    /* Комбобокс */
    QComboBox {{
        background-color: {bg_widget}; color: {accent};
        border: 1px solid {border}; border-radius: 3px; padding: 2px 6px;
    }}
    QComboBox QAbstractItemView {{
        background-color: {bg_widget}; color: {accent};
        selection-background-color: {accent_dark};
    }}

    /* Редактор хоткеев */
    QKeySequenceEdit {{
        background-color: {bg_widget}; color: {accent};
        border: 1px solid {accent}; border-radius: 3px; padding: 2px;
    }}
    """


def theme_light() -> str:
    """Светлая тема: белый фон, чёрный текст."""
    return _base_qss(
        bg="#ffffff", bg_alt="#f0f0f0", bg_widget="#e8e8e8",
        border="#c0c0c0", text="#1a1a1a", accent="#0066cc",
        accent_dim="#555555", accent_dark="#cce0ff",
        table_bg="#ffffff", table_alt="#f5f5f5",
    )


def theme_dark() -> str:
    """Тёмная тема (по умолчанию): фон #1a1a1a, текст #e0e0e0, акцент оранжевый."""
    return _base_qss(
        bg="#1a1a1a", bg_alt="#222222", bg_widget="#2a2a2a",
        border="#3a3a3a", text="#e0e0e0", accent="#ff8c00",
        accent_dim="#aaaaaa", accent_dark="#4a3200",
        table_bg="#1e1e1e", table_alt="#1a1a1a",
    )


def theme_hacker() -> str:
    """
    Hacker-тема: чёрный фон, зелёный текст (#00ff00), рамки (#00aa00).
    Таблица полупрозрачная — сквозь неё видна матрица (ЭТАП 5).
    """
    qss = _base_qss(
        bg="#000000", bg_alt="#050505", bg_widget="#0a0a0a",
        border="#00aa00", text="#00ff00", accent="#00ff00",
        accent_dim="#00cc00", accent_dark="#003300",
        # полупрозрачная таблица — матрица просвечивает
        table_bg="rgba(0, 0, 0, 0.8)", table_alt="rgba(0, 0, 0, 0.75)",
    )
    # Явное правило прозрачности таблицы (ЭТАП 5.3)
    qss += """
    QTableWidget {
        background-color: rgba(0, 0, 0, 0.8);
        alternate-background-color: rgba(0, 0, 0, 0.75);
    }
    """
    return qss


# Реестр тем
_THEME_FUNCS = {
    "Light": theme_light,
    "Dark": theme_dark,
    "Hacker": theme_hacker,
}


def get_theme(name: str) -> str:
    """Возвращает QSS-строку для указанной темы (fallback: Dark)."""
    fn = _THEME_FUNCS.get(name, theme_dark)
    return fn()


def theme_is_dark(name: str) -> bool:
    """Тёмная ли тема (для цвета MatrixWidget)."""
    return name in ("Dark", "Hacker")


# ----------------------------------------------------------------------
# ЭТАП 5: MatrixWidget — падающая матрица 0/1 на фоне
# ----------------------------------------------------------------------

class MatrixWidget(QWidget):
    """
    Виджет-фон: падающие столбцы символов 0 и 1 (как в «Матрице»).
    Рисуется через QTimer + QPainter. Виден только в теме Hacker.
    """

    # Палитра «матрицы»: ярко-зелёный головной символ, тёмный хвост
    COLOR_HEAD = QColor(0, 255, 0)
    COLOR_TAIL = QColor(0, 120, 0)
    COLOR_FAINT = QColor(0, 60, 0)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._columns: list[list[str]] = []   # столбцы символов
        self._speeds: list[int] = []          # скорость столбца (тиков)
        self._ticks: list[int] = []           # счётчик тиков
        self._font = QFont("Consolas", 12)
        self._cell_w = 12
        self._cell_h = 16
        self._active = False                  # включена ли анимация
        self._timer = QTimer(self)
        self._timer.setInterval(60)
        self._timer.timeout.connect(self._advance)

    # ------------------------------------------------------------------

    def set_active(self, active: bool):
        """Вкл/выкл анимацию (ЭТАП 5.4: выкл для Light/Dark)."""
        self._active = active
        self.setVisible(active)
        if active:
            self._init_columns()
            if not self._timer.isActive():
                self._timer.start()
        else:
            self._timer.stop()
        self.update()

    # ------------------------------------------------------------------

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._active:
            self._init_columns()

    def _init_columns(self):
        """Инициализация столбцов под текущий размер виджета."""
        import random
        n_cols = max(1, self.width() // self._cell_w)
        n_rows = max(1, self.height() // self._cell_h)
        self._columns = []
        self._speeds = []
        self._ticks = []
        for _ in range(n_cols):
            col = [random.choice("01") for _ in range(n_rows)]
            self._columns.append(col)
            self._speeds.append(random.randint(2, 6))
            self._ticks.append(random.randint(0, 10))

    def _advance(self):
        """Один тик: сдвигаем «хвосты» вниз."""
        import random
        n_rows = max(1, self.height() // self._cell_h)
        for i, col in enumerate(self._columns):
            self._ticks[i] += 1
            if self._ticks[i] >= self._speeds[i]:
                self._ticks[i] = 0
                col.insert(0, random.choice("01"))
                if len(col) > n_rows:
                    col.pop()
        self.update()

    def paintEvent(self, event):
        if not self._active:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        painter.setFont(self._font)
        # Заливка чёрным (таблица поверх — полупрозрачная)
        painter.fillRect(self.rect(), QColor(0, 0, 0))
        n_rows = max(1, self.height() // self._cell_h)
        for i, col in enumerate(self._columns):
            x = i * self._cell_w
            for j, ch in enumerate(col[:n_rows]):
                y = j * self._cell_h
                # Головной символ (первый в столбце) — яркий
                if j == 0:
                    painter.setPen(self.COLOR_HEAD)
                elif j < 4:
                    painter.setPen(self.COLOR_TAIL)
                else:
                    painter.setPen(self.COLOR_FAINT)
                painter.drawText(QRect(x, y, self._cell_w, self._cell_h),
                                 Qt.AlignmentFlag.AlignCenter, ch)
        painter.end()
