"""Память Искры на этом компьютере — то, чему она учится по ходу работы, без интернета и без переобучения нейросети.
1) Отправленные документы: всё, что человек сохранил из редактора в Word, — в data/sent.jsonl. Когда нужна новая
   телеграмма, нейросеть получает самую похожую прошлую как ориентир («как в прошлый раз» — как основу).
2) Поиск: какие документы человек открывает по каким словам — data/search_memory.json. Такие документы
   при следующем поиске стоят выше."""
import json
import os
import re
import threading
import time

SENT_KEEP = 300
CLICK_PATHS = 2000
LAST_TIME = re.compile(r'как\s+(?:и\s+)?(?:в\s+)?(?:прошл\w*|тот|предыдущ\w*)\s+раз|как\s+раньше|как\s+обычно|'
                       r'по\s+образцу\s+прошл\w*|как\s+в\s+прошл\w*', re.IGNORECASE)
STOP = set('''этот этой этого этих того тому также чтобы которые который которая которое будет были было быть
прошу просим необходимо обеспечить телеграмма телеграммы телеграмму текст подпись кому кого дата номер'''.split())
_lock = threading.Lock()


def _root():
    from iskra_index import ROOT
    return ROOT


def stems(text):
    return {w[:6] for w in re.findall(r'[а-яё]{4,}', (text or '').lower().replace('ё', 'е')) if w not in STOP}


def _write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix('.tmp')
    tmp.write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')
    os.replace(tmp, path)


# ---------- отправленные документы ----------

def _field(text, name):
    m = re.search(rf'^\s*{name}\s*:\s*(.*)$', text, re.IGNORECASE | re.MULTILINE)
    if not m:
        return ''
    value = m.group(1).strip()
    if not value:                                     # «Кому:» на одной строке, адресат — на следующих
        rest = text[m.end():].lstrip('\n').splitlines()
        value = ' '.join(x.strip() for x in rest[:3] if x.strip() and not x.strip().endswith(':'))
    return value[:200]


def sent():
    try:
        lines = (_root() / 'sent.jsonl').read_text(encoding='utf-8').splitlines()
    except OSError:
        return []
    out = []
    for line in lines:
        try:
            out.append(json.loads(line))
        except ValueError:
            pass
    return out


def remember_sent(text, file=''):
    """Документ сохранён в Word — запомнить (без списка источников). True — запомнен."""
    from iskra_learn import body
    text = body(text)
    if len(text) < 60 or text.upper().count('[УТОЧНИТЬ') > 3:
        return False                                  # пустой бланк или недописанный черновик — не образец
    with _lock:
        items = [s for s in sent() if s.get('text') != text]
        items.append({'time': time.strftime('%Y-%m-%d %H:%M'), 'to': _field(text, 'Кому'), 'file': os.path.basename(file),
                      'text': text[:6000]})
        path = _root() / 'sent.jsonl'
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(''.join(json.dumps(s, ensure_ascii=False) + '\n' for s in items[-SENT_KEEP:]), encoding='utf-8')
    return True


def _addressee_hit(task, to):
    """Адресат прошлого документа назван в задаче: «в/ч 12345», «Иванову», «начальнику штаба»."""
    task_low = task.lower().replace('ё', 'е')
    numbers = set(re.findall(r'\d{3,}', to))
    if numbers & set(re.findall(r'\d{3,}', task)):
        return True
    words = [w[:5] for w in re.findall(r'[а-яё]{5,}', to.lower().replace('ё', 'е'))]
    return bool(words) and sum(1 for w in words if w in task_low) >= min(2, len(words))


def similar_sent(task, materials='', limit=1):
    """Самые похожие прошлые документы: [(очки, запись)]. Адресат из задачи весит больше всего."""
    want = stems(task) | stems(materials[:3000])
    if not want:
        return []
    scored = []
    items = sent()
    for i, s in enumerate(items):
        have = stems(s.get('text', ''))
        score = len(want & have) / (len(want) ** 0.5 + 1)
        if s.get('to') and _addressee_hit(task, s['to']):
            score += 3
        score += i / max(1, len(items)) * 0.3          # при равенстве — более свежий
        scored.append((score, s))
    scored.sort(key=lambda x: -x[0])
    return [x for x in scored[:limit] if x[0] >= 1.2]


def mask_facts(text):
    """Даты, номера и сроки — в пометки; строки «Кому»/«От кого» остаются (адресат часто тот же)."""
    out = []
    for line in text.splitlines():
        if re.match(r'\s*(Кому|От кого)\s*:', line, re.IGNORECASE):
            out.append(line)
            continue
        line = re.sub(r'\b\d{1,2}\.\d{1,2}\.\d{2,4}\b', '[ДАТА]', line)
        line = re.sub(r'№\s*[\w/.-]+', '№ [НОМЕР]', line)
        out.append(line)
    return '\n'.join(out)


def prompt_block(task, materials='', max_chars=1800):
    """Добавка к задаче нейросети: похожий документ, который человек уже отправлял. Пусто — если такого нет."""
    found = similar_sent(task, materials)
    if not found:
        return ''
    s = found[0][1]
    sample = mask_facts(s['text'])[:max_chars]
    if LAST_TIME.search(task):
        head = ('\nПользователь просит сделать как в прошлый раз. Возьми за ОСНОВУ его прошлый документ ниже: тот же '
                'порядок частей, обороты, адресат и подпись (если задача не говорит иное). Даты, номера и сроки — только '
                'новые, из задачи и материалов; старые ([ДАТА], [НОМЕР]) не переносить:\n')
    else:
        head = ('\nПохожий документ, который пользователь уже отправлял (ориентир по формулировкам и порядку частей; '
                'факты, даты и номера из него НЕ переносить):\n')
    return head + '---\n' + sample + '\n---\n'


# ---------- поиск учится на выборе ----------

def _clicks_path():
    return _root() / 'search_memory.json'


def _clicks():
    try:
        return json.loads(_clicks_path().read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {}


def opened(query, path):
    """Человек открыл документ из результатов поиска по этим словам."""
    words = stems(query) or {w.lower()[:6] for w in re.findall(r'\w{2,}', query or '')}
    if not words or not path:
        return
    with _lock:
        data = _clicks()
        entry = data.setdefault(path, {'t': 0, 'w': {}})
        for w in words:
            entry['w'][w] = entry['w'].get(w, 0) + 1
        entry['t'] = time.time()
        if len(entry['w']) > 60:                       # у документа держим самые частые слова
            entry['w'] = dict(sorted(entry['w'].items(), key=lambda x: -x[1])[:60])
        if len(data) > CLICK_PATHS:
            for old in sorted(data, key=lambda p: data[p]['t'])[:len(data) - CLICK_PATHS]:
                del data[old]
        _write_json(_clicks_path(), data)


def rerank(query, rows):
    """Результаты поиска: документы, которые человек уже открывал по этим словам, — выше. Остальной порядок не меняется.
    Возвращает (строки, сколько поднято)."""
    words = stems(query) or {w.lower()[:6] for w in re.findall(r'\w{2,}', query or '')}
    if not words or not rows:
        return rows, 0
    data = _clicks()
    if not data:
        return rows, 0

    def score(path):
        entry = data.get(path)
        return sum(entry['w'].get(w, 0) for w in words) if entry else 0
    scored = [(score(r[0]), i, r) for i, r in enumerate(rows)]
    raised = sum(1 for s, _, _ in scored if s)
    if not raised:
        return rows, 0
    scored.sort(key=lambda x: (-min(x[0], 5), x[1]))    # 5 открытий хватает, чтобы стоять первым
    return [r for _, _, r in scored], raised


def stats():
    return {'sent': len(sent()), 'search': len(_clicks())}


def forget(what):
    name = {'sent': 'sent.jsonl', 'search': 'search_memory.json'}[what]
    try:
        (_root() / name).unlink()
    except OSError:
        pass
