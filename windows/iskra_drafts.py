"""Автосохранение редактора телеграмм и история версий.
Каждое окно редактора — свой черновик: текущий текст сохраняется каждые 30 секунд (если менялся), версия
откладывается не реже раза в 2 минуты, а также перед заменой текста нейросетью, при сохранении в Word и при
закрытии окна. Черновик, окно которого не закрылось как положено (зависание, выключили компьютер), Искра
предложит восстановить при следующем запуске. Хранится в data/drafts, старые черновики удаляются сами."""
import json
import os
import re
import time
import uuid
from pathlib import Path

VERSIONS = 30                # версий у одного черновика
KEEP = 60                    # черновиков всего
VERSION_EVERY = 120          # секунд между версиями при обычной работе


def folder():
    from iskra_index import ROOT
    return ROOT / 'drafts'


def _write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix('.tmp')
    tmp.write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')
    os.replace(tmp, path)                       # целиком или никак: сбой посреди записи не портит черновик


def title_of(text):
    for line in (text or '').splitlines():
        line = line.strip()
        if line and line.upper() not in ('ТЕЛЕГРАММА', 'ТЕКСТ:', 'ДОКЛАД') and not line.endswith(':'):
            return line[:80]
    return 'Пустой черновик'


class Draft:
    def __init__(self, data=None, base=None):
        self.base = Path(base) if base else folder()
        self.data = data or {'id': time.strftime('%Y%m%d-%H%M%S-') + uuid.uuid4().hex[:6], 'created': time.time(),
                             'updated': time.time(), 'closed': False, 'text': '', 'versions': []}

    @property
    def path(self):
        return self.base / f'{self.data["id"]}.json'

    @classmethod
    def load(cls, path):
        path = Path(path)
        return cls(json.loads(path.read_text(encoding='utf-8')), path.parent)

    def snapshot(self, text, why=''):
        """Отложить версию (если текст не пустой и отличается от последней)."""
        versions = self.data['versions']
        if not text.strip() or (versions and versions[-1]['text'] == text):
            return False
        versions.append({'time': time.time(), 'text': text, 'why': why})
        del versions[:-VERSIONS]
        return True

    def autosave(self, text, why='', force=False):
        """Сохранить текущий текст; версию — если давно не откладывали или есть причина (why). True — что-то записано."""
        changed = text != self.data['text']
        versions = self.data['versions']
        due = not versions or time.time() - versions[-1]['time'] >= VERSION_EVERY
        if not (changed or force or why):
            return False
        self.data['text'] = text
        self.data['updated'] = time.time()
        self.data['title'] = title_of(text)
        if why or due:
            self.snapshot(text, why or 'автосохранение')
        try:
            _write(self.path, self.data)
        except OSError:
            return False
        return True

    def close(self, text):
        self.data['closed'] = True
        self.autosave(text, 'окно закрыто', force=True)


def recent(limit=30, base=None):
    base = Path(base) if base else folder()
    out = []
    for p in base.glob('*.json'):
        try:
            out.append(Draft.load(p))
        except (OSError, ValueError, KeyError):
            continue
    out.sort(key=lambda d: -d.data.get('updated', 0))
    return out[:limit]


def unfinished(base=None, blank=''):
    """Черновики, окно которых не было закрыто, — и в них есть что-то кроме пустого бланка."""
    def bare(text):
        return re.sub(r'[\d\s]+', '', text or '')        # бланк вчерашнего дня отличается только датой
    return [d for d in recent(KEEP, base) if not d.data.get('closed') and d.data.get('text', '').strip()
            and bare(d.data['text']) != bare(blank)]


def mark_closed(draft, base=None):
    draft.data['closed'] = True
    try:
        _write(draft.path, draft.data)
    except OSError:
        pass


def cleanup(base=None, keep=KEEP):
    base = Path(base) if base else folder()
    drafts = recent(10_000, base)
    for d in drafts[keep:]:
        try:
            d.path.unlink()
        except OSError:
            pass


def when(ts):
    t = time.localtime(ts)
    today = time.localtime()
    return time.strftime('%H:%M' if t[:3] == today[:3] else '%d.%m %H:%M', t)
