# Indicador histórico de diferença de ouro aos 15

App separado do indicador de draft/winrate. Não altera os apps anteriores, as
fórmulas de winrate, o scraper, o importador nem o banco de origem. Não faz coleta.

## Executar no Windows

Coloque estes três arquivos na mesma pasta que `mega_lol_s16.sqlite`:

- `app_gold15_sqlite.py` (novo app)
- `modelo_gold15_sqlite.py` (novo cálculo)
- `modelo_draft_sqlite.py` (dependência existente, sem alterações)

No PowerShell:

```powershell
cd D:\Importacao_s16
& "$env:LOCALAPPDATA\Programs\Python\Python313\python.exe" -m pip install --upgrade streamlit
& "$env:LOCALAPPDATA\Programs\Python\Python313\python.exe" -m streamlit run .\app_gold15_sqlite.py --server.port 8502
```

Abra `http://localhost:8502`. A porta separada permite manter o app de draft
aberto. Confirme o caminho do SQLite e selecione os campeões na ordem TOP,
JUNGLE, MID, ADC, SUPPORT. Clique em **Calcular GD@15**. A seleção de Run ID
permite usar bancos com várias coletas sem misturar snapshots.

Atualização: baixe novamente `app_gold15_sqlite.py` e `modelo_gold15_sqlite.py`.
O `modelo_draft_sqlite.py` permanece igual. A interface usa sinergia fixa em
40%, sem controle manual. A opção CLI `--synergy-weight 0` continua disponível
para conferir o cálculo anterior sem mudar as fórmulas.
O mínimo de jogos vale para cada relação exigida, inclusive as relações de
parceria em cada time. Os pesos usados aparecem no JSON.

O mesmo resultado também está integrado ao `app_draft_sqlite.py`, com uma única
seleção de campeões para winrate e ouro. Não é necessário executar os dois apps.
Na interface unificada, ambos os modelos permanecem independentes; detalhes em
`DRAFT_SQLITE.md`. A visualização de ouro mantém as métricas e tabela, sem as
explicações extensas. Metadados e fontes permanecem nos downloads JSON.

## Cálculo

A definição de GD@15 individual foi informada pelo usuário. Este app assume que
o sinal pertence ao campeão selecionado na captura. Essa perspectiva específica
e o denominador da estatística não foram verificados independentemente no site.

1. Usa `Direct_Matchup` dos cinco pares alinhados e `Ally_Synergy` (Good with)
   nas duas direções ADC → suporte e suporte → ADC, em cada time. Não usa winrate,
   matchup indireta, sinergias mid/jungle ou pesos do outro modelo.
2. Em cada direção e patch, reúne as linhas de papéis distintos com
   `sum(Games * GD@15) / sum(Games)`, usando apenas Games positivo e GD presente.
   Winrate ausente não impede usar GD disponível. Zero GD é um valor válido.
3. Se existirem A→B e B→A no mesmo patch, escolhe somente a direção com mais
   jogos válidos. Empates usam a ordem canônica dos nomes normalizados. A direção
   B→A tem sinal invertido para expressar azul menos vermelho. É uma regra
   operacional, não prova de que uma direção seja mais correta. Não soma as duas
   amostras potencialmente sobrepostas; ambas ficam no JSON para inspeção.
4. Reúne os patches individuais, ponderando os valores escolhidos pelos jogos.
   A seleção de direção pode mudar entre patches. Mantém captura, índice da
   linha, papel original, jogos e GD de cada registro na evidência.
5. Para TOP/JUNGLE/MID, mantém somente a média direta. Para ADC/SUPPORT, combina
   confronto e parceria como descrito abaixo.
6. Soma as cinco contribuições individuais. As posições contribuem uma vez cada; não
   recebem pesos diferentes conforme sua quantidade de jogos. Trocar os times
   inverte o sinal do indicador.

### Parceria integrada ao total

Para cada posição do bot, `B` é o GD do campeão azul **com seu aliado**, `R` é
o GD do campeão vermelho **com seu aliado** e `D` é o confronto direto já
expresso como azul menos vermelho:

```text
Parceria comparativa = (B - R) / 2
Contribuição final = 0,60 × D + 0,40 × Parceria comparativa
```

A divisão por dois centraliza duas perspectivas de diferença individual, para
não adicionar duas diferenças completas ao misturar com D. É uma hipótese de
escala do indicador, não uma identidade verificada entre essas amostras.
Os pesos são fixos na interface, configuráveis somente pela CLI/função; não
foram calibrados com partidas futuras.

Cada média B e R usa `sum(Games × GD) / sum(Games)` dos patches e papéis
disponíveis. A quantidade de jogos não é usada para redistribuir os pesos
60/40. Não se aplica redução em direção a zero.

**Lucian com Milio e Milio com Lucian são resultados individuais diferentes.**
Nenhuma direção aliada substitui a outra; não se inverte seu sinal para estimar
o parceiro. O GD de Lucian com Milio também não é a soma do GD da dupla.
Não se somam os jogos dessas relações como partidas independentes.

Se faltar B, R ou D exigido por um peso positivo, a contribuição fica ausente.
Não há fallback automático para outro peso. Com sinergia 0%, somente D é
necessário; com 100%, somente B e R são necessários no bot. O cálculo direto
original fica disponível em `direct_total_gd15` para conferência.

No app, as colunas mostram direto, parceria comparativa, valor final e jogos
separados por fonte/time. O JSON preserva médias originais, pesos, categorias,
IDs das capturas e linhas de origem. Trocar o suporte altera também a estimativa
do ADC quando os dados da parceria diferirem.

O resultado está em **ouro**, não porcentagem: positivo favorece azul e negativo
favorece vermelho. Não é ouro total acumulado das equipes.

Se qualquer confronto não tiver dados suficientes, o total fica indisponível e
aparece apenas um subtotal explicitamente identificado. Ausência nunca vira
zero. O mínimo padrão é 1 jogo; o usuário pode aumentá-lo. O aviso abaixo de 10
jogos é operacional e não representa confiança estatística. Uma média abaixo do
mínimo continua preservada em `observed_gd15` no JSON.

O JSON exportado identifica os drafts, execução, versão, regras de direção,
patches disponíveis e fontes efetivamente usadas por confronto. Não grava
análises automaticamente nem escreve no SQLite.

## Limites de interpretação

- É um indicador histórico experimental, não uma previsão validada ou efeito
  causal da composição. A soma combina médias de partidas diferentes.
- Games é o único peso disponível. Não foi confirmado se todas essas partidas
  entram no denominador do GD@15 (por exemplo, partidas encerradas antes dos 15).
- Os papéis da fonte são preservados e reunidos. A posição digitada seleciona
  o par rival; ela não restringe os registros a partidas naquela posição.
- Não reúne filtros diferentes, patches desconhecidos/ALL ou snapshots
  diferentes. Repetições de mesmo par/papel/patch são recusadas.
- Partidas podem aparecer em várias relações. Não há contagem de partidas
  independentes, variância por partida nem intervalo de confiança.
- O uso de Good with pressupõe GD individual do campeão selecionado com o
  aliado. Não houve verificação independente da definição dessa tabela no site.
- As médias separadas de confronto e parceria não isolam os quatro campeões da
  matchup do bot, força dos jogadores ou efeitos causais. A combinação é uma
  aproximação experimental, não uma soma de ganhos independentes.
- Filtros conhecidos conflitantes entre categorias são recusados. Valores
  desconhecidos permanecem desconhecidos; compatibilidade completa não é
  demonstrada pela ausência de evidência de conflito.

## Verificação

```bash
python -m unittest discover -s tests -p 'test_gold15_sqlite.py' -v
```

Os 15 testes usam fixtures **sintéticas**, incluindo uma execução offline do
Streamlit. Cobrem alinhamento, soma, inversão, pesos por papel/patch, direção
inversa, rastreabilidade, valores negativos/zero/ausentes, mínimo, banco vazio de
GD, filtros incompatíveis dentro e entre categorias, duplicação, snapshots
separados, peso 0%/100%, direção individual de sinergia, troca de suporte,
sinergia ausente e banco inalterado. Também passam os dez testes do modelo de
draft anterior, cujo código não foi alterado.

Também foi executado o cálculo sobre o SQLite reconstruído das capturas reais
da coleta S16 (Run ID `4e5cbd2e773449f08888afad07a61a54`). Para Ambessa, Skarner,
Ryze, Lucian, Milio contra Gnar, Wukong, Annie, Kalista, Renata Glasc, a
**referência somente direta** continua:

| Posição | GD@15 azul menos vermelho | Jogos usados |
|---|---:|---:|
| TOP | -260,39 | 197 |
| JUNGLE | -127,00 | 50 |
| MID | +300,58 | 118 |
| ADC | -155,53 | 45 |
| SUPPORT | -17,91 | 32 |
| Soma | -260,25 | Não somar como partidas independentes |

Com a parceria integrada em 40%, TOP/JUNGLE/MID permanecem iguais. ADC passa a
-118,73 e SUPPORT a -19,32; o novo total é **-224,87**. As médias individuais
aliadas são Lucian com Milio +25,75 (860 jogos), Milio com Lucian -24,29 (860),
Kalista com Renata Glasc +152,83 (278) e Renata com Kalista +18,60 (278).
A inversão de times produziu o sinal oposto; o SHA256 do SQLite permaneceu
idêntico antes/depois. A interface também foi executada offline com essa base.

Isso verifica o cálculo sobre dados coletados, sem demonstrar capacidade
preditiva. Nenhuma nova coleta ou verificação ao vivo do gol.gg foi realizada.
