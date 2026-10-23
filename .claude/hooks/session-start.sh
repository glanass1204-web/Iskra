#!/bin/bash
# Облачный сеанс Claude Code: ставит библиотеки Искры (Windows-программа на Python), чтобы сразу работали тесты
# и проверка pyflakes. PyInstaller не нужен: exe собирает GitHub Actions на Windows.
set -euo pipefail

if [ "${CLAUDE_CODE_REMOTE:-}" != "true" ]; then
  exit 0
fi

cd "$CLAUDE_PROJECT_DIR/windows"
grep -v -i '^pyinstaller' requirements.txt > /tmp/iskra-requirements.txt
python3 -m pip install --quiet --disable-pip-version-check --root-user-action=ignore -r /tmp/iskra-requirements.txt pyflakes
