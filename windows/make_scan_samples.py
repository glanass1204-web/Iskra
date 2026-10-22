"""Тестовые сканы: картинка и PDF без текстового слоя с русским текстом (для проверки распознавания).
Запуск: python make_scan_samples.py <папка> [шрифт.ttf]. Нужен Pillow (только для проверки, в программу не входит)."""
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

LINES = ['ТЕЛЕГРАММА № 217/4 от 21.10.2026', 'Начальнику госпиталя', 'Представить сведения о численности',
         'личного состава до 28.10.2026.', 'Начальник штаба Сидоров']


def page(font):
    img = Image.new('L', (2480, 1200), 255)
    d = ImageDraw.Draw(img)
    for i, line in enumerate(LINES):
        d.text((150, 120 + i * 180), line, fill=0, font=font)
    return img


def main(folder, font_path):
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    font = ImageFont.truetype(font_path, 80)
    img = page(font)
    img.save(folder / 'скан телеграммы.png')
    img.convert('RGB').save(folder / 'скан приказа.pdf', resolution=300)


if __name__ == '__main__':
    main(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else r'C:\Windows\Fonts\arial.ttf')
