"""Synthetic importer fixtures. No gol.gg, browser, clipboard or credentials."""
import hashlib
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest

import importar_golgg_sqlite as importer

RAW=('Champion\tRole\t# Games\tNocturne Winrate\tCSD@15\tGD@15\tXPD@15\tKDA\tExtra\r\n'
     '\xa0Wukong\t JUNGLE \t1,234\t55,5%\t+1.2\t-181\t−2\t3,2\t=original\r\n'
     'Ahri\t\t\t\t—\t\tNA\t-\t\r\n'
     '\xa0Wukong\t JUNGLE \t1,234\t55,5%\t+1.2\t-181\t−2\t3,2\t=original\r\n')


def fixture(directory, cid='synthetic', category='Direct_Matchup', raw=RAW, rows=3, run='run-a'):
    metadata={'capture_id':cid,'run_id':run,'raw_file':cid+'.txt',
              'raw_sha256':hashlib.sha256(raw.encode()).hexdigest(),
              'parse_status':'parsed' if rows else 'empty','row_count':rows,
              'collected_at_utc':'2026-10-21T22:00:00+00:00',
              'source_url':'https://example.invalid/synthetic',
              'requested':{'Selected champion':'Nocturne','Matchup category':category,
                           'Game version':'16.20','Season':'unknown'},
              'verified':{'Selected champion':'Nocturne','Matchup category':category,
                          'Game version':'16.20','Season':'unknown','Role filter':'ALL',
                          'Page champion role':'unknown','League selections':'unknown'},
              'source_context':{'url_parameters':{'season':'S16','split':'ALL'}}}
    path=directory/(cid+'.json')
    path.write_text(json.dumps(metadata,ensure_ascii=False),encoding='utf-8')
    path.with_suffix('.txt').write_bytes(raw.encode())
    return path


class ImportTests(unittest.TestCase):
    def test_preservation_numeric_nulls_categories_and_idempotency(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); source=root/'source';source.mkdir();db=root/'data.sqlite'
            originals={}
            for i,category in enumerate(importer.CATEGORIES):
                path=fixture(source,cid=f'synthetic-{i}',category=category)
                originals[path.stem]=(path.read_bytes(),path.with_suffix('.txt').read_bytes())
            report=importer.import_directory(source,db,expect_captures=3,expect_records=9)
            self.assertEqual(report['inserted_records'],9)
            con=sqlite3.connect(db)
            try:
                self.assertEqual(con.execute('SELECT COUNT(*) FROM dados_coletados').fetchone()[0],9)
                self.assertEqual(len(con.execute('SELECT DISTINCT category FROM capturas').fetchall()),3)
                cap=con.execute('SELECT capture_id,raw_bytes,metadata_bytes,season_verified,season_url,page_role_verified,table_role_filter_verified FROM capturas LIMIT 1').fetchone()
                self.assertEqual((cap[2],cap[1]),originals[cap[0]])
                self.assertEqual(cap[3:],(None,'S16',None,'ALL'))
                first=con.execute('SELECT related_champion,source_role,games,winrate,csd15,gd15,xpd15,kda,source_fields_json FROM registros WHERE record_index=1 LIMIT 1').fetchone()
                self.assertEqual(first[:8],('\xa0Wukong',' JUNGLE ',1234,.555,1.2,-181,-2,3.2))
                self.assertEqual(json.loads(first[8])['Extra'],'=original')
                self.assertEqual(con.execute('SELECT games,winrate,csd15,gd15,xpd15,kda FROM registros WHERE record_index=2 LIMIT 1').fetchone(),(None,)*6)
            finally:con.close()
            second=importer.import_directory(source,db,append=True)
            self.assertEqual(second['already_imported_captures'],3)
            self.assertEqual(second['inserted_records'],0)
            self.assertEqual(second['database_records'],9)
            with self.assertRaises(FileExistsError):importer.import_directory(source,db)

    def test_corruption_rolls_back_entire_import(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);source=root/'source';source.mkdir();db=root/'data.sqlite'
            fixture(source,'a');bad=fixture(source,'z',category='Ally_Synergy')
            bad.with_suffix('.txt').write_text('changed')
            with self.assertRaisesRegex(ValueError,'Checksum'):
                importer.import_directory(source,db)
            self.assertFalse(db.exists())
            bad.unlink();bad.with_suffix('.txt').unlink()
            importer.import_directory(source,db)
            before=db.read_bytes()
            bad=fixture(source,'z',category='Ally_Synergy')
            metadata=json.loads(bad.read_text());metadata['row_count']=999;bad.write_text(json.dumps(metadata))
            with self.assertRaisesRegex(ValueError,'Contagem'):
                importer.import_directory(source,db,append=True)
            self.assertEqual(db.read_bytes(),before)

    def test_changed_existing_id_and_duplicate_context_are_refused(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);source=root/'source';source.mkdir();db=root/'data.sqlite'
            path=fixture(source);importer.import_directory(source,db)
            metadata=json.loads(path.read_text());metadata['extra']='new'
            path.write_text(json.dumps(metadata))
            with self.assertRaisesRegex(ValueError,'conteúdo diferente'):
                importer.import_directory(source,db,append=True)
            path=fixture(source)
            fixture(source,'duplicate')
            with self.assertRaisesRegex(ValueError,'UNIQUE constraint'):
                importer.import_directory(source,db,append=True)

    def test_existing_rows_modified_without_count_change_are_refused(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);source=root/'source';source.mkdir();db=root/'data.sqlite'
            fixture(source);importer.import_directory(source,db)
            con=sqlite3.connect(db);con.execute('UPDATE registros SET games=999 WHERE record_index=1');con.commit();con.close()
            with self.assertRaisesRegex(ValueError,'inconsistentes'):
                importer.import_directory(source,db,append=True)

    def test_empty_diagnostics_failed_and_run_selection(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);source=root/'source';source.mkdir();db=root/'data.sqlite'
            fixture(source,raw='Champion\tGames\tNocturne Winrate\r\n',rows=0)
            fixture(source,'other',run='run-b')
            failed=fixture(source,'failed');meta=json.loads(failed.read_text());meta['parse_status']='failed';failed.write_text(json.dumps(meta))
            (source/'diagnostic-x.json').write_text('{"run_id":"run-a","error":"synthetic"}')
            report=importer.import_directory(source,db,run_id='run-a')
            self.assertEqual(report['source_captures'],1)
            self.assertEqual(report['source_records'],0)
            self.assertEqual(report['empty_captures'],1)
            self.assertEqual(report['diagnostics_ignored'],1)
            self.assertEqual(report['unvalidated_ignored'],1)
            self.assertEqual(report['other_runs_ignored'],1)

    def test_limits_expected_counts_and_unrelated_database(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);source=root/'source';source.mkdir();db=root/'test.sqlite'
            fixture(source,'a');fixture(source,'b',category='Ally_Synergy')
            report=importer.import_directory(source,db,limit=1)
            self.assertEqual(report['source_captures'],1)
            with self.assertRaisesRegex(ValueError,'Conferência falhou'):
                importer.import_directory(source,root/'wrong.sqlite',expect_captures=99)
            self.assertFalse((root/'wrong.sqlite').exists())
            unrelated=root/'unrelated.sqlite'
            con=sqlite3.connect(unrelated);con.execute('CREATE TABLE keep_me (value TEXT)');con.commit();con.close()
            before=unrelated.read_bytes()
            with self.assertRaisesRegex(ValueError,'não pertence'):
                importer.import_directory(source,unrelated,append=True)
            self.assertEqual(unrelated.read_bytes(),before)

    def test_malformed_fields_and_untrusted_paths(self):
        for raw,pattern in [(RAW.replace('55,5%','101%'),'Winrate'),
                            (RAW.replace('1,234','-1'),'Games'),
                            (RAW.replace('+1.2','oops'),'Registro'),
                            (RAW.replace('Nocturne Winrate','Ahri Winrate'),'Cabeçalho')]:
            with self.subTest(pattern=pattern),self.assertRaisesRegex(ValueError,pattern):
                importer.parse_rows(raw,'Nocturne')
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);path=fixture(root);metadata=json.loads(path.read_text());metadata['raw_file']='../private.txt'
            with self.assertRaisesRegex(ValueError,'raw_file'):
                importer.read_capture(path,metadata,path.read_bytes())

    def test_cli_uses_standard_library_only_and_writes_report(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);source=root/'source';source.mkdir();fixture(source)
            result=subprocess.run([sys.executable,'-S',str(Path(importer.__file__)),
                '--source',str(source),'--database',str(root/'cli.sqlite'),
                '--expect-captures','1','--expect-records','3'],capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)
            reports=list(root.glob('*.import-*.json'))
            self.assertEqual(len(reports),1)
            self.assertEqual(json.loads(reports[0].read_text())['status'],'committed')


if __name__=='__main__':unittest.main()
