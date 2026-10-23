"""Offline Russian spelling and office-style checks (Hunspell ru_RU dictionary via spylls). No network."""
import re
import sys
import threading
from dataclasses import dataclass
from pathlib import Path

from iskra_index import BASE, ROOT

DICT_DIR = Path(getattr(sys, '_MEIPASS', BASE)) / 'dict'
USER_WORDS = ROOT / 'user_words.txt'
WORD = re.compile(r'[А-Яа-яЁё]+(?:-[А-Яа-яЁё]+)*')


@dataclass(frozen=True)
class Issue:
    start: int
    end: int
    kind: str        # 'spelling' | 'style' | 'typo'
    text: str        # the problem fragment
    message: str
    fix: str = ''    # suggested replacement, if any


# Frequent mistakes in official letters and telegrams: (pattern, correct form, explanation).
STYLE_RULES = [
    (r'\bсогласно\s+(приказа|распоряжения|указания|решения|плана|графика|договора|положения|постановления)\b', None,
     '«согласно» требует дательного падежа: согласно приказу, распоряжению, плану'),
    (r'\bв течении\b(?!\s+(реки|болезни|процесса|событий))', 'в течение', 'о времени пишется «в течение»'),
    (r'\bв продолжении\b', 'в продолжение', 'о времени пишется «в продолжение»'),
    (r'\bв заключении\b(?=\s+(хочу|отмеч|сообщ|прошу|следует))', 'в заключение', 'в смысле «в конце» — «в заключение»'),
    (r'\bпо приезду\b', 'по приезде', 'правильно: по приезде'),
    (r'\bпо прибытию\b', 'по прибытии', 'правильно: по прибытии'),
    (r'\bпо окончанию\b', 'по окончании', 'правильно: по окончании'),
    (r'\bпо истечению\b', 'по истечении', 'правильно: по истечении'),
    (r'\bпо завершению\b', 'по завершении', 'правильно: по завершении'),
    (r'\bоплатить за\b(?!\s+сч[её]т)', 'оплатить', '«оплатить» без «за» (но «заплатить за», «за счёт»)'),
    (r'\bоплата за\b(?!\s+сч[её]т)', 'оплата', '«оплата» без «за» (но «плата за», «за счёт»)'),
    (r'\bвследствии\b', 'вследствие', 'правильно: вследствие'),
    (r'\bввиду того что\b', None, 'в официальном тексте лучше «в связи с тем, что»'),
    (r'\bсогласно с\b', None, '«согласно» без «с» и с дательным падежом: согласно приказу'),
    (r'\bнесмотря\s+на\s+то,?\s+что\b', None, 'перед «что» нужна запятая: «несмотря на то, что»'),
    (r'\bв виду\b(?=\s+(того|отсутствия|необходимости|изменения))', 'ввиду', 'в значении «из-за» — «ввиду»'),
    (r'\bна протяжение\b', 'на протяжении', 'правильно: на протяжении'),
    (r'\bпредоставить\s+(отчет|отчёт|доклад|донесение|сведения\s+о\s+выполнении)\b', None,
     'отчёт, доклад «представляют» (предъявляют), а не «предоставляют» (дают в пользование)'),
]


# Служебные слова и сокращения, которых нет в общем словаре.
OFFICE_WORDS = set('''шифротелеграмма шифротелеграммы шифротелеграмму шифртелеграмма шифртелеграммы телефонограмма
телефонограммы телефонограмму спецсвязь спецсвязи медслужба медслужбы медпункт медпункта автобат автобата автобатом
госзакупки госзакупок вриo врио врид нач зам пом исх вх тлг вч в/ч мто гсм ввст сизо ло рхбз кмб окр вво уво дшб
допуск допуска делопроизводство делопроизводства несекретно секретно подразделение подразделения комендатура
комендатуры'''.split())

# Войсковые сокращения и слова, которых нет в общем словаре (иначе вычитка «исправит» «дроны» на «доны»).
MIL_WORDS = set('''мсп мсб мср мсд мсбр мсв тб тбр тп тд тр адн абатр адн сабр обр брспн спн бтгр бтг сво зкп кп пу нп ппу
пвд ппд пд мпп омедб медр лбс бк бп бпла бэк рэб птур пзрк зрк сау рсзо бмп бтр бмд ктп ппт ввст сочп вбд вус нш зкб
орвб исб рвбр ремр рмо взв кв квс зкв зкр зкб кшм кшмр рлс гсм вдв мтлб мтлбу уаз камаз урал брэм рхбз рхбзр мтоб
фпв fpv овп оп нп кнп тпу вкп спу ртр сбр гсн нвг пнв тпв бпк рпг агс сптп тмп'''.split())
MIL_STEMS = ('дрон', 'беспилот', 'квадрокоптер', 'коптер', 'контрактник', 'срочник', 'мобилизов', 'добровол',
             'штурмов', 'артдивизион', 'артполк', 'артбригад', 'минометн', 'миномётн', 'миномет', 'миномёт', 'гранатомет',
             'гранатомёт', 'пулемет', 'пулемёт', 'снайпер', 'зенитн', 'ротаци', 'эвакуац', 'фортификац', 'разминир',
             'военнослуж', 'боекомплект', 'боеприпас', 'бронежилет', 'тероборон', 'росгвард', 'нацгвард', 'военкомат',
             'призывник', 'мотострелк', 'десантник', 'разведчик', 'связист', 'шифровальщик', 'спецназ', 'комиссован',
             'госпитализ', 'контузи', 'бпла', 'рэбов', 'артиллерист', 'танкист', 'зенитчик', 'сапер', 'сапёр',
             'командировочн', 'отпускник', 'военнопленн', 'самоходк', 'бронетехник', 'автомобилист', 'ремонтник',
             'заградотряд', 'наградн', 'пополнени', 'увольняем', 'убывш', 'прибывш', 'выбывш', 'полевк', 'блиндаж')


def _issue_style(text):
    out = []
    for pattern, fix, message in STYLE_RULES:
        for m in re.finditer(pattern, text, re.IGNORECASE):
            out.append(Issue(m.start(), m.end(), 'style', m.group(0), message, fix or ''))
    # Повтор слова: «и и», «в в».
    for m in re.finditer(r'(?<![\w/-])([А-Яа-яЁё]+)\s+\1(?![\w/-])', text, re.IGNORECASE):   # «в в/ч» — не повтор
        if m.group(1).lower() not in ('так', 'еле', 'чуть', 'едва', 'нет', 'да', 'ой'):
            out.append(Issue(m.start(), m.end(), 'typo', m.group(0), 'слово повторяется', m.group(1)))
    for m in re.finditer(r'[ \t]{2,}', text):
        out.append(Issue(m.start(), m.end(), 'typo', m.group(0), 'лишние пробелы', ' '))
    for m in re.finditer(r'\s+([,.;:!?])', text):
        out.append(Issue(m.start(), m.end(), 'typo', m.group(0), 'пробел перед знаком препинания', m.group(1)))
    for m in re.finditer(r'([,;])(?=[А-Яа-яЁё])', text):
        out.append(Issue(m.start(), m.end(), 'typo', m.group(0), 'нет пробела после знака препинания', m.group(1) + ' '))
    return out


class SpellChecker:
    """Lazy: the dictionary (3 MB) is loaded in the background on first use."""

    def __init__(self, dict_dir=DICT_DIR, user_words=USER_WORDS):
        self.dict_dir = Path(dict_dir)
        self.user_words_path = Path(user_words)
        self._dict = None
        self._lock = threading.Lock()
        self._auto = None
        self.user_words = set()
        try:
            self.user_words = {w.strip().lower() for w in self.user_words_path.read_text(encoding='utf-8').splitlines() if w.strip()}
        except OSError:
            pass

    @property
    def available(self):
        return (self.dict_dir / 'ru_RU.dic').is_file()

    def _dictionary(self):
        with self._lock:
            if self._dict is None:
                from spylls.hunspell import Dictionary
                self._dict = Dictionary.from_files(str(self.dict_dir / 'ru_RU'))
            return self._dict

    def preload(self):
        threading.Thread(target=self._dictionary, daemon=True).start()

    @property
    def auto_words(self):
        """Слова, которые Искра выучила по вашим документам (iskra_harvest)."""
        if self._auto is None:
            try:
                self._auto = {w.strip() for w in (self.user_words_path.parent / 'auto_words.txt').read_text(
                    encoding='utf-8').splitlines() if w.strip()}
            except OSError:
                self._auto = set()
        return self._auto

    @auto_words.setter
    def auto_words(self, words):
        self._auto = set(words)

    def known(self, word, learned=True):
        w = word.replace('ё', 'е').replace('Ё', 'Е')
        low = w.lower()
        if low in self.user_words or low in OFFICE_WORDS or low in MIL_WORDS:
            return True
        if any(low.startswith(st) and len(low) <= len(st) + 5 for st in MIL_STEMS):
            return True                                # «дроны», «контрактника», «срочников», «военнослужащему»
        if learned and w.lower() in self.auto_words:
            return True
        if any(ch.isupper() for ch in w[1:]):
            return True                                # ВрИО, ВрИД, МТО — сокращения
        if re.match(r'(спец|мед|авто|гос|военно|воен|тех|хоз|инж|комм|нач|зам|пом|рем|прод|фин)', w.lower()) and len(w) > 6:
            stem_ok = self._dictionary().lookup(re.sub(r'^(спец|мед|авто|гос|военно|воен|тех|хоз|инж|комм|нач|зам|пом|рем|прод|фин)', '', w.lower()))
            if stem_ok:
                return True                            # спецсвязь, медслужба, автобат, госзакупки: приставка + слово
        d = self._dictionary()
        if d.lookup(word) or d.lookup(w) or d.lookup(w.lower()):
            return True
        # «северо-западный», «кто-то»: каждая часть по отдельности.
        if '-' in w:
            return all(d.lookup(p) or d.lookup(p.lower()) or len(p) <= 2 for p in w.split('-'))
        return False

    def suggest(self, word, limit=6):
        out = []
        for s in self._dictionary().suggest(word):
            if s not in out:
                out.append(s)
            if len(out) >= limit:
                break
        return out

    def add_word(self, word):
        self.user_words.add(word.lower())
        self.user_words_path.parent.mkdir(parents=True, exist_ok=True)
        with self.user_words_path.open('a', encoding='utf-8') as f:
            f.write(word.lower() + '\n')

    def check(self, text, with_style=True):
        """All issues in text, sorted by position. Proper names, abbreviations and short words are not flagged."""
        issues = []
        for m in WORD.finditer(text):
            w = m.group(0)
            if len(w) < 3 or w.isupper():
                continue
            # Слово с заглавной не в начале предложения — скорее всего фамилия или название.
            if w[0].isupper():
                before = text[:m.start()].rstrip()
                if before and before[-1] not in '.!?:\n«"':
                    continue
            if not self.known(w):
                issues.append(Issue(m.start(), m.end(), 'spelling', w, 'нет в словаре'))
        if with_style:
            issues.extend(_issue_style(text))
        issues.sort(key=lambda i: (i.start, i.end))
        return issues


def summary(issues):
    spelling = sum(1 for i in issues if i.kind == 'spelling')
    style = sum(1 for i in issues if i.kind == 'style')
    typo = sum(1 for i in issues if i.kind == 'typo')
    if not issues:
        return 'Ошибок не найдено.'
    return f'Орфография: {spelling}, стиль: {style}, опечатки и пробелы: {typo}.'


def fix_typical(text):
    """Applies only the safe, unambiguous fixes (style rules with a correct form, repeated words, spaces).
    Spelling is not changed automatically: a word may be a term or a name. Returns (text, number of fixes)."""
    issues = [i for i in _issue_style(text) if i.fix]
    done, last = 0, len(text) + 1
    for i in sorted(issues, key=lambda x: x.start, reverse=True):
        if i.end > last:
            continue  # пересекается с уже исправленным
        fix = i.fix
        if i.text[:1].isupper() and fix[:1].islower():
            fix = fix[:1].upper() + fix[1:]
        text = text[:i.start] + fix + text[i.end:]
        last = i.start
        done += 1
    return text, done
