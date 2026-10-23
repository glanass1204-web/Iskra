"""Чтение заголовка файла модели GGUF (без загрузки весов): архитектура и есть ли голова MTP
(многотокенное предсказание — ускоряет ответ движка без потери качества)."""
import struct

_SCALAR = {0: '<B', 1: '<b', 2: '<H', 3: '<h', 4: '<I', 5: '<i', 6: '<f', 7: '<?', 10: '<Q', 11: '<q', 12: '<d'}


def _read(f, fmt):
    size = struct.calcsize(fmt)
    data = f.read(size)
    if len(data) != size:
        raise ValueError('файл модели оборван')
    return struct.unpack(fmt, data)[0]


def _string(f):
    n = _read(f, '<Q')
    if n > 1 << 24:
        raise ValueError('слишком длинная строка в заголовке')
    return f.read(n).decode('utf-8', 'replace')


def _value(f, t):
    if t in _SCALAR:
        return _read(f, _SCALAR[t])
    if t == 8:
        return _string(f)
    if t == 9:
        inner, n = _read(f, '<I'), _read(f, '<Q')
        if inner in _SCALAR:                                  # числа — пропускаем целиком, не читая по одному
            f.seek(struct.calcsize(_SCALAR[inner]) * n, 1)
            return None
        for _ in range(n):
            _value(f, inner)
        return None
    raise ValueError(f'неизвестный тип {t}')


def metadata(path, wanted=('general.architecture',), suffixes=('.nextn_predict_layers',)):
    """{ключ: значение} для нужных ключей заголовка. Ошибка чтения — пустой словарь."""
    out = {}
    try:
        with open(path, 'rb') as f:
            if f.read(4) != b'GGUF':
                return {}
            _read(f, '<I')                                    # версия
            _read(f, '<Q')                                    # число тензоров
            for _ in range(_read(f, '<Q')):
                key = _string(f)
                value = _value(f, _read(f, '<I'))
                if key in wanted or key.endswith(suffixes):
                    out[key] = value
    except (OSError, ValueError, struct.error):
        return out
    return out


def has_mtp(path):
    """В файле есть голова MTP (Qwen3.5/3.6 из сборок «MTP»)."""
    return any(k.endswith('.nextn_predict_layers') and (v or 0) > 0 for k, v in metadata(path).items())
