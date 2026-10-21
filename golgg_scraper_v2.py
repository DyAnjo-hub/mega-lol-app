import argparse
import io
import time
from dataclasses import dataclass
from typing import List

import pandas as pd
import json
import math
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from dataclasses import field


def load_browser_dependencies():
    # Browser/clipboard packages are only required for interactive collection.
    global pyperclip, webdriver, Service, By, EC, Select, WebDriverWait, ChromeDriverManager
    import pyperclip
    from selenium import webdriver
    from selenium.webdriver.chrome.service import Service
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.webdriver.support.ui import Select, WebDriverWait
    from webdriver_manager.chrome import ChromeDriverManager


SEASON = 'S16'
SPLIT = 'ALL'
TOURNAMENT = 'ALL'
BASE_URL = 'https://gol.gg/premium/champion-synergy/1/season-{season}/split-{split}/tournament-{tournament}/'

CHAMPION_NAMES = {
    'Aatrox','Ahri','Akali','Akshan','Alistar','Amumu','Anivia','Annie','Aphelios','Ashe','Aurelion Sol',
    'Azir','Bard','Belveth','Blitzcrank','Brand','Braum','Caitlyn','Camille','Cassiopeia','Cho Gath','Corki',
    'Darius','Diana','Dr Mundo','Draven','Ekko','Elise','Evelynn','Ezreal','Fiddlesticks','Fiora','Fizz',
    'Galio','Gangplank','Garen','Gnar','Gragas','Graves','Gwen','Hecarim','Heimerdinger','Illaoi','Irelia','Ivern',
    'Janna','Jarvan IV','Jax','Jayce','Jhin','Jinx','Kai Sa','Kalista','Karma','Karthus','Kassadin','Katarina','Kayle',
    'Kayn','Kennen','Kha Zix','Kindred','Kled','Kog Maw','Leblanc','Lee Sin','Leona','Lillia','Lissandra','Lucian',
    'Lulu','Lux','Malphite','Malzahar','Maokai','Master Yi','Miss Fortune','Mordekaiser','Morgana','Nami','Nasus',
    'Nautilus','Neeko','Nidalee','Nilah','Nocturne','Nunu & Willump','Olaf','Orianna','Ornn','Pantheon','Poppy',
    'Pyke','Qiyana','Quinn','Rakan','Rammus','Rek Sai','Renata Glasc','Renekton','Rengar','Riven','Rumble','Ryze',
    'Samira','Sejuani','Senna','Seraphine','Sett','Shaco','Shen','Shyvana','Singed','Sion','Sivir','Skarner','Sona',
    'Soraka','Swain','Sylas','Syndra','Tahm Kench','Taliyah','Talon','Taric','Teemo','Thresh','Tristana','Trundle',
    'Tryndamere','Twisted Fate','Twitch','Udyr','Urgot','Varus','Vayne','Veigar','Vel Koz','Vi','Viego',
    'Viktor','Vladimir','Volibear','Warwick','Wukong','Xayah','Xerath','Xin Zhao','Yasuo','Yone','Yorick','Yuumi',
    'Zac','Zed','Ziggs','Zilean','Zoe','Zyra'
}


def normalize_name(text: str) -> str:
    return ' '.join(text.replace('\u00a0', ' ').strip().replace("'", '').split()).title()


def is_champion_name(text: str) -> bool:
    if not text:
        return False
    return normalize_name(text) in CHAMPION_NAMES or text.strip() in CHAMPION_NAMES


UNKNOWN = 'unknown'
CATEGORIES = ('Direct_Matchup', 'Indirect_Matchup', 'Ally_Synergy')
HEADERS = ['Campeao', 'Champion', 'Games', 'Winrate', 'Category', 'Source',
           'Source_URL', 'Season', 'Collected_At_UTC', 'Source_Role',
           'Requested_Filters', 'Verified_Active_Filters', 'Source_Fields',
           'CSD@15', 'GD@15', 'XPD@15', 'KDA', 'Capture_ID',
           'Selected_Champion_Normalized', 'Related_Champion_Normalized', 'Source_Context']
REQUESTED_FILTERS = {'Season': SEASON, 'Split': SPLIT, 'Tournament': TOURNAMENT,
                     'Game version': 'ALL', 'Role filter': 'ALL', 'Pick Selection': 'ALL',
                     'Page champion role': UNKNOWN, 'League selections': UNKNOWN,
                     'Minimum game count': UNKNOWN}


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


def wait_for(driver, locator, timeout=20):
    return WebDriverWait(driver, timeout).until(EC.presence_of_element_located(locator))


def find_champion_select(driver):
    selects = driver.find_elements(By.TAG_NAME, 'select')
    best = None
    best_champ_count = 0
    for sel in selects:
        try:
            options = Select(sel).options
        except Exception:
            continue
        champ_count = sum(1 for opt in options if is_champion_name(opt.text))
        if champ_count > best_champ_count:
            best_champ_count = champ_count
            best = sel
    if best is None or best_champ_count == 0:
        raise RuntimeError('Não encontrei a lista de campeões no site.')
    return best


def get_champion_list(driver) -> List[str]:
    select = find_champion_select(driver)
    options = Select(select).options
    champions = [opt.text.strip() for opt in options if opt.text.strip() and is_champion_name(opt.text)]
    return sorted(set(champions))


def click_tab(driver, label: str):
    possible = driver.find_elements(By.XPATH, "//button|//a|//div[@role='tab']")
    for el in possible:
        text = el.text.strip().lower()
        if el.is_displayed() and label.lower() == text:
            driver.execute_script('arguments[0].click();', el)
            time.sleep(1.0)
            return True
    return False


def click_element_by_text(driver, text: str, exact: bool = False) -> bool:
    if exact:
        xpath = f"//*[normalize-space(text())='{text}']"
    else:
        xpath = f"//*[contains(normalize-space(text()), '{text}') ]"
    candidates = driver.find_elements(By.XPATH, xpath)
    for el in candidates:
        if el.is_displayed():
            try:
                driver.execute_script('arguments[0].click();', el)
                time.sleep(0.5)
                return True
            except Exception:
                continue
    return False


def select_champion_custom(driver, champion_name: str) -> bool:
    current = driver.find_elements(By.XPATH, "//*[contains(text(), 'Aatrox') or contains(text(), 'Champion') or contains(text(), 'Select')]")
    for el in current:
        if el.is_displayed():
            try:
                driver.execute_script('arguments[0].click();', el)
                time.sleep(1.0)
                break
            except Exception:
                continue

    for xpath in ["//*[@role='option']", "//li", "//div[contains(@class,'option') or contains(@class,'item') or contains(@class,'dropdown')]"]:
        for el in driver.find_elements(By.XPATH, xpath):
            if el.text.strip().lower() == champion_name.lower() and el.is_displayed():
                try:
                    driver.execute_script('arguments[0].click();', el)
                    time.sleep(1.5)
                    return True
                except Exception:
                    continue
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
    import csv
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


def save_results(results, output_path, *, overwrite=False):
    """Write one fresh snapshot; never combine, deduplicate or append rows."""
    from openpyxl import Workbook
    output_path = Path(output_path)
    if output_path.exists() and not overwrite:
        raise FileExistsError(f'Refusing to overwrite {output_path}; use --overwrite explicitly.')
    results = list(results)
    source_headers = list(dict.fromkeys(key for r in results for key in r.source_fields))
    workbook = Workbook()
    workbook.remove(workbook.active)
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
        sheet.append(values + [record.source_fields.get(key) for key in source_headers])
        # Keep source strings literal, including strings beginning with '='.
        for cell in sheet[sheet.max_row]:
            if isinstance(cell.value, str):
                cell.data_type = 's'
        sheet.cell(sheet.max_row, 4).number_format = '0.00%'
    # Exclusive creation also prevents a race with another exporter.
    with output_path.open('wb' if overwrite else 'xb') as destination:
        workbook.save(destination)


def apply_filters(driver):
    """Do not change unidentified dropdowns or claim requested values are active.

    A label/selector contract has not been verified against live gol.gg markup.
    Users can set filters interactively; their active state remains unknown here.
    """
    return {name: UNKNOWN for name in REQUESTED_FILTERS}


def preserve_capture(text, champion, category, directory, *, source_url=UNKNOWN,
                     verified=None, requested=None, source_context=None):
    """Persist untouched clipboard text and context before parsing.

    Failed parses keep both original files. No append/merge/deduplication occurs.
    """
    categories = {'Direct_Matchup': 'Direct Matchup',
                  'Indirect_Matchup': 'Indirect Matchup', 'Ally_Synergy': 'Good with'}
    capture_id = uuid.uuid4().hex
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    collected = datetime.now(timezone.utc).isoformat()
    desired = dict(REQUESTED_FILTERS)
    desired.update({'Selected champion': champion, 'Matchup category': category, 'Source URL': UNKNOWN})
    desired.update(requested or {})
    observed = {key: UNKNOWN for key in desired}
    observed.update(verified or {})
    observed['Source URL'] = source_url
    metadata = dict(capture_id=capture_id, source_url=source_url,
                    collected_at_utc=collected, requested=desired, verified=observed,
                    raw_file=capture_id + '.txt', parse_status='pending',
                    source_context=source_context or {})
    raw_path = directory / (capture_id + '.txt')
    metadata_path = directory / (capture_id + '.json')
    # Binary UTF-8 avoids newline conversion on Windows; original text is exact.
    with raw_path.open('xb') as handle:
        handle.write(text.encode('utf-8'))
    with metadata_path.open('x', encoding='utf-8') as handle:
        json.dump(metadata, handle, ensure_ascii=False, indent=2)
    try:
        rows = parse_table(champion, parse_clipboard_table(text), category,
                           categories[category], source_url=source_url,
                           season=observed.get('Season', UNKNOWN),
                           collected_at_utc=collected, requested_filters=desired,
                           verified_active_filters=observed, capture_id=capture_id,
                           source_context=source_context or {})
        metadata.update(parse_status='parsed' if rows else 'empty', row_count=len(rows))
        return rows
    except Exception as exc:
        metadata.update(parse_status='failed', error=str(exc))
        raise
    finally:
        metadata_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding='utf-8')


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


def main():
    parser = argparse.ArgumentParser(description='Preserve gol.gg tables and original clipboard captures')
    parser.add_argument('--output', default='golgg_champion_synergy_v2.xlsx', help='New Excel output file')
    parser.add_argument('--captures-dir', default='golgg_raw_captures', help='Directory for unique UTF-8 captures and metadata')
    parser.add_argument('--limit', type=int, default=None)
    parser.add_argument('--champions', nargs='*', default=None)
    parser.add_argument('--overwrite', action='store_true', help='Explicitly allow replacing output')
    args = parser.parse_args()
    if Path(args.output).exists() and not args.overwrite:
        parser.error('Output already exists; choose a new path or explicitly use --overwrite.')
    load_browser_dependencies()
    driver = init_driver(headless=False)
    try:
        driver.get(BASE_URL.format(season=SEASON, split=SPLIT, tournament=TOURNAMENT))
        print('Faça login e ajuste os filtros manualmente. Solicitados:', REQUESTED_FILTERS)
        input('Quando estiver logado e a página carregada, pressione Enter...')
        print('Filtros não verificados são registrados como unknown, nunca como ALL.')
        champions = args.champions or get_champion_list(driver)
        if args.limit is not None:
            champions = champions[:args.limit]
        results = []
        for champ in champions:
            verified_champion = UNKNOWN
            try:
                select = find_champion_select(driver)
                Select(select).select_by_visible_text(champ)
                time.sleep(1.5)
                actual = Select(find_champion_select(driver)).first_selected_option.text
                if normalize_name(actual) == normalize_name(champ):
                    verified_champion = actual
            except Exception:
                if not select_champion_custom(driver, champ):
                    print('Não foi possível selecionar:', champ)
                    continue
            for category, label in [('Direct_Matchup', 'Direct Matchup'),
                                    ('Indirect_Matchup', 'Indirect Matchup'),
                                    ('Ally_Synergy', 'Good with')]:
                if not click_tab(driver, label):
                    print('Aba não encontrada:', champ, label)
                    continue
                # Live DOM/update signals are unverified. Preserve the interactive
                # workflow and require visual confirmation rather than pretend a
                # fixed sleep proves that an asynchronous table has finished.
                input(f'Confira {champ} / {label}, aguarde a atualização da tabela e pressione Enter para copiar...')
                try:
                    text = click_copy_table(driver)
                    try:
                        controls = {'visible_selects': read_source_controls(driver)}
                    except Exception as exc:
                        controls = {'visible_selects': UNKNOWN, 'read_error': str(exc)}
                    rows = preserve_capture(text, champ, category, args.captures_dir,
                                            source_url=driver.current_url,
                                            verified={'Selected champion': verified_champion},
                                            source_context=controls)
                    results.extend(rows)
                    print('Captura preservada:', champ, label, len(rows), 'linhas; filtros não verificados.')
                except Exception as exc:
                    print('Falha na captura/parsing:', champ, label, str(exc))
                    print('Se houve texto copiado, o original e o erro permanecem em', args.captures_dir)
        save_results(results, args.output, overwrite=args.overwrite)
        print('Salvo em', args.output)
    finally:
        driver.quit()


if __name__ == '__main__':
    main()
