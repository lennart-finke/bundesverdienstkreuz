import datetime
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from selectolax.lexbor import LexborHTMLParser
from bvk import common, official
from bvk.extract import parse_list, parse_wp
from bvk.merge import source_key, preserve_ids
from bvk.src_bundesanzeiger import notice_text
from bvk.coverage import audit

TEXT = 'Verdienstkreuz am Bande\nMuster, Erika, Dr., Berlin\nVerdienstmedaille\nBeispiel\n, Karl, Bonn\nBerlin, den\n5. Dezember 2025\nDie Chefin des Bundespräsidialamtes'

class OfficialTests(unittest.TestCase):
    def test_paragraphs_preserve_inline_surnames(self):
        tree = LexborHTMLParser('<div id="preview_data"><h3>Verdienstmedaille</h3><p><span>Muster</span>, Erika, Berlin</p></div>')
        self.assertIn('Muster, Erika, Berlin', notice_text(tree))

    def test_split_names_and_footer(self):
        records = parse_list({'url': 'https://www.bundesanzeiger.de/notice.pdf', 'date': '2025-12-05', 'text': TEXT})['awards']
        self.assertEqual([a['name'] for a in records], ['Erika Muster', 'Karl Beispiel'])
        self.assertEqual(records[0]['titles'], 'Dr.')
        self.assertEqual(records[0]['announced'], '2025-12-05')

    def test_misspelled_headings(self):
        text = 'Verdienstkreuz am Band\nMuster, Erika, Berlin\nVerdientmedaille\nBeispiel, Karl, Bonn'
        aa = parse_list({'url': 'https://example.org/list', 'date': '2025-12-05', 'text': text})['awards']
        self.assertEqual([a['grade'] for a in aa], ['Verdienstkreuz am Bande', 'Verdienstmedaille'])

    def test_title_before_given_name(self):
        aa = parse_list({'url': 'https://example.org/list', 'date': '2026-04-10',
                         'text': 'Verdienstmedaille\nBlaszczyk, Dr., Timo, Kiel'})['awards']
        self.assertEqual(aa[0]['name'], 'Timo Blaszczyk')
        self.assertEqual(aa[0]['residence'], 'Kiel')

    def test_retains_id_after_residence_change(self):
        source = {'url': 'https://example.org/list', 'quote': 'Muster, Erika, Berlin'}
        old = {'id': 'old', 'name': 'Erika Muster', 'wikidata': None, 'awards': [{'sources': [source]}]}
        new = {**old, 'id': 'new', 'residence': 'Berlin-Mitte'}
        preserve_ids([new], [old])
        self.assertEqual(new['id'], 'old')

    def test_noble_name_and_multi_recipient_wiki_line(self):
        aa = parse_list({'url': 'https://example.org/list', 'date': '2021-12-06',
                         'text': 'Verdienstmedaille\nSeebach, Freiin von, Christiane, Tübingen'})['awards']
        self.assertEqual(aa[0]['name'], 'Christiane von Seebach')
        self.assertEqual(aa[0]['residence'], 'Tübingen')
        aa = parse_wp({'text': '== 1. Juni 2015 ==\n<div style="font-weight:bold">Verdienstkreuz 1. Klasse</div>\n[[Beate Klarsfeld|Beate]] und [[Serge Klarsfeld]], Paris'})['awards']
        self.assertEqual([a['name'] for a in aa], ['Beate Klarsfeld','Serge Klarsfeld'])
        self.assertTrue(all(a['residence'] == 'Paris' for a in aa))

    def test_error_page_rejected(self):
        self.assertFalse(official.valid_list('Ihre Anfrage war unzulässig. Verdienstkreuz am Bande\nMuster, Erika, Berlin'))
        with self.assertRaises(ValueError):
            parse_list({'url': 'https://www.bundesanzeiger.de/notice.pdf', 'date': '2025-12-05', 'text': 'Ihre Anfrage war unzulässig.'})

    def test_distinct_retrievals_survive_merge(self):
        a = {'url': 'https://example.org/award', 'via': 'bpr'}
        b = {**a, 'via': 'wikiprojekt', 'mirror': 'https://de.wikipedia.org/wiki/List'}
        self.assertNotEqual(source_key(a), source_key(b))
        self.assertEqual(source_key(a), source_key(dict(a)))

    def test_official_page_not_downgraded_by_search(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); raw = root/'raw'; ext = root/'ext'; raw.mkdir(); ext.mkdir()
            url = 'https://www.bundespraesident.de/SharedDocs/Berichte/Bekanntgabe-Ordensverleihung/251205-Verleihungen.html'
            with patch.object(common, 'RAW', raw), patch.object(common, 'EXT', ext):
                common.save_doc(url, TEXT, 'bpr')
                cached = ext/f'{common.h(url)}.json'; cached.write_text('{}')
                common.save_doc(url, TEXT, 'search')
                doc = json.loads((raw/f'{common.h(url)}.json').read_text())
                self.assertEqual(doc['src'], 'bpr')
                self.assertEqual(doc['collected_via'], ['bpr', 'search'])
                self.assertTrue(cached.exists())
                common.save_doc(url, TEXT+'\nUpdated', 'bpr')
                self.assertFalse(cached.exists())

    def test_audit_records_missing_and_failed_extraction(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); (root/'bvk.json').write_text('[]')
            doc = {'url': 'https://example.org/notice', 'src': 'bundesanzeiger', 'announcement_month': '2015-01', 'text': TEXT}
            with patch('bvk.coverage.DATA', root), patch('bvk.coverage.EXT', root), patch('bvk.coverage.docs', return_value=iter([('test', doc)])):
                report = audit(datetime.date(2015, 2, 1))
            self.assertIn('not_extracted', report['problems'][0]['issues'])
            self.assertEqual(len(report['months']), 2)
            self.assertEqual(len(report['months'][1]['missing_sources']), 3)

if __name__ == '__main__': unittest.main()
