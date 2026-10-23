"""Synthetic local SQLite and mocked portraits; UI tests never contact the site."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from streamlit.testing.v1 import AppTest
from draft_workspace import AnalysisHistory, PortraitCache
from modelo_draft_sqlite import POSITIONS
from importar_golgg_sqlite import import_directory
from test_modelo_draft_sqlite import make_source, BLUE, RED


class WorkspaceUITests(unittest.TestCase):
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
