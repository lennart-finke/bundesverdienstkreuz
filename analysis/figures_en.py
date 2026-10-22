"""Render the English figures with the same data and styling, using cached classifications only.
Run after analysis.figures: python -m analysis.figures_en
"""
import json
import re
import xml.etree.ElementTree as ET
from matplotlib.text import Text
from . import figures as f

TRANSLATIONS = json.loads((f.ROOT / 'translations/en.json').read_text())

def translate(text):
    if not isinstance(text, str): return text
    if text in TRANSLATIONS: return TRANSLATIONS[text]
    text = re.sub(r'häufigste Länder \(Top (\d+) von (\d+)\)', r'most common countries (top \1 of \2)', text)
    text = text.replace(' von ', ' of ')
    if 'je 100,000 Einwohner und Jahr' in text:
        text = text.replace('je 100,000 Einwohner und Jahr', 'per 100,000 inhabitants per year').replace('Verleihungen in', 'awards in').replace('Kalenderjahren', 'calendar years')
        for de, en in [('Kreisfreie Stadt', 'independent city'), ('Stadtkreis', 'urban district'), ('Landkreis', 'district'), ('Kreis', 'district')]:
            text = re.sub(r'\b' + de + r'\b', en, text)
        for de in f.STATES.values(): text = text.replace(de, TRANSLATIONS.get(de, de))
    # German thousands separators in sample sizes; decimal percentages below 1%.
    text = re.sub(r'(?<=\d)\.(?=\d{3}(?:\D|$))', ',', text)
    text = re.sub(r'(\d),(\d)%', r'\1.\2%', text)
    return '\n'.join(TRANSLATIONS.get(line, line) for line in text.split('\n'))

def run():
    original_text = Text.set_text
    original_classify, original_out = f.classify, f.OUT
    def set_text(self, value): return original_text(self, translate(value))
    def cached(reasons, cats=f.CATS, ask=f.CATS_ASK, cache='categories.json'):
        data = json.loads((f.CACHE / cache).read_text())
        missing = set(reasons) - data.keys()
        if missing: raise ValueError(f'{len(missing)} missing cached classifications in {cache}')
        return data
    f.OUT = original_out / 'en'
    f.OUT.mkdir(exist_ok=True)
    f.classify = cached
    Text.set_text = set_text
    try:
        f.run()
        path = f.OUT / 'kreise_map.svg'
        ET.register_namespace('', 'http://www.w3.org/2000/svg')
        tree = ET.parse(path)
        for element in tree.iter():
            if element.text: element.text = translate(element.text)
            if 'aria-label' in element.attrib: element.set('aria-label', translate(element.get('aria-label')))
            if 'data-t' in element.attrib: element.set('data-t', translate(element.get('data-t')))
        tree.write(path, encoding='unicode')
        # Both languages search and download the same unmodified source records and share the German link preview image.
        for name in ('people.json', 'kreise.png'): (f.OUT / name).unlink(missing_ok=True)
    finally:
        Text.set_text, f.classify, f.OUT = original_text, original_classify, original_out

if __name__ == '__main__': run()
