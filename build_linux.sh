#!/usr/bin/env bash
# HyperMix — сборка портативного Linux-релиза (onefile + tar.gz)
# Требуется: python3, python3-venv, интернет для установки зависимостей.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

VERSION="$(tr -d '[:space:]' < VERSION)"
ARCH="$(uname -m)"
NAME="HyperMix-${VERSION}-Linux-${ARCH}"
DIST="$ROOT/release/$NAME"
VENV="${BUILD_VENV:-$ROOT/.build-venv-linux}"

echo "==> HyperMix ${VERSION} (${ARCH})"
rm -rf "$ROOT/build" "$ROOT/dist" "$DIST" "$ROOT/release/$NAME.tar.gz"
mkdir -p "$ROOT/release"

if [ ! -x "$VENV/bin/python" ]; then
  echo "==> Создаю build-venv: $VENV"
  python3 -m venv "$VENV"
fi
# shellcheck disable=SC1091
source "$VENV/bin/activate"
python -m pip install --upgrade pip
python -m pip install -r requirements-linux.txt pyinstaller

echo "==> PyInstaller"
python -m PyInstaller --noconfirm --clean --onefile \
  --name "HyperMix" \
  --add-data "assets:assets" \
  --distpath "$ROOT/dist" \
  --workpath "$ROOT/build" \
  main.py

echo "==> Формирую $DIST"
mkdir -p "$DIST"
cp "$ROOT/dist/HyperMix" "$DIST/HyperMix"
chmod +x "$DIST/HyperMix"
cp "$ROOT/packaging/config.default.json" "$DIST/config.json"
cp "$ROOT/README.md" "$ROOT/CHANGELOG.md" "$ROOT/LICENSE" "$DIST/"
cp "$ROOT/assets/hypermix.png" "$DIST/hypermix.png"
cp "$ROOT/packaging/hypermix.desktop" "$DIST/hypermix.desktop"

# Проверка бинарника
"$DIST/HyperMix" --version

tar -czf "$ROOT/release/$NAME.tar.gz" -C "$ROOT/release" "$NAME"
(cd "$ROOT/release" && sha256sum "$NAME.tar.gz" > "$NAME.tar.gz.sha256")

echo
echo "Готово:"
ls -lh "$ROOT/release/$NAME.tar.gz" "$ROOT/release/$NAME.tar.gz.sha256"
