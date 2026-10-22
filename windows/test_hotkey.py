import sys
import unittest

import iskra_hotkey as hk


@unittest.skipUnless(sys.platform == 'win32', 'только Windows')
class ClipboardTest(unittest.TestCase):
    def test_roundtrip(self):
        before = hk.get_clipboard()
        try:
            self.assertTrue(hk.set_clipboard('Телеграмма № 154/2 — «проверка»'))
            self.assertEqual(hk.get_clipboard(), 'Телеграмма № 154/2 — «проверка»')
        finally:
            hk.set_clipboard(before or '')

    def test_hotkey_registers(self):
        h = hk.Hotkey(lambda *a: None)
        h.start()
        self.assertIsNotNone(h.ok)
        h.stop()


if __name__ == '__main__':
    unittest.main()
