---
name: iskra-release
description: Выпуск новой версии Искры для пользователя — тесты, отправка в main, ожидание сборки Windows и самопроверки нейросети, проверка Iskra-AI-chast-01.zip и отправка файла и ссылки. Использовать, когда изменения готовы и пользователю нужен файл («давай файл», «ссылку», «собери»).
---

# Выпуск Искры (часть 01)

Пользователю нужна только `Iskra-AI-chast-01.zip`. Части 02–10 не меняются — так и сказать.

## 1. Перед отправкой
- `cd windows && python3 -m unittest discover -p 'test_*.py'` — только OK, без падений.
- `python3 -m pyflakes` по изменённым файлам — без «undefined name».
- `VERSION` в `windows/iskra.py` поднята, раздел в `windows/CHANGELOG_v1_10_0.txt` дописан.

## 2. Отправка
- Коммит с понятным описанием по-русски, `git push origin HEAD:main`.
- Пуш в main запускает сборку «Windows EXE» (и «AI quality»). Новый пуш отменяет идущую сборку — несколько
  правок подряд лучше собрать в один пуш.

## 3. Ожидание сборки (в фоне, без sleep в основном потоке)
```bash
H=$(git -C "$CLAUDE_PROJECT_DIR" rev-parse HEAD)
until id=$(curl -s -m 20 "https://api.github.com/repos/glanass1204-web/Iskra/actions/runs?head_sha=$H" | python3 -c "
import json,sys;r={x['name']:x['id'] for x in json.load(sys.stdin)['workflow_runs']};print(r.get('Windows EXE',''))"); [ -n "$id" ]; do sleep 15; done
until s=$(curl -s -m 20 https://api.github.com/repos/glanass1204-web/Iskra/actions/runs/$id | python3 -c "import json,sys;print(json.load(sys.stdin).get('conclusion') or '')"); [ -n "$s" ]; do sleep 30; done
echo "$id $s"
```
Запускать с `run_in_background`. `cancelled` — сборку заменил более новый пуш, ждать новую.

## 4. Если сборка упала
- Найти шаг: `https://api.github.com/repos/glanass1204-web/Iskra/actions/runs/<id>/jobs`, лог — `mcp__github__get_job_logs`.
- Частый случай — «Neural network works without internet»: самопроверка `selftest_ai()` в `windows/iskra.py`
  на настоящей модели. Строки `FAIL …` показывают, какой ответ не прошёл. Исправить причину в коде (не ослаблять
  проверку), добавить тест, снова п. 1–3. Пользователю — коротко, что было и что исправлено.

## 5. Проверка архива
```bash
mkdir -p "$CLAUDE_PROJECT_DIR/download" && cd "$CLAUDE_PROJECT_DIR/download"
curl -s https://api.github.com/repos/glanass1204-web/Iskra/releases/tags/iskra-windows-latest   # digest и updated_at части 01
curl -sL -o Iskra-AI-chast-01.zip https://github.com/glanass1204-web/Iskra/releases/download/iskra-windows-latest/Iskra-AI-chast-01.zip
sha256sum Iskra-AI-chast-01.zip   # = digest из выпуска
python3 -I -c "import zipfile;z=zipfile.ZipFile('Iskra-AI-chast-01.zip');n=z.namelist();print(z.testzip(),[x for x in n if x.startswith('Iskra/data/')],[x for x in n if x.endswith('.gguf')])"
```
Нужно: `None [] []` (архив цел, нет данных пользователя и модели); `updated_at` части 01 — внутри времени
успешной сборки (`run_started_at`…`updated_at` запуска). Папка `download/` в `.git/info/exclude`, не коммитить.

## 6. Отдать пользователю
- `SendUserFile` с `download/Iskra-AI-chast-01.zip`, подпись «Искра X.Y.Z — часть 01. Части 02–10 прежние».
- Ссылка: https://github.com/glanass1204-web/Iskra/releases/download/iskra-windows-latest/Iskra-AI-chast-01.zip
- Коротко по-русски: что нового (по CHANGELOG), как ставить — распаковать с заменой в ту же папку, данные
  и настройки сохраняются.
