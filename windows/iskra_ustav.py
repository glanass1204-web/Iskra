"""Уставы: статьи боевых и общевоинских уставов из файлов пользователя — поиск по статьям и точные ссылки.

Нейросеть не «заучивает» уставы (небольшая модель всё равно путала бы номера и формулировки), а при каждом
вопросе получает нужные статьи целиком и отвечает по ним со ссылкой «(БУ ч.2, ст. 45)».
Тексты уставов берутся только из папки «Уставы» на этом компьютере — сеть не нужна."""
import json
import math
import re
import shutil
import threading
from collections import Counter
from pathlib import Path

ARTICLE_MAX = 6000                      # очень длинная статья (таблица, приложение) — дальше не нужна для ответа

# Короткое имя устава — по имени файла или началу текста.
KNOWN = [
    (r'боев\w*\s+устав\w*.{0,150}?(?:част\w*|ч\.)\s*(?:1|i|перв\w*)(?![\di])', 'БУ ч.1'),
    (r'боев\w*\s+устав\w*.{0,150}?(?:част\w*|ч\.)\s*(?:2|ii|втор\w*)(?![\di])', 'БУ ч.2'),
    (r'боев\w*\s+устав\w*.{0,150}?(?:част\w*|ч\.)\s*(?:3|iii|трет\w*)(?![\di])', 'БУ ч.3'),
    (r'(?<![а-я])бу[\s_.-]*(?:св[\s_.-]*)?(?:ч|част\w*)?[\s_.-]*1(?![\d])', 'БУ ч.1'),
    (r'(?<![а-я])бу[\s_.-]*(?:св[\s_.-]*)?(?:ч|част\w*)?[\s_.-]*2(?![\d])', 'БУ ч.2'),
    (r'(?<![а-я])бу[\s_.-]*(?:св[\s_.-]*)?(?:ч|част\w*)?[\s_.-]*3(?![\d])', 'БУ ч.3'),
    (r'внутренн\w*\s+служб|(?<![а-я])увс(?![а-я])', 'УВС'),
    (r'дисциплинарн\w*\s+устав|(?<![а-я])ду(?:\s+вс)?(?![а-я])', 'ДУ'),
    (r'гарнизонн\w*|караульн\w*\s+служб|(?<![а-я])угикс(?![а-я])', 'УГиКС'),
    (r'строев\w*\s+устав|(?<![а-я])су(?:\s+вс)?(?![а-я])', 'СУ'),
    (r'боев\w*\s+устав', 'БУ'),
]
SHORTS = ('БУ ч.1', 'БУ ч.2', 'БУ ч.3', 'УВС', 'ДУ', 'УГиКС', 'СУ', 'БУ')

ARTICLE_WORD = re.compile(r'^\s*(?:Статья|Ст\.)\s*(\d{1,4})\s*[.:)]?\s*(.*)$', re.IGNORECASE)
NUMBERED = re.compile(r'^\s*(\d{1,4})\.\s+(\S.*)$')
HEADING = re.compile(r'^[А-ЯЁ][^.;:!?]{2,70}$')   # короткая строка без точки в конце
CHAPTER = re.compile(r'^\s*((?:Глава|Раздел|ГЛАВА|РАЗДЕЛ)\s+[\dIVXLC]+\.?.*)$')
WORD = re.compile(r'[а-яёa-z0-9]{3,}', re.IGNORECASE)
STOP = set('''как что где когда кто какой какая какие каков каковы порядок должен должна должны должно нужно надо можно
ли или для при про это этот эта эти тот так там тут его её их ему ему нам вам все всех всё всего есть быть был была
было были будет устав устава уставу уставе уставы уставов статья статьи статье статью части часть по боевой боевого
говорит гласит требует сказано написано согласно скажи расскажи объясни'''.split())


def _root():
    from iskra_index import ROOT
    return ROOT


def folder():
    return _root() / 'Уставы'


def _cache_path():
    return _root() / 'ustav_cache.json'


def norm(text):
    return (text or '').lower().replace('ё', 'е')


def short_name(name, head=''):
    """«Боевой устав по подготовке и ведению общевойскового боя. Часть 2» → «БУ ч.2»."""
    for text in (norm(Path(str(name)).stem).replace('_', ' '), re.sub(r'\s+', ' ', norm(head[:600]))):
        best = None                                   # раньше всех в тексте назван — тот и есть (заголовок)
        for pattern, short in KNOWN:
            m = re.search(pattern, text)
            key = (m.start(), short == 'БУ', m.end()) if m else None   # «БУ» без части — только если часть не названа
            if m and (best is None or key < best[0]):
                best = (key, short)
        if best:
            return best[1]
    return Path(str(name)).stem[:40]


def split_articles(text, doc):
    """Статьи устава: «Статья 12.» или «12. Текст…» в начале строки. Нумерованный перечень внутри статьи
    («1. …», «2. …» после статьи 45) статьёй не считается — номер статьи идёт по порядку."""
    out, cur, chapter, last, pending, section = [], None, '', 0, '', ''
    for line in (text or '').splitlines():
        s = line.strip()
        if not s:
            continue
        m = CHAPTER.match(s)
        if m and len(s) < 200:
            chapter, pending, section = s, '', ''
            continue
        if HEADING.match(s) and not NUMBERED.match(s) and not ARTICLE_WORD.match(s):
            if pending and cur is not None and len(cur['text']) < ARTICLE_MAX:
                cur['text'] += '\n' + pending
            pending = s                       # подзаголовок («Дежурный по роте») — к следующей статье
            continue
        num, rest = None, ''
        m = ARTICLE_WORD.match(s)
        if m:
            num, rest = int(m.group(1)), m.group(2)
        else:
            m = NUMBERED.match(s)
            if m and (int(m.group(1)) == last + 1 or (m.group(2)[:1].isupper() and (last == 0 or 0 < int(m.group(1)) - last <= 3))):
                num, rest = int(m.group(1)), m.group(2)
        if num is not None:
            section = pending or section          # подзаголовок действует до следующего
            cur = {'doc': doc, 'num': num, 'chapter': chapter, 'title': section, 'text': rest}
            out.append(cur)
            last, pending = num, ''
            continue
        if pending and cur is not None and len(cur['text']) < ARTICLE_MAX:
            cur['text'] += '\n' + pending            # короткая строка оказалась частью текста
        pending = ''
        if cur is not None and len(cur['text']) < ARTICLE_MAX:
            cur['text'] += '\n' + s
    for a in out:
        a['text'] = a['text'][:ARTICLE_MAX].strip()
    return [a for a in out if a['text']]


def ref(article):
    return f'{article["doc"]}, ст. {article["num"]}'


def stem(word):
    w = norm(word)
    if not re.search('[а-я]', w):
        return w
    if len(w) >= 6:
        return w[:5]                          # «пожаре», «пожарный» → «пожар»; «дежурного» → «дежур»
    return re.sub(r'[аеиоуыэюяйь]$', '', w) if len(w) >= 4 else w   # «роте», «роты» → «рот»


def terms(text):
    return [stem(w) for w in WORD.findall(norm(text)) if norm(w) not in STOP]


class Library:
    """Статьи всех уставов из папки. Разбор файла кэшируется (по времени изменения и размеру)."""

    def __init__(self, path=None, read=None):
        self.path = Path(path) if path else folder()
        self.read = read
        self.articles = []
        self.docs = {}                     # имя файла → (короткое имя, число статей)
        self._df, self._terms = {}, []

    def _reader(self, p):
        if self.read:
            return self.read(p)
        from iskra_index import extract
        return extract(p)

    def files(self):
        from iskra_index import supported
        own = sorted(p for p in self.path.rglob('*') if p.is_file() and supported(p) and not p.name.startswith('~$')) \
            if self.path.exists() else []
        names = {p.name for p in own}
        return own + [p for p in indexed_ustavs() if p.name not in names]

    def load(self):
        try:
            cache = json.loads(_cache_path().read_text(encoding='utf-8')) if not self.read else {}
        except (OSError, ValueError):
            cache = {}
        fresh, arts, docs = {}, [], {}
        for p in self.files():
            st = p.stat()
            key = f'{p}|{int(st.st_mtime)}|{st.st_size}'
            item = cache.get(key)
            if item is None:
                try:
                    text = self._reader(p)
                except Exception:                  # noqa: BLE001 — нечитаемый файл просто пропускаем
                    text = ''
                doc = short_name(p.name, text)
                item = {'doc': doc, 'articles': split_articles(text, doc)}
            fresh[key] = item
            docs[p.name] = (item['doc'], len(item['articles']))
            arts.extend(item['articles'])
        if not self.read:
            try:
                _cache_path().parent.mkdir(parents=True, exist_ok=True)
                _cache_path().write_text(json.dumps(fresh, ensure_ascii=False), encoding='utf-8')
            except OSError:
                pass
        self.articles, self.docs = arts, docs
        self._terms = [set(terms(a['chapter'] + ' ' + a.get('title', '') + ' ' + a['text'])) for a in arts]
        self._head = [set(terms(a['chapter'] + ' ' + a.get('title', ''))) for a in arts]
        self._tf = [Counter(terms(a['text'])) for a in arts]
        self._df = {}
        for ts in self._terms:
            for t in ts:
                self._df[t] = self._df.get(t, 0) + 1
        return self

    def get(self, doc, num):
        """Статья по ссылке: get('БУ ч.2', 45). doc можно неточно: «бу 2», «увс»."""
        want = short_name(doc) if doc else ''
        for a in self.articles:
            if a['num'] == num and (not want or a['doc'] == want or norm(a['doc']).startswith(norm(want))):
                return a
        return None

    def search(self, query, k=6):
        """Статьи по смыслу вопроса: сколько важных слов вопроса есть в статье (редкие слова весят больше).
        Возвращает [(доля покрытых слов вопроса, статья)], лучшие сверху."""
        q = list(dict.fromkeys(terms(query)))
        if not q or not self.articles:
            return []
        n = len(self.articles)
        weight = {t: math.log(1 + n / (1 + self._df.get(t, 0))) for t in q}
        total = sum(weight.values()) or 1
        want_doc = mentioned_doc(query)
        scored = []
        for a, ts, head, tf in zip(self.articles, self._terms, self._head, self._tf):
            hit = [t for t in q if t in ts]
            if not hit:
                continue
            score = sum(weight[t] for t in hit) / total
            # Подзаголовок/глава про то же («Дежурный по роте») — статья именно об этом; частые слова — по теме.
            score += 0.4 * sum(weight[t] for t in hit if t in head) / total
            score += 0.15 * min(1.0, sum(min(tf[t], 3) for t in hit) / (3 * len(q)))
            if want_doc and a['doc'] == want_doc:
                score += 0.25
            scored.append((score, a))
        scored.sort(key=lambda x: -x[0])
        return [(round(s, 3), a) for s, a in scored[:k]]


FILE_NAME = re.compile(r'устав|(?<![а-я])(бу|увс|угикс)(?![а-я])')


def indexed_ustavs():
    """Уставы, которые уже лежат в папках поиска (по имени файла) — подключаются сами, копировать не нужно."""
    try:
        from iskra_index import connect
        c = connect()
        try:
            rows = c.execute('SELECT path FROM docs').fetchall()
        finally:
            c.close()
    except Exception:                                      # noqa: BLE001 — нет индекса — только папка «Уставы»
        return []
    out = []
    for (path,) in rows:
        p = Path(path)
        if FILE_NAME.search(norm(p.stem).replace('_', ' ')) and not p.name.startswith('~$') and p.is_file():
            out.append(p)
    return sorted(out)[:40]


def mentioned_doc(text):
    """Какой устав назван в вопросе (или None)."""
    t = norm(text)
    if not re.search(r'устав|(?<![а-я])(бу|увс|угикс)(?![а-я])', t):
        return None
    for pattern, short in KNOWN:
        if re.search(pattern, t):
            return short
    return None


DIRECT = re.compile(r'(?:статья|статью|статьи|ст\.?)\s*(\d{1,4})', re.IGNORECASE)


def direct_ref(text):
    """«статья 45 БУ ч.2», «ст. 12 УВС» → ('БУ ч.2', 45); без названия устава — (None, 45)."""
    m = DIRECT.search(text or '')
    if not m:
        return None
    return mentioned_doc(text), int(m.group(1))


QUESTION = re.compile(r'(по уставу|в уставе|уставом|устав\w*\s+(говорит|требует|гласит|определяет|сказано)|'
                      r'(статья|статью|ст\.)\s*\d+\s*(бу|увс|ду|угикс|су|боев|устав)|'
                      r'(?<![а-я])(бу|увс|угикс)(?![а-я])|боев\w* устав|общевоинск\w* устав|дисциплинарн\w* устав|'
                      r'устав\w* (внутренн|гарнизон|караул|строев))', re.IGNORECASE)


def is_question(text):
    return bool(QUESTION.search(norm(text)))


def materials(found, limit=ARTICLE_MAX):
    """Статьи для нейросети: [(«Устав: БУ ч.2, ст. 45», текст)]."""
    return [(f'Устав: {ref(a)}', ((a['chapter'] + '\n' if a['chapter'] else '') + a['text'])[:limit]) for _, a in found]


def add_files(paths):
    """Скопировать файлы уставов в папку «Уставы». Возвращает число скопированных."""
    dest = folder()
    dest.mkdir(parents=True, exist_ok=True)
    n = 0
    for p in paths:
        p = Path(p)
        if p.is_file():
            shutil.copy2(p, dest / p.name)
            n += 1
    return n


_LIB = None
_LIB_LOCK = threading.Lock()


def library(reload=False):
    """Общая библиотека (загружается один раз; reload=True — после добавления файлов)."""
    global _LIB
    with _LIB_LOCK:                                      # окно, чат и нейросеть могут попросить одновременно
        if _LIB is None or reload:
            _LIB = Library().load()
        return _LIB
