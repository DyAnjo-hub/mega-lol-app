# Comparador de drafts SQLite — versão paralela

Arquivos: `modelo_draft_sqlite.py` (consulta/cálculo), `app_draft_sqlite.py`
(interface) e `draft_workspace.py` (histórico e retratos em cache). O modelo/app antigos, merge, scraper, planilhas e banco não são
alterados. O SQLite é aberto em `mode=ro`. Não é necessária nova importação.

## Executar no computador do usuário

Baixe os três arquivos e coloque-os junto do banco em `D:\Importacao_s16`.
No PowerShell:

```powershell
cd D:\Importacao_s16
& "$env:LOCALAPPDATA\Programs\Python\Python313\python.exe" -m pip install --upgrade streamlit
& "$env:LOCALAPPDATA\Programs\Python\Python313\python.exe" -m streamlit run .\app_draft_sqlite.py
```

Escolha `mega_lol_s16.sqlite`, cinco campeões distintos por lado. Todos os patches disponíveis são agregados automaticamente.
A ordem é TOP, JUNGLE, MID, ADC e SUPPORT nos dois times. Run ID fica vazio se o banco contém apenas uma execução;
caso contrário, informe-o explicitamente. O browser é local, sem gol.gg ou login.

Também é possível executar o modelo sem interface e sem pacotes externos:

```powershell
& "$env:LOCALAPPDATA\Programs\Python\Python313\python.exe" .\modelo_draft_sqlite.py --database .\mega_lol_s16.sqlite --blue "Shen, Vi, Syndra, Smolder, Nautilus" --red "Vayne, Aatrox, Ahri, Sivir, Lulu"
```

## Preparação da base: sem modificar dados preservados

Roles diferentes são agregadas pelo mesmo par **direcionado**, categoria,
Run ID e contexto, reunindo os patches individuais disponíveis. A média é `SUM(Games * Winrate) / SUM(Games)`. Exemplo sintético:
10 jogos a 49% e 3 jogos a 55% produzem 13 Games agregados e 50,3846%. O mesmo cálculo se aplica às contribuições de patches diferentes, sem média simples entre percentuais.
A tabela de origem permanece intacta; não se calcula uma contagem de vitórias exatas.

Dados nulos/sem Games não produzem observações utilizáveis; winrate zero com Games
positivo é válido. Repetições do mesmo par/role/contexto são rejeitadas em vez de
somadas automaticamente. Categorias e direções opostas não são misturadas.
O carregamento recusa contextos diferentes dentro da mesma categoria, inclusive entre patches. Uma linha do mesmo par/role em patches diferentes é válida; repetição dentro do mesmo patch continua sendo rejeitada.
O contexto provém dos metadados preservados: isso não verifica retroativamente
filtros que eram desconhecidos na coleta. Não há fusão com a planilha antiga.

## Cálculo

Para cada lado, Direct_Matchup consulta apenas os cinco pares alinhados pela
ordem informada (TOP×TOP, JUNGLE×JUNGLE, MID×MID, ADC×ADC e SUPPORT×SUPPORT).
Indirect_Matchup consulta os outros 20 cruzamentos, excluindo os rivais alinhados.
As posições vêm da entrada do usuário; a role de origem das linhas não é
reinterpretada nem filtrada. A agregação de roles por par/patch permanece.
A interface oferece cinco seletores por lado e mostra os confrontos antes dos resultados.
Cada componente usa a média ponderada por Games das relações encontradas.

Na sinergia, consultam-se os 10 pares não ordenados de aliados. Se há A→B e B→A,
escolhe-se, em cada patch, a direção utilizável com mais Games; empate usa ordem
canônica das chaves. Depois, as contribuições dos patches são agregadas. As direções
opostas do mesmo patch não são somadas e a ordem de entrada não altera o resultado.
Isso permite usar um patch com A→B disponível e outro com apenas B→A disponível.

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
confira a cobertura antes de interpretar o indicador. Os denominadores 5/20/10
são pares consultados, não uma prova de que todos deveriam existir no site.

A normalização de nomes resolve espaços, apóstrofos e pontuação comuns, preservando
os nomes originais no banco. Não inventa equivalências entre nomes completamente
diferentes. O seletor usa o catálogo da execução para evitar nomes desconhecidos.

GD@15, CSD@15, XPD@15 e KDA não entram no cálculo. Não há ponderação por recência;
todos os patches individuais da execução entram com peso proporcional aos Games
das relações. Um peso adicional para os últimos cinco patches fica para depois.
O resultado inclui patches_used e patch_sources em cada relação, com Games,
winrate e direção utilizada por patch. A interface não exige escolher patch.
O argumento CLI --patch continua apenas como opção explícita de auditoria; se
omitido, o cálculo usa o histórico completo. Registros de patch desconhecido ou
ALL agregado não são somados com patches individuais. O SQL original permanece
separado por patch; a união só existe na camada de análise em memória.

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


## Explicações e registro de análises

A nova interface reorganiza o trabalho em seleção do draft, resumo do resultado,
explicação, evidências e anotações. A barra lateral guarda a conexão e os critérios.
Um gráfico de barras mostra as contribuições dos componentes à diferença azul −
vermelho. Azul/positivo favorece o azul; vermelho/negativo favorece o vermelho.

A diferença dos scores é decomposta exatamente por categoria:
`peso * (score_azul - score_vermelho)`. Para expressar as contribuições na escala
do indicador relativo, multiplica-se por `100 / (score_azul + score_vermelho)`.
Dentro do componente, a contribuição de cada relação usa seu peso por Games e
uma referência algébrica de 50%. Não se preenchem relações ausentes com 50%.
Essa decomposição reconstrói a diferença observada; não mede o efeito de remover
um campeão e não demonstra causalidade ou força real independente das relações.
As categorias podem compartilhar jogos; as contribuições são aritméticas.

O relatório destaca os componentes e relações que favorecem o líder, contrapontos,
ausências, relações influentes com até dois Games e concentração de um componente
em uma relação. Por padrão, uma diferença >=10 p.p. recebe destaque visual de
disparidade; o limiar é configurável e não é uma regra de confiança estatística.
Sem indicador final, não são inventados líder ou contribuições comparáveis.

Cada clique em Analisar e registrar cria uma entrada com nome, drafts, Run ID,
patches, pesos, horário UTC, resultado e explicação. As anotações pessoais são
salvas no registro somente ao clicar Registrar anotações. O histórico é salvo automaticamente em um SQLite pessoal separado da coleta e
restaurado ao reabrir o app. Nome, tags e observações são atualizados ao clicar
Registrar anotações. Os downloads JSON/Markdown são cópias adicionais opcionais.
O registro exportado inclui os dados utilizados no cálculo e a origem por patch.
A interface identifica quando as configurações exibidas diferem do registro aberto.

Consultas idênticas usam cache vinculado ao caminho, tamanho e data de modificação
do SQLite e aos parâmetros do cálculo. Não é necessário importar os dados outra vez.
A interface atual usa Streamlit recente; atualize com o comando de instalação acima.

Testes adicionais:

```sh
python -m unittest discover -s tests -p test_explicacoes_draft.py -v
```

Incluem reconstrução exata da diferença por componentes e relações, normalização
com denominador diferente de 100, sinais/líder, empates, limiar visual e falta de
componentes. A interface também foi exercitada com a base real e anotações em sessão.


A versão ordered-direct-v1 torna a ordem do draft significativa para direta e
indireta. Reordenar somente um time muda seus rivais alinhados; reordenar os dois
com a mesma permutação preserva os confrontos. Sinergia continua independente da
ordem. Análises de versões anteriores podem mudar numericamente e devem ser
refeitas com as posições preenchidas corretamente. Nenhuma mudança no SQLite,
pesos 40/30/30 ou agregação do histórico é necessária.


## Mesa de draft e histórico permanente

Atualize app_draft_sqlite.py e mantenha modelo_draft_sqlite.py e draft_workspace.py
na mesma pasta. O comando Streamlit é o mesmo. A mesa alinha os cinco confrontos
TOP/JUNGLE/MID/ADC/SUPPORT, exibe retratos de 48px dos campeões selecionados e
permite trocar os lados ou carregar um draft do histórico para revisão. Seletores
continuam pesquisáveis. Repetições são sinalizadas e impedem registrar um draft
inválido. Não há download antecipado de todos os retratos do catálogo.

O painel central mostra indicadores, diferença e principal contribuição aritmética
a favor do líder. Cards por componente exibem os dois scores, pesos e cobertura;
os detalhes e a origem por patch continuam disponíveis. As explicações, os pesos
40/30/30 e o cálculo são os mesmos desta versão anterior.

O histórico pessoal padrão fica em `.mega_lol_workspace/analises.sqlite`, ao lado
do script. Não é a base `mega_lol_s16.sqlite`. A aplicação recusa usar a própria
base de coleta ou um SQLite alheio como arquivo de histórico. Resultados salvos
são imutáveis; revisar um draft gera outra análise, enquanto nome, notas e tags
podem ser atualizados. O histórico permite busca por nome/campeão, filtro por tag,
prévia dos drafts e comparação de dois registros. Comparações com configurações
diferentes recebem aviso. Fechar o navegador não apaga as análises já salvas.
Faça backup desse arquivo pessoal se quiser preservar suas anotações ao mudar
ou reinstalar a aplicação; ele também pode ser escolhido na barra lateral.

Os retratos usam os endpoints HTTPS oficiais do Data Dragon (Riot), com mapeamento
por nome e ID oficiais (por exemplo, Wukong → MonkeyKing). São apenas recursos
visuais; a versão das imagens não filtra a base do modelo. O cache em disco fica em
`.mega_lol_workspace/portraits`. O manifesto é atualizado após sete dias; falhas
são amortecidas por cinco minutos para evitar repetir pedidos em cada interação.
Somente imagens de campeões usados são buscadas. Sem rede, bloqueio do CDN, nome
não reconhecido ou resposta inválida, aparecem iniciais e nomes, e o cálculo segue.
O acesso inicial ao CDN da Riot foi bloqueado com HTTP 403 pelo proxy deste ambiente;
a integração de rede real ainda precisa ser conferida no computador do usuário.
Testes automatizados usam respostas sintéticas e não dependem desse serviço.

Novas verificações:

```sh
python -m unittest discover -s tests -p test_draft_workspace.py -v
python -m unittest discover -s tests -p test_workspace_ui.py -v
```

Incluem persistência/reabertura, notas/tags, imutabilidade de resultados, proteção
da base de origem, cache e falha de imagens, seleção/troca de lados, bloqueio de
campeão repetido, filtros do histórico e comparação. A interface também foi
exercitada contra a cópia real importada; o draft Ambessa/Skarner/Ryze/Lucian/Milio
contra Gnar/Wukong/Annie/Kalista/Renata Glasc manteve 47,93% / 52,07%.
