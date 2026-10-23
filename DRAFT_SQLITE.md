# Comparador de drafts SQLite — versão paralela

Arquivos novos: `modelo_draft_sqlite.py` (consulta/cálculo) e `app_draft_sqlite.py`
(interface). O modelo/app antigos, merge, scraper, planilhas e banco não são
alterados. O SQLite é aberto em `mode=ro`. Não é necessária nova importação.

## Executar no computador do usuário

Baixe os dois arquivos e coloque-os junto do banco em `D:\Importacao_s16`.
No PowerShell:

```powershell
cd D:\Importacao_s16
& "$env:LOCALAPPDATA\Programs\Python\Python313\python.exe" -m pip install streamlit
& "$env:LOCALAPPDATA\Programs\Python\Python313\python.exe" -m streamlit run .\app_draft_sqlite.py
```

Escolha `mega_lol_s16.sqlite`, o patch e cinco campeões distintos por lado.
Não há ordem de posições. Run ID fica vazio se o banco contém apenas uma execução;
caso contrário, informe-o explicitamente. O browser é local, sem gol.gg ou login.

Também é possível executar o modelo sem interface e sem pacotes externos:

```powershell
& "$env:LOCALAPPDATA\Programs\Python\Python313\python.exe" .\modelo_draft_sqlite.py --database .\mega_lol_s16.sqlite --patch 16.10 --blue "Shen, Vi, Syndra, Smolder, Nautilus" --red "Vayne, Aatrox, Ahri, Sivir, Lulu"
```

## Preparação da base: sem modificar dados preservados

Roles diferentes são agregadas pelo mesmo par **direcionado**, categoria, patch,
Run ID e contexto. A média é `SUM(Games * Winrate) / SUM(Games)`. Exemplo sintético:
10 jogos a 49% e 3 jogos a 55% produzem 13 Games agregados e 50,3846%.
A tabela de origem permanece intacta; não se calcula uma contagem de vitórias exatas.

Dados nulos/sem Games não produzem observações utilizáveis; winrate zero com Games
positivo é válido. Repetições do mesmo par/role/contexto são rejeitadas em vez de
somadas automaticamente. Categorias e direções opostas não são misturadas.
O carregamento recusa contextos diferentes dentro de uma mesma categoria/patch.
O contexto provém dos metadados preservados: isso não verifica retroativamente
filtros que eram desconhecidos na coleta. Não há fusão com a planilha antiga.

## Cálculo

Para cada lado, são consultados os 25 cruzamentos contra os cinco adversários em
Direct_Matchup e, separadamente, os 25 em Indirect_Matchup. Isso não exige função
nem pressupõe que todos os cruzamentos terão dados nessas duas categorias.
Cada componente usa a média ponderada por Games das relações encontradas.

Na sinergia, consultam-se os 10 pares não ordenados de aliados. Se há A→B e B→A,
escolhe-se a direção utilizável com mais Games; empate usa ordem canônica das
chaves. As direções não são somadas e a ordem de entrada não altera o resultado.

Pesos iniciais configuráveis: 40% direta, 30% indireta e 30% sinergia. O score de
cada lado é a soma ponderada dos componentes. O indicador relativo é
`score_lado / (score_azul + score_vermelho) * 100`. Isso é apenas normalização:
**não equivale a uma probabilidade de vitória calibrada**. Os pesos são uma
hipótese experimental, ainda não validada contra resultados de partidas.

Cada componente exige por padrão soma de Games >=10. Esse é um limiar operacional,
não uma garantia de confiança, e não exige 10 jogos em cada par. A soma pode contar
partidas presentes em várias relações; não representa jogos independentes.

Sem componente utilizável com peso positivo, o score final fica indisponível:
não se inventa 50% nem se redistribuem pesos automaticamente. A interface ainda
mostra os componentes disponíveis. Pares ausentes são excluídos da média daquele
componente e exibidos explicitamente. O resultado pode existir com cobertura parcial;
confira a cobertura antes de interpretar o indicador. Os denominadores 25/25/10
são pares consultados, não uma prova de que todos deveriam existir no site.

A normalização de nomes resolve espaços, apóstrofos e pontuação comuns, preservando
os nomes originais no banco. Não inventa equivalências entre nomes completamente
diferentes. O seletor usa o catálogo da execução para evitar nomes desconhecidos.

GD@15, CSD@15, XPD@15 e KDA não entram no cálculo. Não há ponderação por recência;
a primeira versão usa somente o patch escolhido. A combinação de últimos cinco
patches e sua validação ficam para uma próxima etapa.

## Verificação

```sh
python -m unittest discover -s tests -p test_modelo_draft_sqlite.py -v
```

Testes sintéticos cobrem média por roles, direção, pesos, ausência de dados,
invariância à ordem, troca dos times, sinergia sem dupla contagem, rejeição de
contextos misturados, isolamento de snapshots/patches e independência do GD@15.
Também foi feito teste com a cópia real importada, incluindo execução da interface
pelo AppTest do Streamlit. São testes funcionais, não avaliação da capacidade
preditiva em partidas futuras.
