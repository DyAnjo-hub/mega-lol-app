import math
from typing import List

import streamlit as st
from modelo_winrate_mega import calcular_chance_vitoria

# ==========================
# CONFIG
# ==========================

EDGE_MIN = 8.0      # edge mínimo p.p. para entrar
KELLY_CAP = 0.05    # teto de Kelly (5% da banca)


# ==========================
# FUNÇÕES AUX
# ==========================

def parse_float(s: str):
    """Converte string com vírgula/ponto para float. Retorna None se der erro."""
    if s is None:
        return None
    s = str(s).strip().replace(",", ".")
    if not s:
        return None
    try:
        return float(s)
    except Exception:
        return None


def parse_champs(raw: str) -> List[str]:
    """Transforma 'Aatrox, Ahri, Jinx, ...' em lista limpa."""
    return [c.strip() for c in raw.split(",") if c.strip()]


def implied_prob(odd: float):
    """Prob implícita em %."""
    if odd is None or odd <= 1.0:
        return None
    return 100.0 / odd


def kelly_fraction(odd: float, p_model_pct: float):
    """Kelly cheio (fração da banca)."""
    if odd is None or odd <= 1.0:
        return 0.0
    p = p_model_pct / 100.0
    if p <= 0.0 or p >= 1.0:
        return 0.0
    b = odd - 1.0
    return (odd * p - 1.0) / b


def odd_minima_para_entrar(p_model_pct: float, edge_min: float):
    """
    Calcula a odd mínima para essa probabilidade do modelo
    atender a regra: edge > edge_min e Kelly > 0.

    Se p_model <= edge_min, não existe odd que faça edge > edge_min (retorna None).
    """
    if p_model_pct <= 0:
        return None

    # Kelly > 0  -> aposta +EV  -> odd > 100 / p_model
    odd_kelly_min = 100.0 / p_model_pct

    # Edge > edge_min:
    # p_model - 100/odd > edge_min  ->  odd > 100 / (p_model - edge_min)
    if p_model_pct <= edge_min:
        return None  # nunca bate edge_min
    odd_edge_min = 100.0 / (p_model_pct - edge_min)

    # precisa satisfazer as duas coisas ao mesmo tempo
    return max(odd_kelly_min, odd_edge_min)


# ==========================
# UI STREAMLIT
# ==========================

st.set_page_config(page_title="MEGA LoL EV", layout="centered")

st.title("MEGA LoL – Decisor de aposta (draft + odds)")

st.caption(
    f"Regra: edge > {EDGE_MIN} p.p. e Kelly > 0, com teto de {KELLY_CAP*100:.1f}% da banca."
)

# Inputs principais
banca_str = st.text_input("Banca atual (R$)", value="2000")

col1, col2 = st.columns(2)
with col1:
    champs_azul_raw = st.text_input(
        "Time AZUL (5 champs, separados por vírgula)",
        value="Shen, Vi, Syndra, Smolder, Nautilus",
    )
    odd_azul_str = st.text_input("Odd time AZUL", value="2,30")

with col2:
    champs_vermelho_raw = st.text_input(
        "Time VERMELHO (5 champs, separados por vírgula)",
        value="Vayne, Aatrox, Ahri, Sivir, Lulu",
    )
    odd_vermelho_str = st.text_input("Odd time VERMELHO", value="1,55")

botao = st.button("Calcular aposta")

if botao:
    # Parse básico
    banca = parse_float(banca_str)
    odd_azul = parse_float(odd_azul_str)
    odd_vermelho = parse_float(odd_vermelho_str)

    champs_azul = parse_champs(champs_azul_raw)
    champs_vermelho = parse_champs(champs_vermelho_raw)

    # Validações
    if banca is None or banca <= 0:
        st.error("Banca inválida.")
    elif odd_azul is None or odd_vermelho is None:
        st.error("Odd inválida. Use algo como 2,30 ou 1.8.")
    elif len(champs_azul) != 5 or len(champs_vermelho) != 5:
        st.error("Cada time precisa ter exatamente 5 campeões.")
    else:
        # Calcula p_model com o MEGA
        try:
            p_azul, p_vermelho = calcular_chance_vitoria(
                champs_azul, champs_vermelho, verbose=False
            )
        except Exception as e:
            st.error(f"Erro no modelo: {e}")
            st.stop()

        st.subheader("Probabilidades do modelo")
        c1, c2 = st.columns(2)
        with c1:
            st.metric("p_model AZUL", f"{p_azul:.2f}%")
        with c2:
            st.metric("p_model VERMELHO", f"{p_vermelho:.2f}%")

        # Odd mínima pra cada lado pela sua regra
        odd_min_azul = odd_minima_para_entrar(p_azul, EDGE_MIN)
        odd_min_vermelho = odd_minima_para_entrar(p_vermelho, EDGE_MIN)

        st.subheader("Odd mínima para valer a pena (pela regra)")

        c3, c4 = st.columns(2)
        with c3:
            if odd_min_azul is None:
                st.metric("Odd mínima AZUL", "—")
            else:
                st.metric("Odd mínima AZUL", f"{odd_min_azul:.2f}")
        with c4:
            if odd_min_vermelho is None:
                st.metric("Odd mínima VERMELHO", "—")
            else:
                st.metric("Odd mínima VERMELHO", f"{odd_min_vermelho:.2f}")

        # Decide lado pelo p_model
        if p_azul >= p_vermelho:
            lado = "AZUL"
            p_model = p_azul
            odd_escolhida = odd_azul
        else:
            lado = "VERMELHO"
            p_model = p_vermelho
            odd_escolhida = odd_vermelho

        p_house = implied_prob(odd_escolhida)
        edge = None if p_house is None else (p_model - p_house)
        kelly_full = kelly_fraction(odd_escolhida, p_model)
        kelly_cap = min(kelly_full, KELLY_CAP)
        if kelly_cap < 0:
            kelly_cap = 0.0

        st.subheader("Resumo da aposta sugerida")
        c5, c6, c7 = st.columns(3)
        with c5:
            st.metric("Lado recomendado", lado)
        with c6:
            st.metric("Odd usada", f"{odd_escolhida:.2f}")
        with c7:
            st.metric(
                "p_house (impl.)",
                f"{p_house:.2f}%" if p_house is not None else "-",
            )

        c8, c9, c10 = st.columns(3)
        with c8:
            st.metric("Edge (p.p.)", f"{edge:.2f}" if edge is not None else "-")
        with c9:
            st.metric("Kelly cheio", f"{kelly_full*100:.2f}%")
        with c10:
            st.metric("Kelly capado", f"{kelly_cap*100:.2f}%")

        # Regra de entrada
        entra = edge is not None and edge > EDGE_MIN and kelly_full > 0

        # Mensagem final
        if entra and kelly_cap > 0:
            stake = banca * kelly_cap
            st.success(
                f"✅ ENTRA\n\n"
                f"Lado: **{lado}** @ **{odd_escolhida:.2f}**\n\n"
                f"Stake sugerida: **R$ {stake:.2f}** "
                f"({kelly_cap*100:.2f}% da banca)."
            )
        else:
            msg = "❌ Sem entrada pela regra (edge ou Kelly não batem).\n\n"
            if odd_min_azul is not None or odd_min_vermelho is not None:
                msg += "Para valer a pena, pelas probabilidades atuais:\n"
                if odd_min_azul is not None:
                    msg += f"- AZUL começaria a valer a partir de ~**{odd_min_azul:.2f}**\n"
                if odd_min_vermelho is not None:
                    msg += f"- VERMELHO começaria a valer a partir de ~**{odd_min_vermelho:.2f}**\n"
            st.warning(msg)
            st.write("Stake sugerida: **R$ 0,00**.")
