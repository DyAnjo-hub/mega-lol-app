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

## Cálculo

A definição de GD@15 individual foi informada pelo usuário. Este app assume que
o sinal pertence ao campeão selecionado na captura. Essa perspectiva específica
e o denominador da estatística não foram verificados independentemente no site.

1. Usa somente `Direct_Matchup` dos cinco pares alinhados. Não usa winrate,
   sinergia, matchup indireta ou pesos do outro modelo.
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
5. Soma as cinco médias individuais. As posições contribuem uma vez cada; não
   recebem pesos diferentes conforme sua quantidade de jogos. Trocar os times
   inverte o sinal do indicador.

O resultado está em **ouro**, não porcentagem: positivo favorece azul e negativo
favorece vermelho. Não é ouro total acumulado das equipes.

Se qualquer confronto não tiver dados suficientes, o total fica indisponível e
aparece apenas um subtotal explicitamente identificado. Ausência nunca vira
zero. O mínimo padrão é 1 jogo; o usuário pode aumentá-lo. O aviso abaixo de 10
jogos é operacional e não representa confiança estatística. Uma média abaixo do
mínimo continua preservada em `observed_gd15` no JSON.

O JSON exportado identifica os drafts, execução, versão, regra de direção,
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
- O banco continua contendo as outras categorias sem que elas sejam usadas aqui.

## Verificação

```bash
python -m unittest discover -s tests -p 'test_gold15_sqlite.py' -v
```

Os oito testes usam fixtures **sintéticas**, incluindo uma execução offline do
Streamlit. Cobrem alinhamento, soma, inversão, pesos por papel/patch, direção
inversa, rastreabilidade, valores negativos/zero/ausentes, mínimo, banco vazio de
GD, filtros incompatíveis, duplicação, snapshots separados e banco inalterado.

Também foi executado o cálculo sobre o SQLite reconstruído das capturas reais
da coleta S16 (Run ID `4e5cbd2e773449f08888afad07a61a54`). Para Ambessa, Skarner,
Ryze, Lucian, Milio contra Gnar, Wukong, Annie, Kalista, Renata Glasc:

| Posição | GD@15 azul menos vermelho | Jogos usados |
|---|---:|---:|
| TOP | -260,39 | 197 |
| JUNGLE | -127,00 | 50 |
| MID | +300,58 | 118 |
| ADC | -155,53 | 45 |
| SUPPORT | -17,91 | 32 |
| Soma | -260,25 | Não somar como partidas independentes |

Isso verifica o cálculo sobre dados coletados, sem demonstrar capacidade
preditiva. Nenhuma nova coleta ou verificação ao vivo do gol.gg foi realizada.
