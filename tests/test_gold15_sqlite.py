"""Synthetic GD@15 fixtures. No browsing or claims of predictive validation."""
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from importar_golgg_sqlite import import_directory
from modelo_gold15_sqlite import compare_gold15
from test_modelo_draft_sqlite import BLUE, RED, make_source


class GoldTests(unittest.TestCase):
    def database(self, root):
        db = root/'synthetic.sqlite'
        import_directory(make_source(root), db)
        con = sqlite3.connect(db)
        con.execute('UPDATE registros SET gd15=100')
        # Canonical direction wins the equal-Games tie. Deliberately conflicting
        # reverse values ensure opposite directions are not averaged or added.
        con.execute("UPDATE registros SET gd15=-900 WHERE capture_id IN (SELECT capture_id FROM capturas WHERE selected_champion IN ('F','G','H','I','J'))")
        con.commit(); con.close()
        return db

    def execute(self, db, sql, parameters=()):
        con = sqlite3.connect(db)
        try:
            con.execute(sql, parameters)
            con.commit()
        finally:
            con.close()

    def test_five_aligned_sum_swap_and_source_unchanged(self):
        with tempfile.TemporaryDirectory() as d:
            db = self.database(Path(d)); before = db.read_bytes()
            result = compare_gold15(db, BLUE, RED)
            self.assertEqual(result['total_gd15'], 500)
            self.assertEqual([(x['blue'],x['red']) for x in result['lanes']], list(zip(BLUE,RED)))
            self.assertEqual([x['games'] for x in result['lanes']], [10]*5)
            self.assertEqual(compare_gold15(db,RED,BLUE)['total_gd15'], -500)
            self.assertEqual(db.read_bytes(),before)
            json.dumps(result, allow_nan=False)

    def test_signed_zero_missing_and_partial_not_zero_filled(self):
        with tempfile.TemporaryDirectory() as d:
            db = self.database(Path(d))
            self.execute(db,"UPDATE registros SET gd15=NULL WHERE (related_champion='F' AND capture_id IN (SELECT capture_id FROM capturas WHERE selected_champion='A')) OR (related_champion='A' AND capture_id IN (SELECT capture_id FROM capturas WHERE selected_champion='F'))")
            self.execute(db,"UPDATE registros SET gd15=0 WHERE related_champion='G' AND capture_id IN (SELECT capture_id FROM capturas WHERE selected_champion='B')")
            self.execute(db,"UPDATE registros SET gd15=-50 WHERE related_champion='H' AND capture_id IN (SELECT capture_id FROM capturas WHERE selected_champion='C')")
            result = compare_gold15(db,BLUE,RED)
            self.assertIsNone(result['total_gd15'])
            self.assertEqual(result['covered_positions'],4)
            self.assertEqual(result['partial_gd15'],150)
            self.assertIsNone(result['lanes'][0]['gd15'])
            self.assertEqual(result['lanes'][1]['gd15'],0)
            self.assertEqual(result['lanes'][2]['gd15'],-50)

    def test_weighted_roles_patches_and_traceable_one_direction(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); db=self.database(root)
            second=root/'second';second.mkdir()
            import_directory(make_source(second,patch='16.11'),db,append=True)
            self.execute(db,"UPDATE registros SET gd15=200 WHERE capture_id IN (SELECT capture_id FROM capturas WHERE patch_verified='16.11')")
            con=sqlite3.connect(db)
            cid=con.execute("SELECT capture_id FROM capturas WHERE selected_champion='A' AND category='Direct_Matchup' AND patch_verified='16.10'").fetchone()[0]
            con.execute('INSERT INTO registros VALUES (?,?,?,?,?,?,?,?,?,?,?,?)',
                        (cid,99,'F','F','MID',5,None,None,-200,None,None,'{}'))
            con.commit();con.close()
            lane=compare_gold15(db,BLUE,RED)['lanes'][0]
            self.assertEqual(lane['games'],25)
            self.assertEqual(lane['gd15'],80) # (10*100 + 5*-200 + 10*200)/25
            self.assertEqual(len(lane['sources']),2)
            source=lane['sources'][0]['directions']
            self.assertEqual(sum(x['chosen'] for x in source),1)
            self.assertEqual({r['source_role'] for x in source if x['chosen'] for r in x['rows']},{'TOP','MID'})
            self.assertTrue(all(r['capture_id'] for x in source for r in x['rows']))

    def test_reverse_only_and_more_games_sign(self):
        with tempfile.TemporaryDirectory() as d:
            db=self.database(Path(d))
            self.execute(db,"UPDATE registros SET games=20 WHERE related_champion='A' AND capture_id IN (SELECT capture_id FROM capturas WHERE selected_champion='F')")
            lane=compare_gold15(db,BLUE,RED)['lanes'][0]
            self.assertEqual(lane['gd15'],900)
            self.assertEqual(lane['games'],20)
            self.execute(db,"DELETE FROM registros WHERE related_champion='F' AND capture_id IN (SELECT capture_id FROM capturas WHERE selected_champion='A')")
            self.assertEqual(compare_gold15(db,BLUE,RED)['lanes'][0]['gd15'],900)
            self.assertEqual(compare_gold15(db,RED,BLUE)['lanes'][0]['gd15'],-900)

    def test_empty_and_threshold(self):
        with tempfile.TemporaryDirectory() as d:
            db=self.database(Path(d))
            result=compare_gold15(db,BLUE,RED,minimum_games=11)
            self.assertIsNone(result['total_gd15'])
            self.assertEqual(result['lanes'][0]['status'],'insufficient_games')
            self.assertEqual(result['lanes'][0]['observed_gd15'],100)
            self.execute(db,'UPDATE registros SET gd15=NULL')
            result=compare_gold15(db,BLUE,RED)
            self.assertIsNone(result['partial_gd15'])
            self.assertEqual(result['covered_positions'],0)

    def test_invalid_repeated_and_mixed_context_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            db=self.database(Path(d))
            with self.assertRaises(ValueError):compare_gold15(db,BLUE,BLUE)
            with self.assertRaises(ValueError):compare_gold15(db,BLUE,RED,minimum_games=0)
            self.execute(db,"UPDATE registros SET gd15='malformed'")
            with self.assertRaisesRegex(ValueError,'GD@15 inválido'):compare_gold15(db,BLUE,RED)
            self.execute(db,'UPDATE registros SET gd15=10')
            with self.assertRaises(sqlite3.IntegrityError):
                self.execute(db,"UPDATE registros SET games=-1")
            self.execute(db,"UPDATE capturas SET patch_verified='ALL'")
            with self.assertRaises(ValueError):compare_gold15(db,BLUE,RED)
            self.execute(db,"UPDATE capturas SET patch_verified='16.10'")
            self.execute(db,"UPDATE capturas SET source_context_json=? WHERE selected_champion='A'",(json.dumps({'url_parameters':{'split':'Summer'}}),))
            with self.assertRaisesRegex(ValueError,'Contextos diferentes'):compare_gold15(db,BLUE,RED)

    def test_duplicate_role_and_multiple_snapshots(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);db=self.database(root)
            second=root/'second';second.mkdir()
            import_directory(make_source(second,run='run-b'),db,append=True)
            with self.assertRaisesRegex(ValueError,'Run ID'):compare_gold15(db,BLUE,RED)
            self.assertEqual(compare_gold15(db,BLUE,RED,run_id='run-a')['total_gd15'],500)
            con=sqlite3.connect(db)
            cid=con.execute("SELECT capture_id FROM capturas WHERE run_id='run-a' AND selected_champion='A' AND category='Direct_Matchup'").fetchone()[0]
            con.execute('INSERT INTO registros VALUES (?,?,?,?,?,?,?,?,?,?,?,?)',
                        (cid,99,'F','F','TOP',5,None,None,5,None,None,'{}'))
            con.commit();con.close()
            with self.assertRaisesRegex(ValueError,'Linha repetida'):compare_gold15(db,BLUE,RED,run_id='run-a')


class GoldUITests(unittest.TestCase):
    def test_calculate_download_and_stale_warning(self):
        from streamlit.testing.v1 import AppTest
        with tempfile.TemporaryDirectory() as d:
            db=GoldTests().database(Path(d)); before=db.read_bytes()
            app=AppTest.from_file(str(Path(__file__).resolve().parents[1]/'app_gold15_sqlite.py')).run()
            app.text_input[0].set_value(str(db)).run()
            for position,a,b in zip(('TOP','JUNGLE','MID','ADC','SUPPORT'),BLUE,RED):
                next(x for x in app.selectbox if x.label=='Azul — '+position).set_value(a)
                next(x for x in app.selectbox if x.label=='Vermelho — '+position).set_value(b)
            app.run()
            next(x for x in app.button if x.label=='Calcular GD@15').click().run(timeout=30)
            self.assertFalse(app.exception)
            self.assertEqual(app.metric[0].value,'+500 ouro')
            self.assertEqual(app.metric[1].value,'5/5')
            self.assertEqual(len(app.get('download_button')),1)
            app.number_input[0].set_value(20).run()
            self.assertTrue(any('anterior' in x.value for x in app.warning))
            next(x for x in app.button if x.label=='Calcular GD@15').click().run()
            self.assertEqual(app.metric[1].value,'0/5')
            self.assertEqual(db.read_bytes(),before)
