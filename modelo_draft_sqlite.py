"""Comparative draft indicator using preserved gol.gg SQLite data (read-only).

Scores are experimental indicators, not calibrated win probabilities.
"""
import argparse
from dataclasses import dataclass, field
import itertools
import json
import math
from pathlib import Path
import sqlite3
import unicodedata

WEIGHTS = {'Direct_Matchup': .40, 'Indirect_Matchup': .30, 'Ally_Synergy': .30}
APPLICATION_ID = 0x4D4C4F4C


def name_key(name):
    return ''.join(c for c in unicodedata.normalize('NFKC', name).casefold() if c.isalnum())


def connect(database):
    path = Path(database).resolve()
    connection = sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)
    connection.row_factory = sqlite3.Row
    if (connection.execute('PRAGMA application_id').fetchone()[0] != APPLICATION_ID or
            connection.execute('PRAGMA user_version').fetchone()[0] != 1):
        connection.close()
        raise ValueError('Banco incompatível: use o SQLite criado pelo importador gol.gg.')
    return connection


def catalog(database, run_id=None):
    connection = connect(database)
    try:
        runs = [r[0] for r in connection.execute('SELECT DISTINCT run_id FROM capturas ORDER BY run_id')]
        if run_id is None:
            if len(runs) != 1:
                raise ValueError('Escolha explicitamente um Run ID; não combinar snapshots.')
            run_id = runs[0]
        if run_id not in runs:
            raise ValueError('Run ID não encontrado.')
        patches = [r[0] for r in connection.execute(
            'SELECT DISTINCT patch_verified FROM capturas WHERE run_id=? AND patch_verified IS NOT NULL', (run_id,))]
        patches.sort(key=lambda p: tuple(int(x) for x in p.split('.')), reverse=True)
        champions = [r[0] for r in connection.execute(
            'SELECT DISTINCT selected_champion FROM capturas WHERE run_id=? ORDER BY selected_champion', (run_id,))]
        return {'runs': runs, 'run_id': run_id, 'patches': patches, 'champions': champions}
    finally:
        connection.close()


@dataclass
class Pair:
    selected: str
    related: str
    category: str
    patch: str
    games: int = 0
    weighted_rate_sum: float = 0
    source_rows: int = 0
    missing_rows: int = 0
    roles: set = field(default_factory=set)
    by_patch: dict = field(default_factory=dict)

    @property
    def winrate(self):
        return self.weighted_rate_sum / self.games if self.games else None


def context_profile(source_json, verified_json):
    source, verified = json.loads(source_json), json.loads(verified_json)
    parameters = {k:v for k,v in source.get('url_parameters', {}).items() if k != 'patch'}
    controls = {c['id']: c['selected'] for c in source.get('visible_selects', [])
                if c['id'] not in ('cbchampselect', 'patch')}
    filters = {k:v for k,v in verified.items()
               if k not in ('Selected champion', 'Game version', 'Matchup category', 'Source URL')}
    return json.dumps([parameters, controls, filters], sort_keys=True, ensure_ascii=False)


def load_pairs(database, run_id, patch=None):
    """Aggregate roles and individual patches within one run/category/context.

    Repeated rows for the same role are ambiguous and are rejected, never summed.
    Opposite directions and categories remain distinct.
    """
    connection = connect(database)
    pairs, profiles, seen = {}, {}, set()
    try:
        clause = 'run_id=?' + (' AND patch_verified=?' if patch is not None else '')
        parameters = (run_id, patch) if patch is not None else (run_id,)
        captures = connection.execute('SELECT category,patch_verified,source_context_json,verified_json FROM capturas WHERE ' + clause, parameters).fetchall()
        if not captures:
            raise ValueError('Patch/execução sem capturas.')
        for capture in captures:
            source_patch = capture['patch_verified']
            if not source_patch or len(source_patch.split('.')) != 2 or not all(p.isdigit() for p in source_patch.split('.')):
                raise ValueError('A base contém patch desconhecido/agregado; não somar com patches individuais.')
            category = capture['category']
            profile = context_profile(capture['source_context_json'], capture['verified_json'])
            if category in profiles and profiles[category] != profile:
                raise ValueError(f'Contextos diferentes em {category}; selecione uma base homogênea.')
            profiles[category] = profile
        rows = connection.execute('''SELECT c.selected_champion, c.category, c.patch_verified,
            r.related_champion, r.source_role, r.games, r.winrate FROM capturas c
            JOIN registros r USING(capture_id) WHERE ''' + 'c.' + clause.replace(' AND ', ' AND c.'), parameters)
        for row in rows:
            category = row['category']
            if category not in WEIGHTS:
                continue
            key = (category, name_key(row['selected_champion']), name_key(row['related_champion']))
            identity = (*key, row['patch_verified'], row['source_role'])
            if identity in seen:
                raise ValueError('Mais de uma linha para o mesmo par/role/contexto; não somar automaticamente.')
            seen.add(identity)
            pair = pairs.setdefault(key, Pair(row['selected_champion'], row['related_champion'], category, patch or 'ALL'))
            part = pair.by_patch.setdefault(row['patch_verified'], {'games':0,'weighted_rate_sum':0.,'source_rows':0,
                'missing_rows':0,'roles':set(),'selected':row['selected_champion'],'related':row['related_champion']})
            part['source_rows'] += 1
            part['roles'].add(row['source_role'])
            pair.source_rows += 1
            pair.roles.add(row['source_role'])
            games, rate = row['games'], row['winrate']
            if games is None or rate is None or games == 0:
                pair.missing_rows += 1
                part['missing_rows'] += 1
                continue
            if games < 0 or not math.isfinite(rate) or not 0 <= rate <= 1:
                raise ValueError('Valor inválido no banco.')
            pair.games += games
            pair.weighted_rate_sum += games * rate  # weighted arithmetic, not inferred exact wins
            part['games'] += games
            part['weighted_rate_sum'] += games * rate
        return pairs
    finally:
        connection.close()


def validate_draft(blue, red):
    if len(blue) != 5 or len(red) != 5:
        raise ValueError('Cada time precisa ter exatamente cinco campeões.')
    keys = [name_key(c) for c in [*blue, *red]]
    if any(not k for k in keys) or len(set(keys)) != 10:
        raise ValueError('Informe dez campeões distintos e não vazios.')


def synergy_pair(pairs, first, second):
    """Pick one direction per patch, then combine patches without double count."""
    category = 'Ally_Synergy'
    options = [(k, pairs[k]) for k in ((category,name_key(first),name_key(second)),
                                     (category,name_key(second),name_key(first))) if k in pairs]
    parts = {}
    for key, pair in options:
        by_patch = pair.by_patch or {pair.patch: {'games':pair.games,'weighted_rate_sum':pair.weighted_rate_sum,
            'source_rows':pair.source_rows,'missing_rows':pair.missing_rows,'roles':pair.roles,
            'selected':pair.selected,'related':pair.related}}
        for patch_name, part in by_patch.items():
            if part['games'] > 0:
                parts.setdefault(patch_name, []).append((key, part))
    if not parts:
        return None
    combined = Pair(first, second, category, 'ALL')
    for patch_name, choices in parts.items():
        _, part = min(choices, key=lambda item: (-item[1]['games'], item[0]))
        combined.by_patch[patch_name] = part
        combined.games += part['games']
        combined.weighted_rate_sum += part['weighted_rate_sum']
        combined.source_rows += part['source_rows']
        combined.missing_rows += part['missing_rows']
        combined.roles.update(part['roles'])
    return combined


def patch_sources(pair):
    if pair is None:
        return []
    return [{'patch':p, 'games':part['games'],
             'winrate':part['weighted_rate_sum']/part['games'] if part['games'] else None,
             'source_rows':part['source_rows'], 'roles':sorted(str(r) for r in part['roles']),
             'selected_direction':part['selected'], 'related_direction':part['related']}
            for p,part in sorted(pair.by_patch.items(), key=lambda item: tuple(int(x) for x in item[0].split('.')))]


def component(pairs, team, opponents, category, minimum_games):
    candidates = list(itertools.combinations(sorted(team, key=name_key), 2)) if category == 'Ally_Synergy' else list(itertools.product(team, opponents))
    details = []
    for first, second in candidates:
        key = (category, name_key(first), name_key(second))
        if category == 'Ally_Synergy':
            pair = synergy_pair(pairs, first, second)
        else:
            pair = pairs.get(key)
        usable = pair is not None and pair.games > 0
        details.append({'first': first, 'second': second,
                        'selected_direction': pair.selected if usable else None,
                        'related_direction': pair.related if usable else None,
                        'games': pair.games if usable else None,
                        'winrate': pair.winrate if usable else None,
                        'source_rows': pair.source_rows if pair else 0,
                        'roles': sorted(str(r) for r in pair.roles) if pair else [],
                        'patch_sources': patch_sources(pair)})
    games = sum(d['games'] for d in details if d['games'] is not None)
    found = sum(d['winrate'] is not None for d in details)
    score = sum(d['games'] * d['winrate'] for d in details if d['winrate'] is not None) / games * 100 if games >= minimum_games and games else None
    return {'score': score, 'relation_games_sum': games, 'found_pairs': found,
            'queried_pairs': len(candidates), 'missing_pairs': len(candidates)-found,
            'minimum_relation_games_sum': minimum_games, 'details': details}


def compare_drafts(database, blue, red, *, patch=None, run_id=None, weights=None, minimum_games=10):
    validate_draft(blue, red)
    weights = dict(WEIGHTS if weights is None else weights)
    if set(weights) != set(WEIGHTS) or any(not math.isfinite(v) or v < 0 for v in weights.values()) or not math.isclose(sum(weights.values()), 1):
        raise ValueError('Pesos devem ser não negativos e somar 1, com as três categorias.')
    if minimum_games < 1:
        raise ValueError('O mínimo deve ser positivo.')
    metadata = catalog(database, run_id)
    if patch is not None and patch not in metadata['patches']:
        raise ValueError('Patch não disponível nesta execução.')
    known = {name_key(c) for c in metadata['champions']}
    if any(name_key(c) not in known for c in [*blue,*red]):
        raise ValueError('Há campeão não encontrado no catálogo da execução.')
    pairs = load_pairs(database, metadata['run_id'], patch)
    teams = {}
    for side, team, opponents in [('blue',blue,red), ('red',red,blue)]:
        components = {category: component(pairs, team, opponents, category, minimum_games) for category in weights}
        available = all(c['score'] is not None for category,c in components.items() if weights[category] > 0)
        score = sum(weights[k]*c['score'] for k,c in components.items() if weights[k] > 0) if available else None
        teams[side] = {'score': score, 'components': components}
    blue_score, red_score = teams['blue']['score'], teams['red']['score']
    denominator = blue_score + red_score if blue_score is not None and red_score is not None else None
    relative = {'blue':blue_score/denominator*100,'red':red_score/denominator*100} if denominator and denominator > 0 else None
    return {'run_id':metadata['run_id'], 'patch':patch, 'patches_used':metadata['patches'] if patch is None else [patch],
            'drafts':{'blue':list(blue),'red':list(red)},
            'aggregation':'all_available_patches' if patch is None else 'single_patch_audit', 'weights':weights, 'teams':teams,
            'relative_indicator':relative,
            'note':'Indicador experimental, não probabilidade calibrada. Somas de Games de relações não são partidas independentes. Sem redistribuição automática de pesos de componentes ausentes.'}


def explain_comparison(result, large_gap=10):
    """Exact additive decomposition of the indicator, not causal feature effects.

    50% is only the algebraic reference for observed relations. Missing rows are
    never assigned that value. Contributions across available sides cancel this
    reference when both components are usable.
    """
    relative = result['relative_indicator']
    gap = relative['blue'] - relative['red'] if relative else None
    leader = ('blue' if gap > 0 else 'red' if gap < 0 else 'tie') if gap is not None else None
    scores = [result['teams'][side]['score'] for side in ('blue','red')]
    total = sum(scores) if all(score is not None for score in scores) else None
    factor = 100 / total if total and total > 0 else None
    components, relations, alerts = [], [], []
    for category, weight in result['weights'].items():
        blue = result['teams']['blue']['components'][category]
        red = result['teams']['red']['components'][category]
        delta = weight * (blue['score'] - red['score']) if blue['score'] is not None and red['score'] is not None else None
        components.append({'category':category, 'weight':weight,
            'blue_score':blue['score'], 'red_score':red['score'],
            'score_gap_contribution':delta,
            'indicator_gap_contribution':delta * factor if delta is not None and factor is not None else None})
        for side, component, sign in [('blue',blue,1),('red',red,-1)]:
            if component['missing_pairs']:
                alerts.append({'type':'missing_pairs','side':side,'category':category,
                    'found':component['found_pairs'],'queried':component['queried_pairs']})
            if component['score'] is None and weight > 0:
                alerts.append({'type':'unavailable_component','side':side,'category':category})
            denominator = component['relation_games_sum']
            if weight <= 0 or not denominator or component['score'] is None:
                continue
            for detail in component['details']:
                if detail['winrate'] is None:
                    continue
                contribution = sign * weight * detail['games'] / denominator * (detail['winrate'] - .5) * 100
                relations.append({'side':side,'category':category,'first':detail['first'],'second':detail['second'],
                    'games':detail['games'],'winrate':detail['winrate'],
                    'component_share':detail['games']/denominator,
                    'score_gap_contribution':contribution,
                    'indicator_gap_contribution':contribution * factor if factor is not None else None,
                    'patch_count':len(detail.get('patch_sources',[]))})
    relations.sort(key=lambda row: abs(row['score_gap_contribution']),reverse=True)
    for relation in relations[:5]:
        if relation['games'] <= 2:
            alerts.append({'type':'small_sample_influential_relation','relation':relation})
        if relation['component_share'] >= .5:
            alerts.append({'type':'concentrated_component','relation':relation})
    direction = 1 if leader == 'blue' else -1 if leader == 'red' else 0
    supporting = [r for r in relations if direction * r['score_gap_contribution'] > 0][:3]
    opposing = [r for r in relations if direction * r['score_gap_contribution'] < 0][:3]
    return {'leader':leader,'indicator_gap':gap,'large_gap':abs(gap) >= large_gap if gap is not None else None,
            'large_gap_threshold':large_gap,'components':components,'relations':relations,
            'supporting_relations':supporting,'opposing_relations':opposing,'alerts':alerts,
            'method':'Contribuições aditivas ao cálculo. Sinal positivo favorece azul; negativo favorece vermelho. Não são efeitos causais nem probabilidades independentes. O limiar de grande disparidade é apenas visual.'}


def main():
    parser=argparse.ArgumentParser(description='Comparador experimental de drafts, SQLite somente leitura')
    parser.add_argument('--database',required=True)
    parser.add_argument('--patch',help='Opcional: auditoria de um patch. Por padrão, agrega todos.')
    parser.add_argument('--run-id')
    parser.add_argument('--blue',required=True,help='Cinco campeões separados por vírgulas, sem ordem de posição')
    parser.add_argument('--red',required=True)
    args=parser.parse_args()
    try:
        result=compare_drafts(args.database,[c.strip() for c in args.blue.split(',')],
                              [c.strip() for c in args.red.split(',')],patch=args.patch,run_id=args.run_id)
    except (ValueError,sqlite3.Error) as exc:
        parser.exit(1,str(exc)+'\n')
    print(json.dumps(result,ensure_ascii=False,indent=2))


if __name__=='__main__':
    main()
