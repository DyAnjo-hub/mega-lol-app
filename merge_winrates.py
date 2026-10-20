import pandas as pd
import os

# Caminhos dos arquivos
base_dir = os.path.dirname(os.path.abspath(__file__))
dados_mega_path = os.path.join(base_dir, "dados_mega_merged.xlsx")
golgg_path = os.path.join(base_dir, "golgg_champion_synergy.xlsx")
output_path = os.path.join(base_dir, "dados_mega_merged_updated.xlsx")

def merge_winrate_data(base_df, new_df):
    """
    Mescla dados de winrate, somando games e calculando winrate ponderada.
    Mantém todas as colunas do base_df.
    """
    def normalize_names(df):
        df = df.copy()
        for col in ['Campeao', 'Champion']:
            if col in df.columns:
                df[col] = df[col].astype(str).str.strip().str.upper()
        return df

    base_df_norm = normalize_names(base_df)
    new_df_norm = normalize_names(new_df)

    # Selecionar apenas as colunas essenciais para merge
    essential_cols = ['Campeao', 'Champion', 'Games', 'Winrate']
    base_essential = base_df_norm[essential_cols].copy()
    new_essential = new_df_norm[essential_cols].copy()

    def calc_weighted_winrate(group):
        total_games = group['Games'].sum()
        if total_games > 0:
            return (group['Winrate'] * group['Games']).sum() / total_games
        return 0

    # Combinar base e new
    combined = pd.concat([base_essential, new_essential], ignore_index=True)

    # Agrupar e calcular
    final_winrate = combined.groupby(['Campeao', 'Champion']).apply(calc_weighted_winrate).reset_index(name='Winrate')
    final_games = combined.groupby(['Campeao', 'Champion'])['Games'].sum().reset_index(name='Games')
    final_essential = final_winrate.merge(final_games, on=['Campeao', 'Champion'])

    # Manter todas as colunas do base_df, preenchendo com valores do base ou padrão
    # Para pares que existem no base, usar os valores do base, para novos, usar padrão
    result = final_essential.copy()
    for col in base_df.columns:
        if col not in essential_cols:
            # Para colunas extras, tentar pegar do base_df se o par existir, senão usar 0 ou NaN
            result[col] = result.apply(lambda row: base_df[(base_df['Campeao'] == row['Campeao']) & (base_df['Champion'] == row['Champion'])][col].iloc[0] if ((base_df['Campeao'] == row['Campeao']) & (base_df['Champion'] == row['Champion'])).any() else (0 if pd.api.types.is_numeric_dtype(base_df[col]) else pd.NA), axis=1)

    return result[base_df.columns.tolist()]  # Retornar na ordem das colunas do base

def main():
    print("Iniciando merge...")
    # Carregar dados base
    print("Carregando base_vs...")
    base_vs = pd.read_excel(dados_mega_path, sheet_name='Winrate_vs')
    print(f"base_vs shape: {base_vs.shape}")
    print("Carregando base_with...")
    base_with = pd.read_excel(dados_mega_path, sheet_name='Winrate_with')
    print(f"base_with shape: {base_with.shape}")

    # Carregar dados novos
    print("Carregando new_vs...")
    new_vs = pd.read_excel(golgg_path, sheet_name='Winrate_vs')
    print(f"new_vs shape: {new_vs.shape}")
    print("Carregando new_with...")
    new_with = pd.read_excel(golgg_path, sheet_name='Winrate_with')
    print(f"new_with shape: {new_with.shape}")

    # Ajustar colunas para new_vs: Campeao = Champion, Champion = Opponent
    new_vs = new_vs.rename(columns={'Champion': 'Campeao', 'Opponent': 'Champion'})[['Campeao', 'Champion', 'Games', 'Winrate']]

    # Ajustar colunas para new_with: Campeao = Opponent, Champion = Champion
    new_with = new_with.rename(columns={'Opponent': 'Campeao'})[['Campeao', 'Champion', 'Games', 'Winrate']]

    # Normalizar nomes dos dados novos antes de mesclar
    new_vs['Campeao'] = new_vs['Campeao'].astype(str).str.strip().str.upper()
    new_vs['Champion'] = new_vs['Champion'].astype(str).str.strip().str.upper()
    new_with['Campeao'] = new_with['Campeao'].astype(str).str.strip().str.upper()
    new_with['Champion'] = new_with['Champion'].astype(str).str.strip().str.upper()

    # Mesclar VS
    print("Mesclando VS...")
    merged_vs = merge_winrate_data(base_vs, new_vs)
    print(f"merged_vs shape: {merged_vs.shape}")

    # Mesclar WITH
    print("Mesclando WITH...")
    merged_with = merge_winrate_data(base_with, new_with)
    print(f"merged_with shape: {merged_with.shape}")

    # Salvar em novo arquivo
    print("Salvando...")
    with pd.ExcelWriter(output_path, engine='openpyxl') as writer:
        merged_vs.to_excel(writer, sheet_name='Winrate_vs', index=False)
        merged_with.to_excel(writer, sheet_name='Winrate_with', index=False)

    print(f"Dados mesclados salvos em {output_path}")

if __name__ == '__main__':
    main()
