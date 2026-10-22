import json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from bvk import merge
from bvk.identity import clean_name, identity_matches, name_key, publisher

class IdentityTests(unittest.TestCase):
    def test_titles_particles_and_hyphens(self):
        self.assertEqual(name_key('Hon.-Prof. Konrad Gündisch'),name_key('Konrad Gündisch'))
        self.assertEqual(name_key('Georg Graf von Waldersee'),name_key('Georg Waldersee Graf von'))
        self.assertEqual(name_key('Eva-Maria Welskop-Deffaa'),name_key('Eva Maria Welskop-Deffaa'))
        self.assertEqual(clean_name('Drews'), 'Drews')
        self.assertFalse(identity_matches('Hildegard Bulitta','Erich Bulitta'))
        self.assertFalse(identity_matches('Matthias Katsch','Klaus Mertes'))

    def test_publisher_is_not_collection_route(self):
        self.assertEqual(publisher('https://www.bundespraesident.de/ceremony'),'bpr')
        self.assertEqual(publisher('https://en.wikipedia.org/wiki/Person'),'other_wikipedia')

    def run_merge(self,rows):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            with patch.object(merge,'DATA',root),patch.object(merge,'records',return_value=iter(rows)),patch.object(merge.enrich,'run'),patch.object(merge.enrich,'wd_people',return_value={}),patch.object(merge.enrich,'given_names',return_value={}),patch.object(merge,'stats'):
                merge.run()
            return json.loads((root/'bvk.json').read_text())

    def row(self,name='Erika Muster',qid=None,year=2015,estimated=False,url='https://example.org/press',grade='Verdienstkreuz am Bande',residence='Berlin'):
        return dict(name=name,qid=qid,year=year,year_estimated=estimated,grade=grade,date=None,announced='2015-02-01' if estimated else None,residence=residence,occupation=None,place=None,presented_by=None,reason=None,source={'url':url,'via':'bpr' if estimated else 'search','quote':name})

    def test_boundary_evidence_retained_without_adding_pre2015_awards(self):
        a=self.row(year=2014,estimated=True,url='https://example.org/official')
        b=self.row()
        p=self.run_merge([a,b])
        self.assertEqual(len(p),1)
        self.assertEqual(p[0]['awards'][0]['year'],2015)
        self.assertFalse(p[0]['awards'][0]['year_estimated'])
        self.assertEqual(len(p[0]['awards'][0]['sources']),2)
        self.assertEqual(self.run_merge([a]),[])

    def test_validated_qid_connects_aliases_and_moved_residence(self):
        a=self.row(name='Elke Plöger',qid='Q1',year=2015)
        b=self.row(name='Elke Schilling',qid='Q1',year=2020,residence='Bonn',grade='Verdienstkreuz 1. Klasse')
        p=self.run_merge([a,b])
        self.assertEqual(len(p),1)
        self.assertEqual(len(p[0]['awards']),2)

    def test_different_qids_do_not_merge(self):
        self.assertEqual(len(self.run_merge([self.row(qid='Q1'),self.row(qid='Q2')])),2)

    def test_duplicate_party_annotations_keep_evidence(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            rows=[{'id':'old1','name':'Erika Muster','party':'SPD','evidence':'a'}, {'id':'old2','name':'Erika Muster','party':'SPD','evidence':'b'}]
            (root/'party.json').write_text(json.dumps(rows))
            source={'url':'https://example.org/a','quote':'Erika Muster'}
            previous=[{'id':r['id'],'name':r['name'],'awards':[{'sources':[source]}]} for r in rows]
            people=[{'id':'new','name':'Erika Muster','awards':[{'sources':[source]}]}]
            with patch.object(merge,'DATA',root): merge.repair_annotation_ids(people,previous)
            out=json.loads((root/'party.json').read_text())
            self.assertEqual(len(out),1)
            self.assertEqual(out[0]['id'],'new')
            self.assertEqual({r['evidence'] for r in out[0]['merged_annotations']},{'a','b'})

    def test_records_reject_roles_organisations_and_spouse_qid(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            (root/'wikidata.json').write_text(json.dumps([{'qid':'Q1','name':'Erich Bulitta','dewiki':'https://de.wikipedia.org/wiki/Erich_Bulitta','date':None},{'qid':'Q2','name':'Jugendnotmail','dewiki':None,'date':'2015-01-01'}]))
            (root/'wikidata_nonhuman.json').write_text('["Q2"]')
            aa=[{**self.row(name=n), 'quote':n} for n in ['Hildegard Bulitta','Pianist']]
            (root/'doc.json').write_text(json.dumps({'model':'model','provider':None,'awards':aa}))
            d={'url':'https://de.wikipedia.org/wiki/Erich_Bulitta','src':'dewiki','title':'Erich Bulitta','text':'Hildegard Bulitta Pianist','date':None,'qid':'Q1'}
            with patch.object(merge,'CACHE',root),patch.object(merge,'EXT',root),patch.object(merge,'docs',return_value=iter([('doc',d)])):
                rows=list(merge.records())
            self.assertEqual([r['name'] for r in rows],['Hildegard Bulitta'])
            self.assertIsNone(rows[0]['qid'])

if __name__=='__main__':unittest.main()
