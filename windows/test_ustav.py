import os
import tempfile
import unittest
from pathlib import Path

import iskra_ustav as u

BU2 = '''БОЕВОЙ УСТАВ
по подготовке и ведению общевойскового боя
Часть 2
Батальон, рота
Глава 4. Оборона
44. Оборона имеет целью отразить наступление превосходящих сил противника.
45. Командир роты в обороне обязан:
1. организовать систему огня;
2. Определить порядок инженерного оборудования опорного пункта.
Опорный пункт роты оборудуется в инженерном отношении.
46. Опорный пункт взвода оборудуется траншеями и ходами сообщения.
'''
UVS = '''Устав внутренней службы Вооруженных Сил
Глава 7. Суточный наряд
Статья 294. Дневальный по роте назначается из рядовых.
Статья 295. Дежурный по роте подчиняется дежурному по полку и отвечает за порядок в роте.
'''


class Parse(unittest.TestCase):
    def test_names(self):
        self.assertEqual(u.short_name('устав.docx', BU2), 'БУ ч.2')
        self.assertEqual(u.short_name('УВС ВС РФ.pdf'), 'УВС')
        self.assertEqual(u.short_name('x.txt', 'Боевой устав часть II'), 'БУ ч.2')
        self.assertEqual(u.short_name('x.txt', 'Дисциплинарный устав Вооруженных Сил'), 'ДУ')
        self.assertEqual(u.short_name('x.txt', 'Устав гарнизонной и караульной служб'), 'УГиКС')

    def test_articles_skip_inner_lists(self):
        arts = u.split_articles(BU2, 'БУ ч.2')
        self.assertEqual([a['num'] for a in arts], [44, 45, 46])
        self.assertIn('организовать систему огня', arts[1]['text'])
        self.assertIn('инженерного оборудования', arts[1]['text'])
        self.assertEqual(arts[1]['chapter'], 'Глава 4. Оборона')
        arts = u.split_articles(UVS, 'УВС')
        self.assertEqual([a['num'] for a in arts], [294, 295])

    def test_direct_and_question(self):
        self.assertEqual(u.direct_ref('статья 45 БУ ч.2'), ('БУ ч.2', 45))
        self.assertEqual(u.direct_ref('ст. 295 УВС'), ('УВС', 295))
        self.assertTrue(u.is_question('что по уставу делает дежурный по роте'))
        self.assertFalse(u.is_question('найди телеграмму 154'))


class Library(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        Path(self.dir, 'БУ ч2.txt').write_text(BU2, encoding='utf-8')
        Path(self.dir, 'УВС.txt').write_text(UVS, encoding='utf-8')
        self.lib = u.Library(self.dir, read=lambda p: Path(p).read_text(encoding='utf-8')).load()

    def test_get_and_search(self):
        self.assertEqual(self.lib.get('БУ ч.2', 46)['num'], 46)
        self.assertEqual(self.lib.get('увс', 295)['doc'], 'УВС')
        top = self.lib.search('кому подчиняется дежурный по роте')
        self.assertEqual(u.ref(top[0][1]), 'УВС, ст. 295')
        top = self.lib.search('как оборудуется опорный пункт взвода')
        self.assertEqual(top[0][1]['num'], 46)
        self.assertEqual(self.lib.docs['УВС.txt'], ('УВС', 2))

    def test_materials_and_ai_refs(self):
        import iskra_ai as ai
        mats = u.materials(self.lib.search('дежурный по роте'))
        self.assertTrue(mats[0][0].startswith('Устав: УВС, ст. 29'))
        old = ai.run
        try:
            ai.run = lambda *a, **k: 'Дежурный подчиняется дежурному по полку (УВС, ст. 295). Иначе (УВС, ст. 999).'
            out = ai.ustav_answer('кому подчиняется дежурный по роте', mats)
        finally:
            ai.run = old
        self.assertIn('(УВС, ст. 295)', out)
        self.assertNotIn('999', out)              # ссылки на статьи, которых не давали, — убраны


if __name__ == '__main__':
    unittest.main()
