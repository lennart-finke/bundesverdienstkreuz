import datetime, json, tempfile, unittest
from pathlib import Path
from unittest.mock import patch
from bvk import enrich, merge
from bvk.extract import couple, entry, wp_parts

ANN = datetime.date(2016, 2, 1)

def rec(name, grade='Verdienstkreuz am Bande', year=2016, residence='Berlin', qid=None, official=True, url=None, announced='2016-02-01'):
    src = {'url': url or f'https://example.org/{name}/{year}/{official}', 'via': 'bpr' if official else 'search', 'quote': name, 'extracted_by': 'parser' if official else 'model'}
    return dict(name=name, grade=grade, year=year, year_estimated=official, date=None, announced=announced if official else None, residence=residence,
                occupation=None, place=None, presented_by=None, reason=None, qid=qid, source=src)

def run_merge(rows, people=None):
    with tempfile.TemporaryDirectory() as folder:
        root = Path(folder)
        with patch.object(merge, 'DATA', root), patch.object(merge, 'records', return_value=iter(rows)), patch.object(merge.enrich, 'run'), \
             patch.object(merge.enrich, 'wd_people', return_value=people or {}), patch.object(merge.enrich, 'given_names', return_value={}), patch.object(merge, 'stats'):
            merge.run()
        return json.loads((root / 'bvk.json').read_text())

class ParserTests(unittest.TestCase):
    def test_noble_particles_move_before_surname(self):
        self.assertEqual(entry('Puttkamer von, Bettina Ulrike, Meerbusch', 'X', ANN)['name'], 'Bettina Ulrike von Puttkamer')
        e = entry('Platen-Hallermund Gräfin von, Henriette, Wangels', 'X', ANN)
        self.assertEqual((e['name'], e['titles'], e['residence']), ('Henriette von Platen-Hallermund', 'Gräfin', 'Wangels'))
        self.assertEqual(entry('Leyen zu Bloemersheim, Christian, Freiherr von der, Hemmingen', 'X', ANN)['name'], 'Christian von der Leyen zu Bloemersheim')
        self.assertEqual(entry('Le Maire, Bruno, Évreux (Frankreich)', 'X', ANN)['name'], 'Bruno Le Maire')

    def test_couples_and_several_entries_per_line(self):
        self.assertEqual([e['name'] for e in couple(entry('Klarsfeld, Beate und Serge, Paris', 'X', ANN))], ['Beate Klarsfeld', 'Serge Klarsfeld'])
        self.assertEqual([entry(x, 'X', ANN)['name'] for x in wp_parts('[[Beate Klarsfeld|Beate]] und [[Serge Klarsfeld]], Paris')], ['Beate Klarsfeld', 'Serge Klarsfeld'])
        self.assertEqual(len(wp_parts('[[Patrik Winckler]], Illingen |[[Gerd Escher]], Gelsenkirchen-Buer')), 2)
        self.assertEqual(len(wp_parts('[[Ursula Schmitt | Ursula Schmitt (Politikerin)]], Neuburg a.d. Donau')), 1)

class FilterTests(unittest.TestCase):
    def test_state_honours(self):
        page = 'Verdienstorden der Bundesrepublik Deutschland\nKommunale Verdienstmedaille in Silber\nErika Muster hat sich um die kommunale Selbstverwaltung verdient gemacht.'
        self.assertTrue(merge.state_honour(page, {'name': 'Erika Muster', 'quote': 'hat sich verdient gemacht'}))
        self.assertTrue(merge.state_honour('Minister überreicht das Verdienstkreuz 1. Klasse. Den Niedersächsischen Verdienstorden erhält Erika Muster.', {'name': 'Erika Muster', 'quote': 'das Verdienstkreuz 1. Klasse'}))
        q = 'zeichnete acht Personen mit dem Bundesverdienstkreuz beziehungsweise dem Ehrenzeichen des Freistaates aus'
        self.assertTrue(merge.state_honour(q, {'name': 'Erika Muster', 'quote': q}))
        self.assertFalse(merge.state_honour('Erika Muster erhält das Bundesverdienstkreuz. Zuvor bekam sie die Landesehrennadel.', {'name': 'Erika Muster', 'quote': 'erhält das Bundesverdienstkreuz'}))

    def test_names(self):
        self.assertTrue(merge.not_a_name('König der Niederlande', None, None))
        self.assertTrue(merge.not_a_name('Pianist', 'Pianist', None))
        self.assertTrue(merge.not_a_name('Der Herr der Muttenthalbahn', None, None))
        self.assertFalse(merge.not_a_name('Philippe', 'König von Belgien', None))
        self.assertFalse(merge.not_a_name('Madeleine von Rössing und von Hugo', None, None))
        self.assertEqual(merge.clean('Schwester Maria Pfadenhauer'), 'Maria Pfadenhauer')
        self.assertTrue(merge.same_given(['christoph', 'm'], ['christoph', 'matthias']))
        self.assertTrue(merge.same_given(['willi'], ['wilhelm']))
        self.assertFalse(merge.same_given(['hans', 'peter'], ['hans', 'heinrich']))

class MergeTests(unittest.TestCase):
    def test_official_grade_wins_over_press_grade(self):
        p = run_merge([rec('Erika Muster', 'Verdienstmedaille'), rec('Erika Muster', 'Verdienstkreuz am Bande', official=False)])
        self.assertEqual([(a['grade'], len(a['sources'])) for a in p[0]['awards']], [('Verdienstmedaille', 2)])

    def test_two_list_entries_in_different_places_are_two_people(self):
        self.assertEqual(len(run_merge([rec('Wolfgang Müller', residence='Berlin'), rec('Wolfgang Müller', year=2017, residence='Leimen', announced='2017-10-01')])), 2)

    def test_mover_with_wikidata_and_upgrade(self):
        rows = [rec('Lothar Mark', year=2019, residence='Mannheim', qid='Q1'), rec('Lothar Mark', 'Verdienstkreuz 1. Klasse', 2025, 'Rodgau', 'Q1', announced='2025-10-10')]
        self.assertEqual(len(run_merge(rows)), 1)
        rows = [rec('Ralf Bender', 'Verdienstkreuz 1. Klasse', 2017, 'München', 'Q2'), rec('Ralf Bender', 'Verdienstkreuz am Bande', 2021, 'Wiesbaden', 'Q2', announced='2021-03-01')]
        self.assertEqual(len(run_merge(rows)), 2)  # grades never go down

    def test_nickname_press_record_joins_list_entry(self):
        p = run_merge([rec('Wilhelm Killinger', residence='Regen'), rec('Willi Killinger', residence='Regen', official=False)])
        self.assertEqual(len(p), 1)

    def test_placeless_press_record_needs_matching_award(self):
        p = run_merge([rec('Monika Schmidt', 'Verdienstmedaille', 2018, 'Wolfsburg'), rec('Monika Schmidt', year=2022, residence='', official=False)])
        self.assertEqual(len(p), 2)

    def test_qid_dropped_when_person_died_before(self):
        p = run_merge([rec('Helmut Schön', 'Verdienstmedaille', 2017, 'Ulm', 'Q3')], people={'Q3': {'human': True, 'died': '1996-02-23'}})
        self.assertIsNone(p[0]['wikidata'])

class WikidataTests(unittest.TestCase):
    def test_century_precision_birth_is_dropped(self):
        rows = [['<http://www.wikidata.org/entity/Q1>', '2000-01-01T00:00:00Z', '7', '', '', '<http://www.wikidata.org/entity/Q5>', '"Jan"@de'],
                ['<http://www.wikidata.org/entity/Q2>', '1950-01-01T00:00:00Z', '9', '', '', '<http://www.wikidata.org/entity/Q5>', '"Eva"@de']]
        with patch.object(enrich, 'sparql', return_value=[[c.strip('"<>') for c in r] for r in rows]):
            info = enrich.wd_people(['Q1', 'Q2'])
        self.assertNotIn('born', info['Q1'])
        self.assertEqual(info['Q2']['born'], '1950')

def via(r, src, published=None):  # the same list entry as transcribed by another official source
    r['source'] = {**r['source'], 'via': src, 'url': r['source']['url'] + src, 'published': published or r['announced']}
    return r

class ParserFixTests(unittest.TestCase):
    def test_particles_honours_and_name_parts(self):
        e = entry('Hompel, ten, Michael, Dortmund', 'X', ANN)
        self.assertEqual((e['name'], e['residence']), ('Michael ten Hompel', 'Dortmund'))
        e = entry('Beaumont-Beynac, Comte de, Thierry, Paris (Frankreich)', 'X', ANN)
        self.assertEqual((e['name'], e['titles'], e['residence']), ('Thierry de Beaumont-Beynac', 'Comte', 'Paris (Frankreich)'))
        self.assertEqual(entry('Thiel, van Jan Hendrik, Potsdam', 'X', ANN)['name'], 'Jan Hendrik van Thiel')
        self.assertEqual(entry('Holthaus gr. (Große Holthaus), Ursula, Lohne', 'X', ANN)['name'], 'Ursula Große Holthaus')
        self.assertEqual(entry('Reichel, Joachim (Künstlername: Achim Reichel), Hamburg', 'X', ANN)['name'], 'Joachim Reichel')

    def test_titles_and_professions_leave_the_residence(self):
        for line, place in [('Peterfalvi, Emmanuel, Künstlername: Alfons, Hamburg', 'Hamburg'), ('Schaffner, Karin, ehem. Erzieherin, Schweinfurt', 'Schweinfurt'),
                            ('Baier, Herwig Anton, Professor Dr., em. Murnau a. Staffelsee', 'Murnau a. Staffelsee'), ('Dr. [[Lutz Klinkhammer]], Professor, Rom (Italien)', 'Rom (Italien)'),
                            ('[[Theodoros Daskarolis]], S.E., Potsdam', 'Potsdam'), ('Dr. [[Christian Flössner]], Christian, Dr., Dresden', 'Dresden'), ('Krasznahorkai, László, (Ungarn)', 'Ungarn')]:
            self.assertEqual(entry(line, 'X', ANN)['residence'], place, line)

    def test_wiki_link_trails_and_continued_surnames(self):
        e = entry('<s>[[Traute Lafrenz]] Page, South Carolina (USA)</s> |', 'X', ANN)
        self.assertEqual((e['name'], e['residence']), ('Traute Lafrenz Page', 'South Carolina (USA)'))
        e = entry('Professor Dr. [[Ilja Alexandrowitsch Altman]]n, Moskau', 'X', ANN)
        self.assertEqual((e['name'], e['residence']), ('Ilja Alexandrowitsch Altmann', 'Moskau'))
        e = entry('[[Ursula Holthaus gr.]] (Große Holthaus), Lohne |', 'X', ANN)
        self.assertEqual((e['name'], e['residence']), ('Ursula Große Holthaus', 'Lohne'))

    def test_split_headings_and_abbreviation_fragments(self):
        from bvk.extract import parse_list
        text = 'Großes\nVerdienstkreuz\nBallhaus, Michael, Berlin\nVerdienstmedaille\nKappus,\nDr.\nMichael, Itzehoe\nSchmitz, Klaus-Peter, Professor\nDr.\n-\nIng.\n, Warnemünde\n'
        out = parse_list({'url': 'https://www.bundespraesident.de/SharedDocs/Berichte/Bekanntgabe-Ordensverleihung/1509-Verleihungen.html', 'text': text})['awards']
        self.assertEqual([(a['name'], a['grade'], a['residence']) for a in out], [('Michael Ballhaus', 'Großes Verdienstkreuz', 'Berlin'),
                         ('Dr. Michael Kappus', 'Verdienstmedaille', 'Itzehoe'), ('Klaus-Peter Schmitz', 'Verdienstmedaille', 'Warnemünde')])

class DateFixTests(unittest.TestCase):
    def press(self, **kw): return {'name': 'Erika Muster', 'date': None, 'year': None, 'quote': '', 'presented_by': None, **kw}

    def test_year_only_and_malformed_dates_are_dropped(self):
        self.assertEqual(merge.sanitize(self.press(date='2018-01-01', year=2018))['date'], None)
        self.assertEqual(merge.sanitize(self.press(date='2018-01-01', quote='am 1. Januar 2018'))['date'], '2018-01-01')
        self.assertIsNone(merge.sanitize(self.press(date='2020-01-01', year=2020, quote='Ulrich Khuon (* 31. Januar 1951)'))['date'])
        a = merge.sanitize(self.press(date='2020-12-XX', year=2020))
        self.assertEqual((a['date'], a['year']), (None, 2020))

    def test_presenter_out_of_office(self):
        a = merge.sanitize(self.press(date='2026-10-08', year=2026, presented_by='Ministerpräsident Volker Bouffier'))
        self.assertEqual((a['date'], a['year'], a['year_estimated']), (None, 2022, True))
        a = merge.sanitize(self.press(year=2025, presented_by='Bundespräsident Gauck'))
        self.assertEqual((a['year'], a['year_estimated']), (2017, True))
        self.assertEqual(merge.sanitize(self.press(date='2017-03-24', year=2017, presented_by='im Auftrag von Bundespräsident Joachim Gauck'))['date'], '2017-03-24')
        self.assertIsNone(merge.out_of_office('Außenminister Frank-Walter Steinmeier', '2016-04-19'))
        self.assertIsNone(merge.sanitize(self.press(date='2018-12-17'), 'drop'))

class IdentityFixTests(unittest.TestCase):
    def test_surnames_and_places(self):
        from bvk.identity import name_key, split_name
        self.assertEqual(split_name('Günter Hoppe-Waßmuth'), (['gunter'], 'hoppe-wassmuth'))
        self.assertNotEqual(name_key('Renate Jahn-Lutz'), name_key('Renate Lutz'))
        self.assertTrue(merge.same_place('Rheinland-Pfalz', 'Mainz'))
        self.assertFalse(merge.same_place('Berlin', 'Leimen'))
        self.assertTrue(merge.not_a_name('der Niederlande', 'König der Niederlande', None))
        self.assertTrue(merge.not_a_name('Freiherr von Schimmelmann', None, None))
        self.assertTrue(merge.same_given(['lilo'], ['liselotte']))
        self.assertFalse(merge.same_given(['claudia'], ['claudine']))

    def test_complementary_transcriptions_merge_but_one_list_keeps_namesakes(self):
        p = run_merge([rec('Günter Hass', residence='Detmold'), via(rec('Günter Hass', residence='Detmold'), 'bundesanzeiger'), via(rec('Günter Hase', residence='Detmold'), 'wikiprojekt')])
        self.assertEqual([x['name'] for x in p], ['Günter Hass'])
        p = run_merge([rec('Werner Bubenzer', residence='Gummersbach'), via(rec('Werner Bubenzer', residence='Gummbersbach'), 'wikiprojekt')])
        self.assertEqual(len(p), 1)
        p = run_merge([rec('Bernhard Wilhelm Hugo Rudolf Bachof', residence='Gera', announced='2024-03-13'), via(rec('Bernhard Bachof', residence='Gera', announced='2024-03-05'), 'bundesanzeiger')])
        self.assertEqual([x['name'] for x in p], ['Bernhard Wilhelm Hugo Rudolf Bachof'])
        self.assertEqual(len(run_merge([rec('Josef Hobmeier', residence='Pfaffenhofen a. d. Ilm'), rec('Josef Hobmeier', residence='Niederviehbach', url='https://example.org/2')])), 2)

    def test_promotion_listed_with_fewer_given_names(self):
        rows = [rec('Margot Anni Friedländer', 'Verdienstkreuz 1. Klasse', 2022, 'Berlin', announced='2023-02-01'), rec('Margot Friedländer', 'Großes Verdienstkreuz', 2025, 'Berlin', announced='2025-06-11')]
        p = run_merge(rows)
        self.assertEqual([len(x['awards']) for x in p], [2])

    def test_award_year_is_not_the_handover_year(self):
        listed = via(rec('Andreas Zieger', year=2020, residence='Oldenburg', announced='2020-10-01'), 'bpr')
        handover = {**rec('Andreas Zieger', year=2022, residence='Oldenburg', official=False), 'date': '2022-07-07'}
        a = run_merge([listed, handover])[0]['awards'][0]
        self.assertEqual((a['year'], a['date']), (2020, '2022-07-07'))

    def test_guessed_year_of_undated_article_is_dropped(self):
        listed = via(rec('Otto Waalkes', year=2018, residence='Hamburg', announced='2018-10-01'), 'bpr')
        guessed = {**rec('Otto Waalkes', year=2017, residence='Hamburg', official=False), 'date': '2017-10-03'}
        a = run_merge([listed, guessed])[0]['awards'][0]
        self.assertEqual((a['year'], a['date']), (2018, None))

    def test_nicknames_join_but_heiner_is_not_heinz(self):
        self.assertEqual(len(run_merge([rec('Liselotte Habersack', residence='München'), rec('Lilo Habersack', residence='München', official=False)])), 1)
        rows = [rec('Heinz Günther Friedrich', 'Verdienstmedaille', 2022, 'Langenselbold', announced='2022-11-01'), rec('Heiner Friedrich', year=2022, residence='', official=False)]
        self.assertEqual(len(run_merge(rows)), 2)
        rows = [rec('Simon Wittmann', 'Verdienstkreuz 1. Klasse', 2016, 'Tännesberg', announced='2016-09-01'), rec('Simon Wittmann', year=2016, residence='', official=False)]
        self.assertEqual(len(run_merge(rows)), 1)  # a press report naming another grade is the same award

class RepairTests(unittest.TestCase):
    def test_placeholder_reasons(self):
        self.assertIsNone(merge.clean_reason('Ihm wurde 2015 das Bundesverdienstkreuz am Bande verliehen; die genauen Verdienste werden im Dokument nicht näher erläutert.'))
        self.assertEqual(merge.clean_reason('Er wurde als ehemaliger Bürgermeister ausgezeichnet; nähere Verdienste werden im Artikel nicht genannt.'), 'Er wurde als ehemaliger Bürgermeister ausgezeichnet.')
        self.assertEqual(merge.clean_reason('Für ihr Engagement im Hospiz.'), 'Für ihr Engagement im Hospiz.')

    def test_quotes_and_readable_dates(self):
        from bvk import repair
        text = 'Großer Abend in Kiel. Sie freut sich sehr. Erika Muster erhielt am 12. Dezember das Bundesverdienstkreuz.\nMuster dankte allen.'
        self.assertEqual(repair.quote_for(text, 'Erika Muster', 'Sie freut sich sehr.'), 'Erika Muster erhielt am 12. Dezember das Bundesverdienstkreuz.')
        self.assertIsNone(repair.quote_for(text, 'Erika Muster', 'Muster dankte allen.'))
        self.assertTrue(repair.readable('2025-12-12', text, '2025-12-13'))
        self.assertFalse(repair.readable('2025-12-12', text, None))  # an undated page: the year was guessed
        self.assertTrue(repair.readable('2025-12-12', 'Ehrung am 12.12.2025', None))
        self.assertFalse(repair.readable('2025-12-19', text, '2025-12-20'))  # "am Freitag" style dates are not in the page
        self.assertFalse(repair.readable('2020-01-01', 'Erika Muster (* 1. Januar 1950) erhielt 2020 das Bundesverdienstkreuz.', None, 'Erika Muster'))  # a birthday
    def test_apply_fills_only_empty_fields_and_rejects_impossible_presenters(self):
        from bvk import repair
        from bvk.common import h
        url, quote = 'https://example.org/a', 'Sie freut sich sehr.'
        text = 'Erika Muster aus Wiesbaden erhielt am 8. Oktober 2026 das Verdienstkreuz am Bande.'
        def person(): return [{'id': 'p1', 'name': 'Erika Muster', 'occupation': None, 'awards': [{'grade': 'Verdienstkreuz am Bande', 'year': 2018, 'date': None, 'place': None, 'presented_by': None,
                               'reason': 'Für ihr Ehrenamt.', 'sources': [{'url': url, 'via': 'search', 'extracted_by': 'model', 'quote': quote}]}]}]
        answer = {'same_award': True, 'occupation': 'Lehrerin', 'reason': 'Etwas anderes.', 'date': '2026-10-08', 'place': 'Wiesbaden', 'presented_by': 'Ministerpräsident Volker Bouffier', 'model': 'm', 'provider': None}
        ps = person(); repair.apply(ps, {url: {'text': text, 'date': '2026-10-13'}}, {h(f'p1|{url}|{quote}'): answer})
        a = ps[0]['awards'][0]
        self.assertEqual((ps[0]['occupation'], a['reason'], a['date'], a['presented_by'], a['place']), ('Lehrerin', 'Für ihr Ehrenamt.', None, None, 'Wiesbaden'))
        self.assertEqual((a['sources'][0]['quote'], a['sources'][0]['extraction_quote']), (text, quote))
        ps = person(); repair.apply(ps, {url: {'text': text, 'date': '2026-10-13'}}, {h(f'p1|{url}|{quote}'): {**answer, 'same_award': False}})
        self.assertIsNone(ps[0]['occupation'])

def fake_wikidata(cache):  # municipalities, settlements and states as the cached Wikidata tables give them
    q, pop = 'http://www.wikidata.org/entity/', '2023-12-31T00:00:00Z'
    towns = [('Q1', '09190118', 'Burggen', 1743, ['Dessau']), ('Q2', '15001000', 'Dessau-Roßlau', 75000, []), ('Q3', '10044112', 'Lebach', 18000, []), ('Q4', '13076120', 'Rom', 200, [])]
    return {'wd_gemeinde_pop.tsv': [[q + g, str(n), pop] for g, _, _, n, _ in towns],
            'wd_gemeinden.tsv': [[q + g, a, f'{l}"@de', t] for g, a, n, _, al in towns for l, t in [(n, '0')] + [(x, '1') for x in al]],
            'wd_ortsteile.tsv': [['Gresaubach"@de', '10044112'], ['Dessau"@de', '15001000']], 'wd_kreise.tsv': [],
            'wd_staaten.tsv': [[q + 'Q38', 'Italien"@de', '0'], [q + 'Q183', 'Deutschland"@de', '0']]}[cache]

class ReviewFixTests(unittest.TestCase):
    def test_one_list_naming_two_entries_lists_two_people(self):
        u = 'https://example.org/1610-Verleihungen.html'
        p = run_merge([rec('Wolfgang Templin', 'Verdienstkreuz 1. Klasse', url=u), rec('Wolfgang Peter Templin', url=u)])
        self.assertEqual(sorted((x['name'], x['awards'][0]['grade']) for x in p), [('Wolfgang Peter Templin', 'Verdienstkreuz am Bande'), ('Wolfgang Templin', 'Verdienstkreuz 1. Klasse')])

    def test_unknown_grade_report_beside_a_listed_award_is_that_award(self):
        p = run_merge([rec('Karamba Diaby', year=2026, residence='Halle (Saale)', announced='2026-10-12'), rec('Karamba Diaby', 'unbekannt', 2020, 'Halle (Saale)', official=False)])
        self.assertEqual([(a['grade'], a['year'], len(a['sources'])) for a in p[0]['awards']], [('Verdienstkreuz am Bande', 2026, 2)])

    def test_couples_and_descriptions_are_no_names(self):
        for n in ('Ehepaar Christoph', 'Unbekanntes Würzburger Ehepaar', 'Kronacher Heimatdichter'): self.assertTrue(merge.not_a_name(n, None, None), n)
        self.assertFalse(merge.not_a_name('Kurt Bürgermeister', None, None))

    def test_a_date_sets_its_year_and_corrections_can_name_one_record(self):
        self.assertEqual(merge.sanitize({'name': 'Edith Eiersbrock', 'date': '2023-03-17', 'year': 2020, 'quote': '', 'presented_by': None})['year'], 2023)
        fixes = {'u': [{'name': 'Hans Rabl', 'action': 'drop'}, {'action': 'undate'}]}
        self.assertEqual((merge.correction(fixes, 'u', 'Hans Rabl')['action'], merge.correction(fixes, 'u', 'Matthias Stegmeir')['action'], merge.correction(fixes, 'v', 'X')), ('drop', 'undate', None))

    def test_press_ages(self):
        age = lambda text, surname: (m := enrich.press_age(surname).search(text)) and int(m[1] or m[2])
        self.assertEqual(age('die Cloppenburger Notärztin Almut Opolka (50) in Berlin', 'Opolka'), 50)
        self.assertEqual(age('Der 74-jährige Lehrer Peter Fehse wurde geehrt', 'Fehse'), 74)
        self.assertEqual(age('Der 57-jährige Autohändler van Neer hat sich', 'Neer'), 57)
        self.assertIsNone(age('Zum 25-jährigen Außenstellenjubiläum holte Markus Müller die Ausstellung', 'Müller'))
        self.assertIsNone(age('würdigte die nunmehr 30-jährige Tätigkeit Ekkehard Palandts im Vorstand', 'Palandt'))
        self.assertIsNone(age('Als 19-Jähriger kam Icek Ostrowicz allein nach Mönchengladbach', 'Ostrowicz'))

    def test_gender_in_name_order(self):
        ps = [{'name': 'Herbert Marion Pichler', 'wikidata': None, 'occupation': None, 'residence': None, 'country': None, 'state': None, 'ags': None, 'awards': [{'year': 2019, 'date': None, 'sources': []}]}]
        with patch.object(enrich, 'given_names', return_value={'herbert': {'m'}}), patch.object(enrich, 'wd_people', return_value={}), patch.object(enrich, 'docs', return_value=iter([])), patch.object(enrich, 'places'):
            enrich.run(ps)
        self.assertEqual(ps[0]['gender'], 'm')

    def test_places(self):
        with patch.object(enrich, 'sparql', side_effect=lambda query, cache: fake_wikidata(cache)):
            locate = enrich.locator()
        self.assertEqual(locate('Dessau')[:2], ('Deutschland', 'Sachsen-Anhalt'))  # not the alias of Burggen
        self.assertEqual(locate('Rom'), ('Italien', None, None))  # the lists write "Rom", "Prag", "Wien" without a country
        self.assertEqual(locate('Monsignore, Prag'), ('Tschechien', None, None))
        with tempfile.TemporaryDirectory() as folder, patch.object(enrich, '_locate', locate), patch.object(enrich, 'CACHE', Path(folder)):
            self.assertIsNone(enrich.municipality('Lebach'))  # without the cached table the merge does not fetch it
            (Path(folder) / 'wd_gemeinden.tsv').write_text('')
            self.assertTrue(merge.same_place('Gresaubach', 'Lebach'))  # a village and its municipality
            self.assertFalse(merge.same_place('Gresaubach', 'Burggen'))

if __name__ == '__main__': unittest.main()
