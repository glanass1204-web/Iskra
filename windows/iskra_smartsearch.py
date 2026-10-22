"""Поиск по смыслу без интернета: слова запроса приводятся к основе, служебные слова отбрасываются,
и каждое понятие ищется вместе с синонимами из служебного словаря («сколько людей на лицо» находит
«численность личного состава»). Если и так пусто — нейросеть подсказывает, какими словами это обычно пишут."""
import re

from iskra_index import fold, search_docs, stem

# Группы слов, которыми в документах называют одно и то же. Можно дополнять: data/sinonimy.txt
# (одна группа в строке, слова через запятую).
GROUPS = [
    'численность, личный состав, люди, людей, человек, военнослужащие, сотрудники, персонал, на лицо, по списку, штат, укомплектованность',
    'срок, сроки, не позднее, до, дедлайн',
    'доклад, донесение, отчёт, отчет, рапорт, сведения, справка, информация',
    'телеграмма, телеграммы, тлг, шифртелеграмма',
    'приказ, распоряжение, указание, директива, поручение',
    'техника, вооружение, машины, автомобили, автотехника, ВВСТ',
    'госпиталь, больница, медицинский, медпункт, лазарет',
    'больные, заболевшие, госпитализированные, заболеваемость, пациенты',
    'полигон, учения, стрельбы, тактические занятия',
    'проверка, инспекция, контроль, ревизия, аудит',
    'отпуск, отпуска, увольнение, увольнения',
    'деньги, финансы, денежное довольствие, выплаты, зарплата, премия, оплата',
    'продовольствие, питание, паёк, паек, довольствие',
    'топливо, ГСМ, горючее, бензин, дизельное, солярка',
    'ремонт, неисправность, поломка, восстановление, обслуживание',
    'кадры, назначение, перемещение, должность, вакансия',
    'учёба, учеба, занятия, подготовка, обучение, сборы',
    'охрана, караул, наряд, дежурство, дежурный',
    'жильё, жилье, квартиры, общежитие, размещение',
    'план, планирование, график, расписание',
    'нарушение, происшествие, чрезвычайное, ЧП, инцидент',
    'склад, имущество, материальные средства, запасы, обеспечение',
    'связь, телефон, радиостанция, средства связи',
    'документ, документы, бумаги, материалы',
]
STOP = set('''сколько какой какая какие каких где когда кто что чем о об про по для на в во с со и или а но ли же бы
нужно надо найди найти покажи показать есть было будет все всех всё это этот эта эти тот та те у к от из за
мне нам нас мой наш их его её ее как также ещё еще уже там тут здесь вот'''.split())


def _stems(phrase):
    return [stem(w) for w in re.findall(r'[^\W_]+', fold(phrase.lower()))]


def load_groups(root=None):
    groups = list(GROUPS)
    if root is not None:
        try:
            extra = (root / 'sinonimy.txt').read_text(encoding='utf-8').splitlines()
            groups += [g for g in extra if ',' in g and not g.strip().startswith('#')]
        except OSError:
            pass
    out = []
    for g in groups:
        out.append([_stems(w) for w in g.split(',') if w.strip()])
    return out


def _term(stems):
    if len(stems) == 1:
        return f'"{stems[0]}"*'
    return '(' + ' AND '.join(f'"{s}"*' for s in stems) + ')'


def concepts(query, groups):
    """Понятия запроса: [(слово, [варианты-основы])]. Многословные синонимы ищутся всеми словами сразу."""
    words = [w for w in re.findall(r'[^\W_]+', fold(query.lower())) if w not in STOP and len(w) > 1]
    used, out = set(), []
    # Сначала многословные выражения запроса («на лицо», «личный состав»)
    stems = [stem(w) for w in words]
    for g in groups:
        for variant in g:
            if len(variant) > 1 and all(v in stems for v in variant):
                for v in variant:
                    used.add(v)
                out.append((' '.join(variant), g))
                break
    for w, s in zip(words, stems):
        if s in used:
            continue
        group = next((g for g in groups if [s] in g or any(len(v) == 1 and (v[0].startswith(s) or s.startswith(v[0]))
                                                              and min(len(s), len(v[0])) >= 4 for v in g)), None)
        out.append((w, group or [[s]]))
        used.add(s)
    return out


def expression(query, groups, any_concept=False):
    parts = []
    for _, variants in concepts(query, groups):
        terms = list(dict.fromkeys(_term(v) for v in variants))
        parts.append('(' + ' OR '.join(terms) + ')' if len(terms) > 1 else terms[0])
    return (' OR ' if any_concept else ' AND ').join(parts)


def smart_search(query, limit=100, root=None, run_fts=None):
    """(строки, как искали). Сначала все понятия сразу, потом — любое из них."""
    groups = load_groups(root)
    run_fts = run_fts or _fts
    rows = []
    for any_concept in (False, True):
        expr = expression(query, groups, any_concept)
        if not expr:
            return [], ''
        rows = run_fts(expr, limit)
        if rows:
            return rows, ('по смыслу' if not any_concept else 'по смыслу, любое из понятий')
    return rows, ''


def _fts(expr, limit):
    import sqlite3
    from iskra_index import connect
    c = connect()
    try:
        return c.execute('SELECT path, snippet(search,1,"[","]","…",18) FROM search WHERE search MATCH ? ORDER BY rank LIMIT ?',
                         (expr, limit)).fetchall()
    except sqlite3.OperationalError:
        return []
    finally:
        c.close()


def search(query, limit=100, root=None, ai_expand=None):
    """Обычный поиск → по смыслу → (если дали ai_expand) слова от нейросети. (строки, пометка)."""
    rows = search_docs(query, limit)
    if rows:
        return rows, ''
    rows, how = smart_search(query, limit, root)
    if rows or ai_expand is None:
        return rows, how
    words = ai_expand(query)
    if not words:
        return [], ''
    rows = search_docs(' '.join(words), limit, any_word=True)
    return rows, ('нейросеть подсказала слова: ' + ', '.join(words)) if rows else ''
