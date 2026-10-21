"""Offline document assistant: deterministic extraction from document text. No network, no AI model.

Everything it reports is found in the text itself (with the surrounding sentence as proof),
so it never invents dates, names or numbers.
"""
import re
from collections import Counter
from dataclasses import dataclass
from datetime import date, timedelta

MONTHS = {
    'январ': 1, 'феврал': 2, 'март': 3, 'апрел': 4, 'ма': 5, 'июн': 6,
    'июл': 7, 'август': 8, 'сентябр': 9, 'октябр': 10, 'ноябр': 11, 'декабр': 12,
}
MONTH_WORD = r'(январ[яь]|феврал[яь]|марта?|апрел[яь]|ма[яй]|июн[яь]|июл[яь]|августа?|сентябр[яь]|октябр[яь]|ноябр[яь]|декабр[яь])'
NUM_DATE = re.compile(r'(?<!\d)(\d{1,2})\.(\d{1,2})\.(\d{4}|\d{2})(?!\d)')
WORD_DATE = re.compile(r'(?<!\d)(\d{1,2})\s+' + MONTH_WORD + r'(?:\s+(\d{4}))?', re.IGNORECASE)
DEADLINE_WORDS = re.compile(r'(?<![а-яё])(до|не позднее|не позже|срок\w*|в течение|исполнить|представить|направить|подготовить|обеспечить)(?![а-яё])', re.IGNORECASE)
# «к 25 октября» — только прямо перед датой, иначе «№ 15-к от 20.10» тоже считался бы сроком.
DEADLINE_K = re.compile(r'(?<![\w-])к\s+$', re.IGNORECASE)
# Sentence end, but not after initials («С.П. Сидоров») or common abbreviations («тел. 8…», «г. Москва»).
SENTENCE_END = re.compile(
    r'(?<=[.!?…])(?<![А-ЯЁA-Z]\.)(?<!тел\.)(?<!\bг\.)(?<!ул\.)(?<!\bд\.)(?<!руб\.)(?<!\bп\.)(?<!ст\.)(?<!\bр\.)(?<!исх\.)(?<!вх\.)'
    r'\s+(?=[А-ЯЁA-Z0-9«"])|\n+')
WORD = re.compile(r'[а-яёa-z]{3,}', re.IGNORECASE)
# Initials are «И.И.» (not «И. И» inside words); the surname may come before or after them.
PERSON_AFTER = re.compile(r'(?<![А-ЯЁа-яё])([А-ЯЁ][а-яё]{2,}(?:-[А-ЯЁ][а-яё]+)?)\s+([А-ЯЁ])\.\s?([А-ЯЁ])\.')
PERSON_BEFORE = re.compile(r'(?<![А-ЯЁа-яё])([А-ЯЁ])\.\s?([А-ЯЁ])\.\s?([А-ЯЁ][а-яё]{2,}(?:-[А-ЯЁ][а-яё]+)?)')
DOC_NUMBER = re.compile(r'(?:№|N\s?°|номер)\s*([0-9][0-9A-Za-zА-Яа-я./\-]*)', re.IGNORECASE)
MONEY = re.compile(r'(?<![\d,.])(\d{1,3}(?:[\s ]\d{3})+|\d+)(?:[.,](\d{1,2}))?\s*(тыс\.?\s*руб\w*\.?|млн\.?\s*руб\w*\.?|руб\w*\.?|р\.|₽)', re.IGNORECASE)
PHONE = re.compile(r'(?<!\d)(?:\+7|8)[\s\-(]*\d{3}[\s\-)]*\d{3}[\s\-]*\d{2}[\s\-]*\d{2}(?!\d)')
EMAIL = re.compile(r'[\w.+-]+@[\w-]+(?:\.[\w-]+)+')

STOP = set('''и в во не что он на я с со как а то все она так его но да ты к у же вы за бы по только ее мне было вот от меня
еще нет о из ему теперь когда даже ну вдруг ли если уже или ни быть был него до вас нибудь опять уж вам ведь там потом себя
ничего ей может они тут где есть надо ней для мы тебя их чем была сам чтоб без будто чего раз тоже себе под будет ж тогда
кто этот того потому этого какой совсем ним здесь этом один почти мой тем чтобы нее сейчас были куда зачем всех никогда
можно при наконец два об другой хоть после над больше тот через эти нас про всего них какая много разве три эту моя
впрочем хорошо свою этой перед иногда лучше чуть том нельзя такой им более всегда конечно всю между года году также
согласно соответствии является являются которые который которая которое данный данной данного указанный настоящий
настоящего'''.split())


@dataclass(frozen=True)
class Found:
    value: str      # what was found: «25.10.2026», «Иванов И.И.», «№ 15»
    context: str    # the sentence it was found in — proof for the user
    sort_key: object = None


def sentences(text):
    parts = SENTENCE_END.split(text)
    return [re.sub(r'\s+', ' ', p).strip() for p in parts if p and len(p.strip()) > 2]


def _month(word):
    w = word.lower()
    for stem, n in MONTHS.items():
        if w.startswith(stem):
            return n
    return None


def parse_dates(text, today=None):
    """All dates in the text: «25.10.2026», «25.10.26», «25 октября 2026 года», «25 октября» (current year)."""
    today = today or date.today()
    found = []
    for m in NUM_DATE.finditer(text):
        d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if y < 100:
            y += 2000
        try:
            found.append((m.start(), m.end(), date(y, mo, d)))
        except ValueError:
            pass
    for m in WORD_DATE.finditer(text):
        mo = _month(m.group(2))
        y = int(m.group(3)) if m.group(3) else today.year
        try:
            found.append((m.start(), m.end(), date(y, mo, int(m.group(1)))))
        except (ValueError, TypeError):
            pass
    found.sort()
    return found


def deadlines(text, today=None):
    """Dates that look like deadlines: a deadline word stands right before the date in the same sentence."""
    out = []
    seen = set()
    for s in sentences(text):
        for start, _, d in parse_dates(s, today):
            before = s[max(0, start - 40):start]
            if DEADLINE_WORDS.search(before) or DEADLINE_K.search(before):
                key = (d, s)
                if key not in seen:
                    seen.add(key)
                    out.append(Found(d.strftime('%d.%m.%Y'), s[:400], d))
    out.sort(key=lambda f: f.sort_key)
    return out


def all_dates(text, today=None):
    out, seen = [], set()
    for s in sentences(text):
        for _, _, d in parse_dates(s, today):
            if (d, s) not in seen:
                seen.add((d, s))
                out.append(Found(d.strftime('%d.%m.%Y'), s[:400], d))
    out.sort(key=lambda f: f.sort_key)
    return out


def people(text):
    counts = Counter()
    context = {}
    for s in sentences(text):
        for m in PERSON_AFTER.finditer(s):
            name = f'{m.group(1)} {m.group(2)}.{m.group(3)}.'
            counts[name] += 1
            context.setdefault(name, s)
        for m in PERSON_BEFORE.finditer(s):
            name = f'{m.group(3)} {m.group(1)}.{m.group(2)}.'
            counts[name] += 1
            context.setdefault(name, s)
    return [Found(n, context[n][:400], -c) for n, c in counts.most_common()]


def numbers(text):
    out, seen = [], set()
    for s in sentences(text):
        for m in DOC_NUMBER.finditer(s):
            v = '№ ' + m.group(1).rstrip('.,')
            if v not in seen:
                seen.add(v); out.append(Found(v, s[:400]))
    return out


def money(text):
    out = []
    for s in sentences(text):
        for m in MONEY.finditer(s):
            whole = re.sub(r'[\s ]', '', m.group(1))
            value = whole + (',' + m.group(2) if m.group(2) else '')
            out.append(Found(f'{value} {m.group(3).strip()}', s[:400]))
    return out


def contacts(text):
    out, seen = [], set()
    for s in sentences(text):
        for m in list(PHONE.finditer(s)) + list(EMAIL.finditer(s)):
            v = m.group(0).strip()
            if v not in seen:
                seen.add(v); out.append(Found(v, s[:400]))
    return out


def summary(text, limit=5):
    """Extractive summary: the most informative sentences, in their original order. Nothing is rephrased."""
    ss = [s for s in sentences(text) if 25 <= len(s) <= 600]
    if len(ss) <= limit:
        return ss
    freq = Counter(w for s in ss for w in (x.lower() for x in WORD.findall(s)) if w not in STOP)
    if not freq:
        return ss[:limit]
    top = max(freq.values())

    def score(i, s):
        words = [w.lower() for w in WORD.findall(s) if w.lower() not in STOP]
        if not words:
            return 0
        base = sum(freq[w] / top for w in words) / (len(words) ** 0.5)
        # Opening sentences of official documents usually state the subject.
        return base + (0.6 if i < 2 else 0) + (0.3 if DEADLINE_WORDS.search(s) and parse_dates(s) else 0)

    best = sorted(range(len(ss)), key=lambda i: score(i, ss[i]), reverse=True)[:limit]
    return [ss[i] for i in sorted(best)]


def deadline_status(d, today=None):
    today = today or date.today()
    days = (d - today).days
    if days < 0:
        return f'просрочено на {-days} дн.'
    if days == 0:
        return 'сегодня'
    if days == 1:
        return 'завтра'
    return f'через {days} дн.'


def upcoming(docs, today=None, ahead=30, behind=7):
    """Deadlines across many documents: [(date, status, file, sentence)] from `behind` days ago to `ahead` days on."""
    today = today or date.today()
    lo, hi = today - timedelta(days=behind), today + timedelta(days=ahead)
    rows = []
    for path, text in docs:
        for f in deadlines(text, today):
            if lo <= f.sort_key <= hi:
                rows.append((f.sort_key, deadline_status(f.sort_key, today), path, f.context))
    rows.sort(key=lambda r: (r[0], r[2]))
    return rows


# ---------- Понимание команд помощника ----------

HELP = '''Я помогаю работать с документами на этом компьютере — без интернета и без нейросети.
Отвечаю только тем, что действительно написано в документах.

Можно писать так:
• найди приказ о премировании — поиск по всем документам в папках
• кратко — о чём выбранный документ
• сроки — сроки исполнения в выбранном документе
• ближайшие сроки — сроки по всем документам на 30 дней вперёд
• даты, кто (ФИО), номера, суммы, контакты — всё это из выбранного документа
• формула сумма столбца C где в A "Москва" — готовая формула Excel; =ВПР(…) — объясню формулу
• Word в Excel — собрать таблицу из многих документов Word; Excel в Word — документы по образцу
• входящие (что пришло) — новые файлы из папки входящих: вид, номер, от кого, срок
• составь телеграмму — черновик по виду: доклад, указание, запрос, напоминание; ответ на телеграмму — по её пунктам
• объедини телеграммы — из нескольких телеграмм одна; орфография — проверка текста
• свод таблиц — 5 таблиц Excel в одну по организациям (по списку, на лицо…), итог и проверка
• макрос удалить пустые строки и выделить повторы в столбце B — готовый макрос VBA
• обзор папок — что лежит в папках: виды документов, от кого, сроки, темы
• сколько документов — что сейчас в поиске
С нейросетью (версия «с нейросетью», тоже без интернета):
• напиши доклад о готовности техники по последним телеграммам — черновик по найденным документам
• вопрос со знаком «?»: какой срок представления сведений по телеграмме 154? — ответ по документам с источником
• в редакторе телеграмм — «Нейросеть ▾»: официальный стиль, сократить, исправить ошибки
Документ выбирается в списке результатов слева.'''


def intent(text):
    """Turns a free-form request into (command, argument)."""
    t = re.sub(r'\s+', ' ', text.strip().lower().replace('ё', 'е')).rstrip('?!.')
    if not t:
        return 'help', ''
    if t.startswith('='):
        return 'explain', text.strip()
    rules = [
        (r'^(помощь|справка|что (ты )?умеешь|команды|привет\w*|здравствуй\w*)', 'help'),
        (r'^(макрос|напиши макрос|сделай макрос|vba)', 'macro'),
        (r'(орфограф|правописан|проверь текст|ошибк\w* в тексте|грамотност)', 'spell'),
        (r'(?<![а-я])(объедин\w*|сведи|свести|собер\w*|собрать|склей\w*)(?![а-я]).*(телеграм)', 'merge'),
        (r'(ответ\w*|отвеч\w*|доклад\w* на)\s.*(телеграм|входящ|письм)', 'reply'),
        (r'^(входящ\w*|что (пришло|нового|новенького)|новые (файлы|документы)|почта)', 'inbox'),
        (r'из\s+(документ\w*\s+)?(word|ворд)', 'word2excel'),
        (r'(word|ворд|документ\w*).*(в|→|->)\s*(excel|эксел|таблиц)', 'word2excel'),
        (r'(excel|эксел\w*|таблиц\w*).*(в|→|->)\s*(word|ворд|документ)', 'excel2word'),
        (r'(по образцу|рассылк|слияни)', 'excel2word'),
        (r'(word|ворд|документ\w* ворд).*(excel|эксел|таблиц)', 'word2excel'),
        (r'(свод|сведи|собери|собрать|объедин\w*).*(таблиц|эксел|excel|xlsx)|^свод(?!к)', 'svod'),
        (r'^(телеграмм\w*|новая телеграмм|состав\w* телеграмм|напиши телеграмм|подготов\w* телеграмм)', 'telegram'),
        (r'^(объясни|что делает|что значит)\s*.*=', 'explain'),
        (r'(ближайш\w* срок|все срок|срок\w* (по всем|на неделю|на месяц)|что горит|просроч|контроль срок)', 'upcoming'),
        (r'^(кратко|коротко|о ч[её]м|суть|резюме|сводк\w* по документ|перескажи)', 'summary'),
        (r'^(срок|когда сда|к какому числу|дедлайн)', 'deadlines'),
        (r'^(дат[аы]|все дат)', 'dates'),
        (r'^(кто|фио|люди|исполнител|ответственн|фамили)', 'people'),
        (r'^(номер|реквизит|№)', 'numbers'),
        (r'^(сумм[аы]?(?! по)|деньг|стоимост|цен[аы])', 'money'),
        (r'^(контакт|телефон|почт|email)', 'contacts'),
        (r'^(формул|excel|эксель)', 'formula'),
        (r'^(сколько документов|статистик|что в индексе)', 'stats'),
    ]
    rules += [
        (r'(обзор|обобщ\w*|что (лежит |есть )?в (этой |моих |мои[хм] )?папк\w*|что в папках|по папкам)', 'overview'),
        (r'^(напиши|составь|подготовь|сформулируй|набросай|перепиши|придумай|сочини)\b', 'write'),
    ]
    for pattern, cmd in rules:
        if re.search(pattern, t):
            if cmd == 'formula':
                # Без нижнего регистра: имена столбцов и условия в кавычках важны как есть.
                return cmd, re.sub(r'^(формул\w*|excel|эксель)\s*(для|на)?\s*', '', text.strip(), flags=re.IGNORECASE)
            if cmd == 'macro':
                return cmd, re.sub(r'^(напиши |сделай )?(макрос\w*|vba)\s*(для|чтобы|который|:)?\s*', '', text.strip(), flags=re.IGNORECASE)
            if cmd == 'explain':
                return cmd, text[text.index('='):].strip()
            if cmd == 'write':
                return cmd, text.strip()
            return cmd, ''
    m = re.match(r'^(найди|найти|поиск|ищи|покажи|где)\s+(.+)', t)
    if m:
        return 'search', m.group(2)
    if text.strip().endswith('?') and len(t.split()) >= 3:
        return 'ask', text.strip()
    return 'search', t
