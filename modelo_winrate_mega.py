import pandas as pd
import os

# ================================
# Carregar base de winrate
# ================================

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ARQ_DADOS = os.path.join(BASE_DIR, "dados_mega_merged.xlsx")

winrate_vs = pd.read_excel(ARQ_DADOS, sheet_name="Winrate_vs")
winrate_with = pd.read_excel(ARQ_DADOS, sheet_name="Winrate_with")


# ================================
# Funções auxiliares
# ================================

def limpar_numero(x):
    """
    Converte números da planilha para float.
    Aceita:
    - 0.44
    - '0.44'
    - '8,886.00'
    - '55%'
    """
    if pd.isna(x):
        return 0.0
    if isinstance(x, (int, float)):
        return float(x)
    s = str(x)
    s = s.replace(",", "")  # tira vírgula de milhar
    s = s.replace("%", "")
    try:
        return float(s)
    except Exception:
        return 0.0


def normalizar_nome(nome):
    if pd.isna(nome):
        return None
    return (
        str(nome)
        .strip()
        .lower()
        .replace(" ", "")
        .replace("'", "")
    )


# ================================
# Preparar tabelas (VS / WITH)
# ================================

def preparar_tabela(df):
    """
    Constrói dicionário:
      (campeao, champion) -> (jogos, vitorias)

    Para Winrate_vs: champion = inimigo
    Para Winrate_with: champion = aliado
    """
    df = df.copy()

    # padroniza nomes das colunas
    df.columns = df.columns.str.strip().str.lower()

    obrigatorias = ["campeao", "champion", "games", "winrate"]
    faltando = [c for c in obrigatorias if c not in df.columns]
    if faltando:
        raise ValueError(
            f"Faltam colunas {faltando}. Colunas atuais: {list(df.columns)}"
        )

    df["campeao"] = df["campeao"].apply(normalizar_nome)
    df["champion"] = df["champion"].apply(normalizar_nome)
    df["games"] = df["games"].apply(limpar_numero)
    df["winrate"] = df["winrate"].apply(limpar_numero)

    # limpa linhas zoada
    df = df[
        (df["games"] > 0)
        & df["campeao"].notna()
        & df["champion"].notna()
    ]

    registros = {}
    for _, row in df.iterrows():
        chave = (row["campeao"], row["champion"])
        jogos = float(row["games"])
        # winrate vem em fração (0.x). Se estiver em %, ajuste sua planilha.
        wins = float(row["winrate"]) * jogos

        j_ant, w_ant = registros.get(chave, (0.0, 0.0))
        registros[chave] = (j_ant + jogos, w_ant + wins)

    return registros


# monta os dicionários uma vez só
dict_vs = preparar_tabela(winrate_vs)
dict_with = preparar_tabela(winrate_with)

MIN_JOGOS_PARA_CONFIAR = 10


# ================================
# Cálculos principais
# ================================

def calcular_winrate_vs(time_a, time_b):
    """
    time_a vs time_b -> média de winrate do time_a
    usando (campeao, champion) da aba Winrate_vs.
    """
    total_p = 0.0
    total_w = 0.0

    for champ_a in time_a:
        a = normalizar_nome(champ_a)
        for champ_b in time_b:
            b = normalizar_nome(champ_b)
            chave = (a, b)
            if chave in dict_vs:
                jogos, wins = dict_vs[chave]
                total_p += jogos
                total_w += wins

    if total_p < MIN_JOGOS_PARA_CONFIAR:
        return 50.0

    return (total_w / total_p) * 100.0


def calcular_winrate_with(time):
    """
    time (lista de 5 champs) -> média de sinergia "with"
    usando (campeao, champion) da aba Winrate_with.
    """
    total_p = 0.0
    total_w = 0.0

    n = len(time)
    for i in range(n):
        for j in range(i + 1, n):
            a = normalizar_nome(time[i])
            b = normalizar_nome(time[j])

            chave1 = (a, b)
            chave2 = (b, a)

            if chave1 in dict_with:
                jogos, wins = dict_with[chave1]
            elif chave2 in dict_with:
                jogos, wins = dict_with[chave2]
            else:
                continue

            total_p += jogos
            total_w += wins

    if total_p < MIN_JOGOS_PARA_CONFIAR:
        return 50.0

    return (total_w / total_p) * 100.0


def calcular_chance_vitoria(time_azul, time_vermelho, verbose=True):
    """
    Retorna (chance_azul, chance_vermelho) em %.
    time_azul e time_vermelho: listas de 5 campeões (strings).
    """

    # VS
    azul_vs = calcular_winrate_vs(time_azul, time_vermelho)
    vermelho_vs = calcular_winrate_vs(time_vermelho, time_azul)

    # WITH
    azul_with = calcular_winrate_with(time_azul)
    vermelho_with = calcular_winrate_with(time_vermelho)

    score_azul = (azul_vs + azul_with) / 2.0
    score_vermelho = (vermelho_vs + vermelho_with) / 2.0

    total = score_azul + score_vermelho
    if total <= 0:
        chance_azul = 50.0
        chance_vermelho = 50.0
    else:
        chance_azul = round((score_azul / total) * 100.0, 2)
        chance_vermelho = round((score_vermelho / total) * 100.0, 2)

    if verbose:
        print("\n==== RESULTADO FINAL ====")
        print(f"Time Azul: {chance_azul}%")
        print(f"Time Vermelho: {chance_vermelho}%")

    return chance_azul, chance_vermelho


# ================================
# Exemplo de uso interativo
# ================================

if __name__ == "__main__":
    print("Teste rápido do modelo MEGA.")
    print("Digite os 5 campeões de cada time separados por vírgula.\n")

    entrada_azul = input("Time AZUL: ")
    entrada_vermelho = input("Time VERMELHO: ")

    time_azul = [c.strip() for c in entrada_azul.split(",") if c.strip()]
    time_vermelho = [c.strip() for c in entrada_vermelho.split(",") if c.strip()]

    if len(time_azul) != 5 or len(time_vermelho) != 5:
        print("Erro: cada time precisa ter exatamente 5 campeões.")
    else:
        calcular_chance_vitoria(time_azul, time_vermelho)
