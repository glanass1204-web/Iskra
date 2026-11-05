# Проверка через саму программу (окна, меню, кнопки)

Запускает Искру на виртуальном экране, открывает все пункты меню и нажимает кнопки: перенос изменений
(Word и Excel), телеграмма по шаблону в редакторе, отпускной билет по бланку. Диалоги подставляются.

    python3.12 -m venv --system-site-packages /tmp/venv312
    /tmp/venv312/bin/pip install -r <(grep -vi pyinstaller windows/requirements.txt)
    cd dev/gui && xvfb-run -a /tmp/venv312/bin/python run.py

Нужен Python с tkinter (в контейнере — python3.12) и xvfb. Ожидаемо: «ИТОГ: 12 из 12».
