#!/usr/bin/env bash
# HyperMix — запуск на Linux (ЭТАП 5)
# Активирует venv (если есть) и запускает приложение.
# Виртуальный микрофон HyperMix_Mic создаётся автоматически (ЭТАП 3),
# для глобальных хоткеев может потребоваться root (sudo).

set -e
cd "$(dirname "$0")"

# Активация venv, если он существует
if [ -d "venv" ]; then
    # shellcheck disable=SC1091
    source venv/bin/activate
fi

# Без буферизации — чтобы логи PLAY:/ROUTE: были видны сразу
export PYTHONUNBUFFERED=1

exec python3 main.py "$@"
