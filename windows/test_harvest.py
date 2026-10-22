import os
import tempfile
import unittest

os.environ['ISKRA_DATA_DIR'] = tempfile.mkdtemp()

import iskra_harvest as H  # noqa: E402

DOC1 = ('ТЕЛЕГРАММА\nКому: Начальнику штаба полковнику Сидорову С.С.\nТекст: прошу представить сведения, т.е. отчёт.\n'
        'Подпись:\nНачальник отдела кадров\nподполковник А.В. Петров\nИсполнитель: старший лейтенант Ким Е.О.')
DOC2 = 'Доклад.\nКомандир войсковой части 12345\nполковник медицинской службы Б.Б. Орлов\nвсё выполнено, т.е. в срок.'


class People(unittest.TestCase):
    def test_finds_signatures_with_position(self):
        found = {fio: (rank, pos) for fio, rank, pos in H.people_in(DOC1 + '\n' + DOC2)}
        self.assertEqual(found['Петров А.В.'], ('подполковник', 'Начальник отдела кадров'))
        self.assertEqual(found['Орлов Б.Б.'][0], 'полковник медицинской службы')
        self.assertEqual(found['Орлов Б.Б.'][1], 'Командир войсковой части 12345')
        self.assertIn('Ким Е.О.', found)
        self.assertNotIn('Сидоров С.С.', ' '.join(found))          # дательный падеж («полковнику») — не подпись
        self.assertFalse(any('т.е' in f.lower() for f in found))   # «т.е.» — не инициалы

    def test_candidates_skip_known_and_hidden(self):
        found = H.harvest_people([('a.docx', DOC1), ('b.docx', DOC1), ('c.docx', DOC2)], known={'ким'})
        self.assertEqual(found[0]['fio'], 'Петров А.В.')
        self.assertEqual(found[0]['count'], 2)
        self.assertNotIn('Ким Е.О.', [c['fio'] for c in found])
        H._write_json(H._root() / 'people_found.json', {'found': found, 'hidden': []})
        H.hide(['Петров А.В.'])
        self.assertNotIn('Петров А.В.', [c['fio'] for c in H.candidates()])


class Words(unittest.TestCase):
    def test_learns_own_terms_not_typos(self):
        dictionary = {'отчет', 'представить', 'сведения', 'техника', 'прошу', 'срок'}
        docs = [(f'{i}.docx', 'Прошу представить сведения по форме ГСМ-2 и отчет по ЗИП: техника СПЕЦТРАНС, автобатальон. '
                              + ('отчет ' * 6) + 'отчот') for i in range(5)]
        words = H.harvest_words(docs, known=lambda w: w in dictionary,
                                suggest=lambda w: ['отчет'] if w == 'отчот' else [])
        self.assertIn('автобатальон', words)
        self.assertIn('спецтранс', words)
        self.assertNotIn('отчот', words)                          # опечатка: правильное «отчет» встречается намного чаще
        self.assertNotIn('техника', words)


if __name__ == '__main__':
    unittest.main()
