"""Synthetic model fixtures. No browsing, no match outcomes or calibration claims."""
import hashlib
import itertools
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

import importar_golgg_sqlite as importer
import modelo_draft_sqlite as model

BLUE=list('ABCDE');RED=list('FGHIJ')


def make_source(root, *, run='run-a', patch='16.10', duplicate_role=False):
    source=root/'source';source.mkdir(exist_ok=True)
    for champion in BLUE+RED:
        for category in model.WEIGHTS:
            related=[x for x in (BLUE if champion in BLUE else RED) if x!=champion] if category=='Ally_Synergy' else (RED if champion in BLUE else BLUE)
            lines=['Champion\tRole\tGames\t'+champion+' Winrate']
            lines += [f'{other}\tTOP\t10\t'+('60%' if champion in BLUE else '40%') for other in related]
            if duplicate_role and champion=='A' and category=='Direct_Matchup':lines.append('F\tTOP\t2\t50%')
            raw='\n'.join(lines)+'\n';cid=f'{run}-{patch.replace(".","-")}-{champion}-{category}'
            metadata={'capture_id':cid,'run_id':run,'raw_file':cid+'.txt',
                      'raw_sha256':hashlib.sha256(raw.encode()).hexdigest(),'parse_status':'parsed',
                      'row_count':len(lines)-1,'collected_at_utc':'2026-10-23T00:00:00+00:00',
                      'source_url':'https://example.invalid/synthetic',
                      'requested':{'Selected champion':champion,'Matchup category':category,'Game version':patch},
                      'verified':{'Selected champion':champion,'Matchup category':category,'Game version':patch},
                      'source_context':{'url_parameters':{'season':'S16','split':'ALL'}}}
            (source/(cid+'.json')).write_text(json.dumps(metadata))
            (source/(cid+'.txt')).write_bytes(raw.encode())
    return source


class ModelTests(unittest.TestCase):
    def database(self,root,**kwargs):
        source=make_source(root,**kwargs);db=root/'test.sqlite';importer.import_directory(source,db);return db

    def test_weighted_union_of_roles_and_direction(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);db=self.database(root)
            con=sqlite3.connect(db)
            cid=con.execute("SELECT capture_id FROM capturas WHERE selected_champion='A' AND category='Direct_Matchup'").fetchone()[0]
            con.execute("UPDATE registros SET games=10,winrate=.49 WHERE capture_id=? AND related_champion='F'",(cid,))
            con.execute('INSERT INTO registros VALUES (?,?,?,?,?,?,?,?,?,?,?,?)',
                        (cid,99,'F','F','MID',3,.55,None,None,None,None,'{}'))
            con.commit();con.close()
            pairs=model.load_pairs(db,'run-a','16.10')
            pair=pairs[('Direct_Matchup','a','f')]
            self.assertEqual(pair.games,13)
            self.assertAlmostEqual(pair.winrate,(10*.49+3*.55)/13)
            self.assertAlmostEqual(pairs[('Direct_Matchup','f','a')].winrate,.4)
            self.assertEqual(pair.roles,{'TOP','MID'})

    def test_weights_order_invariance_and_draft_swap(self):
        with tempfile.TemporaryDirectory() as directory:
            db=self.database(Path(directory));before=db.read_bytes()
            result=model.compare_drafts(db,BLUE,RED,patch='16.10')
            self.assertAlmostEqual(result['relative_indicator']['blue'],60)
            self.assertEqual(result['weights'],model.WEIGHTS)
            for side in result['teams'].values():
                self.assertEqual(side['components']['Direct_Matchup']['queried_pairs'],25)
                self.assertEqual(side['components']['Ally_Synergy']['queried_pairs'],10)
            reordered=model.compare_drafts(db,BLUE[::-1],RED[::-1],patch='16.10')
            swapped=model.compare_drafts(db,RED,BLUE,patch='16.10')
            self.assertEqual(result['relative_indicator'],reordered['relative_indicator'])
            self.assertAlmostEqual(result['relative_indicator']['blue'],swapped['relative_indicator']['red'])
            self.assertEqual(db.read_bytes(),before)

    def test_synergy_chooses_one_direction_independent_of_order(self):
        a=model.Pair('A','B','Ally_Synergy','16.10',games=10,weighted_rate_sum=6)
        b=model.Pair('B','A','Ally_Synergy','16.10',games=20,weighted_rate_sum=8)
        pairs={('Ally_Synergy','a','b'):a,('Ally_Synergy','b','a'):b}
        component=model.component(pairs,['A','B'],[], 'Ally_Synergy',1)
        self.assertEqual(component['relation_games_sum'],20)
        self.assertEqual(component['score'],40)
        self.assertEqual(component,model.component(pairs,['B','A'],[],'Ally_Synergy',1))

    def test_missing_components_not_filled_or_reweighted(self):
        with tempfile.TemporaryDirectory() as directory:
            db=self.database(Path(directory));con=sqlite3.connect(db)
            con.execute("DELETE FROM registros WHERE capture_id IN (SELECT capture_id FROM capturas WHERE category='Ally_Synergy')")
            con.commit();con.close()
            result=model.compare_drafts(db,BLUE,RED,patch='16.10')
            self.assertIsNone(result['relative_indicator'])
            self.assertIsNone(result['teams']['blue']['score'])
            self.assertIsNone(result['teams']['blue']['components']['Ally_Synergy']['score'])
            self.assertEqual(result['teams']['blue']['components']['Direct_Matchup']['score'],60)

    def test_patch_run_isolation_and_repeated_role_rejection(self):
        with tempfile.TemporaryDirectory() as directory:
            db=self.database(Path(directory),duplicate_role=True)
            with self.assertRaisesRegex(ValueError,'mesmo par/role'):
                model.load_pairs(db,'run-a','16.10')
            with self.assertRaisesRegex(ValueError,'Patch não disponível'):
                model.compare_drafts(db,BLUE,RED,patch='16.20')
            with self.assertRaisesRegex(ValueError,'Run ID não encontrado'):
                model.catalog(db,'other')

    def test_exact_weights_no_gold_and_snapshot_isolation(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);db=self.database(root);con=sqlite3.connect(db)
            con.execute("UPDATE registros SET winrate=1 WHERE capture_id IN (SELECT capture_id FROM capturas WHERE selected_champion IN ('A','B','C','D','E') AND category='Direct_Matchup')")
            con.execute("UPDATE registros SET winrate=0 WHERE capture_id IN (SELECT capture_id FROM capturas WHERE selected_champion IN ('F','G','H','I','J') AND category='Direct_Matchup')")
            con.commit();con.close()
            result=model.compare_drafts(db,BLUE,RED,patch='16.10',run_id='run-a')
            self.assertAlmostEqual(result['relative_indicator']['blue'],76)
            con=sqlite3.connect(db);con.execute('UPDATE registros SET gd15=9999999');con.commit();con.close()
            self.assertEqual(result['relative_indicator'],model.compare_drafts(db,BLUE,RED,patch='16.10',run_id='run-a')['relative_indicator'])
            other=root/'other';other.mkdir();source=make_source(other,run='run-b',patch='16.11')
            importer.import_directory(source,db,append=True)
            with self.assertRaisesRegex(ValueError,'Escolha explicitamente'):
                model.catalog(db)
            isolated=model.load_pairs(db,'run-a','16.10')
            self.assertEqual(isolated[('Direct_Matchup','a','f')].games,10)
            self.assertAlmostEqual(model.compare_drafts(db,BLUE,RED,patch='16.10',run_id='run-a')['relative_indicator']['blue'],76)

    def test_mixed_context_refused_and_bad_inputs(self):
        with tempfile.TemporaryDirectory() as directory:
            db=self.database(Path(directory));con=sqlite3.connect(db)
            con.execute("UPDATE capturas SET source_context_json=? WHERE selected_champion='A' AND category='Direct_Matchup'",(json.dumps({'url_parameters':{'season':'S16','split':'Summer'}}),))
            con.commit();con.close()
            with self.assertRaisesRegex(ValueError,'Contextos diferentes'):
                model.load_pairs(db,'run-a','16.10')
            with self.assertRaisesRegex(ValueError,'dez campeões distintos'):
                model.compare_drafts(db,BLUE,BLUE,patch='16.10')
            with self.assertRaisesRegex(ValueError,'somar 1'):
                model.compare_drafts(db,BLUE,RED,patch='16.10',weights=dict.fromkeys(model.WEIGHTS,1))
