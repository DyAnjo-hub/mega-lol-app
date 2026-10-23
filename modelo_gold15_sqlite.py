"""Historical individual GD@15 draft indicator. Source SQLite is read-only."""
import argparse
import json
import math

from modelo_draft_sqlite import (
    POSITIONS, catalog, connect, context_profile, name_key, validate_draft,
)

MODEL_VERSION = 'direct-bot-synergy-gd15-v2'


def load_gold_pairs(database, run_id, category='Direct_Matchup'):
    """Pool source roles within directed pairs/patches, never pool snapshots."""
    if category not in ('Direct_Matchup', 'Ally_Synergy'):
        raise ValueError('Categoria não suportada pelo indicador de ouro.')
    connection = connect(database)
    pairs, seen, profiles = {}, set(), set()
    try:
        captures = connection.execute('''SELECT patch_verified,source_context_json,verified_json FROM capturas
            WHERE run_id=? AND category=? ''', (run_id,category)).fetchall()
        if not captures:
            if category == 'Ally_Synergy':
                return {}
            raise ValueError('Execução sem capturas Direct_Matchup.')
        for capture in captures:
            patch = capture['patch_verified']
            if not patch or len(patch.split('.')) != 2 or not all(x.isdigit() for x in patch.split('.')):
                raise ValueError('Patch desconhecido/agregado: não combinar com patches individuais.')
            profiles.add(context_profile(capture['source_context_json'], capture['verified_json']))
        if len(profiles) != 1:
            raise ValueError(f'Contextos diferentes em {category}; não combinar filtros.')
        rows = connection.execute('''SELECT c.capture_id,c.selected_champion,c.patch_verified,
            r.record_index,r.related_champion,r.source_role,r.games,r.gd15
            FROM capturas c JOIN registros r USING(capture_id)
            WHERE c.run_id=? AND c.category=? ''', (run_id,category))
        for row in rows:
            key = (name_key(row['selected_champion']), name_key(row['related_champion']), row['patch_verified'])
            identity = (*key, row['source_role'])
            if identity in seen:
                raise ValueError('Linha repetida para o mesmo par/role/patch; agregação recusada.')
            seen.add(identity)
            pair = pairs.setdefault(key, {'selected':row['selected_champion'],
                'related':row['related_champion'], 'patch':row['patch_verified'], 'category':category,
                'games':0, 'weighted_gold_sum':0., 'rows':[]})
            games, gold = row['games'], row['gd15']
            if games is not None and (not isinstance(games, int) or games < 0):
                raise ValueError('Games inválido no banco.')
            if gold is not None and (not isinstance(gold, (float, int)) or not math.isfinite(gold)):
                raise ValueError('GD@15 inválido no banco.')
            usable = games is not None and games > 0 and gold is not None
            pair['rows'].append({'capture_id':row['capture_id'], 'record_index':row['record_index'],
                'source_role':row['source_role'], 'games':games, 'gd15':gold, 'used':usable})
            if usable:
                pair['games'] += games
                pair['weighted_gold_sum'] += games * gold
        return pairs
    finally:
        connection.close()


def matchup(pairs, blue, red, position, minimum_games):
    """Choose one direction per patch; exact antisymmetry when teams swap."""
    a, b = name_key(blue), name_key(red)
    patches = sorted({p for x,y,p in pairs if (x,y) in ((a,b),(b,a))},
                     key=lambda p: tuple(map(int, p.split('.'))))
    sources, games, numerator = [], 0, 0.
    for patch in patches:
        options = [(key, pairs[key]) for key in ((a,b,patch),(b,a,patch)) if key in pairs]
        usable = [(key, pair) for key,pair in options if pair['games'] > 0]
        chosen_key, chosen = min(usable, key=lambda item: (-item[1]['games'], item[0])) if usable else (None,None)
        evidence = []
        for key, pair in options:
            sign = 1 if key[0] == a else -1
            average = pair['weighted_gold_sum']/pair['games'] if pair['games'] else None
            evidence.append({**pair, 'gd15':average,
                'blue_gd15':sign*average if average is not None else None, 'chosen':key == chosen_key})
        if chosen is not None:
            sign = 1 if chosen_key[0] == a else -1
            games += chosen['games']
            numerator += sign*chosen['weighted_gold_sum']
        sources.append({'patch':patch, 'directions':evidence})
    mean = numerator/games if games else None
    return {'position':position, 'blue':blue, 'red':red, 'games':games if games else None,
        'observed_gd15':mean, 'gd15':mean if games >= minimum_games else None,
        'status':'available' if games >= minimum_games else 'insufficient_games' if games else 'missing',
        'sources':sources}


def ally_estimate(pairs, selected, ally, minimum_games):
    """The selected champion's GD with an ally; reverse is a different outcome."""
    parts = [part for (first,second,_),part in pairs.items()
             if first == name_key(selected) and second == name_key(ally)]
    parts.sort(key=lambda p: tuple(map(int,p['patch'].split('.'))))
    games = sum(part['games'] for part in parts)
    mean = sum(part['weighted_gold_sum'] for part in parts)/games if games else None
    return {'selected':selected, 'ally':ally, 'category':'Ally_Synergy',
        'games':games if games else None, 'observed_gd15':mean,
        'gd15':mean if games >= minimum_games else None,
        'status':'available' if games >= minimum_games else 'insufficient_games' if games else 'missing',
        'sources':[{**part, 'gd15':part['weighted_gold_sum']/part['games'] if part['games'] else None}
                   for part in parts]}


def validate_shared_context(database,run_id):
    """Reject conflicting observed settings across categories, preserve unknowns."""
    connection = connect(database)
    observed = {}
    try:
        rows = connection.execute('''SELECT source_context_json,verified_json FROM capturas
            WHERE run_id=? AND category IN ('Direct_Matchup','Ally_Synergy')''',(run_id,))
        for row in rows:
            groups = json.loads(context_profile(row['source_context_json'],row['verified_json']))
            for group,settings in enumerate(groups):
                for key,value in settings.items():
                    if value is None or value == 'unknown' or value == '':
                        continue
                    identity = (group,key)
                    canonical = json.dumps(value,sort_keys=True,ensure_ascii=False)
                    if identity in observed and observed[identity] != canonical:
                        raise ValueError('Contextos diferentes entre confronto direto e sinergia; não combinar filtros.')
                    observed[identity] = canonical
    finally:
        connection.close()


def combine_bot(lane, allies, blue_ally, red_ally, minimum_games, synergy_weight):
    blue = ally_estimate(allies,lane['blue'],blue_ally,minimum_games)
    red = ally_estimate(allies,lane['red'],red_ally,minimum_games)
    # Each allied mean is already an individual difference versus an opponent.
    # Center their two perspectives rather than adding two full differences.
    synergy = (blue['gd15']-red['gd15'])/2 if blue['gd15'] is not None and red['gd15'] is not None else None
    direct = lane['gd15']
    available = (synergy_weight == 0 or synergy is not None) and (synergy_weight == 1 or direct is not None)
    combined = None
    if available:
        combined = 0.
        if synergy_weight < 1:
            combined += (1-synergy_weight)*direct
        if synergy_weight:
            combined += synergy_weight*synergy
    statuses = [blue['status'],red['status']] if synergy_weight else []
    if synergy_weight < 1:
        statuses.append(lane['status'])
    return {**lane, 'direct_gd15':direct, 'gd15':combined,
        'status':'available' if available else 'missing' if 'missing' in statuses else 'insufficient_games',
        'synergy':{'blue':blue,'red':red,'gd15':synergy},
        'weights':{'direct':1-synergy_weight,'synergy':synergy_weight}}


def compare_gold15(database, blue, red, *, run_id=None, minimum_games=1, synergy_weight=.4):
    validate_draft(blue, red)
    if not isinstance(minimum_games, int) or minimum_games < 1:
        raise ValueError('Mínimo de jogos deve ser inteiro positivo.')
    if not isinstance(synergy_weight, (int,float)) or not math.isfinite(synergy_weight) or not 0 <= synergy_weight <= 1:
        raise ValueError('Peso de sinergia deve estar entre 0 e 1.')
    metadata = catalog(database, run_id)
    known = {name_key(c) for c in metadata['champions']}
    if any(name_key(c) not in known for c in [*blue,*red]):
        raise ValueError('Campeão não encontrado no catálogo da execução.')
    pairs = load_gold_pairs(database, metadata['run_id'])
    lanes = [matchup(pairs,a,b,position,minimum_games) for position,a,b in zip(POSITIONS,blue,red)]
    direct_values = [lane['gd15'] for lane in lanes if lane['gd15'] is not None]
    if synergy_weight:
        allies = load_gold_pairs(database,metadata['run_id'],'Ally_Synergy')
        validate_shared_context(database,metadata['run_id'])
        for index,other in ((3,4),(4,3)):
            lanes[index] = combine_bot(lanes[index],allies,blue[other],red[other],minimum_games,synergy_weight)
    for lane in lanes:
        lane.setdefault('direct_gd15',lane['gd15'])
    available = [lane['gd15'] for lane in lanes if lane['gd15'] is not None]
    return {'model_version':MODEL_VERSION, 'run_id':metadata['run_id'],
        'drafts':{'blue':list(blue), 'red':list(red)}, 'minimum_games':minimum_games,
        'aggregation':'all_available_individual_patches',
        'categories':['Direct_Matchup','Ally_Synergy'] if synergy_weight else ['Direct_Matchup'],
        'bot_weights':{'direct':1-synergy_weight,'synergy':synergy_weight},
        'synergy_rule':'half_blue_selected_gd_minus_red_selected_gd',
        'direct_total_gd15':sum(direct_values) if len(direct_values)==5 else None,
        'patches_available':metadata['patches'], 'lanes':lanes,
        'covered_positions':len(available), 'total_gd15':sum(available) if len(available)==5 else None,
        'partial_gd15':sum(available) if available else None,
        'direction_rule':'one_direction_per_patch_most_games_canonical_tie',
        'interpretation':'GD@15 individual, perspectiva do campeão selecionado; definição informada pelo usuário.',
        'limitations':[
            'Indicador histórico experimental; não é previsão validada nem efeito causal do draft.',
            'Games é o peso disponível; o denominador específico do GD@15 não foi verificado.',
            'Papéis das linhas são reunidos; não há condicionamento por posição real na partida.',
            'Jogos de relações podem se sobrepor; não são somados como amostra independente.',
            'Sem dados por partida, não são calculados intervalos de confiança.',
            'Pesos de confronto/sinergia e centralização das duas perspectivas são hipóteses não calibradas.',
            'Good with é usado como GD individual do campeão selecionado com o aliado; perspectiva ainda sem verificação independente.',
            'Médias marginais não representam a matchup específica entre as duas duplas nem isolam efeito causal do aliado.',
        ]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database', required=True)
    parser.add_argument('--blue', required=True, help='TOP,JUNGLE,MID,ADC,SUPPORT')
    parser.add_argument('--red', required=True, help='TOP,JUNGLE,MID,ADC,SUPPORT')
    parser.add_argument('--run-id')
    parser.add_argument('--minimum-games', type=int, default=1)
    parser.add_argument('--synergy-weight', type=float, default=.4, help='Peso ADC/SUPPORT de 0 a 1; 0 recupera cálculo direto.')
    args = parser.parse_args()
    result = compare_gold15(args.database, [x.strip() for x in args.blue.split(',')],
        [x.strip() for x in args.red.split(',')], run_id=args.run_id, minimum_games=args.minimum_games,
        synergy_weight=args.synergy_weight)
    print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))


if __name__ == '__main__':
    main()
