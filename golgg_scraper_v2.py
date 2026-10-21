import argparse
import io
import csv
import hashlib
import os
from urllib.parse import urlsplit, unquote
import time
from dataclasses import dataclass, field

import pandas as pd
import json
import math
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path


def load_browser_dependencies():
    # Browser/clipboard packages are only required for interactive collection.
    global pyperclip, webdriver, Service, By, Select, ChromeDriverManager
    import pyperclip
    from selenium import webdriver
    from selenium.webdriver.chrome.service import Service
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import Select
    from webdriver_manager.chrome import ChromeDriverManager


def normalize_name(text: str) -> str:
    return ' '.join(text.replace('\u00a0', ' ').strip().replace("'", '').split()).title()


UNKNOWN = 'unknown'
CATEGORY_LABELS = {'Direct_Matchup': 'Direct Matchup', 'Indirect_Matchup': 'Indirect Matchup',
                   'Ally_Synergy': 'Good with'}
CATEGORIES = tuple(CATEGORY_LABELS)
HEADERS = ['Campeao', 'Champion', 'Games', 'Winrate', 'Category', 'Source',
           'Source_URL', 'Season', 'Collected_At_UTC', 'Source_Role',
           'Requested_Filters', 'Verified_Active_Filters', 'Source_Fields',
           'CSD@15', 'GD@15', 'XPD@15', 'KDA', 'Capture_ID',
           'Selected_Champion_Normalized', 'Related_Champion_Normalized', 'Source_Context']
REQUESTED_FILTERS = dict.fromkeys(
    ('Season', 'Split', 'Tournament', 'Game version', 'Role filter', 'Pick Selection',
     'Page champion role', 'League selections', 'Minimum game count'), UNKNOWN)
CONTROL_FIELDS = {'cbchampselect': 'Selected champion', 'patch': 'Game version',
                  'cbtournament': 'Tournament', 'rolefilter': 'Role filter',
                  'pickfilter': 'Pick Selection'}


@dataclass
class ScrapeResult:
    champion: str
    category: str
    opponent: str
    games: int | None
    winrate: float | None
    role: str = UNKNOWN
    source: str = UNKNOWN
    source_url: str = UNKNOWN
    season: str = UNKNOWN
    collected_at_utc: str = UNKNOWN
    requested_filters: dict = field(default_factory=dict)
    verified_active_filters: dict = field(default_factory=dict)
    source_fields: dict = field(default_factory=dict)
    csd15: float | None = None
    gd15: float | None = None
    xpd15: float | None = None
    kda: float | None = None
    capture_id: str = UNKNOWN
    source_context: dict = field(default_factory=dict)


def init_driver(headless: bool = False):
    options = webdriver.ChromeOptions()
    if headless:
        options.add_argument('--headless=new')
    options.add_argument('--disable-gpu')
    options.add_argument('--window-size=1600,1000')
    options.add_argument('--no-sandbox')
    options.add_argument('--disable-dev-shm-usage')
    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=options)
    return driver


def click_tab(driver, label: str):
    possible = driver.find_elements(By.XPATH, "//button|//a|//div[@role='tab']")
    for el in possible:
        text = el.text.strip().lower()
        if el.is_displayed() and label.lower() == text:
            driver.execute_script('arguments[0].click();', el)
            return True
    return False


def click_copy_table(driver) -> str:
    # Never mistake clipboard content from a previous table for a new copy.
    sentinel = 'golgg-copy-' + uuid.uuid4().hex
    buttons = driver.find_elements(By.XPATH, "//*[normalize-space(text())='Copy table to clipboard']")
    visible = [b for b in buttons if b.is_displayed() and
               b.text.strip() == 'Copy table to clipboard']
    if len(visible) != 1:
        raise RuntimeError('É necessário exatamente um botão de cópia visível; confira a tabela.')
    pyperclip.copy(sentinel)
    webdriver.ActionChains(driver).move_to_element(visible[0]).click(visible[0]).perform()
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        text = pyperclip.paste()
        if text != sentinel:
            return text
        time.sleep(.1)
    raise RuntimeError('A cópia não atualizou o clipboard; captura não realizada.')


def parse_clipboard_table(table_text: str) -> pd.DataFrame:
    """Parse copied TSV without guessing whitespace-separated champion names."""
    if not table_text.strip():
        return pd.DataFrame()
    rows = list(csv.reader(io.StringIO(table_text), delimiter='\t'))
    headers, values = rows[0], rows[1:]
    if len(headers) != len(set(headers)):
        raise ValueError('Duplicate source headers; preserved in raw capture, cannot map unambiguously')
    if any(len(row) != len(headers) for row in values):
        raise ValueError('Ragged TSV rows; preserved in raw capture')
    return pd.DataFrame(values, columns=headers)


def parse_games(value) -> int:
    text = str(value).strip()
    # Accept integral counts and conventional comma thousands, never truncate.
    if not re.fullmatch(r'(?:[0-9]+|[0-9]{1,3}(?:,[0-9]{3})+)(?:\.0+)?', text):
        raise ValueError(f'invalid Games: {value!r}')
    return int(text.replace(',', '').split('.')[0])


def parse_winrate(value) -> float:
    text = str(value).strip()
    percent = text.endswith('%')
    text = text.removesuffix('%').strip().replace(',', '.')
    try:
        number = float(text)
    except (ValueError, TypeError):
        raise ValueError(f'invalid Winrate: {value!r}') from None
    # Bare values must already be fractions; do not guess whether 1 means 1%.
    if percent:
        number /= 100
    if not math.isfinite(number) or not 0 <= number <= 1:
        raise ValueError(f'invalid Winrate: {value!r}')
    return number


def missing_number(value):
    return value is None or (not isinstance(value, str) and pd.isna(value)) or (
        isinstance(value, str) and value.strip().casefold() in {'', '-', '—', 'n/a', 'na'})


def optional_number(value, parser):
    return None if missing_number(value) else parser(value)


def parse_stat(value):
    text = str(value).strip().replace('−', '-').replace(',', '.')
    try:
        result = float(text)
    except (TypeError, ValueError):
        raise ValueError(f'invalid statistic: {value!r}') from None
    if not math.isfinite(result):
        raise ValueError(f'invalid statistic: {value!r}')
    return result


def original_value(value):
    # JSON-safe source scalars, retaining blanks and numeric types from Excel.
    if value is None or (not isinstance(value, str) and pd.isna(value)):
        return None
    return value.item() if hasattr(value, 'item') else value


def source_value(value):
    return UNKNOWN if pd.isna(value) or value == '' else str(value)


def parse_table(champion, df, category, source=UNKNOWN, **metadata):
    if category not in CATEGORIES:
        raise ValueError(f'Unknown category: {category}')
    if df.empty:
        return []
    aliases = {'name': {'champion', 'opponent', 'ally', 'with', 'vs'},
               'games': {'games', '# games'}, 'winrate': {'winrate', 'win rate'}}
    columns = {}
    for key, names in aliases.items():
        matches = [c for c in df.columns if str(c).strip().lower() in names or (
            key == 'winrate' and normalize_name(str(c).removesuffix(' Winrate')) == normalize_name(champion)
            and str(c).endswith(' Winrate'))]
        if len(matches) != 1:
            raise ValueError(f'{category}: expected one {key} column, got {matches!r}')
        columns[key] = matches[0]
    roles = [c for c in df.columns if str(c).strip().lower() == 'role']
    rows, errors = [], []
    for index, (_, row) in enumerate(df.iterrows(), start=2):
        try:
            opponent = source_value(row[columns['name']])
            if opponent == UNKNOWN or not opponent.strip():
                raise ValueError('missing related champion')
            rows.append(ScrapeResult(
                champion=champion, category=category, opponent=opponent,
                games=optional_number(row[columns['games']], parse_games),
                winrate=optional_number(row[columns['winrate']], parse_winrate),
                role=source_value(row[roles[0]]) if len(roles) == 1 else UNKNOWN,
                source=source,
                source_fields={str(c): original_value(row[c]) for c in df.columns},
                **{attr: optional_number(row[label], parse_stat) if label in df.columns else None
                   for label, attr in [('CSD@15', 'csd15'), ('GD@15', 'gd15'),
                                       ('XPD@15', 'xpd15'), ('KDA', 'kda')]},
                **metadata))
        except ValueError as exc:
            errors.append(f'{champion} / {category} / row {index}: {exc}; raw={row.to_dict()!r}')
    if errors:
        raise ValueError('Malformed records; export aborted:\n' + '\n'.join(errors))
    return rows


def parse_vs_table(champion, df, source, **metadata):
    categories = {'Direct Matchup': 'Direct_Matchup', 'Indirect Matchup': 'Indirect_Matchup'}
    if source not in categories:
        raise ValueError(f'Unknown matchup source: {source}')
    return parse_table(champion, df, categories[source], source, **metadata)


def parse_with_table(champion, df, **metadata):
    return parse_table(champion, df, 'Ally_Synergy', 'Good with', **metadata)


def save_results(results, output_path, *, overwrite=False, source_headers=None):
    """Write one fresh snapshot; never combine, deduplicate or append rows."""
    from openpyxl import Workbook
    output_path = Path(output_path)
    if output_path.exists() and not overwrite:
        raise FileExistsError(f'Refusing to overwrite {output_path}; use --overwrite explicitly.')
    if source_headers is None:
        results = list(results)
        source_headers = list(dict.fromkeys(key for r in results for key in r.source_fields))
    if isinstance(results, list):
        for record in results:
            if record.games is not None:
                parse_games(record.games)
            if record.winrate is not None:
                parse_winrate(record.winrate)
    workbook = Workbook(write_only=True)
    for category in CATEGORIES:
        workbook.create_sheet(category).append(HEADERS + ['Source::' + key for key in source_headers])
    for record in results:
        if record.category not in CATEGORIES:
            raise ValueError(f'Unknown category: {record.category}')
        games = None if record.games is None else parse_games(record.games)
        winrate = None if record.winrate is None else parse_winrate(record.winrate)
        values = [record.champion, record.opponent, games, winrate,
                  record.category, record.source, record.source_url, record.season,
                  record.collected_at_utc, record.role,
                  json.dumps(record.requested_filters or UNKNOWN, ensure_ascii=False),
                  json.dumps(record.verified_active_filters or UNKNOWN, ensure_ascii=False),
                  json.dumps(record.source_fields or UNKNOWN, ensure_ascii=False),
                  *[optional_number(getattr(record, attr), parse_stat)
                    for attr in ('csd15', 'gd15', 'xpd15', 'kda')], record.capture_id,
                  normalize_name(record.champion), normalize_name(record.opponent),
                  json.dumps(record.source_context or UNKNOWN, ensure_ascii=False)]
        sheet = workbook[record.category]
        from openpyxl.cell import WriteOnlyCell
        cells = [WriteOnlyCell(sheet, value=value) for value in
                 values + [record.source_fields.get(key) for key in source_headers]]
        for cell in cells:
            if isinstance(cell.value, str):
                cell.data_type = 's'
        cells[3].number_format = '0.00%'
        sheet.append(cells)
    # Exclusive creation also prevents a race with another exporter.
    with output_path.open('wb' if overwrite else 'xb') as destination:
        workbook.save(destination)


def write_json(path, data):
    temporary = path.with_suffix('.json.tmp')
    with temporary.open('w', encoding='utf-8') as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2, allow_nan=False)
        handle.flush()
        os.fsync(handle.fileno())
    temporary.replace(path)


def begin_capture(text, champion, category, directory, *, source_url=UNKNOWN,
                  verified=None, requested=None, source_context=None, run_id=UNKNOWN):
    """Durably save original text before any subsequent browser/parse operation."""
    capture_id = uuid.uuid4().hex
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    desired = dict(REQUESTED_FILTERS)
    desired.update({'Selected champion': champion, 'Matchup category': category, 'Source URL': UNKNOWN})
    desired.update(requested or {})
    observed = dict.fromkeys(desired, UNKNOWN)
    observed.update(verified or {})
    observed['Source URL'] = source_url
    metadata = dict(capture_id=capture_id, run_id=run_id, source_url=source_url,
                    collected_at_utc=datetime.now(timezone.utc).isoformat(),
                    requested=desired, verified=observed, raw_file=capture_id + '.txt',
                    parse_status='pending', source_context=source_context or {},
                    raw_sha256=hashlib.sha256(text.encode('utf-8')).hexdigest())
    path = directory / (capture_id + '.json')
    with path.with_suffix('.txt').open('xb') as handle:
        handle.write(text.encode('utf-8'))
        handle.flush()
        os.fsync(handle.fileno())
    write_json(path, metadata)
    return path, metadata


def capture_rows(path, metadata):
    raw = path.with_suffix('.txt').read_bytes()
    if metadata.get('raw_sha256') and hashlib.sha256(raw).hexdigest() != metadata['raw_sha256']:
        raise ValueError('Raw capture checksum mismatch: ' + str(path))
    text = raw.decode('utf-8')
    category = metadata['requested']['Matchup category']
    if metadata['source_context'].get('verified_empty_table'):
        return []
    return parse_table(metadata['requested']['Selected champion'], parse_clipboard_table(text),
                       category, CATEGORY_LABELS[category], source_url=metadata['source_url'],
                       season=metadata['verified'].get('Season', UNKNOWN),
                       collected_at_utc=metadata['collected_at_utc'],
                       requested_filters=metadata['requested'], verified_active_filters=metadata['verified'],
                       capture_id=metadata['capture_id'], source_context=metadata['source_context'])


def finish_capture(path, metadata, validation_error=None):
    try:
        if validation_error:
            raise ValueError(validation_error)
        rows = capture_rows(path, metadata)
        metadata.update(parse_status='parsed' if rows else 'empty', row_count=len(rows))
        return rows
    except BaseException as exc:
        metadata.update(parse_status='failed', error=str(exc) or type(exc).__name__)
        raise
    finally:
        write_json(path, metadata)


def preserve_capture(text, champion, category, directory, *, validation_error=None, **context):
    path, metadata = begin_capture(text, champion, category, directory, **context)
    return finish_capture(path, metadata, validation_error)


def export_captures(paths, output, *, overwrite=False):
    """One run, one snapshot; never sum attempts or silently remove repeated rows."""
    paths = list(paths)
    run_ids, ids, headers = set(), set(), {}
    for path in paths:
        metadata = json.loads(path.read_text(encoding='utf-8'))
        if metadata.get('run_id', UNKNOWN) == UNKNOWN:
            raise ValueError('Cannot safely rebuild captures without a known run ID')
        run_ids.add(metadata['run_id'])
        if metadata['capture_id'] in ids:
            raise ValueError('Duplicate capture ID; refusing duplicate import')
        ids.add(metadata['capture_id'])
        if metadata['parse_status'] not in ('parsed', 'empty'):
            raise ValueError('Capture is not validated: ' + str(path))
        capture_rows(path, metadata)  # Validate every capture before opening an Excel writer.
        text = path.with_suffix('.txt').read_bytes().decode('utf-8')
        columns = (next(csv.reader(io.StringIO(text), delimiter='\t'), [])
                   if metadata['source_context'].get('verified_empty_table')
                   else parse_clipboard_table(text).columns)
        headers.update(dict.fromkeys(columns))
    if len(run_ids) > 1:
        raise ValueError('Cannot combine captures from different runs')
    def records():
        for path in paths:
            yield from capture_rows(path, json.loads(path.read_text(encoding='utf-8')))
    save_results(records(), output, overwrite=overwrite, source_headers=list(headers))


def verified_context(state, controls):
    verified = {'Selected champion': state['champion'], 'Game version': state['patch']}
    for control in controls:
        if control.get('id') in CONTROL_FIELDS and len(control.get('selected', [])) == 1:
            selected = control['selected'][0]
            verified[CONTROL_FIELDS[control['id']]] = selected['text'].strip()
    # URL parameters are source evidence, not proof that a filter is active.
    parameters = {}
    for part in urlsplit(state['url']).path.split('/'):
        key, separator, value = part.partition('-')
        if separator and key in {'season','split','tournament','patch','role','league'}:
            parameters[key] = unquote(value)
    return verified, {'visible_selects': controls, 'url_parameters': parameters}


def read_source_controls(driver):
    """Keep visible select settings without guessing which control means what.

    Deliberately exclude text/password inputs and credential fields.
    """
    return driver.execute_script("""
        return [...document.querySelectorAll('select')]
          .filter(e => e.getClientRects().length)
          .map(e => ({id:e.id, name:e.name, aria_label:e.getAttribute('aria-label'),
             labels:[...(e.labels || [])].map(l => l.textContent),
             selected:[...e.selectedOptions].map(o => ({text:o.textContent, value:o.value}))}));
    """)


def option_pairs(options, *, patches=False):
    """Read live options rather than a fixed champion/patch list. Exclude ALL."""
    pairs = [(o.text.strip(), o.get_attribute('value')) for o in options
             if o.is_enabled() and o.get_attribute('value') and
             o.text.strip() and 'empty' not in o.text.casefold()]
    if patches:
        pairs = [(text, value) for text, value in pairs if re.fullmatch(r'\d+\.\d+', text)]
    return pairs


def browser_state(driver):
    return driver.execute_script("""
        const selected = id => {
          const e=document.getElementById(id);
          return e && e.selectedOptions.length ? e.selectedOptions[0].textContent.trim() : 'unknown';
        };
        const visible = e => e.getClientRects().length > 0;
        let table=window.golggObservedTable;
        if (!table || !table.isConnected || !visible(table))
          table=[...document.querySelectorAll('table')].filter(visible).find(t => [...t.querySelectorAll('th,td')].some(h =>
          /.+\\s+winrate/i.test(h.textContent.trim())));
        let rows=table ? [...table.querySelectorAll('tr')].map(r =>
          [...r.querySelectorAll(':scope > th, :scope > td')].map(c => c.textContent)) : [];
        if (table && window.golggObservedTable !== table) {
          if(window.golggTableObserver) window.golggTableObserver.disconnect();
          window.golggObservedTable=table;
          window.golggRevision=(window.golggRevision || 0)+1;
          window.golggTableObserver=new MutationObserver(() => window.golggRevision++);
          window.golggTableObserver.observe(table,{subtree:true,childList:true,characterData:true});
        }
        const empty=!!(table && [...table.querySelectorAll('td')].some(c =>
          /no (data|records|matching records)|no games/i.test(c.textContent.trim()) && c.colSpan > 1));
        return {champion:selected('cbchampselect'), patch:selected('patch'), rows, empty,
          url:location.href, origin:performance.timeOrigin, revision:window.golggRevision || 0,
          busy:document.readyState !== 'complete' || !!(window.jQuery && window.jQuery.active),
          category:[...document.querySelectorAll('a,button')].filter(visible).filter(e =>
            e.matches('.active,[aria-selected="true"]') || e.parentElement.matches('li.active'))
            .map(e => e.textContent.trim())};
    """)


def table_identity(state, champion, patch, category=None):
    return (not state['busy'] and normalize_name(state['champion']) == normalize_name(champion)
            and (patch is None or state['patch'] == patch) and bool(state['rows'])
            and (category is None or category in state['category'])
            and any(normalize_name(h.strip()[:-8]) == normalize_name(champion)
                    for h in state['rows'][0] if h.strip().lower().endswith(' winrate')))


def wait_table(driver, champion, patch, before=None, *, timeout=30, category=None):
    deadline = time.monotonic() + timeout
    previous, stable_since = None, None
    while time.monotonic() < deadline:
        state = browser_state(driver)
        transition = before is None or any(state[k] != before[k] for k in
                                            ('url', 'origin', 'revision', 'rows', 'category'))
        signature = json.dumps({k: state[k] for k in ('champion', 'patch', 'rows', 'url', 'category', 'empty')})
        if table_identity(state, champion, patch, category) and transition:
            if signature != previous:
                previous, stable_since = signature, time.monotonic()
            elif time.monotonic() - stable_since >= 2:
                return state
        else:
            previous, stable_since = None, None
        time.sleep(.25)
    raise RuntimeError('Tabela não confirmou campeão/patch e atualização estável; captura interrompida.')


def change_control(driver, control_id, value, champion, patch):
    before = browser_state(driver)
    control = Select(driver.find_element(By.ID, control_id))
    changed = control.first_selected_option.get_attribute('value') != value
    if changed:
        control.select_by_value(value)
    return wait_table(driver, champion, patch, before if changed else None)


def clipboard_matches(text, state):
    copied = list(csv.reader(io.StringIO(text), delimiter='\t'))
    clean = lambda rows: [[' '.join(str(c).split()).casefold() for c in row] for row in rows]
    return (clean(copied) == clean(state['rows']) or
            (state.get('empty', False) and clean(copied) in ([], clean(state['rows'][:1]))))


def collect_table(driver, champion, patch, category, directory, run_id, requested,
                  *, confirm=False):
    label = CATEGORY_LABELS[category]
    before = browser_state(driver)
    if label not in before['category']:
        if not click_tab(driver, label):
            raise RuntimeError('Aba não encontrada: ' + label)
        state = wait_table(driver, champion, patch, before, category=label)
    else:
        state = wait_table(driver, champion, patch, category=label)
    if confirm:
        input(f'Confira {champion} / {patch} / {label} e pressione Enter...')
        state = wait_table(driver, champion, patch, category=label)
    controls = read_source_controls(driver)
    verified, source_context = verified_context(state, controls)
    verified['Matchup category'] = category
    source_context['verified_empty_table'] = state.get('empty', False)
    text = click_copy_table(driver)
    # The very next operation persists the clipboard. All later failures have a
    # pending/failed sidecar and raw text available for review/reprocessing.
    path, metadata = begin_capture(text, champion, category, directory,
        source_url=state['url'], verified=verified, requested=requested,
        source_context=source_context, run_id=run_id)
    try:
        after = browser_state(driver)
        if (not table_identity(after, champion, patch, label)
                or any(state.get(k) != after.get(k) for k in ('rows', 'url', 'revision', 'origin', 'empty'))
                or controls != read_source_controls(driver)
                or not clipboard_matches(text, after)):
            raise ValueError('Tabela/filtros mudaram durante a cópia ou clipboard divergente.')
    except BaseException as exc:
        metadata.update(parse_status='failed', error=str(exc) or type(exc).__name__)
        write_json(path, metadata)
        raise
    rows = finish_capture(path, metadata)
    return path, len(rows)


def main():
    parser = argparse.ArgumentParser(description='Collect champions and individual patches; preserve original data')
    parser.add_argument('--output', default='golgg_champion_synergy_v2.xlsx')
    parser.add_argument('--captures-dir', default='golgg_raw_captures')
    parser.add_argument('--champions', nargs='+')
    parser.add_argument('--versions', nargs='+', help='Default: all numbered patches, excluding ALL')
    parser.add_argument('--limit', type=int, default=None)
    parser.add_argument('--start-url', default='https://gol.gg/')
    parser.add_argument('--confirm-tables', action='store_true')
    parser.add_argument('--overwrite', action='store_true')
    parser.add_argument('--rebuild-captures', metavar='DIRECTORY', help='Offline rebuild from one existing run')
    parser.add_argument('--run-id', help='Required only with --rebuild-captures')
    args = parser.parse_args()
    if Path(args.output).exists() and not args.overwrite:
        parser.error('Output already exists; choose a new path or explicitly use --overwrite.')
    if args.limit is not None and args.limit < 1:
        parser.error('--limit must be positive')
    if bool(args.rebuild_captures) != bool(args.run_id):
        parser.error('--rebuild-captures and --run-id must be used together')
    if args.rebuild_captures:
        paths = []
        for path in Path(args.rebuild_captures).glob('*.json'):
            metadata = json.loads(path.read_text(encoding='utf-8'))
            if metadata.get('run_id') == args.run_id:
                if metadata['parse_status'] in ('parsed', 'empty'):
                    paths.append(path)
                else:
                    print('Captura não validada, excluída da reconstrução:', path.name)
        if not paths:
            parser.error('No validated captures found for this run ID')
        paths.sort(key=lambda p: json.loads(p.read_text(encoding='utf-8'))['collected_at_utc'])
        export_captures(paths, args.output, overwrite=args.overwrite)
        print('Reconstruído sem browser ou clipboard:', args.output)
        return
    load_browser_dependencies()
    driver = init_driver(headless=False)
    paths, run_id, complete = [], uuid.uuid4().hex, False
    print('Run ID:', run_id, '| Originais:', Path(args.captures_dir).resolve())
    try:
        driver.get(args.start_url)
        input('Faça login, abra Champion Synergy, ajuste os demais filtros e pressione Enter...')
        champions = option_pairs(Select(driver.find_element(By.ID, 'cbchampselect')).options)
        if args.champions:
            wanted = {normalize_name(c) for c in args.champions}
            champions = [(t,v) for t,v in champions if normalize_name(t) in wanted]
            if {normalize_name(t) for t,v in champions} != wanted:
                raise ValueError('Campeão solicitado não encontrado no seletor.')
        if args.limit is not None:
            champions = champions[:args.limit]
        versions = option_pairs(Select(driver.find_element(By.ID, 'patch')).options, patches=True)
        if args.versions:
            versions = [(t,v) for t,v in versions if t in args.versions]
            if {t for t,v in versions} != set(args.versions):
                raise ValueError('Versão solicitada não encontrada; ALL não é patch individual.')
        if not champions or not versions:
            raise ValueError('Nenhum campeão ou patch individual disponível.')
        initial = browser_state(driver)
        baseline, _ = verified_context(initial, read_source_controls(driver))
        total = len(champions) * len(versions) * len(CATEGORIES)
        print('Plano:', len(champions), 'campeões x', len(versions), 'patches x 3 categorias.')
        # Keep the proven traversal order; changing it requires live measurements.
        for patch, patch_value in versions:
            for champion, champion_value in champions:
                change_control(driver, 'cbchampselect', champion_value, champion, None)
                change_control(driver, 'patch', patch_value, champion, patch)
                for category in CATEGORIES:
                    requested = dict(baseline, **{'Selected champion': champion, 'Game version': patch})
                    path, count = collect_table(driver, champion, patch, category,
                        args.captures_dir, run_id, requested, confirm=args.confirm_tables)
                    paths.append(path)
                    print(f'[{len(paths)}/{total}] {champion} / {patch} / {CATEGORY_LABELS[category]}: {count} linhas')
        complete = True
    finally:
        try:
            export_captures(paths, args.output, overwrite=args.overwrite)
            print('Coleta concluída.' if complete else 'Coleta interrompida; resultado parcial.')
            print('Excel:', args.output, '| Capturas validadas:', len(paths), '| Run ID:', run_id)
        finally:
            driver.quit()


if __name__ == '__main__':
    main()
