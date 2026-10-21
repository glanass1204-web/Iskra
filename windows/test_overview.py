import tempfile
import unittest
from datetime import date
from pathlib import Path

from iskra_overview import folder_overview, render, folders_summary, topics

TODAY = date(2026, 10, 21)


class OverviewTest(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        (self.root / 'Телеграммы').mkdir()
        files = {
            'Телеграммы/т1.docx': 'т1\nТЕЛЕГРАММА\nОт кого: Штаб округа\nНомер: 154\nДата: 20.10.2026\nПредставить сведения о численности личного состава до 25.10.2026.',
            'Телеграммы/т2.docx': 'т2\nТЕЛЕГРАММА\nОт кого: Штаб округа\nНомер: 155\nОбеспечить готовность техники. Уточнить численность личного состава до 10.10.2026.',
            'приказ.docx': 'приказ\nПРИКАЗ № 7\nО проверке готовности техники и личного состава.',
            'свод.xlsx': 'свод\nНаименование | По списку | На лицо',
        }
        self.docs = []
        for name, text in files.items():
            p = self.root / name
            p.write_text('x', encoding='utf-8')
            self.docs.append((str(p), text))
        self.docs.append(('/другая/папка/x.docx', 'x\nПостороннее'))

    def test_overview(self):
        ov = folder_overview(self.root, self.docs, TODAY)
        self.assertEqual(ov['total'], 4)
        self.assertEqual(dict(ov['by_kind'])['Телеграмма'], 2)
        self.assertEqual(ov['senders'][0], ('Штаб округа', 2))
        self.assertEqual([d.strftime('%d.%m') for d, _, _ in ov['upcoming']], ['25.10'])
        self.assertEqual([d.strftime('%d.%m') for d, _, _ in ov['overdue']], ['10.10'])
        self.assertIn(('Телеграммы', 2), ov['subfolders'])
        self.assertIn('личного состава', [t for t, _ in ov['topics']])
        text = render(ov)
        self.assertIn('Документов: 4', text)
        self.assertIn('ПРОСРОЧЕНО', text)
        self.assertIn('т1.docx № 154 от 20.10.2026 (Штаб округа)', text)

    def test_summary_lines(self):
        lines = folders_summary([str(self.root), str(self.root / 'нет')], self.docs, TODAY)
        self.assertIn('4 док.', lines[0])
        self.assertIn('ближайший срок 25.10.2026', lines[0])
        self.assertIn('пока нет документов', lines[1])

    def test_topics_need_two_documents(self):
        self.assertEqual(topics(['Ремонт кровли здания.']), [])


if __name__ == '__main__':
    unittest.main()
