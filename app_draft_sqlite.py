"""Draft workspace. Source SQLite is read-only; notes stay in the browser session."""
import json
from pathlib import Path
import sqlite3
from datetime import datetime, timezone
import uuid

import streamlit as st
from modelo_draft_sqlite import WEIGHTS, POSITIONS, MODEL_VERSION, catalog, compare_drafts, explain_comparison

LABELS = {'Direct_Matchup':'Confronto direto','Indirect_Matchup':'Confronto indireto','Ally_Synergy':'Sinergia'}
SIDES = {'blue':'Azul','red':'Vermelho','tie':'Equilíbrio'}
st.set_page_config(page_title='MEGA • Estúdio de drafts', layout='wide', initial_sidebar_state='expanded')
st.markdown('''<style>
.block-container {max-width:1250px; padding-top:2rem; padding-bottom:3rem;}
[data-testid="stMetric"] {border:1px solid #8494aa40; border-radius:14px; padding:1rem;}
[data-testid="stMetricValue"] {font-weight:750;}
[data-testid="stSidebar"] {border-right:1px solid #8494aa30;}
.stButton>button {border-radius:10px; font-weight:650;}
</style>''',unsafe_allow_html=True)


@st.cache_data(show_spinner=False)
def available(database, run, fingerprint):
    return catalog(database, run)


@st.cache_data(show_spinner=False)
def calculate(database, blue, red, run, weights, minimum, fingerprint, model_version):
    return compare_drafts(database,list(blue),list(red),run_id=run,
                          weights=dict(weights),minimum_games=minimum)


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
    return '\n\n'.join(lines)


st.caption('MEGA LoL / ANÁLISE DE DRAFT')
st.title('Entenda o placar. Registre sua leitura.')
st.write('Compare dez campeões com o histórico completo e acompanhe o que mais pesou no cálculo.')
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
    st.caption(f"{len(options['champions'])} campeões · {len(options['patches'])} patches agregados")
    with st.expander('Pesos e critérios'):
        direct = st.number_input('Confronto direto (%)',0,100,40)
        indirect = st.number_input('Confronto indireto (%)',0,100,30)
        synergy = st.number_input('Sinergia (%)',0,100,30)
        minimum = st.number_input('Mínimo da soma de Games por componente',min_value=1,value=10)
        large_gap = st.number_input('Destaque visual de disparidade (p.p.)',min_value=0.,value=10.,step=1.)
        st.caption('Limiares operacionais e visuais; não medem confiança estatística.')
    with st.expander('Origem dos dados'):
        st.write('Run ID:',options['run_id'])
        st.write('Patches:',', '.join(options['patches']))
        st.caption('SQLite somente leitura. Gold/GD@15 e peso adicional por recência não são usados.')
weights = tuple(zip(WEIGHTS,(direct/100,indirect/100,synergy/100)))
st.session_state.setdefault('analyses',[])
with st.form('draft_form'):
    name = st.text_input('Nome da análise (opcional)',placeholder='Ex.: teste de composição / jogo 1')
    left,right = st.columns(2)
    with left:
        st.subheader('🔵 Time azul')
        blue = [st.selectbox('Azul — '+position,options['champions'],index=None,placeholder='Escolha o campeão',key='blue_'+position) for position in POSITIONS]
    with right:
        st.subheader('🔴 Time vermelho')
        red = [st.selectbox('Vermelho — '+position,options['champions'],index=None,placeholder='Escolha o campeão',key='red_'+position) for position in POSITIONS]
    st.caption('Direta: TOP × TOP, JUNGLE × JUNGLE, MID × MID, ADC × ADC e SUPPORT × SUPPORT. Indireta: os outros 20 cruzamentos. Sinergia: os dez pares de aliados.')
    submitted = st.form_submit_button('Analisar e registrar',type='primary',width='stretch')
if submitted:
    try:
        if any(c is None for c in [*blue,*red]):
            raise ValueError('Preencha as cinco posições de cada time.')
        with st.spinner('Consultando as relações do draft…'):
            result = calculate(str(path),tuple(blue),tuple(red),options['run_id'],weights,int(minimum),fingerprint,MODEL_VERSION)
        entry = {'id':uuid.uuid4().hex,'name':name.strip() or f"Análise {len(st.session_state.analyses)+1}",
                 'created_at_utc':datetime.now(timezone.utc).isoformat(), 'result':result,
                 'explanation':explain_comparison(result,float(large_gap)), 'notes':'',
                 'settings':{'database':str(path),'fingerprint':fingerprint,'minimum_games':int(minimum)}}
        st.session_state.analyses.append(entry)
        st.session_state['selected_analysis'] = entry['id']
    except (ValueError,sqlite3.Error) as exc:
        st.error(str(exc))
if not st.session_state.analyses:
    st.info('Selecione cinco campeões por lado e clique em Analisar e registrar. O banco original não será alterado.')
    st.stop()
st.divider()
entries = {e['id']:e for e in st.session_state.analyses}
selected = st.selectbox('Registro desta sessão',list(entries),format_func=lambda key:entries[key]['name'],key='selected_analysis')
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
st.write('**Azul:** '+', '.join(result['drafts']['blue']))
st.write('**Vermelho:** '+', '.join(result['drafts']['red']))
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
    if explanation['leader'] == 'tie':
        st.info('Os indicadores ficaram iguais.')
    else:
        label = 'Disparidade destacada' if explanation['large_gap'] else 'Leitura do cálculo'
        st.write(f"**{label}: lado {SIDES[explanation['leader']].lower()} à frente.**")
read_tab,evidence_tab,notes_tab = st.tabs(['Por que deu esse resultado?','Relações e cobertura','Anotações e exportação'])
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
        with st.expander(f"Limitações desta leitura ({len(explanation['alerts'])})",expanded=True):
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
    note = st.text_area('Sua leitura / observações',value=entry['notes'],key='note_'+entry['id'],
                        placeholder='Ex.: quero revisar a amostra do confronto direto antes de confiar no placar.')
    if st.button('Registrar anotações'):
        entry['notes'] = note
        st.success('Anotações atualizadas no registro desta sessão.')
    st.info('Os registros ficam nesta sessão do app. Baixe os arquivos para guardá-los antes de fechar ou reiniciar. Alterações no texto só entram na exportação após Registrar anotações.')
    c1,c2 = st.columns(2)
    c1.download_button('Baixar análise JSON',json.dumps(entry,ensure_ascii=False,indent=2),
                       file_name=f"draft_{entry['id'][:8]}.json",mime='application/json')
    c2.download_button('Baixar relatório legível',markdown_record(entry),
                       file_name=f"draft_{entry['id'][:8]}.md",mime='text/markdown')
    st.download_button('Baixar todos os registros da sessão',json.dumps(st.session_state.analyses,ensure_ascii=False,indent=2),
                       file_name='historico_drafts.json',mime='application/json')
st.caption(result['note'])
