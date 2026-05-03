from typing import List, Tuple

import streamlit as st

from modelo_winrate_mega import calcular_chance_vitoria


def parse_champs(raw: str) -> List[str]:
    """Transforma 'Aatrox, Ahri, Jinx, ...' em lista limpa."""
    return [champ.strip() for champ in raw.split(",") if champ.strip()]


def classificar_vantagem(delta: float) -> Tuple[str, str]:
    """Classifica a diferenca entre os times em uma leitura simples."""
    if delta < 2.0:
        return "Equilibrado", "Draft muito proximo. A leitura pede cautela."
    if delta < 5.0:
        return "Leve vantagem", "Existe inclinacao, mas ainda sem dominio claro."
    if delta < 8.0:
        return "Vantagem relevante", "O modelo enxerga um lado mais confortavel."
    return "Forte vantagem", "A diferenca de poder esta bem marcada pelo modelo."


def formatar_lista(champs: List[str]) -> str:
    return " / ".join(champs)


st.set_page_config(page_title="MEGA LoL - Radar de Draft", layout="wide")

st.markdown(
    """
    <style>
        .block-container {
            max-width: 1120px;
            padding-top: 2rem;
            padding-bottom: 2.5rem;
        }

        .mega-title {
            font-size: 2.35rem;
            font-weight: 800;
            letter-spacing: 0;
            margin-bottom: 0.25rem;
        }

        .mega-subtitle {
            color: #9ca3af;
            font-size: 1rem;
            margin-bottom: 1.4rem;
        }

        .panel {
            border: 1px solid rgba(148, 163, 184, 0.22);
            border-radius: 8px;
            padding: 1.05rem 1.15rem;
            background: rgba(17, 24, 39, 0.58);
        }

        .side-label {
            color: #cbd5e1;
            font-size: 0.84rem;
            font-weight: 700;
            letter-spacing: 0.05em;
            text-transform: uppercase;
            margin-bottom: 0.35rem;
        }

        .winner-card {
            border: 1px solid rgba(34, 197, 94, 0.34);
            border-radius: 8px;
            padding: 1rem 1.1rem;
            background: rgba(20, 83, 45, 0.23);
        }

        .winner-kicker {
            color: #86efac;
            font-size: 0.78rem;
            font-weight: 800;
            letter-spacing: 0.08em;
            text-transform: uppercase;
        }

        .winner-name {
            font-size: 2rem;
            font-weight: 850;
            line-height: 1.15;
            margin-top: 0.2rem;
        }

        .winner-note {
            color: #d1fae5;
            font-size: 0.95rem;
            margin-top: 0.4rem;
        }

        .draft-list {
            color: #d1d5db;
            font-size: 0.95rem;
            line-height: 1.45;
            margin-top: 0.4rem;
        }

        div[data-testid="stMetric"] {
            border: 1px solid rgba(148, 163, 184, 0.18);
            border-radius: 8px;
            padding: 0.85rem 0.95rem;
            background: rgba(15, 23, 42, 0.5);
        }

        div[data-testid="stMetricLabel"] {
            color: #cbd5e1;
        }

        div[data-testid="stMetricValue"] {
            font-size: 1.75rem;
        }

        .stButton > button {
            width: 100%;
            border-radius: 8px;
            min-height: 2.8rem;
            font-weight: 800;
        }
    </style>
    """,
    unsafe_allow_html=True,
)

st.markdown('<div class="mega-title">MEGA LoL - Radar de forca do draft</div>', unsafe_allow_html=True)
st.markdown(
    '<div class="mega-subtitle">Indicador comparativo entre composicoes. Sem odds, sem Kelly, sem edge: apenas leitura de poder entre os campeoes.</div>',
    unsafe_allow_html=True,
)

with st.container():
    col_azul, col_vermelho = st.columns(2, gap="large")

    with col_azul:
        st.markdown('<div class="panel">', unsafe_allow_html=True)
        st.markdown('<div class="side-label">Time azul</div>', unsafe_allow_html=True)
        champs_azul_raw = st.text_input(
            "Campeoes do time azul",
            value="Shen, Vi, Syndra, Smolder, Nautilus",
            label_visibility="collapsed",
            placeholder="Ex: Aurora, Pantheon, Sylas, Miss Fortune, Gragas",
        )
        st.markdown("</div>", unsafe_allow_html=True)

    with col_vermelho:
        st.markdown('<div class="panel">', unsafe_allow_html=True)
        st.markdown('<div class="side-label">Time vermelho</div>', unsafe_allow_html=True)
        champs_vermelho_raw = st.text_input(
            "Campeoes do time vermelho",
            value="Vayne, Aatrox, Ahri, Sivir, Lulu",
            label_visibility="collapsed",
            placeholder="Ex: Sion, Xin Zhao, LeBlanc, Varus, Alistar",
        )
        st.markdown("</div>", unsafe_allow_html=True)

calcular = st.button("Analisar poder do draft", type="primary")

if calcular:
    champs_azul = parse_champs(champs_azul_raw)
    champs_vermelho = parse_champs(champs_vermelho_raw)

    if len(champs_azul) != 5 or len(champs_vermelho) != 5:
        st.error("Cada time precisa ter exatamente 5 campeoes separados por virgula.")
        st.stop()

    try:
        p_azul, p_vermelho = calcular_chance_vitoria(
            champs_azul, champs_vermelho, verbose=False
        )
    except Exception as exc:
        st.error(f"Erro no modelo: {exc}")
        st.stop()

    lado_forte = "AZUL" if p_azul >= p_vermelho else "VERMELHO"
    prob_forte = max(p_azul, p_vermelho)
    prob_fraco = min(p_azul, p_vermelho)
    delta = prob_forte - prob_fraco
    leitura, descricao = classificar_vantagem(delta)

    st.divider()

    top_left, top_right = st.columns([1.1, 1], gap="large")
    with top_left:
        st.markdown(
            f"""
            <div class="winner-card">
                <div class="winner-kicker">lado mais forte no indicador</div>
                <div class="winner-name">{lado_forte}</div>
                <div class="winner-note">{leitura}. {descricao}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    with top_right:
        m1, m2 = st.columns(2)
        with m1:
            st.metric("Diferenca", f"{delta:.2f} p.p.")
        with m2:
            st.metric("Forca do lado lider", f"{prob_forte:.2f}%")

    st.subheader("Placar do modelo")
    score_azul, score_vermelho = st.columns(2, gap="large")
    with score_azul:
        st.metric("AZUL", f"{p_azul:.2f}%")
        st.progress(int(round(p_azul)))
        st.markdown(
            f'<div class="draft-list">{formatar_lista(champs_azul)}</div>',
            unsafe_allow_html=True,
        )

    with score_vermelho:
        st.metric("VERMELHO", f"{p_vermelho:.2f}%")
        st.progress(int(round(p_vermelho)))
        st.markdown(
            f'<div class="draft-list">{formatar_lista(champs_vermelho)}</div>',
            unsafe_allow_html=True,
        )

    st.subheader("Leitura operacional")
    l1, l2, l3 = st.columns(3)
    with l1:
        st.metric("Estado do confronto", leitura)
    with l2:
        st.metric("Time pressionado", "VERMELHO" if lado_forte == "AZUL" else "AZUL")
    with l3:
        st.metric("Perfil de uso", "Stake fixa")

    st.info(
        "Use o painel como indicador de poder do draft. A decisao final pode considerar contexto externo, "
        "patch, lado do mapa, prioridade de lanes, substituicoes e qualidade recente dos times."
    )
else:
    st.info("Preencha os dois drafts e clique em analisar para gerar o placar de poder.")
