"""Parallel Streamlit app; the old app and model remain unchanged."""
import sqlite3
import json
import streamlit as st
from modelo_draft_sqlite import WEIGHTS, catalog, compare_drafts

st.set_page_config(page_title='MEGA LoL — Draft SQLite',layout='wide')
st.title('Comparativo de drafts — SQLite')
st.caption('Indicador experimental de relações históricas; não é probabilidade calibrada de vitória.')
database=st.text_input('Arquivo SQLite',value='mega_lol_s16.sqlite')
run_input=st.text_input('Run ID (deixe vazio se houver apenas uma execução)',value='')
try:
    options=catalog(database,run_input.strip() or None)
except (ValueError,sqlite3.Error) as exc:
    st.info(f'Selecione um banco válido: {exc}')
    st.stop()
patch=st.selectbox('Patch (somente este patch será usado)',options['patches'])
st.caption('Sem ordem de posição. Roles diferentes do mesmo par são agregadas por Games dentro de cada categoria e patch.')
left,right=st.columns(2)
with left:
    blue=st.multiselect('Time azul — cinco campeões',options['champions'],max_selections=5)
with right:
    red=st.multiselect('Time vermelho — cinco campeões',options['champions'],max_selections=5)
with st.expander('Pesos experimentais'):
    direct=st.number_input('Direct Matchup (%)',min_value=0,max_value=100,value=40)
    indirect=st.number_input('Indirect Matchup (%)',min_value=0,max_value=100,value=30)
    synergy=st.number_input('Good with (%)',min_value=0,max_value=100,value=30)
    minimum=st.number_input('Mínimo da soma de Games das relações por componente',min_value=1,value=10)
st.caption('O mínimo é uma regra operacional, não um limite validado de confiança. Gold/GD@15 e recência não entram no cálculo.')
if st.button('Comparar drafts',type='primary'):
    try:
        result=compare_drafts(database,blue,red,patch=patch,run_id=options['run_id'],minimum_games=int(minimum),
                              weights=dict(zip(WEIGHTS,(direct/100,indirect/100,synergy/100))))
    except (ValueError,sqlite3.Error) as exc:
        st.error(str(exc));st.stop()
    if result['relative_indicator'] is None:
        st.warning('Indicador final indisponível: falta componente utilizável ou os scores não permitem comparação. Não foi preenchido com 50%.')
    else:
        c1,c2=st.columns(2)
        c1.metric('Indicador relativo azul',f"{result['relative_indicator']['blue']:.2f}%")
        c2.metric('Indicador relativo vermelho',f"{result['relative_indicator']['red']:.2f}%")
    if any(c['missing_pairs'] for side in result['teams'].values() for c in side['components'].values()):
        st.warning('Há relações ausentes. O indicador resume apenas as relações encontradas; consulte a cobertura abaixo.')
    summary=[]
    for side,label in [('blue','Azul'),('red','Vermelho')]:
        for category,component in result['teams'][side]['components'].items():
            summary.append({'Time':label,'Categoria':category,'Score':component['score'],
                            'Pares encontrados':component['found_pairs'],'Pares consultados':component['queried_pairs'],
                            'Soma de Games das relações':component['relation_games_sum']})
            with st.expander(f'{label} — {category}: relações utilizadas e ausentes'):
                st.dataframe(component['details'],use_container_width=True)
    st.subheader('Componentes e cobertura')
    st.dataframe(summary,use_container_width=True)
    st.info(result['note'])
    st.download_button('Baixar detalhamento JSON',data=json.dumps(result,ensure_ascii=False,indent=2),
                       file_name='comparativo_draft.json',mime='application/json')
