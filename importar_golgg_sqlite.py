"""Offline, lossless gol.gg capture import. Python standard library only."""
import argparse
import csv
import hashlib
import io
import json
import math
import os
from pathlib import Path
import re
import sqlite3
from datetime import datetime, timezone
import uuid

APPLICATION_ID = 0x4D4C4F4C
SCHEMA_VERSION = 1
CATEGORIES = ('Direct_Matchup', 'Indirect_Matchup', 'Ally_Synergy')
UNKNOWN = 'unknown'
SCHEMA = (
    '''CREATE TABLE capturas (
        capture_id TEXT PRIMARY KEY, run_id TEXT NOT NULL,
        selected_champion TEXT NOT NULL, selected_champion_normalized TEXT NOT NULL,
        category TEXT NOT NULL CHECK(category IN ('Direct_Matchup','Indirect_Matchup','Ally_Synergy')),
        collected_at_utc TEXT NOT NULL, source_url TEXT,
        season_verified TEXT, patch_verified TEXT, split_verified TEXT,
        tournament_verified TEXT, page_role_verified TEXT, table_role_filter_verified TEXT,
        pick_selection_verified TEXT, minimum_games_verified TEXT, league_selections_verified_json TEXT,
        season_url TEXT, split_url TEXT,
        context_sha256 TEXT NOT NULL, raw_sha256 TEXT NOT NULL, metadata_sha256 TEXT NOT NULL,
        parse_status TEXT NOT NULL CHECK(parse_status IN ('parsed','empty')),
        row_count INTEGER NOT NULL CHECK(row_count >= 0),
        raw_text TEXT NOT NULL, raw_bytes BLOB NOT NULL,
        metadata_original TEXT NOT NULL, metadata_bytes BLOB NOT NULL,
        requested_json TEXT NOT NULL, verified_json TEXT NOT NULL, source_context_json TEXT NOT NULL,
        UNIQUE(run_id, selected_champion_normalized, category, context_sha256)
    )''',
    '''CREATE TABLE registros (
        capture_id TEXT NOT NULL REFERENCES capturas(capture_id),
        record_index INTEGER NOT NULL CHECK(record_index > 0),
        related_champion TEXT NOT NULL, related_champion_normalized TEXT NOT NULL,
        source_role TEXT,
        games INTEGER CHECK(games IS NULL OR (typeof(games)='integer' AND games>=0)),
        winrate REAL CHECK(winrate IS NULL OR (winrate>=0 AND winrate<=1)),
        csd15 REAL, gd15 REAL, xpd15 REAL, kda REAL,
        source_fields_json TEXT NOT NULL,
        PRIMARY KEY(capture_id, record_index)
    )''',
    'CREATE INDEX idx_capturas_run ON capturas(run_id)',
    'CREATE INDEX idx_capturas_patch_category ON capturas(patch_verified, category)',
    'CREATE INDEX idx_registros_champion ON registros(related_champion_normalized)',
    '''CREATE VIEW dados_coletados AS SELECT c.run_id, c.capture_id, r.record_index,
        c.selected_champion, r.related_champion, c.category, c.patch_verified,
        c.season_verified, c.season_url, c.split_verified, c.split_url,
        r.source_role, r.games, r.winrate, r.csd15, r.gd15, r.xpd15, r.kda,
        c.collected_at_utc, c.source_url
        FROM capturas c JOIN registros r ON r.capture_id=c.capture_id''',
)


def dump(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False)


def sha(value):
    return hashlib.sha256(value).hexdigest()


def normalized(value):
    return ' '.join(value.replace('\u00a0', ' ').strip().replace("'", '').split()).title()


def known(value):
    return None if value is None or value == '' or value == UNKNOWN else value


def optional(value, parser):
    if value is None or str(value).strip().casefold() in ('', '-', '—', 'n/a', 'na'):
        return None
    return parser(value)


def games(value):
    text = str(value).strip()
    if not re.fullmatch(r'(?:[0-9]+|[0-9]{1,3}(?:,[0-9]{3})+)(?:\.0+)?', text):
        raise ValueError(f'Games inválido: {value!r}')
    number = int(text.replace(',', '').split('.')[0])
    if number > 2**63 - 1:
        raise ValueError('Games excede o limite INTEGER do SQLite')
    return number


def statistic(value):
    number = float(str(value).strip().replace('−', '-').replace(',', '.'))
    if not math.isfinite(number):
        raise ValueError(f'Estatística não finita: {value!r}')
    return number


def winrate(value):
    text = str(value).strip()
    percent = text.endswith('%')
    number = statistic(text.removesuffix('%').strip())
    if percent:
        number /= 100
    if not 0 <= number <= 1:
        raise ValueError(f'Winrate inválido: {value!r}; use percentual explícito ou fração 0–1')
    return number


def parse_rows(raw_text, champion, verified_empty=False):
    """All original cells remain strings; normalized values are additional fields."""
    if not raw_text.strip():
        return []
    reader = csv.reader(io.StringIO(raw_text), delimiter='\t', strict=True)
    headers = next(reader)
    if len(headers) != len(set(headers)):
        raise ValueError('Cabeçalhos duplicados')
    values = list(reader)
    if verified_empty:
        if not values or (len(values) == 1 and len(values[0]) == 1 and
                          re.search(r'no (data|records|matching records)|no games', values[0][0], re.I)):
            return []
        raise ValueError('Marcador de tabela vazia conflita com conteúdo bruto')
    if not values:
        return []
    if any(len(row) != len(headers) for row in values):
        raise ValueError('Quantidade de campos inconsistente no TSV')
    aliases = {'champion': {'champion', 'opponent', 'ally', 'with', 'vs'},
               'games': {'games', '# games'}, 'winrate': {'winrate', 'win rate'}}
    columns = {}
    for key, names in aliases.items():
        matches = []
        for header in headers:
            dynamic = re.fullmatch(r'(.+?)\s+winrate', header.strip(), re.I)
            if (header.strip().lower() in names or
                (key == 'winrate' and dynamic and normalized(dynamic[1]) == normalized(champion))):
                matches.append(header)
        if len(matches) != 1:
            raise ValueError(f'Cabeçalho {key} ausente ou ambíguo: {matches}')
        columns[key] = matches[0]
    role = next((h for h in headers if h.strip().lower() == 'role'), None)
    result = []
    for index, values_row in enumerate(values, 1):
        original = dict(zip(headers, values_row))
        try:
            related = original[columns['champion']]
            if not related.strip():
                raise ValueError('Campeão relacionado ausente')
            result.append((index, related, normalized(related), known(original.get(role)),
                           optional(original[columns['games']], games),
                           optional(original[columns['winrate']], winrate),
                           *[optional(original.get(h), statistic) for h in ('CSD@15', 'GD@15', 'XPD@15', 'KDA')],
                           dump(original)))
        except (ValueError, OverflowError) as exc:
            raise ValueError(f'Registro {index}: {exc}') from exc
    return result


def read_capture(path, metadata, metadata_bytes):
    cid = metadata['capture_id']
    if not isinstance(cid, str) or not re.fullmatch(r'[A-Za-z0-9_-]+', cid) or path.stem != cid:
        raise ValueError('Capture ID inválido ou diferente do nome do JSON')
    if metadata.get('raw_file') != cid + '.txt':
        raise ValueError('raw_file deve ser o TXT correspondente na mesma pasta')
    raw = path.with_suffix('.txt').read_bytes()
    raw_hash = sha(raw)
    if raw_hash != metadata.get('raw_sha256'):
        raise ValueError('Checksum SHA-256 do texto original divergente ou ausente')
    raw_text = raw.decode('utf-8')
    requested, verified = metadata['requested'], metadata['verified']
    source = metadata.get('source_context', {})
    champion = requested['Selected champion']
    category = requested['Matchup category']
    if not isinstance(champion, str) or not champion.strip() or category not in CATEGORIES:
        raise ValueError('Campeão selecionado/categoria inválidos')
    run_id = known(metadata.get('run_id'))
    if not run_id:
        raise ValueError('Run ID ausente')
    timestamp = metadata['collected_at_utc']
    dt = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
    if dt.utcoffset() is None or dt.utcoffset().total_seconds() != 0:
        raise ValueError('Horário da captura deve incluir UTC explícito')
    if known(verified.get('Selected champion')) and normalized(verified['Selected champion']) != normalized(champion):
        raise ValueError('Campeão verificado difere do solicitado')
    if known(verified.get('Matchup category')) and verified['Matchup category'] != category:
        raise ValueError('Categoria verificada difere da solicitada')
    if known(verified.get('Game version')) and known(requested.get('Game version')) and verified['Game version'] != requested['Game version']:
        raise ValueError('Patch verificado difere do solicitado')
    records = parse_rows(raw_text, champion, source.get('verified_empty_table', False))
    if len(records) != metadata['row_count']:
        raise ValueError(f'Contagem divergente: JSON={metadata["row_count"]}, TSV={len(records)}')
    if (metadata['parse_status'] == 'empty') != (len(records) == 0):
        raise ValueError('Status parsed/empty incompatível com os registros')
    url_parameters = source.get('url_parameters', {})
    context_hash = sha(dump({'requested':requested, 'verified':verified}).encode('utf-8'))
    values = {
        'capture_id':cid, 'run_id':run_id, 'selected_champion':champion,
        'selected_champion_normalized':normalized(champion), 'category':category,
        'collected_at_utc':timestamp, 'source_url':known(metadata.get('source_url')),
        'season_verified':known(verified.get('Season')), 'patch_verified':known(verified.get('Game version')),
        'split_verified':known(verified.get('Split')), 'tournament_verified':known(verified.get('Tournament')),
        'page_role_verified':known(verified.get('Page champion role')),
        'table_role_filter_verified':known(verified.get('Role filter')),
        'pick_selection_verified':known(verified.get('Pick Selection')),
        'minimum_games_verified':known(verified.get('Minimum game count')),
        'league_selections_verified_json':dump(verified['League selections']) if known(verified.get('League selections')) is not None else None,
        'season_url':known(url_parameters.get('season')), 'split_url':known(url_parameters.get('split')),
        'context_sha256':context_hash, 'raw_sha256':raw_hash, 'metadata_sha256':sha(metadata_bytes),
        'parse_status':metadata['parse_status'], 'row_count':len(records),
        'raw_text':raw_text, 'raw_bytes':raw, 'metadata_original':metadata_bytes.decode('utf-8-sig'),
        'metadata_bytes':metadata_bytes, 'requested_json':dump(requested), 'verified_json':dump(verified),
        'source_context_json':dump(source),
    }
    return values, records


def initialize(connection, existing):
    if existing:
        if (connection.execute('PRAGMA application_id').fetchone()[0] != APPLICATION_ID or
            connection.execute('PRAGMA user_version').fetchone()[0] != SCHEMA_VERSION):
            raise ValueError('Banco não pertence a este importador ou possui versão incompatível')
    else:
        for statement in SCHEMA:
            connection.execute(statement)
        connection.execute(f'PRAGMA application_id={APPLICATION_ID}')
        connection.execute(f'PRAGMA user_version={SCHEMA_VERSION}')


def import_directory(source, database, *, append=False, limit=None, run_id=None,
                     expect_captures=None, expect_records=None):
    source, database = Path(source), Path(database)
    if not source.is_dir():
        raise ValueError('Pasta de originais não encontrada; informe a pasta que contém os JSON/TXT')
    paths = sorted(source.glob('*.json'))
    if not paths:
        raise ValueError('Nenhum JSON encontrado diretamente na pasta informada')
    if limit is not None and limit < 1:
        raise ValueError('O limite deve ser positivo')
    existing = database.exists()
    if existing and not append:
        raise FileExistsError('Banco já existe; escolha outro nome ou use --append para importar sem duplicar')
    if database.resolve().parent == source.resolve() and database.suffix.lower() in ('.txt', '.json'):
        raise ValueError('Escolha um arquivo de banco separado dos originais')
    created = False
    if not existing:
        descriptor = os.open(database, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        os.close(descriptor)
        created = True
    connection = sqlite3.connect(database)
    report = {'schema_version':SCHEMA_VERSION, 'source_directory':str(source.resolve()),
              'database':str(database.resolve()), 'source_captures':0, 'source_records':0,
              'inserted_captures':0, 'inserted_records':0, 'already_imported_captures':0,
              'empty_captures':0, 'diagnostics_ignored':0, 'unvalidated_ignored':0,
              'other_runs_ignored':0, 'runs':{}, 'records_by_category':{}, 'captures_by_patch':{}}
    try:
        connection.execute('PRAGMA foreign_keys=ON')
        connection.execute('BEGIN IMMEDIATE')
        initialize(connection, existing)
        for path in paths:
            try:
                metadata_bytes = path.read_bytes()
                metadata = json.loads(metadata_bytes)
                if 'capture_id' not in metadata:
                    report['diagnostics_ignored'] += 1
                    continue
                if run_id and metadata.get('run_id') != run_id:
                    report['other_runs_ignored'] += 1
                    continue
                if metadata.get('parse_status') not in ('parsed', 'empty'):
                    report['unvalidated_ignored'] += 1
                    continue
                values, records = read_capture(path, metadata, metadata_bytes)
                cid = values['capture_id']
                old = connection.execute('SELECT raw_sha256, metadata_sha256, row_count, raw_bytes, metadata_bytes FROM capturas WHERE capture_id=?', (cid,)).fetchone()
                if old:
                    if old != (values['raw_sha256'], values['metadata_sha256'], len(records), values['raw_bytes'], values['metadata_bytes']):
                        raise ValueError('Capture ID já importado com conteúdo diferente')
                    stored = connection.execute('''SELECT record_index,related_champion,related_champion_normalized,source_role,
                        games,winrate,csd15,gd15,xpd15,kda,source_fields_json FROM registros
                        WHERE capture_id=? ORDER BY record_index''', (cid,)).fetchall()
                    if stored != records:
                        raise ValueError('Banco existente possui registros inconsistentes com os originais')
                    report['already_imported_captures'] += 1
                else:
                    columns = ','.join(values)
                    connection.execute(f'INSERT INTO capturas ({columns}) VALUES ({",".join("?" for _ in values)})', tuple(values.values()))
                    connection.executemany('INSERT INTO registros VALUES (?,?,?,?,?,?,?,?,?,?,?,?)',
                                           ((cid, *record) for record in records))
                    report['inserted_captures'] += 1
                    report['inserted_records'] += len(records)
                report['source_captures'] += 1
                report['source_records'] += len(records)
                report['empty_captures'] += not records
                for key, value, number in [('runs',values['run_id'],1),
                                           ('records_by_category',values['category'],len(records)),
                                           ('captures_by_patch',values['patch_verified'] or UNKNOWN,1)]:
                    report[key][value] = report[key].get(value,0) + number
                if report['source_captures'] % 500 == 0:
                    print(f'Conferidas: {report["source_captures"]} capturas / {report["source_records"]} registros', flush=True)
                if limit is not None and report['source_captures'] >= limit:
                    break
            except Exception as exc:
                raise ValueError(f'{path.name}: {exc}') from exc
        if not report['source_captures']:
            raise ValueError('Nenhuma captura validada encontrada para importar')
        for name, expected in [('source_captures', expect_captures), ('source_records', expect_records)]:
            if expected is not None and report[name] != expected:
                raise ValueError(f'Conferência falhou: {name}={report[name]}, esperado={expected}')
        if connection.execute('PRAGMA foreign_key_check').fetchone():
            raise ValueError('Falha de integridade referencial')
        if connection.execute('PRAGMA quick_check').fetchone()[0] != 'ok':
            raise ValueError('Falha de integridade do SQLite')
        report['database_captures'] = connection.execute('SELECT COUNT(*) FROM capturas').fetchone()[0]
        report['database_records'] = connection.execute('SELECT COUNT(*) FROM registros').fetchone()[0]
        connection.commit()
        report['status'] = 'committed'
        report['completed_at_utc'] = datetime.now(timezone.utc).isoformat()
        return report
    except BaseException:
        connection.rollback()
        raise
    finally:
        connection.close()
        if created and report.get('status') != 'committed':
            database.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description='Importa originais gol.gg em SQLite, sem navegador e sem dependências externas')
    parser.add_argument('--source', required=True, help='Pasta contendo diretamente os arquivos .json e .txt')
    parser.add_argument('--database', required=True, help='Arquivo SQLite novo; existente requer --append')
    parser.add_argument('--run-id', help='Importar somente esta execução')
    parser.add_argument('--limit', type=int, help='Teste limitado de capturas em um banco separado')
    parser.add_argument('--append', action='store_true', help='Adicionar sem substituir capturas; reimportação idêntica é ignorada')
    parser.add_argument('--expect-captures', type=int)
    parser.add_argument('--expect-records', type=int)
    args = parser.parse_args()
    try:
        report = import_directory(args.source, args.database, append=args.append, limit=args.limit,
                                  run_id=args.run_id, expect_captures=args.expect_captures,
                                  expect_records=args.expect_records)
    except (ValueError, OSError, sqlite3.Error) as exc:
        parser.exit(1, f'IMPORTAÇÃO CANCELADA (transação revertida): {exc}\n')
    report_path = Path(args.database).with_name(Path(args.database).stem + '.import-' + uuid.uuid4().hex[:8] + '.json')
    report_path.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False,indent=2))
    print('Relatório:', report_path)


if __name__ == '__main__':
    main()
