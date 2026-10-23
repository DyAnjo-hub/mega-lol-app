"""Synthetic GD@15 fixtures. No browsing or claims of predictive validation."""
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from importar_golgg_sqlite import import_directory
from functools import partial
from modelo_gold15_sqlite import compare_gold15 as compare_with_synergy

# Preserve the original direct-only regression tests through the explicit option.
compare_gold15 = partial(compare_with_synergy, synergy_weight=0)
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
            self.assertEqual(app.metric[0].value,'+820 ouro')
            self.assertEqual(app.metric[1].value,'5/5')
            self.assertEqual(app.metric[2].value,'+500 ouro')
            self.assertEqual(len(app.get('download_button')),1)
            app.slider[0].set_value(0).run()
            self.assertTrue(any('anterior' in x.value for x in app.warning))
            next(x for x in app.button if x.label=='Calcular GD@15').click().run()
            self.assertEqual(app.metric[0].value,'+500 ouro')
            app.number_input[0].set_value(20).run()
            self.assertTrue(any('anterior' in x.value for x in app.warning))
            next(x for x in app.button if x.label=='Calcular GD@15').click().run()
            self.assertEqual(app.metric[1].value,'0/5')
            self.assertEqual(db.read_bytes(),before)


class BotSynergyTests(unittest.TestCase):
    """Synthetic directed allied outcomes; never treat A-with-B as B-with-A."""
    def update_pair(self,db,selected,related,gold,*,category='Ally_Synergy',games=10,patch='16.10'):
        GoldTests().execute(db,'''UPDATE registros SET gd15=?,games=? WHERE related_champion=?
            AND capture_id IN (SELECT capture_id FROM capturas WHERE selected_champion=?
            AND category=? AND patch_verified=?)''',(gold,games,related,selected,category,patch))

    def test_blend_exact_direction_preservation_swap_and_no_source_writes(self):
        with tempfile.TemporaryDirectory() as d:
            db=GoldTests().database(Path(d))
            for first,second,gd in [('D','E',400),('E','D',-50),('I','J',-200),('J','I',150)]:
                self.update_pair(db,first,second,gd)
            before=db.read_bytes()
            result=compare_with_synergy(db,BLUE,RED)
            adc,support=result['lanes'][3:]
            self.assertEqual(adc['direct_gd15'],100)
            self.assertEqual(adc['synergy']['gd15'],300) # (400 - -200)/2
            self.assertEqual(adc['gd15'],180) # .6*100 + .4*300
            self.assertEqual(support['synergy']['gd15'],-100) # (-50 - 150)/2
            self.assertEqual(support['gd15'],20)
            self.assertEqual(result['total_gd15'],500)
            self.assertEqual(adc['synergy']['blue']['sources'][0]['category'],'Ally_Synergy')
            self.assertEqual(adc['synergy']['blue']['sources'][0]['rows'][0]['gd15'],400)
            self.assertEqual(compare_with_synergy(db,RED,BLUE)['total_gd15'],-500)
            self.assertEqual([x['gd15'] for x in result['lanes'][:3]],[100]*3)
            self.assertEqual(db.read_bytes(),before)
            json.dumps(result,allow_nan=False)

    def test_changing_support_changes_adc_contribution(self):
        with tempfile.TemporaryDirectory() as d:
            db=GoldTests().database(Path(d))
            self.update_pair(db,'D','E',600)
            self.update_pair(db,'D','C',-200)
            original=compare_with_synergy(db,BLUE,RED)
            revised=compare_with_synergy(db,['A','B','E','D','C'],RED)
            self.assertEqual(original['lanes'][3]['direct_gd15'],revised['lanes'][3]['direct_gd15'])
            self.assertNotEqual(original['lanes'][3]['gd15'],revised['lanes'][3]['gd15'])

    def test_missing_selected_direction_is_not_replaced_with_reverse(self):
        with tempfile.TemporaryDirectory() as d:
            db=GoldTests().database(Path(d))
            self.update_pair(db,'D','E',None)
            result=compare_with_synergy(db,BLUE,RED)
            self.assertIsNone(result['total_gd15'])
            self.assertEqual(result['covered_positions'],4)
            self.assertIsNone(result['lanes'][3]['synergy']['blue']['gd15'])
            self.assertIsNotNone(result['lanes'][4]['synergy']['blue']['gd15'])
            self.assertIsNone(result['lanes'][3]['gd15'])
            self.assertEqual(result['direct_total_gd15'],500)
            self.assertEqual(compare_with_synergy(db,BLUE,RED,synergy_weight=0)['total_gd15'],500)

    def test_weighted_patches_roles_threshold_and_zero(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);db=GoldTests().database(root)
            second=root/'second';second.mkdir()
            import_directory(make_source(second,patch='16.11'),db,append=True)
            self.update_pair(db,'D','E',100,games=10)
            self.update_pair(db,'D','E',400,games=20,patch='16.11')
            con=sqlite3.connect(db)
            cid=con.execute("SELECT capture_id FROM capturas WHERE selected_champion='D' AND category='Ally_Synergy' AND patch_verified='16.10'").fetchone()[0]
            con.execute('INSERT INTO registros VALUES (?,?,?,?,?,?,?,?,?,?,?,?)',
                        (cid,99,'E','E','SUPPORT',5,None,None,-200,None,None,'{}'))
            con.commit();con.close()
            lane=compare_with_synergy(db,BLUE,RED)['lanes'][3]
            ally=lane['synergy']['blue']
            self.assertEqual(ally['games'],35)
            self.assertAlmostEqual(ally['gd15'],8000/35)
            self.assertEqual(len(ally['sources']),2)
            self.assertTrue(ally['sources'][0]['rows'][0]['capture_id'])
            self.assertEqual({r['source_role'] for r in ally['sources'][0]['rows']},{'TOP','SUPPORT'})
            self.assertIsNone(compare_with_synergy(db,BLUE,RED,minimum_games=36)['lanes'][3]['gd15'])
            self.update_pair(db,'D','E',0)
            self.update_pair(db,'D','E',0,patch='16.11')
            # The other source-role row is also set to zero by update_pair.
            self.assertEqual(compare_with_synergy(db,BLUE,RED)['lanes'][3]['synergy']['blue']['gd15'],0)

    def test_weights_endpoints_invalid_and_missing_category(self):
        with tempfile.TemporaryDirectory() as d:
            db=GoldTests().database(Path(d))
            for bad in (-.1,1.1,float('nan'),float('inf'),'40'):
                with self.assertRaises(ValueError):compare_with_synergy(db,BLUE,RED,synergy_weight=bad)
            self.assertEqual(compare_with_synergy(db,BLUE,RED,synergy_weight=1)['total_gd15'],1300)
            GoldTests().execute(db,"DELETE FROM registros WHERE capture_id IN (SELECT capture_id FROM capturas WHERE category='Ally_Synergy')")
            GoldTests().execute(db,"DELETE FROM capturas WHERE category='Ally_Synergy'")
            self.assertEqual(compare_with_synergy(db,BLUE,RED)['covered_positions'],3)
            self.assertEqual(compare_with_synergy(db,BLUE,RED,synergy_weight=0)['total_gd15'],500)

    def test_synergy_context_and_duplicate_safeguards(self):
        with tempfile.TemporaryDirectory() as d:
            db=GoldTests().database(Path(d))
            GoldTests().execute(db,"UPDATE capturas SET source_context_json=? WHERE category='Ally_Synergy' AND selected_champion='D'",
                                (json.dumps({'url_parameters':{'split':'Summer'}}),))
            with self.assertRaisesRegex(ValueError,'Contextos diferentes em Ally_Synergy'):
                compare_with_synergy(db,BLUE,RED)
            GoldTests().execute(db,"UPDATE capturas SET source_context_json=? WHERE category='Ally_Synergy'",
                                (json.dumps({'url_parameters':{'season':'S16','split':'ALL'}}),))
            con=sqlite3.connect(db)
            cid=con.execute("SELECT capture_id FROM capturas WHERE selected_champion='D' AND category='Ally_Synergy'").fetchone()[0]
            con.execute('INSERT INTO registros VALUES (?,?,?,?,?,?,?,?,?,?,?,?)',
                        (cid,99,'E','E','TOP',5,None,None,5,None,None,'{}'))
            con.commit();con.close()
            with self.assertRaisesRegex(ValueError,'Linha repetida'):compare_with_synergy(db,BLUE,RED)

    def test_conflicting_context_between_categories_refused(self):
        with tempfile.TemporaryDirectory() as d:
            db=GoldTests().database(Path(d))
            GoldTests().execute(db,"UPDATE capturas SET source_context_json=? WHERE category='Ally_Synergy'",
                                (json.dumps({'url_parameters':{'season':'S16','split':'Summer'}}),))
            with self.assertRaisesRegex(ValueError,'entre confronto direto e sinergia'):
                compare_with_synergy(db,BLUE,RED)
            self.assertEqual(compare_with_synergy(db,BLUE,RED,synergy_weight=0)['total_gd15'],500)
