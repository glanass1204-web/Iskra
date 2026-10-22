import tempfile
import unittest
from unittest import mock

import iskra_drafts as D


class Drafts(unittest.TestCase):
    def setUp(self):
        self.base = tempfile.mkdtemp()

    def draft(self):
        return D.Draft(base=self.base)

    def test_autosave_only_when_changed_and_versions_spaced(self):
        d = self.draft()
        self.assertTrue(d.autosave('ТЕЛЕГРАММА\nКому: штаб\nТекст: раз'))
        self.assertFalse(d.autosave('ТЕЛЕГРАММА\nКому: штаб\nТекст: раз'))     # без изменений — не пишем
        self.assertTrue(d.autosave('ТЕЛЕГРАММА\nКому: штаб\nТекст: два'))
        self.assertEqual(len(d.data['versions']), 1)                          # версия не чаще раза в 2 минуты
        with mock.patch('time.time', return_value=d.data['versions'][-1]['time'] + D.VERSION_EVERY + 1):
            d.autosave('ТЕЛЕГРАММА\nКому: штаб\nТекст: три')
        self.assertEqual(len(d.data['versions']), 2)
        d.autosave('ТЕЛЕГРАММА\nКому: штаб\nТекст: четыре', 'до нейросети')  # с причиной — версия сразу
        self.assertEqual(d.data['versions'][-1]['why'], 'до нейросети')
        again = D.Draft.load(d.path)
        self.assertEqual(again.data['text'], 'ТЕЛЕГРАММА\nКому: штаб\nТекст: четыре')
        self.assertEqual(again.data['title'], 'Кому: штаб')

    def test_versions_capped(self):
        d = self.draft()
        for i in range(D.VERSIONS + 10):
            d.autosave(f'текст {i}', 'правка')
        self.assertEqual(len(d.data['versions']), D.VERSIONS)
        self.assertEqual(d.data['versions'][-1]['text'], f'текст {D.VERSIONS + 9}')

    def test_unfinished_after_crash(self):
        crashed, closed, blank = self.draft(), self.draft(), self.draft()
        crashed.autosave('ТЕЛЕГРАММА\nТекст: важный текст')
        closed.autosave('ТЕЛЕГРАММА\nТекст: сохранённый'); closed.close('ТЕЛЕГРАММА\nТекст: сохранённый')
        blank.autosave('ТЕЛЕГРАММА\nДата: 21.10.2026\nТекст:')
        lost = D.unfinished(self.base, blank='ТЕЛЕГРАММА\nДата: 22.10.2026\nТекст:')
        self.assertEqual([d.data['id'] for d in lost], [crashed.data['id']])
        D.mark_closed(lost[0])
        left = {d.data['id'] for d in D.unfinished(self.base)}
        self.assertNotIn(crashed.data['id'], left)          # отказались восстанавливать — больше не предлагается

    def test_cleanup_keeps_newest(self):
        for i in range(5):
            d = self.draft()
            d.data['updated'] = i
            d.autosave(f'черновик {i}')
        D.cleanup(self.base, keep=2)
        self.assertEqual(len(D.recent(100, self.base)), 2)


if __name__ == '__main__':
    unittest.main()
