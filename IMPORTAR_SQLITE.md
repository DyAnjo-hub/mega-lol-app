# Importar os originais gol.gg no SQLite

`importar_golgg_sqlite.py` é um programa separado: não muda scraper, modelo, app,
merge, Excel ou originais. Não precisa instalar SQLite nem pacotes Python. Usa
apenas a biblioteca padrão do Python 3.10 ou superior (compatível com Python 3.13).
Não acessa o site, navegador, clipboard ou rede.

## Preparar

Guarde o ZIP e o Excel como backup. Extraia uma cópia dos originais. A pasta de
entrada deve conter diretamente os pares `<Capture_ID>.json` e `.txt`; o script
não procura recursivamente nem extrai ZIPs. Arquivos de origem nunca são alterados.

Baixe `importar_golgg_sqlite.py` deste repositório e salve em:

```text
D:\Importacao_s16\importar_golgg_sqlite.py
```

Para o caminho informado pelo usuário, a entrada é:

```text
D:\Importacao_s16\originais_completa_s16_01_final\originais_completa_s16_01
```

## Primeiro teste: dez capturas em um banco separado

No PowerShell:

```powershell
cd D:\Importacao_s16
& "$env:LOCALAPPDATA\Programs\Python\Python313\python.exe" .\importar_golgg_sqlite.py --source ".\originais_completa_s16_01_final\originais_completa_s16_01" --database ".\teste_importacao.sqlite" --run-id 4e5cbd2e773449f08888afad07a61a54 --limit 10 --expect-captures 10
```

O limite se aplica a capturas validadas, incluindo vazias; não são dez linhas.
A seleção é por nome do JSON, sem preferência por campeão/patch. Confira o relatório
com `status: committed`. O número de registros depende das dez capturas selecionadas.

## Importação completa em um arquivo novo

```powershell
cd D:\Importacao_s16
& "$env:LOCALAPPDATA\Programs\Python\Python313\python.exe" .\importar_golgg_sqlite.py --source ".\originais_completa_s16_01_final\originais_completa_s16_01" --database ".\mega_lol_s16.sqlite" --run-id 4e5cbd2e773449f08888afad07a61a54 --expect-captures 9861 --expect-records 235358
```

Não use o nome do banco de teste como destino da importação definitiva. O programa
não sobrescreve bancos existentes. Para outra tentativa em um nome novo, altere
`--database`. Para reexecutar sobre um banco deste importador, acrescente `--append`:
Captures idênticas são conferidas e ignoradas, sem reinserir registros. Um Capture ID
com bytes/metadados diferentes é erro. Um novo Capture ID com o mesmo contexto
solicitado/verificado, campeão/categoria e Run ID também é rejeitado como possível
importação duplicada. Linhas repetidas dentro da tabela original são preservadas.

Para futuras coletas, o Run ID separa snapshots; não há soma/agrupamento automático.
O mesmo campeão/patch em outra execução pode ser armazenado separadamente. Nas
consultas futuras, selecione explicitamente o run desejado para não somar snapshots.

## O que é conferido

- Identidade do arquivo, checksum SHA-256 do texto e presença do par JSON/TXT.
- Horário UTC explícito, campeão selecionado, categoria e consistência dos filtros
  solicitado/verificado quando ambos estão presentes.
- Cabeçalhos dinâmicos, Games inteiro não negativo, Winrate em 0–1, estatísticas
  finitas com sinal. Percentuais explícitos e frações são aceitos; `55` sem `%`
  não é interpretado como `55%`.
- Ausências (`''`, `-`, `—`, `NA`, `N/A`) viram NULL, nunca zero. Valores malformados
  abortam a transação. A grafia original continua disponível.
- Contagem de registros de cada captura e totais exigidos pelo comando.
- Integridade SQLite e chaves estrangeiras antes do commit.

Uma importação é uma única transação: falha/CTRL+C reverte as inserções dessa
execução. Em erro tratado, um banco novo incompleto é removido; um banco existente
é mantido sem as novas inserções. Um encerramento forçado pode deixar um banco vazio
ou journal de recuperação: preserve os originais e use outro nome para uma nova
tentativa, em vez de apagar arquivos de banco/journal manualmente.

JSONs de diagnóstico não são dados de captura e aparecem como `diagnostics_ignored`.
Capturas pending/failed não são importadas e aparecem como `unvalidated_ignored`.
Os arquivos continuam intactos na pasta original. O programa não tenta reparar,
inventar ou preencher os dados ausentes.

## Tabelas e proveniência

- **capturas**: Capture ID, Run ID, campeão selecionado, categoria, contexto,
  horários, checksums, texto original e seus bytes, metadados originais e seus
  bytes. Capturas vazias são preservadas como capturas com `row_count=0`.
- **registros**: índice da linha de origem, campeão relacionado original e
  normalizado, role de origem, Games/Winrate/CSD/GD/XPD/KDA e JSON de todas as
  colunas originais, inclusive extras. Chave: `(capture_id, record_index)`.
- **dados_coletados**: view que une as duas tabelas para facilitar consultas.

Season/Split verificados ficam em `season_verified`/`split_verified`. Valores
extraídos dos parâmetros preservados da URL ficam em `season_url`/`split_url`:
não representam confirmação de filtros ativos. `page_role_verified`,
`table_role_filter_verified` e `source_role` são campos diferentes. Não se atribui
significado não confirmado à role da linha ou à perspectiva de CSD/GD/XPD/KDA.
Campos estruturados desconhecidos são NULL; textos JSON/TXT originais continuam
exatos. Os bytes preservam também quebras de linha e espaços não separáveis.
Não há coluna de vitórias exatas derivada de winrate arredondado.

`PRAGMA application_id` e `user_version=1` identificam o banco. O modo --append
recusa um banco de outro programa ou schema incompatível.

## Conferir e consultar

O JSON `mega_lol_s16.import-<id>.json` é criado ao lado do banco e o resumo aparece
no terminal. Para esta coleta completa, o resultado esperado é:

| Conteúdo | Total |
| --- | ---: |
| Capturas | 9.861 |
| Capturas vazias | 2.060 |
| Direct_Matchup | 25.063 registros |
| Indirect_Matchup | 106.598 registros |
| Ally_Synergy | 103.697 registros |
| Total de registros | 235.358 |

Opcionalmente abra o `.sqlite` com DB Browser for SQLite (https://sqlitebrowser.org/).
Não é necessário esse aplicativo para importar. Exemplos de consultas:

```sql
SELECT COUNT(*) FROM capturas;
SELECT COUNT(*) FROM registros;
SELECT category, COUNT(*) FROM dados_coletados GROUP BY category;
SELECT patch_verified, COUNT(*) FROM capturas GROUP BY patch_verified;
SELECT * FROM dados_coletados
WHERE selected_champion = 'Nocturne' AND patch_verified = '16.20'
LIMIT 20;
```

Não interprete COUNT de relações como número de partidas independentes. Os mesmos
jogos podem participar de várias relações e as amostras entre tabelas podem se
sobrepor. O banco não calibra probabilidades nem altera o indicador existente.

## Testes

```sh
python -m unittest discover -s tests -p test_importar_sqlite.py -v
```

Fixtures unitárias são sintéticas. Incluem preservação de bytes/colunas extras,
NULLs, percentuais, sinais, categorias, linhas repetidas, idempotência, rollback,
checksum, limites, contagens esperadas, recusa de banco alheio e CLI sem site-packages.
A importação completa também foi exercitada offline sobre o ZIP real fornecido.
