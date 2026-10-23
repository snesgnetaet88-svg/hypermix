# HyperMix — пути к пользовательским данным.
# В обычном запуске config.json лежит рядом с main.py, а в собранном
# PyInstaller-exe — рядом с самим exe (портативный режим).

import sys
from pathlib import Path


def config_path() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent / "config.json"
    return Path(__file__).resolve().parent.parent / "config.json"


CONFIG_PATH = config_path()


def resource_path(relative: str) -> Path:
    """Путь к ресурсу и в исходниках, и внутри PyInstaller-сборки."""
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
    return base / relative
