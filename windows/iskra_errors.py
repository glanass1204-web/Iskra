"""Понятные причины ошибок вместо сообщений Python."""


def friendly_error(exc):
    """Понятная причина вместо сообщения Python."""
    import re
    import zipfile
    if isinstance(exc, (ValueError, RuntimeError)) and re.search('[а-яё]', str(exc), re.IGNORECASE):
        return str(exc)                                # наше собственное понятное сообщение
    if isinstance(exc, PermissionError):
        return 'файл занят — он открыт в Word или Excel. Закройте его и повторите.'
    if isinstance(exc, FileNotFoundError):
        return 'файл не найден — возможно, его переместили или удалили.'
    if isinstance(exc, zipfile.BadZipFile) or type(exc).__name__ == 'InvalidFileException':
        return 'файл повреждён или это не .docx/.xlsx (старый .doc/.xls сохраните в новом формате).'
    if isinstance(exc, MemoryError):
        return 'не хватает памяти — закройте лишние программы.'
    if isinstance(exc, OSError):
        return f'не удалось открыть или записать файл ({exc.strerror or exc}).'
    return 'что-то пошло не так. Подробности — в папке данных, файл ai_log.txt.'
