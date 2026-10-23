import os
import tempfile
import unittest

os.environ['ISKRA_DATA_DIR'] = tempfile.mkdtemp()

import iskra_pu as P  # noqa: E402


def snap(rows):
    return [{'headers': ['ПУ', 'Удаление', 'Положение'],
             'rows': [{'object': o, 'section': 'СЕВЕРОДОНЕЦКОЕ НАПРАВЛЕНИЕ', 'cells': {'ПУ': o, 'Удаление': km, 'Положение': pos}}
                      for o, km, pos in rows]}]


class PU(unittest.TestCase):
    def test_report(self):
        changes = [{'object': 'КП 5447 обр СпН', 'column': 'Удаление от линии фронта', 'old': '56 км', 'new': '43 км', 'files': ['a']},
                   {'object': 'КП 5447 обр СпН', 'column': 'Количество ОС/ВВСТ', 'old': '27/2', 'new': '27/4', 'files': ['a']},
                   {'object': 'КП 101 мсп', 'new_row': True, 'section': 'лиманское направление',
                    'values': {'Наименование ПУ': 'КП 101 мсп', 'Удаление от линии фронта': '30 км'}, 'files': ['b']}]
        points = P.report_points(changes, ['ЗКП 5447 — 6 сут. с 17.10.2026'])
        self.assertEqual(points[0], 'КП 5447 обр СпН: удаление от линии фронта — 43 км (было 56 км); '
                                    'количество ОС/ВВСТ — 27/4 (было 27/2)')
        self.assertEqual(points[1], 'Новый: КП 101 мсп (ЛИМАНСКОЕ НАПРАВЛЕНИЕ): удаление от линии фронта — 30 км')
        self.assertIn('дольше', points[2])
        draft = P.report_draft(changes, me={'from': 'Штаб', 'signature': 'НШ\nполковник И.И. Иванов'})
        self.assertIn('Доношу', draft)
        self.assertIn('1. КП 5447 обр СпН: удаление', draft)
        self.assertIn('И.И. Иванов', draft)

    def test_history(self):
        P.save_snapshot(snap([('КП 5447', '56 км', 'ЗАЛУПИНСК'), ('ЗКП 5447', '80 км', 'КРЕМЕННАЯ')]), 'итог.docx')
        P.save_snapshot(snap([('КП 5447', '43 км', 'ЗАЛУПИНСК'), ('ЗКП 5447', '80 км', 'КРЕМЕННАЯ'), ('КП 101', '30 км', 'ЛИМАН')]))
        P.save_snapshot(snap([('КП 5447', '43 км', 'ПЕЧОРИНСК'), ('КП 101', '30 км', 'ЛИМАН')]))
        h = P.history('кп 5447')
        self.assertEqual([(x[1], x[2], x[3], x[4]) for x in h],
                         [('КП 5447', 'Положение', 'ЗАЛУПИНСК', 'ПЕЧОРИНСК'), ('КП 5447', 'Удаление', '56 км', '43 км')])
        everything = P.history()
        self.assertIn(('ЗКП 5447', 'убран из таблицы'), [(x[1], x[2]) for x in everything])
        self.assertIn(('КП 101', 'появился'), [(x[1], x[2]) for x in everything])
        self.assertEqual(P.query_from_phrase('где был КП 5447 на прошлой неделе'), 'КП 5447')

    def test_senders(self):
        texts = {'/x/1рота_изм.docx': 'Сведения 1 роты', '/x/док.docx': 'ТЕЛЕГРАММА от 3 рота ...', '/x/прочее.docx': 'текст'}
        got, missing = P.check_senders(['1рота', '3 рота', '4 рота'], list(texts), read=texts.get)
        self.assertEqual(set(got), {'1рота', '3 рота'})
        self.assertEqual(missing, ['4 рота'])
        self.assertEqual(P.parse_expected('1 рота, 2 рота\n3 рота;'), ['1 рота', '2 рота', '3 рота'])
        self.assertIn('4 рота', P.reminder_draft(['4 рота'], deadline='18:00'))


if __name__ == '__main__':
    unittest.main()
