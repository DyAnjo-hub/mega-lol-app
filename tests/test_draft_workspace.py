"""Synthetic history fixtures and mocked official asset responses; no network."""
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from draft_workspace import AnalysisHistory, PortraitCache


class WorkspaceTests(unittest.TestCase):
    def entry(self):
        return {'id':'one','name':'Teste','created_at_utc':'2026-10-23T00:00:00+00:00',
                'notes':'','tags':[],'result':{'score':42}}

    def test_history_persists_notes_tags_and_keeps_results_immutable(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);source=root/'source.sqlite';source.write_bytes(b'preserve-source')
            store=AnalysisHistory(root/'workspace.sqlite',source)
            entry=self.entry();store.save(entry)
            entry.update(notes='Revisar amostra',tags=['Revisar'],name='Meu draft')
            store.save(entry)
            loaded=AnalysisHistory(root/'workspace.sqlite',source).entries()
            self.assertEqual(len(loaded),1)
            self.assertEqual(loaded[0]['notes'],'Revisar amostra')
            self.assertEqual(loaded[0]['tags'],['Revisar'])
            entry['result']['score']=99
            with self.assertRaisesRegex(ValueError,'imutável'):store.save(entry)
            self.assertEqual(source.read_bytes(),b'preserve-source')

    def test_cannot_use_source_or_unrelated_sqlite_as_history(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);source=root/'source.sqlite'
            con=sqlite3.connect(source);con.execute('CREATE TABLE keep_me (value TEXT)');con.commit();con.close()
            before=source.read_bytes()
            with self.assertRaisesRegex(ValueError,'diferente'):AnalysisHistory(source,source)
            with self.assertRaisesRegex(ValueError,'incompatível'):AnalysisHistory(source,root/'another-source.sqlite')
            self.assertEqual(source.read_bytes(),before)

    def test_portrait_ids_names_mapping_cache_and_unknown_fallback(self):
        with tempfile.TemporaryDirectory() as directory:
            calls=[]
            def download(url):
                calls.append(url)
                if url.endswith('versions.json'):return b'["16.20.1"]'
                if url.endswith('champion.json'):
                    return json.dumps({'data':{'MonkeyKing':{'id':'MonkeyKing','name':'Wukong'},
                                               'Chogath':{'id':'Chogath','name':"Cho'Gath"}}}).encode()
                return b'\x89PNG\r\n\x1a\nsynthetic-test-image'
            cache=PortraitCache(directory,download)
            self.assertIsNotNone(cache.image('Wukong'))
            self.assertTrue(calls[-1].endswith('/MonkeyKing.png'))
            self.assertIsNotNone(cache.image('Cho Gath'))
            count=len(calls)
            self.assertIsNotNone(PortraitCache(directory,download).image('Wukong'))
            self.assertEqual(len(calls),count)
            self.assertIsNone(cache.image('Unknown champion'))
            self.assertEqual(len(calls),count)

    def test_offline_failure_does_not_retry_on_every_rerun(self):
        with tempfile.TemporaryDirectory() as directory:
            calls=[]
            def offline(url):calls.append(url);raise OSError('offline')
            self.assertIsNone(PortraitCache(directory,offline).image('Ahri'))
            self.assertIsNone(PortraitCache(directory,offline).image('Ahri'))
            self.assertEqual(len(calls),1)

    def test_non_png_response_is_not_saved_as_an_image(self):
        with tempfile.TemporaryDirectory() as directory:
            def download(url):
                if url.endswith('versions.json'):return b'["16.20.1"]'
                if url.endswith('champion.json'):return b'{"data":{"Ahri":{"id":"Ahri","name":"Ahri"}}}'
                return b'<html>error</html>'
            self.assertIsNone(PortraitCache(directory,download).image('Ahri'))
            self.assertEqual(list(Path(directory).glob('*.png')),[])
