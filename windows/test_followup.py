import unittest

import iskra_ai as ai
import iskra_assistant as a


class FollowupTest(unittest.TestCase):
    def test_detects_corrections(self):
        for text in ('сделай короче', 'поменяй срок на 30.10.2026', 'добавь пункт про технику', 'а адресат — начальник штаба',
                     'убери последний пункт', 'перепиши её официальнее', 'не так, срок 25.10', 'исправь ошибки',
                     'добавь подпись', 'сделай официальнее', 'только без второго пункта'):
            self.assertTrue(a.is_followup(text, 'write'), text)

    def test_follow_up_questions(self):
        for text in ('а когда срок?', 'а кто подписал?', 'а сумма?', 'какой номер?'):
            self.assertTrue(a.is_followup(text, 'ask'), text)
            self.assertTrue(a.is_question(text), text)
        self.assertTrue(a.is_followup('а если по столбцу D', 'formula'))

    def test_new_requests_are_not_followups(self):
        for text in ('найди приказ о премировании', 'составь новую телеграмму в полигон', 'сводка', 'журнал',
                     'напиши доклад о готовности техники по последним телеграммам', 'новое: телеграмма в госпиталь'):
            self.assertFalse(a.is_followup(text, 'write'), text)
        self.assertEqual(a.new_topic_text('новое: телеграмма в госпиталь'), 'телеграмма в госпиталь')
        self.assertIsNone(a.new_topic_text('сделай короче'))
        # «кто» после ответа — по-прежнему ФИО из документа, а не справочник
        self.assertEqual(a.intent('кто')[0], 'people')
        self.assertEqual(a.intent('справочник')[0], 'directory')

    def test_revise_and_followup_prompts(self):
        seen = {}
        old = ai.run
        ai.run = lambda prompt, **kw: seen.setdefault('p', prompt) and 'ok'
        try:
            ai.revise('телеграмма в госпиталь', 'ТЕЛЕГРАММА\nСрок до 25.10.2026.', 'поменяй срок на 30.10.2026')
            self.assertIn('Срок до 25.10.2026', seen['p'])
            self.assertIn('поменяй срок на 30.10.2026', seen['p'])
            self.assertIn('Всё остальное оставь как есть', seen['p'])
            seen.clear()
            ai.followup([('какой срок?', 'До 25.10.2026. Источник: тлг 154.txt')], 'а кто подписал?', [('тлг 154.txt', 'Подписал Сидоров')])
            self.assertIn('Вопрос: какой срок?', seen['p'])
            self.assertIn('а кто подписал?', seen['p'])
            self.assertIn('Подписал Сидоров', seen['p'])
        finally:
            ai.run = old


class KeepUnaskedTest(unittest.TestCase):
    PREV = ('ТЕЛЕГРАММА\n\nКому: Штаб округа\n\nТекст:\nСведения до 25.10.2026.\n\nПодпись:\nНачальник штаба\nполковник\nП.П. Сидоров')
    BAD = ('ТЕЛЕГРАММА\n\nКому: [УТОЧНИТЬ]\n\nТекст:\nСведения до 30.10.2026.\n\nПодпись:\n[УТОЧНИТЬ: должность]\nполковник\nП.П. Сидоров')

    def test_signature_and_addressee_restored(self):
        out = ai.keep_unasked(self.PREV, self.BAD, 'поменяй срок на 30.10.2026')
        self.assertIn('30.10.2026', out)
        self.assertIn('Начальник штаба', out)
        self.assertIn('Кому: Штаб округа', out)

    def test_asked_changes_kept(self):
        out = ai.keep_unasked(self.PREV, self.BAD.replace('[УТОЧНИТЬ: должность]', 'Заместитель начальника штаба'),
                              'в подписи поставь заместителя начальника штаба')
        self.assertIn('Заместитель начальника штаба', out)
        out = ai.keep_unasked(self.PREV, self.BAD.replace('Кому: [УТОЧНИТЬ]', 'Кому: Начальнику госпиталя'), 'адресат — начальник госпиталя')
        self.assertIn('Кому: Начальнику госпиталя', out)


if __name__ == '__main__':
    unittest.main()
