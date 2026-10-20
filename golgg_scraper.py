import argparse
import io
import time
from dataclasses import dataclass
from typing import List

import pandas as pd
import pyperclip
from selenium import webdriver
from selenium.common.exceptions import NoSuchElementException
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
    return ' '.join(text.strip().replace("'", '').replace('&', '&').split()).title()


def is_champion_name(text: str) -> bool:
    if not text:
        return False
    return normalize_name(text) in CHAMPION_NAMES or text.strip() in CHAMPION_NAMES


@dataclass
class ScrapeResult:
    champion: str
    category: str
    opponent: str
    games: int
    winrate: float
    role: str | None = None
    source: str | None = None


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
        if label.lower() in text:
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
    buttons = driver.find_elements(By.XPATH, "//*[contains(normalize-space(text()), 'Copy table to clipboard')]")
    for btn in buttons:
        if btn.is_displayed():
            try:
                webdriver.ActionChains(driver).move_to_element(btn).click(btn).perform()
                time.sleep(0.7)
                return pyperclip.paste()
            except Exception:
                continue
    raise RuntimeError('Botão Copy table to clipboard não encontrado.')


def parse_clipboard_table(table_text: str) -> pd.DataFrame:
    text = table_text.strip().replace('\r\n', '\n').replace('\r', '\n')
    if not text:
        return pd.DataFrame()
    try:
        return pd.read_csv(io.StringIO(text), sep='\t')
    except Exception:
        return pd.read_csv(io.StringIO(text), sep='\s+', engine='python')


def parse_vs_table(champion: str, df: pd.DataFrame, source: str) -> List[ScrapeResult]:
    rows: List[ScrapeResult] = []
    if df.empty:
        return rows
    name_col = next((c for c in df.columns if 'champion' in c.lower() or 'opponent' in c.lower() or 'vs' in c.lower()), df.columns[0])
    games_col = next((c for c in df.columns if 'games' in c.lower()), None)
    winrate_col = next((c for c in df.columns if 'winrate' in c.lower()), None)
    role_col = next((c for c in df.columns if 'role' in c.lower()), None)
    for _, row in df.iterrows():
        opponent = str(row.get(name_col, '')).strip()
        games = int(row.get(games_col, 0)) if games_col is not None and pd.notna(row.get(games_col)) else 0
        raw = str(row.get(winrate_col, '')).strip() if winrate_col else ''
        raw = raw.replace('%', '').replace(',', '.').strip()
        winrate = float(raw) / 100.0 if raw else 0.0
        role = str(row.get(role_col, '')).strip() if role_col else None
        rows.append(ScrapeResult(champion=champion, category='VS', opponent=opponent, games=games, winrate=winrate, role=role, source=source))
    return rows


def parse_with_table(champion: str, df: pd.DataFrame) -> List[ScrapeResult]:
    rows: List[ScrapeResult] = []
    if df.empty:
        return rows
    name_col = next((c for c in df.columns if 'champion' in c.lower() or 'with' in c.lower() or 'ally' in c.lower()), df.columns[0])
    games_col = next((c for c in df.columns if 'games' in c.lower()), None)
    winrate_col = next((c for c in df.columns if 'winrate' in c.lower()), None)
    role_col = next((c for c in df.columns if 'role' in c.lower()), None)
    for _, row in df.iterrows():
        ally = str(row.get(name_col, '')).strip()
        games = int(row.get(games_col, 0)) if games_col is not None and pd.notna(row.get(games_col)) else 0
        raw = str(row.get(winrate_col, '')).strip() if winrate_col else ''
        raw = raw.replace('%', '').replace(',', '.').strip()
        winrate = float(raw) / 100.0 if raw else 0.0
        role = str(row.get(role_col, '')).strip() if role_col else None
        rows.append(ScrapeResult(champion=champion, category='WITH', opponent=ally, games=games, winrate=winrate, role=role, source='Good with'))
    return rows


def save_results(results: List[ScrapeResult], output_path: str):
    if not results:
        pd.DataFrame(columns=['Campeao', 'Champion', 'Games', 'Winrate']).to_excel(output_path, sheet_name='Winrate_vs', index=False)
        with pd.ExcelWriter(output_path, engine='openpyxl', mode='a') as writer:
            pd.DataFrame(columns=['Campeao', 'Champion', 'Games', 'Winrate']).to_excel(writer, sheet_name='Winrate_with', index=False)
        return

    df = pd.DataFrame([{
        'Campeao': r.champion,
        'Champion': r.opponent,
        'Games': r.games,
        'Winrate': r.winrate,
        'Source': r.source,
        'Role': r.role,
        'Category': r.category,
    } for r in results])

    vs_df = df[df['Category'] == 'VS'].copy()
    with_df = df[df['Category'] == 'WITH'].copy()

    vs_df = vs_df[['Campeao', 'Champion', 'Games', 'Winrate']]
    with_df = with_df[['Campeao', 'Champion', 'Games', 'Winrate']]

    with pd.ExcelWriter(output_path, engine='openpyxl') as writer:
        vs_df.to_excel(writer, sheet_name='Winrate_vs', index=False)
        with_df.to_excel(writer, sheet_name='Winrate_with', index=False)


def apply_filters(driver):
    for label, value in [('Tournament', 'ALL'), ('Game version', 'ALL'), ('Role filter', 'ALL'), ('Pick Selection', 'ALL')]:
        selects = driver.find_elements(By.TAG_NAME, 'select')
        for sel in selects:
            try:
                options = [opt.text.strip() for opt in Select(sel).options]
            except Exception:
                continue
            if value in options:
                try:
                    Select(sel).select_by_visible_text(value)
                    time.sleep(0.5)
                except Exception:
                    pass
                break


def main():
    parser = argparse.ArgumentParser(description='Scrape gol.gg champion synergy tables via clipboard')
    parser.add_argument('--output', default='golgg_champion_synergy.xlsx', help='Excel output file')
    parser.add_argument('--limit', type=int, default=None, help='Number of champions to scrape (default all)')
    parser.add_argument('--champions', nargs='*', default=None, help='List of champions to scrape')
    args = parser.parse_args()

    driver = init_driver(headless=False)
    try:
        url = BASE_URL.format(season=SEASON, split=SPLIT, tournament=TOURNAMENT)
        driver.get(url)
        print('Abra o navegador e faça login se necessário.')
        input('Quando a página estiver carregada e você estiver logado, pressione Enter para continuar...')

        apply_filters(driver)
        print('Filtros aplicados onde possível.')

        champions = args.champions or get_champion_list(driver)
        print(f'Champions found: {len(champions)}')
        if args.limit is not None:
            champions = champions[:args.limit]
        print(f'Will scrape {len(champions)} champions: {champions}')

        results: List[ScrapeResult] = []
        for champ in champions:
            print(f'Scraping champion {champ}...')
            try:
                select = find_champion_select(driver)
                Select(select).select_by_visible_text(champ)
                time.sleep(1.5)
            except Exception:
                if not select_champion_custom(driver, champ):
                    print(f'Could not select champion {champ}, skipping.')
                    continue

            if click_tab(driver, 'Direct Matchup'):
                text = click_copy_table(driver)
                df = parse_clipboard_table(text)
                results.extend(parse_vs_table(champ, df, 'Direct Matchup'))
            else:
                print('Direct Matchup tab not found for', champ)

            if click_tab(driver, 'Indirect Matchup'):
                text = click_copy_table(driver)
                df = parse_clipboard_table(text)
                results.extend(parse_vs_table(champ, df, 'Indirect Matchup'))
            else:
                print('Indirect Matchup tab not found for', champ)

            if click_tab(driver, 'Good with'):
                text = click_copy_table(driver)
                df = parse_clipboard_table(text)
                results.extend(parse_with_table(champ, df))
            else:
                print('Good with tab not found for', champ)

        save_results(results, args.output)
        print('Saved output to', args.output)
    finally:
        driver.quit()


if __name__ == '__main__':
    main()
