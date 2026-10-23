"""Separate Streamlit app for the historical early-game gold indicator."""
import json
from pathlib import Path
import sqlite3

import streamlit as st

from modelo_draft_sqlite import POSITIONS, catalog, connect, name_key
from modelo_gold15_sqlite import MODEL_VERSION, compare_gold15

st.set_page_config(page_title='MEGA · GOLD 15', page_icon='🪙', layout='wide')
st.markdown('''<style>
.stApp {background: #101a29;}
.gold-hero {padding:24px;border:1px solid #b49b56;border-radius:14px;
background:linear-gradient(110deg,#172c43,#292b22);margin-bottom:20px;}
.gold-hero h1 {color:#ecd38c;margin:0;} .gold-hero p {color:#c6d2de;}
</style><div class="gold-hero"><h1>MEGA / GOLD 15</h1>
<p>Diferença histórica de ouro aos 15 · confrontos e parceria ADC/suporte</p></div>''', unsafe_allow_html=True)


@st.cache_data(show_spinner='Calculando confrontos…')
def calculate(path, stamp, blue, red, run, minimum, synergy_weight, version):
    return compare_gold15(path, blue, red, run_id=run, minimum_games=minimum, synergy_weight=synergy_weight)


def gold(value):
    return 'Sem dados suficientes' if value is None else f'{value:+,.0f} ouro'


with st.sidebar:
    st.header('Base de dados')
    database = st.text_input('Arquivo SQLite', str(Path(__file__).with_name('mega_lol_s16.sqlite')))
    minimum = st.number_input('Mínimo de jogos por confronto', min_value=1, value=1, step=1)
    synergy_weight = .4
    st.caption('Todos os patches individuais reunidos. Banco aberto somente para leitura.')
try:
    path = Path(database).expanduser().resolve()
    stamp = (path.stat().st_mtime_ns, path.stat().st_size)
    # A multi-run database requires explicit choice, never automatic snapshot pooling.
    con = connect(path)
    try:
        runs = [r[0] for r in con.execute('SELECT DISTINCT run_id FROM capturas ORDER BY run_id')]
    finally:
        con.close()
    if not runs:
        raise ValueError('Banco sem execuções.')
    run = st.sidebar.selectbox('Run ID', runs)
    metadata = catalog(path, run)
except (OSError, ValueError, sqlite3.Error) as exc:
    st.info(f'Informe um SQLite criado pelo importador gol.gg. {exc}')
    st.stop()

champions = metadata['champions']
blue_default = ['Ambessa','Skarner','Ryze','Lucian','Milio']
red_default = ['Gnar','Wukong','Annie','Kalista','Renata Glasc']
st.caption('Ordem: TOP, JUNGLE, MID, ADC, SUPPORT. Positivo favorece o azul; negativo favorece o vermelho.')
blue, red = [], []
for i, position in enumerate(POSITIONS):
    left, center, right = st.columns([5,2,5])
    def default_index(name, fallback):
        return champions.index(name) if name in champions else min(fallback, len(champions)-1)
    blue.append(left.selectbox('Azul — '+position, champions, index=default_index(blue_default[i],i), key='gold_blue_'+position))
    center.markdown(f'<p style="text-align:center;padding-top:30px;white-space:nowrap">{position}</p>', unsafe_allow_html=True)
    red.append(right.selectbox('Vermelho — '+position, champions, index=default_index(red_default[i],i+5), key='gold_red_'+position))
unique = len({name_key(c) for c in blue+red}) == 10
if not unique:
    st.warning('Selecione dez campeões distintos.')
if st.button('Calcular GD@15', type='primary', disabled=not unique):
    try:
        st.session_state['gold_result'] = calculate(str(path), stamp, tuple(blue), tuple(red), run, int(minimum), synergy_weight, MODEL_VERSION)
        st.session_state['gold_inputs'] = (str(path),stamp,blue,red,run,minimum,synergy_weight)
    except (ValueError, OSError, sqlite3.Error) as exc:
        st.error(str(exc))

result = st.session_state.get('gold_result')
if result:
    if st.session_state.get('gold_inputs') != (str(path),stamp,blue,red,run,minimum,synergy_weight):
        st.warning('O resultado abaixo pertence ao draft/contexto anterior. Clique em Calcular GD@15 para atualizar.')
    st.subheader('Resultado · azul menos vermelho')
    st.caption('Azul: '+', '.join(result['drafts']['blue'])+' | Vermelho: '+', '.join(result['drafts']['red']))
    a,b,c = st.columns(3)
    a.metric('Diferença estimada aos 15', gold(result['total_gd15']))
    b.metric('Confrontos com dados suficientes', f"{result['covered_positions']}/5")
    c.metric('Referência: somente direto', gold(result['direct_total_gd15']))
    if result['total_gd15'] is None:
        st.warning('Sem total completo. Subtotal dos confrontos disponíveis: '+gold(result['partial_gd15']))
    rows = [{'Posição':lane['position'],'Azul':lane['blue'],'Vermelho':lane['red'],
             'GD@15 direto':lane['direct_gd15'],
             'GD@15 parceria (comparativo)':lane.get('synergy',{}).get('gd15'),
             'GD@15 final (azul − vermelho)':lane['gd15'],'Jogos direto':lane['games'],
             'Jogos parceria azul':lane.get('synergy',{}).get('blue',{}).get('games'),
             'Jogos parceria vermelho':lane.get('synergy',{}).get('red',{}).get('games'),
             'Situação':{'available':'Disponível','missing':'Sem dados','insufficient_games':'Abaixo do mínimo'}[lane['status']]}
            for lane in result['lanes']]
    st.dataframe(rows, hide_index=True, width='stretch')
    st.download_button('Baixar análise JSON', json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False),
                       file_name='analise_gold15.json',mime='application/json')
