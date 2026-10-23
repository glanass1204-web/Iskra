"""Offline workflows: compare revisions, create source-grounded drafts, and save history."""
import difflib
import json
import re
from datetime import datetime
from pathlib import Path


def compare_texts(before, after):
    return '\n'.join(difflib.unified_diff(before.splitlines(), after.splitlines(),
        fromfile='Предыдущая редакция', tofile='Новая редакция', lineterm='')) or 'Отличий не найдено.'


def normalize_layout(text):
    """Conservative whitespace cleanup; does not rewrite names, dates or facts."""
    lines = [re.sub(r'[ \t]{2,}', ' ', line).strip() for line in text.replace('\r\n', '\n').split('\n')]
    result = []
    for line in lines:
        if line or (result and result[-1]):
            result.append(line)
    return '\n'.join(result).strip()


def draft_from_sources(subject, sources, template=''):
    """Clearly labelled human-review draft, no invented facts or AI claims."""
    if not sources:
        raise ValueError('Выберите хотя бы один документ-источник.')
    subject = subject.strip() or '[УТОЧНИТЬ ТЕМУ]'
    excerpts = []
    for path, content in sources:
        clean = normalize_layout(content)
        if clean:
            excerpts.append((str(path), clean[:3000]))
    if not excerpts:
        raise ValueError('Не удалось получить текст выбранных документов.')
    head = template.strip() if template.strip() else (       # без шапки и подписи — их даёт свой шаблон
        '{subject}\n\n[СФОРМУЛИРОВАТЬ РЕШЕНИЕ ПО МАТЕРИАЛАМ НИЖЕ]')
    head = head.replace('{subject}', subject)
    evidence = '\n\n'.join(f'Источник {i}: {Path(path).name}\n{content}' for i, (path, content) in enumerate(excerpts, 1))
    return head + '\n\n--- МАТЕРИАЛЫ ДЛЯ ПРОВЕРКИ (НЕ ЧАСТЬ ТЕЛЕГРАММЫ) ---\n' + evidence


def save_history(root, action, details):
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    record = {'timestamp': datetime.now().isoformat(timespec='seconds'),
              'action': str(action)[:100], 'details': str(details)[:500]}
    with (root / 'history.jsonl').open('a', encoding='utf-8') as f:
        f.write(json.dumps(record, ensure_ascii=False) + '\n')


def read_history(root, limit=100):
    p = Path(root) / 'history.jsonl'
    if not p.exists():
        return []
    with p.open(encoding='utf-8') as f:
        lines = f.readlines()[-limit:]
    result = []
    for line in reversed(lines):
        try: result.append(json.loads(line))
        except json.JSONDecodeError: pass
    return result
