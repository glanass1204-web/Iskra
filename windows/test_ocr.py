import os
import shutil
import tempfile
import unittest
from pathlib import Path

import iskra_ocr

TESS = shutil.which('tesseract')
FONT = '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'


@unittest.skipUnless(TESS and Path(FONT).is_file(), 'нет tesseract или шрифта')
class OCRTest(unittest.TestCase):
    def setUp(self):
        import make_scan_samples
        self.dir = Path(tempfile.mkdtemp()) / 'Входящие сканы'
        make_scan_samples.main(self.dir, FONT)
        iskra_ocr.BINARY = TESS
        iskra_ocr.TESSDATA = next(Path('/usr/share/tesseract-ocr').glob('*/tessdata'))
        os.environ['ISKRA_DATA_DIR'] = tempfile.mkdtemp()

    def tearDown(self):
        iskra_ocr.BINARY = iskra_ocr.TESSDATA = None

    def test_image_and_pdf(self):
        import iskra_index
        for name in ('скан телеграммы.png', 'скан приказа.pdf'):
            text = iskra_index.extract(self.dir / name)
            self.assertIn('РАСПОЗНАНО СО СКАНА', text)
            self.assertIn('217/4', text)
            self.assertIn('28.10.2026', text)
            self.assertIn('численности', text.lower())

    def test_cached(self):
        p = self.dir / 'скан телеграммы.png'
        first = iskra_ocr.recognize(p)
        iskra_ocr.BINARY = '/nonexistent'
        self.assertFalse(iskra_ocr.available())
        iskra_ocr.BINARY = TESS
        self.assertEqual(iskra_ocr.recognize(p), first)


if __name__ == '__main__':
    unittest.main()
