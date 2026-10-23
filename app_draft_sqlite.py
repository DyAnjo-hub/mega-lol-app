"""Draft workspace. Source SQLite is read-only; history and portraits use a separate local workspace."""
import json
import html
from collections import Counter
from pathlib import Path
import sqlite3
from datetime import datetime, timezone
import uuid

import streamlit as st
from modelo_draft_sqlite import WEIGHTS, POSITIONS, MODEL_VERSION, name_key, catalog, compare_drafts, explain_comparison
from modelo_gold15_sqlite import MODEL_VERSION as GOLD_MODEL_VERSION, compare_gold15
from draft_workspace import AnalysisHistory, PortraitCache

LABELS = {'Direct_Matchup':'Confronto direto','Indirect_Matchup':'Confronto indireto','Ally_Synergy':'Sinergia'}
SIDES = {'blue':'Azul','red':'Vermelho','tie':'Equilíbrio'}
GOLD_SYNERGY_WEIGHT = .4
st.set_page_config(page_title='MEGA • Estúdio de drafts', layout='wide', initial_sidebar_state='expanded')
st.markdown('''<style>
.block-container {max-width:1320px; padding-top:2rem; padding-bottom:3rem;}
[data-testid="stMetric"] {border:1px solid #8494aa40; border-radius:14px; padding:1rem;}
[data-testid="stMetricValue"] {font-weight:750;}
[data-testid="stSidebar"] {border-right:1px solid #8494aa30;}
.stButton>button {border-radius:10px; font-weight:650;}
.mega-hero {background:linear-gradient(120deg,#0d1729,#1c3049);padding:28px 32px;border-radius:18px;color:#f4f7fc;margin-bottom:24px;}
.mega-hero h1 {color:#f4f7fc !important;font-size:2rem;margin:4px 0 8px;}
.mega-hero small {color:#d8b875;letter-spacing:.15em;font-weight:700;}
.mega-hero p {color:#becce0;margin:0;}
.portrait-fallback {width:48px;height:48px;border-radius:10px;background:#17283e;color:#c7d4e8;display:flex;align-items:center;justify-content:center;font-weight:700;margin-top:25px;}
.lane {text-align:center;color:#9c8b67;font-size:.75rem;letter-spacing:.08em;padding-top:40px;}
.component-card {border:1px solid #8294ad40;border-radius:14px;padding:18px;margin-bottom:12px;}
.component-card h4 {margin:0 0 12px;font-size:1rem;}
.component-line {display:flex;justify-content:space-between;margin:8px 0 4px;font-size:.85rem;}
.component-track {height:7px;background:#8294ad25;border-radius:7px;overflow:hidden;}
.component-blue {height:100%;background:#3b82f6;border-radius:7px;}
.component-red {height:100%;background:#ef4444;border-radius:7px;}
.compare-bar {display:flex;height:12px;border-radius:12px;overflow:hidden;margin:8px 0 18px;}
.compare-bar .blue {background:#3b82f6;}.compare-bar .red {background:#ef4444;}
</style>''',unsafe_allow_html=True)


@st.cache_data(show_spinner=False)
def available(database, run, fingerprint):
    return catalog(database, run)


@st.cache_data(show_spinner=False)
def calculate(database, blue, red, run, weights, minimum, fingerprint, model_version):
    return compare_drafts(database,list(blue),list(red),run_id=run,
                          weights=dict(weights),minimum_games=minimum)


@st.cache_data(show_spinner=False)
def calculate_gold(database, blue, red, run, fingerprint, model_version):
    return compare_gold15(database,list(blue),list(red),run_id=run,
                          minimum_games=1,synergy_weight=GOLD_SYNERGY_WEIGHT)


def render_gold(result, error=None):
    st.subheader('MEGA / GOLD 15 · azul menos vermelho')
    if result is None:
        st.info('Ouro indisponível: '+error if error else 'Este registro ainda não contém a análise de ouro. Carregue o draft e clique em Analisar e registrar.')
        return
    def gold(value):
        return 'Sem dados suficientes' if value is None else f'{value:+,.0f} ouro'
    st.caption('Azul: '+', '.join(result['drafts']['blue'])+' | Vermelho: '+', '.join(result['drafts']['red']))
    a,b,c = st.columns(3)
    a.metric('Diferença estimada aos 15',gold(result['total_gd15']))
    b.metric('Confrontos com dados suficientes',f"{result['covered_positions']}/5")
    c.metric('Referência: somente direto',gold(result['direct_total_gd15']))
    if result['total_gd15'] is None:
        st.warning('Sem total completo. Subtotal disponível: '+gold(result['partial_gd15']))
    st.dataframe([{'Posição':lane['position'],'Azul':lane['blue'],'Vermelho':lane['red'],
        'GD@15 direto':lane['direct_gd15'],
        'GD@15 parceria (comparativo)':lane.get('synergy',{}).get('gd15'),
        'GD@15 final (azul − vermelho)':lane['gd15'],'Jogos direto':lane['games'],
        'Jogos parceria azul':lane.get('synergy',{}).get('blue',{}).get('games'),
        'Jogos parceria vermelho':lane.get('synergy',{}).get('red',{}).get('games'),
        'Situação':{'available':'Disponível','missing':'Sem dados','insufficient_games':'Abaixo do mínimo'}[lane['status']]}
        for lane in result['lanes']],width='stretch',hide_index=True)


def signed(value):
    return '—' if value is None else f'{value:+.2f}'


def pair_label(row):
    connector = ' + ' if row['category'] == 'Ally_Synergy' else ' → '
    return row['first'] + connector + row['second']


def alert_text(alert):
    side = SIDES.get(alert.get('side'),'')
    category = LABELS.get(alert.get('category'),'')
    if alert['type'] == 'missing_pairs':
        return f"{side} / {category}: {alert['found']} de {alert['queried']} pares consultados têm dados. Nem todos os cruzamentos precisam existir nessa categoria."
    if alert['type'] == 'unavailable_component':
        return f'{side} / {category}: componente indisponível; pesos não foram redistribuídos.'
    relation = alert['relation']
    if alert['type'] == 'small_sample_influential_relation':
        return f"{pair_label(relation)} aparece entre as principais contribuições com apenas {relation['games']} Games agregados."
    return f"{pair_label(relation)} representa {relation['component_share']:.0%} dos Games do componente {LABELS[relation['category']]} do lado {SIDES[relation['side']]}."


def markdown_record(entry):
    result, explanation = entry['result'], entry['explanation']
    lines = [f"# {entry['name']}", f"Data UTC: {entry['created_at_utc']}",
             'Azul: '+', '.join(result['drafts']['blue']), 'Vermelho: '+', '.join(result['drafts']['red']),
             f"Run ID: {result['run_id']}", 'Patches: '+', '.join(result['patches_used']),
             f"Indicador: {result['relative_indicator']}",
             'Contribuições à diferença do indicador (p.p.; positivo favorece azul):']
    if result.get('direct_alignment'):
        lines += ['Confrontos diretos alinhados:']
        lines += [f"- {r['position']}: {r['blue']} × {r['red']}" for r in result['direct_alignment']]
    lines += [f"- {LABELS[c['category']]}: {signed(c['indicator_gap_contribution'])}" for c in explanation['components']]
    lines += ['Principais relações a favor do líder:']
    lines += [f"- {pair_label(r)} ({SIDES[r['side']]}): {signed(r['indicator_gap_contribution'])} p.p.; {r['games']} Games." for r in explanation['supporting_relations']]
    lines += ['Relações que puxaram para o outro lado:']
    lines += [f"- {pair_label(r)} ({SIDES[r['side']]}): {signed(r['indicator_gap_contribution'])} p.p.; {r['games']} Games." for r in explanation['opposing_relations']]
    lines += ['Alertas:']+[f'- {alert_text(a)}' for a in explanation['alerts']]
    lines += ['Anotações pessoais:',entry['notes'],explanation['method'],result['note']]
    gold_result = entry.get('gold_result')
    if gold_result:
        lines += ['GD@15 — análise independente',f"Versão: {gold_result['model_version']}",
                  f"Diferença azul − vermelho: {gold_result['total_gd15']} ouro",
                  f"Cobertura: {gold_result['covered_positions']}/5",f"Pesos do bot: {gold_result['bot_weights']}"]
        lines += [f"- {lane['position']}: {lane['blue']} × {lane['red']}: {lane['gd15']} ouro" for lane in gold_result['lanes']]
    elif entry.get('gold_error'):
        lines += ['GD@15 indisponível: '+entry['gold_error']]
    return '\n\n'.join(lines)


WORKSPACE = Path(__file__).resolve().parent / '.mega_lol_workspace'
portraits = PortraitCache(WORKSPACE / 'portraits')


def portrait(champion):
    image = portraits.image(champion)
    if image:
        st.image(image,width=48)
    else:
        initials = html.escape((champion or '—')[:2].upper())
        st.markdown(f'<div class="portrait-fallback">{initials}</div>',unsafe_allow_html=True)


def draft_strip(champions):
    for column, champion in zip(st.columns(5),champions):
        with column:
            portrait(champion)
            st.caption(champion)


def swap_sides():
    blue_values = [st.session_state.get('blue_'+position) for position in POSITIONS]
    red_values = [st.session_state.get('red_'+position) for position in POSITIONS]
    for position,a,b in zip(POSITIONS,blue_values,red_values):
        st.session_state['blue_'+position] = b
        st.session_state['red_'+position] = a


def load_draft(entry):
    for side in ('blue','red'):
        for position,champion in zip(POSITIONS,entry['result']['drafts'][side]):
            st.session_state[side+'_'+position] = champion if champion in options['champions'] else None
    st.session_state['draft_name'] = entry['name']+' — revisão'


st.markdown('<div class="mega-hero"><small>MEGA / DRAFT LAB</small><h1>Da composição à leitura do jogo.</h1><p>Monte os dois lados, entenda as contribuições e guarde suas análises.</p></div>',unsafe_allow_html=True)
with st.sidebar:
    st.header('Base e cálculo')
    database = st.text_input('Arquivo SQLite', value='mega_lol_s16.sqlite')
    run_input = st.text_input('Run ID (opcional para uma única execução)',value='')
    try:
        path = Path(database).resolve()
        stat = path.stat()
        fingerprint = (stat.st_mtime_ns,stat.st_size)
        options = available(str(path),run_input.strip() or None,fingerprint)
    except (OSError,ValueError,sqlite3.Error) as exc:
        st.info(f'Abra seu banco para começar: {exc}')
        st.stop()
    history_path = st.text_input('Arquivo do histórico pessoal',value=str(WORKSPACE / 'analises.sqlite'))
    try:
        history = AnalysisHistory(history_path,path)
        if 'history_initialized' not in st.session_state:
            stored_ids = {e['id'] for e in history.entries()}
            for old in st.session_state.get('analyses',[]):
                if old['id'] not in stored_ids:
                    old.setdefault('tags',[])
                    history.save(old)
            st.session_state['history_initialized'] = True
        st.session_state['analyses'] = history.entries()
    except (OSError,ValueError,sqlite3.Error) as exc:
        st.error(f'Não foi possível abrir o histórico: {exc}')
        st.stop()
    st.caption(f"{len(options['champions'])} campeões · {len(options['patches'])} patches agregados")
    st.caption('Análises e anotações salvas automaticamente em um banco separado da coleta.')
    with st.expander('Winrate: pesos e critérios'):
        direct = st.number_input('Confronto direto (%)',0,100,40)
        indirect = st.number_input('Confronto indireto (%)',0,100,30)
        synergy = st.number_input('Sinergia (%)',0,100,30)
        minimum = st.number_input('Mínimo da soma de Games por componente',min_value=1,value=10)
        large_gap = st.number_input('Destaque visual de disparidade (p.p.)',min_value=0.,value=10.,step=1.)
        st.caption('Limiares operacionais e visuais; não medem confiança estatística.')
    with st.expander('Origem dos dados'):
        st.write('Run ID:',options['run_id'])
        st.write('Patches:',', '.join(options['patches']))
        st.caption('SQLite somente leitura. Winrate e GD@15 são calculados separadamente; sem peso adicional por recência.')
weights = tuple(zip(WEIGHTS,(direct/100,indirect/100,synergy/100)))
name = st.text_input('Nome da análise (opcional)',placeholder='Ex.: pré-jogo / composição de teste',key='draft_name')
head_blue,head_swap,head_red = st.columns([5,2,5])
head_blue.subheader('🔵 Time azul')
head_swap.button('⇄ Trocar lados',on_click=swap_sides,width='stretch')
head_red.subheader('🔴 Time vermelho')
blue,red = [],[]
for position in POSITIONS:
    a,lane,b = st.columns([5,1,5])
    with a:
        image,selector = st.columns([1,6])
        current = st.session_state.get('blue_'+position)
        with image: portrait(current)
        with selector:
            blue.append(st.selectbox('Azul — '+position,options['champions'],index=None,placeholder='Buscar campeão',key='blue_'+position))
    with lane:
        st.markdown('<div class="lane">'+position+'</div>',unsafe_allow_html=True)
    with b:
        image,selector = st.columns([1,6])
        current = st.session_state.get('red_'+position)
        with image: portrait(current)
        with selector:
            red.append(st.selectbox('Vermelho — '+position,options['champions'],index=None,placeholder='Buscar campeão',key='red_'+position))
chosen = [c for c in [*blue,*red] if c]
counts = Counter(name_key(c) for c in chosen)
duplicates = sorted({c for c in chosen if counts[name_key(c)]>1})
if duplicates:
    st.warning('Campeão repetido: '+', '.join(duplicates)+'. Cada campeão só pode ocupar uma posição no draft.')
st.caption(f'{len(chosen)}/10 posições preenchidas · 5 confrontos diretos · 20 cruzamentos indiretos por lado · 10 pares de aliados')
submitted = st.button('Analisar e registrar',type='primary',width='stretch',disabled=len(chosen)!=10 or bool(duplicates))
if submitted:
    gold_result, gold_error = None, None
    try:
        with st.spinner('Calculando ouro aos 15…'):
            gold_result = calculate_gold(str(path),tuple(blue),tuple(red),options['run_id'],fingerprint,GOLD_MODEL_VERSION)
    except (ValueError,OSError,sqlite3.Error) as exc:
        gold_error = str(exc)
    try:
        if any(c is None for c in [*blue,*red]):
            raise ValueError('Preencha as cinco posições de cada time.')
        with st.spinner('Consultando as relações do draft…'):
            result = calculate(str(path),tuple(blue),tuple(red),options['run_id'],weights,int(minimum),fingerprint,MODEL_VERSION)
        entry = {'id':uuid.uuid4().hex,'name':name.strip() or f"Análise {len(st.session_state.analyses)+1}",
                 'created_at_utc':datetime.now(timezone.utc).isoformat(), 'result':result,
                 'gold_result':gold_result,'gold_error':gold_error,
                 'explanation':explain_comparison(result,float(large_gap)), 'notes':'', 'tags':[],
                 'settings':{'database':str(path),'fingerprint':fingerprint,'minimum_games':int(minimum)}}
        history.save(entry)
        st.session_state.analyses.insert(0,entry)
        st.session_state['selected_analysis'] = entry['id']
        st.session_state['history_search'] = ''
        st.session_state['history_tag'] = 'Todas'
    except (ValueError,sqlite3.Error) as exc:
        st.error(str(exc))
        render_gold(gold_result,gold_error)
if not st.session_state.analyses:
    st.info('Selecione cinco campeões por lado e clique em Analisar e registrar. O banco original não será alterado.')
    st.stop()
st.divider()
with st.expander(f"Histórico salvo — {len(st.session_state.analyses)} análises"):
    search = st.text_input('Buscar por nome ou campeão',key='history_search')
    filter_tag = st.selectbox('Filtrar tag',['Todas']+sorted({tag for e in st.session_state.analyses for tag in e.get('tags',[])}),key='history_tag')
filtered = [e for e in st.session_state.analyses if
            (not search or search.casefold() in (e['name']+' '+str(e['result']['drafts'])).casefold()) and
            (filter_tag=='Todas' or filter_tag in e.get('tags',[]))]
if not filtered:
    st.info('Nenhum registro corresponde aos filtros do histórico. Limpe a busca para ver as análises.')
    st.stop()
entries = {e['id']:e for e in filtered}
if st.session_state.get('selected_analysis') not in entries:
    st.session_state['selected_analysis'] = next(iter(entries))
selected = st.selectbox('Análise salva',list(entries),format_func=lambda key:entries[key]['name']+' · '+entries[key]['created_at_utc'][:16].replace('T',' ')+' UTC',key='selected_analysis')
entry = entries[selected]
result, explanation = entry['result'],entry['explanation']
if (result.get('model_version') != MODEL_VERSION or list(blue) != result['drafts']['blue'] or list(red) != result['drafts']['red'] or
        weights != tuple(result['weights'].items()) or str(path) != entry['settings']['database'] or
        options['run_id'] != result['run_id'] or int(minimum) != entry['settings']['minimum_games'] or
        float(large_gap) != explanation['large_gap_threshold'] or
        tuple(fingerprint) != tuple(entry['settings']['fingerprint'])):
    st.warning('Exibindo um registro anterior. As entradas atuais diferem desta análise; clique em Analisar e registrar para gerar outra.')
st.subheader(entry['name'])
st.caption(f"Registrado em {entry['created_at_utc']} · {len(result['patches_used'])} patches de origem")
preview_blue,preview_red = st.columns(2)
with preview_blue:
    st.caption('TIME AZUL REGISTRADO')
    draft_strip(result['drafts']['blue'])
with preview_red:
    st.caption('TIME VERMELHO REGISTRADO')
    draft_strip(result['drafts']['red'])
st.button('Carregar este draft para revisar',on_click=load_draft,args=(entry,))
if result.get('direct_alignment'):
    with st.expander('Conferir os cinco confrontos diretos',expanded=True):
        st.dataframe([{'Posição':row['position'],'Azul':row['blue'],'Vermelho':row['red']} for row in result['direct_alignment']],width='stretch',hide_index=True)
if result['relative_indicator'] is None:
    st.warning('Indicador final indisponível. Há componentes sem dados utilizáveis ou scores incompatíveis com a normalização.')
else:
    left,middle,right = st.columns([2,1,2])
    left.metric('Indicador azul',f"{result['relative_indicator']['blue']:.2f}%")
    middle.metric('Diferença',f"{abs(explanation['indicator_gap']):.2f} p.p.")
    right.metric('Indicador vermelho',f"{result['relative_indicator']['red']:.2f}%")
    st.markdown(f"<div class='compare-bar'><div class='blue' style='width:{result['relative_indicator']['blue']}%'></div><div class='red' style='width:{result['relative_indicator']['red']}%'></div></div>",unsafe_allow_html=True)
    if explanation['leader'] == 'tie':
        st.info('Os indicadores ficaram iguais.')
    else:
        label = 'Disparidade destacada' if explanation['large_gap'] else 'Leitura do cálculo'
        st.write(f"**{label}: lado {SIDES[explanation['leader']].lower()} à frente.**")
        direction = 1 if explanation['leader']=='blue' else -1
        favorable = [c for c in explanation['components'] if c['indicator_gap_contribution'] is not None and direction*c['indicator_gap_contribution']>0]
        if favorable:
            main = max(favorable,key=lambda c:abs(c['indicator_gap_contribution']))
            st.write(f"Principal contribuição a favor do líder: **{LABELS[main['category']]}**, com {abs(main['indicator_gap_contribution']):.2f} p.p. da diferença.")
for column,category in zip(st.columns(3),WEIGHTS):
    with column:
        blue_component = result['teams']['blue']['components'][category]
        red_component = result['teams']['red']['components'][category]
        blue_value,red_value = blue_component['score'],red_component['score']
        blue_text = 'Sem dados' if blue_value is None else f'{blue_value:.1f}'
        red_text = 'Sem dados' if red_value is None else f'{red_value:.1f}'
        st.markdown(f"""<div class="component-card"><h4>{LABELS[category]} · {result['weights'][category]:.0%}</h4>
          <div class="component-line"><span>Azul</span><b>{blue_text}</b></div>
          <div class="component-track"><div class="component-blue" style="width:{blue_value or 0}%"></div></div>
          <div class="component-line"><span>Vermelho</span><b>{red_text}</b></div>
          <div class="component-track"><div class="component-red" style="width:{red_value or 0}%"></div></div></div>""",unsafe_allow_html=True)
        st.caption(f"Pares com dados: azul {blue_component['found_pairs']}/{blue_component['queried_pairs']} · vermelho {red_component['found_pairs']}/{red_component['queried_pairs']}")
st.caption('Indicadores comparativos, não probabilidades calibradas. As amostras de relações podem compartilhar partidas.')
st.divider()
render_gold(entry.get('gold_result'),entry.get('gold_error'))
read_tab,evidence_tab,notes_tab,compare_tab = st.tabs(['Entender o resultado','Relações e cobertura','Anotações e exportação','Comparar análises'])
with read_tab:
    st.caption('Decomposição matemática do indicador. Não demonstra causas reais de vitória.')
    component_rows = [{'Componente':LABELS[c['category']], 'Peso':f"{c['weight']:.0%}",
                       'Score azul':c['blue_score'],'Score vermelho':c['red_score'],
                       'Contribuição à diferença (p.p.)':c['indicator_gap_contribution']} for c in explanation['components']]
    st.dataframe(component_rows,width='stretch',hide_index=True)
    chart_rows = [{'componente':row['Componente'],'contribuicao':row['Contribuição à diferença (p.p.)']}
                  for row in component_rows if row['Contribuição à diferença (p.p.)'] is not None]
    if chart_rows:
        st.vega_lite_chart(chart_rows, {
            'mark':{'type':'bar','cornerRadiusEnd':4},
            'encoding':{
                'y':{'field':'componente','type':'nominal','title':None},
                'x':{'field':'contribuicao','type':'quantitative','title':'Contribuição à diferença do indicador (p.p.)'},
                'color':{'condition':{'test':'datum.contribuicao >= 0','value':'#3b82f6'},'value':'#ef4444'},
                'tooltip':[{'field':'componente','title':'Componente'},
                           {'field':'contribuicao','title':'Contribuição (p.p.)','format':'+.2f'}]},
            'height':150}, width='stretch')
    st.caption('Sinal positivo puxa a diferença para o azul; negativo, para o vermelho. Quando o indicador está disponível, as contribuições dos componentes somam a diferença azul − vermelho.')
    a,b = st.columns(2)
    for column,key,title in [(a,'supporting_relations','Relações que mais favoreceram o líder'),(b,'opposing_relations','Relações que puxaram para o outro lado')]:
        with column:
            st.markdown('**'+title+'**')
            for relation in explanation[key]:
                st.write(f"{pair_label(relation)} · {SIDES[relation['side']]} / {LABELS[relation['category']]}")
                st.caption(f"Contribuição: {signed(relation['indicator_gap_contribution'])} p.p. · {relation['games']} Games agregados · taxa histórica {relation['winrate']:.1%}")
            if not explanation[key]:
                st.caption('Não há contribuição comparável para destacar.')
    if explanation['alerts']:
        with st.expander(f"Limitações desta leitura ({len(explanation['alerts'])})",expanded=False):
            for alert in explanation['alerts']:
                st.write('• '+alert_text(alert))
with evidence_tab:
    coverage = []
    for side,label in [('blue','Azul'),('red','Vermelho')]:
        for category,comp in result['teams'][side]['components'].items():
            coverage.append({'Time':label,'Componente':LABELS[category],
                             'Pares com dados':comp['found_pairs'],'Pares consultados':comp['queried_pairs'],
                             'Soma de Games das relações':comp['relation_games_sum']})
            with st.expander(label+' / '+LABELS[category]):
                st.dataframe(comp['details'],width='stretch',hide_index=True)
    st.dataframe(coverage,width='stretch',hide_index=True)
    st.caption('Games somados entre relações não representam partidas independentes. Pares consultados não são necessariamente pares que deveriam existir na categoria.')
with notes_tab:
    renamed = st.text_input('Nome do registro',value=entry['name'],key='rename_'+entry['id'])
    tags = st.multiselect('Tags',['Pré-jogo','Teste','Revisar','Concluído'],default=entry.get('tags',[]),key='tags_'+entry['id'])
    note = st.text_area('Sua leitura / observações',value=entry['notes'],key='note_'+entry['id'],
                        placeholder='Ex.: quero revisar a amostra do confronto direto antes de confiar no placar.')
    if st.button('Registrar anotações'):
        entry['notes'] = note
        entry['tags'] = tags
        entry['name'] = renamed.strip() or entry['name']
        history.save(entry)
        st.rerun()
    st.info('Histórico permanente salvo no arquivo pessoal, separado da coleta. Clique em Registrar anotações para salvar nome, tags e observações. Os downloads servem como cópias adicionais.')
    st.caption('Arquivo do histórico: '+str(history.path))
    c1,c2 = st.columns(2)
    c1.download_button('Baixar análise JSON',json.dumps(entry,ensure_ascii=False,indent=2),
                       file_name=f"draft_{entry['id'][:8]}.json",mime='application/json')
    c2.download_button('Baixar relatório legível',markdown_record(entry),
                       file_name=f"draft_{entry['id'][:8]}.md",mime='text/markdown')
    st.download_button('Baixar histórico completo',json.dumps(st.session_state.analyses,ensure_ascii=False,indent=2),
                       file_name='historico_drafts.json',mime='application/json')
with compare_tab:
    all_entries = {e['id']:e for e in st.session_state.analyses}
    if len(all_entries)<2:
        st.info('Registre outra análise para comparar os drafts lado a lado.')
    else:
        first_column,second_column = st.columns(2)
        first_id = first_column.selectbox('Análise A',list(all_entries),format_func=lambda k:all_entries[k]['name'],key='compare_a')
        second_options = [k for k in all_entries if k != first_id]
        second_id = second_column.selectbox('Análise B',second_options,format_func=lambda k:all_entries[k]['name'],key='compare_b')
        selected_entries = [all_entries[first_id],all_entries[second_id]]
        comparison=[]
        for column,snapshot in zip((first_column,second_column),selected_entries):
            with column:
                st.write(snapshot['name'])
                st.caption('Azul: '+', '.join(snapshot['result']['drafts']['blue']))
                draft_strip(snapshot['result']['drafts']['blue'])
                st.caption('Vermelho: '+', '.join(snapshot['result']['drafts']['red']))
                draft_strip(snapshot['result']['drafts']['red'])
            relative = snapshot['result']['relative_indicator']
            comparison.append({'Análise':snapshot['name'],'Azul':relative['blue'] if relative else None,
                'Vermelho':relative['red'] if relative else None,'Diferença azul − vermelho':snapshot['explanation']['indicator_gap'],
                'GD@15 azul − vermelho':(snapshot.get('gold_result') or {}).get('total_gd15'),
                'Patches':len(snapshot['result']['patches_used']),'Tags':', '.join(snapshot.get('tags',[]))})
        st.dataframe(comparison,width='stretch',hide_index=True)
        a,b = (snapshot['result'] for snapshot in selected_entries)
        gold_a,gold_b = (snapshot.get('gold_result') or {} for snapshot in selected_entries)
        gold_changed = any(gold_a.get(k)!=gold_b.get(k) for k in ('model_version','bot_weights','minimum_games'))
        if gold_changed or any(a.get(k)!=b.get(k) for k in ('model_version','run_id','weights','patches_used')) or json.dumps(selected_entries[0]['settings'],sort_keys=True)!=json.dumps(selected_entries[1]['settings'],sort_keys=True):
            st.warning('Esses registros usam configurações, versão ou base diferentes. A comparação não isola o efeito da troca de campeões.')
        st.caption('Comparação descritiva de análises salvas; não comprova qual modelo prevê melhor.')
st.caption(result['note'])
