"""Synthetic local SQLite and mocked portraits; UI tests never contact the site."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from streamlit.testing.v1 import AppTest
from draft_workspace import AnalysisHistory, PortraitCache
from modelo_draft_sqlite import POSITIONS
from importar_golgg_sqlite import import_directory
from modelo_draft_sqlite import compare_drafts
from modelo_gold15_sqlite import compare_gold15
import test_gold15_sqlite as gold_fixtures
from test_modelo_draft_sqlite import make_source, BLUE, RED


class WorkspaceUITests(unittest.TestCase):
    def open_app(self,root,db):
        app_file=root/'app_draft_sqlite.py'
        app_file.write_text((Path(__file__).resolve().parents[1]/'app_draft_sqlite.py').read_text())
        app=AppTest.from_file(str(app_file)).run(timeout=30)
        next(t for t in app.text_input if t.label=='Arquivo SQLite').set_value(str(db)).run(timeout=30)
        for position,a,b in zip(POSITIONS,BLUE,RED):
            next(s for s in app.selectbox if s.label=='Azul — '+position).set_value(a)
            next(s for s in app.selectbox if s.label=='Vermelho — '+position).set_value(b)
        return app.run(timeout=30)

    def test_shared_draft_independent_outputs_and_archived_gold(self):
        with tempfile.TemporaryDirectory() as d, patch.object(PortraitCache,'image',return_value=None):
            root=Path(d);db=gold_fixtures.GoldTests().database(root);before=db.read_bytes()
            app=self.open_app(root,db)
            next(b for b in app.button if b.label=='Analisar e registrar').click().run(timeout=30)
            self.assertFalse(app.exception);self.assertFalse(app.error)
            store=AnalysisHistory(root/'.mega_lol_workspace/analises.sqlite',db)
            saved=store.entries()[0]
            self.assertEqual(saved['result'],compare_drafts(db,BLUE,RED))
            self.assertEqual(saved['gold_result'],compare_gold15(db,BLUE,RED))
            self.assertEqual(next(m.value for m in app.metric if m.label=='Diferença estimada aos 15'),'+820 ouro')
            self.assertEqual(len(app.slider),0)
            self.assertFalse(any(x.label=='Como interpretar e limitações' for x in app.expander))
            # Winrate controls must not become gold parameters.
            next(n for n in app.number_input if n.label=='Confronto direto (%)').set_value(100)
            next(n for n in app.number_input if n.label=='Confronto indireto (%)').set_value(0)
            next(n for n in app.number_input if n.label=='Sinergia (%)').set_value(0)
            app.run()
            next(b for b in app.button if b.label=='Analisar e registrar').click().run(timeout=30)
            self.assertEqual(store.entries()[0]['gold_result'],saved['gold_result'])
            # A fresh session restores both snapshots, without recalculating.
            second=AppTest.from_file(str(root/'app_draft_sqlite.py')).run()
            next(t for t in second.text_input if t.label=='Arquivo SQLite').set_value(str(db)).run(timeout=30)
            self.assertEqual(next(m.value for m in second.metric if m.label=='Diferença estimada aos 15'),'+820 ouro')
            # Draft changes affect the shared input, never the displayed archive.
            next(b for b in second.button if b.label=='Carregar este draft para revisar').click().run()
            next(b for b in second.button if b.label=='⇄ Trocar lados').click().run()
            self.assertEqual(next(m.value for m in second.metric if m.label=='Diferença estimada aos 15'),'+820 ouro')
            next(b for b in second.button if b.label=='Analisar e registrar').click().run(timeout=30)
            self.assertEqual(next(m.value for m in second.metric if m.label=='Diferença estimada aos 15'),'-820 ouro')
            self.assertEqual(db.read_bytes(),before)

    def test_gold_failure_does_not_block_winrate(self):
        with tempfile.TemporaryDirectory() as d, patch.object(PortraitCache,'image',return_value=None), \
                patch('modelo_gold15_sqlite.compare_gold15',side_effect=ValueError('Synthetic GD failure')):
            root=Path(d);db=gold_fixtures.GoldTests().database(root)
            app=self.open_app(root,db)
            next(b for b in app.button if b.label=='Analisar e registrar').click().run(timeout=30)
            self.assertFalse(app.exception);self.assertFalse(app.error)
            self.assertEqual(app.metric[0].value,'60.00%')
            store=AnalysisHistory(root/'.mega_lol_workspace/analises.sqlite',db)
            saved=store.entries()[0]
            self.assertIsNone(saved['gold_result'])
            self.assertEqual(saved['gold_error'],'Synthetic GD failure')

    def test_winrate_failure_does_not_block_gold(self):
        with tempfile.TemporaryDirectory() as d, patch.object(PortraitCache,'image',return_value=None):
            root=Path(d);db=gold_fixtures.GoldTests().database(root)
            app=self.open_app(root,db)
            next(n for n in app.number_input if n.label=='Confronto direto (%)').set_value(100).run()
            next(b for b in app.button if b.label=='Analisar e registrar').click().run(timeout=30)
            self.assertFalse(app.exception)
            self.assertTrue(app.error)
            self.assertEqual(next(m.value for m in app.metric if m.label=='Diferença estimada aos 15'),'+820 ouro')

    def test_legacy_history_is_preserved_without_retroactive_gold(self):
        with tempfile.TemporaryDirectory() as d, patch.object(PortraitCache,'image',return_value=None):
            from datetime import datetime,timezone
            from modelo_draft_sqlite import explain_comparison
            root=Path(d);db=gold_fixtures.GoldTests().database(root)
            stat=db.stat();result=compare_drafts(db,BLUE,RED)
            old={'id':'legacy','name':'Registro anterior','created_at_utc':datetime.now(timezone.utc).isoformat(),
                 'result':result,'explanation':explain_comparison(result),'notes':'Manter','tags':[],
                 'settings':{'database':str(db),'fingerprint':[stat.st_mtime_ns,stat.st_size],'minimum_games':10}}
            store=AnalysisHistory(root/'.mega_lol_workspace/analises.sqlite',db);store.save(old)
            app=self.open_app(root,db)
            self.assertFalse(app.exception)
            self.assertTrue(any('ainda não contém' in x.value for x in app.info))
            self.assertEqual(store.entries()[0],old)

    def test_persistence_swap_duplicate_guard_and_history_filter(self):
        with tempfile.TemporaryDirectory() as d, patch.object(PortraitCache,'image',return_value=None):
            root=Path(d);db=root/'source.sqlite';import_directory(make_source(root),db)
            original=db.read_bytes()
            app_file=root/'app_draft_sqlite.py'
            app_file.write_text((Path(__file__).resolve().parents[1]/'app_draft_sqlite.py').read_text())
            app=AppTest.from_file(str(app_file)).run(timeout=30)
            next(t for t in app.text_input if t.label=='Arquivo SQLite').set_value(str(db)).run(timeout=30)
            for position,a,b in zip(POSITIONS,BLUE,RED):
                next(s for s in app.selectbox if s.label=='Azul — '+position).set_value(a)
                next(s for s in app.selectbox if s.label=='Vermelho — '+position).set_value(b)
            app.run(timeout=30)
            next(b for b in app.button if b.label=='Analisar e registrar').click().run(timeout=30)
            self.assertFalse(app.exception);self.assertFalse(app.error)
            self.assertEqual(app.metric[0].value,'60.00%')
            next(t for t in app.text_area if t.label=='Sua leitura / observações').set_value('Minha anotação')
            next(t for t in app.multiselect if t.label=='Tags').set_value(['Revisar'])
            next(b for b in app.button if b.label=='Registrar anotações').click().run(timeout=30)
            store=AnalysisHistory(root/'.mega_lol_workspace/analises.sqlite',db)
            self.assertEqual(store.entries()[0]['notes'],'Minha anotação')
            second=AppTest.from_file(str(app_file)).run(timeout=30)
            next(t for t in second.text_input if t.label=='Arquivo SQLite').set_value(str(db)).run(timeout=30)
            self.assertEqual(second.session_state['analyses'][0]['notes'],'Minha anotação')
            next(b for b in second.button if b.label=='Carregar este draft para revisar').click().run(timeout=30)
            next(b for b in second.button if b.label=='⇄ Trocar lados').click().run(timeout=30)
            self.assertEqual(next(s for s in second.selectbox if s.label=='Azul — TOP').value,RED[0])
            next(b for b in second.button if b.label=='Analisar e registrar').click().run(timeout=30)
            self.assertFalse(second.exception);self.assertEqual(len(store.entries()),2)
            next(s for s in second.selectbox if s.label=='Filtrar tag').set_value('Revisar').run(timeout=30)
            self.assertEqual(len(next(s for s in second.selectbox if s.label=='Análise salva').options),1)
            next(s for s in second.selectbox if s.label=='Azul — TOP').set_value(BLUE[0]).run(timeout=30)
            self.assertTrue(next(b for b in second.button if b.label=='Analisar e registrar').disabled)
            self.assertEqual(db.read_bytes(),original)
