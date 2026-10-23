"""Local analysis history and Riot portraits. No access writes to the source DB."""
from contextlib import contextmanager
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import sqlite3
import time
import unicodedata
from urllib.request import Request, urlopen

HISTORY_APP_ID = 0x4D4C4452


def key(text):
    return ''.join(c for c in unicodedata.normalize('NFKC', text).casefold() if c.isalnum())


class AnalysisHistory:
    def __init__(self, path, source_database):
        self.path = Path(path).resolve()
        source = Path(source_database).resolve()
        if self.path == source or (self.path.exists() and source.exists() and self.path.samefile(source)):
            raise ValueError('O histórico precisa de um arquivo diferente da base de coleta.')
        self.path.parent.mkdir(parents=True, exist_ok=True)
        existing = self.path.exists()
        with self.connection() as connection, connection:
            if existing:
                if (connection.execute('PRAGMA application_id').fetchone()[0] != HISTORY_APP_ID or
                        connection.execute('PRAGMA user_version').fetchone()[0] != 1):
                    raise ValueError('Arquivo de histórico incompatível; não será modificado.')
            else:
                connection.execute('''CREATE TABLE analises (
                    id TEXT PRIMARY KEY, name TEXT NOT NULL, created_at_utc TEXT NOT NULL,
                    updated_at_utc TEXT NOT NULL, notes TEXT NOT NULL, tags_json TEXT NOT NULL,
                    payload_json TEXT NOT NULL)''')
                connection.execute(f'PRAGMA application_id={HISTORY_APP_ID}')
                connection.execute('PRAGMA user_version=1')

    @contextmanager
    def connection(self):
        connection = sqlite3.connect(self.path, timeout=10)
        try:
            yield connection
        finally:
            connection.close()

    def entries(self):
        with self.connection() as connection:
            return [json.loads(row[0]) for row in connection.execute(
                'SELECT payload_json FROM analises ORDER BY created_at_utc DESC, id DESC')]

    def save(self, entry):
        payload = json.dumps(entry, ensure_ascii=False, allow_nan=False)
        with self.connection() as connection, connection:
            previous = connection.execute('SELECT payload_json FROM analises WHERE id=?', (entry['id'],)).fetchone()
            if previous and json.loads(previous[0])['result'] != entry['result']:
                raise ValueError('O resultado de uma análise salva é imutável; crie outro registro.')
            connection.execute('''INSERT INTO analises VALUES (?,?,?,?,?,?,?)
                ON CONFLICT(id) DO UPDATE SET name=excluded.name, updated_at_utc=excluded.updated_at_utc,
                notes=excluded.notes, tags_json=excluded.tags_json, payload_json=excluded.payload_json''',
                (entry['id'], entry['name'], entry['created_at_utc'], datetime.now(timezone.utc).isoformat(),
                 entry.get('notes',''), json.dumps(entry.get('tags',[]),ensure_ascii=False),payload))


def fetch(url):
    """Only fixed official HTTPS endpoints are used; TLS remains verified."""
    with urlopen(Request(url, headers={'User-Agent':'MegaLoL-DraftWorkspace/1.0'}), timeout=3) as response:
        content = response.read(8 * 1024 * 1024 + 1)
    if len(content) > 8 * 1024 * 1024:
        raise ValueError('Asset maior que o limite de cache')
    return content


class PortraitCache:
    def __init__(self, directory, downloader=fetch):
        self.directory = Path(directory)
        self.downloader = downloader
        self.manifest = None
        self.attempted = False

    def _manifest(self):
        if self.attempted:
            return self.manifest
        self.attempted = True
        try:
            self.directory.mkdir(parents=True, exist_ok=True)
            path = self.directory/'manifest.json'
            if path.exists():
                try:
                    candidate = json.loads(path.read_text(encoding='utf-8'))
                    if re.fullmatch(r'\d+\.\d+\.\d+', candidate['version']) and isinstance(candidate['mapping'],dict):
                        self.manifest = candidate
                        if time.time() - path.stat().st_mtime < 7*24*3600:
                            return candidate
                except (ValueError,KeyError,TypeError):
                    pass
            failure = self.directory/'manifest.failed'
            if failure.exists() and time.time() - failure.stat().st_mtime < 300:
                return self.manifest
            versions = json.loads(self.downloader('https://ddragon.leagueoflegends.com/api/versions.json'))
            version = versions[0]
            if not re.fullmatch(r'\d+\.\d+\.\d+', version):
                raise ValueError('Versão inválida')
            data = json.loads(self.downloader(f'https://ddragon.leagueoflegends.com/cdn/{version}/data/en_US/champion.json'))
            mapping = {}
            for champion in data['data'].values():
                identity = champion['id']
                if not re.fullmatch(r'[A-Za-z0-9]+', identity):
                    continue
                mapping[key(champion['name'])] = identity
                mapping[key(identity)] = identity
            self.manifest = {'version':version,'mapping':mapping}
            temporary = self.directory/'manifest.tmp'
            temporary.write_text(json.dumps(self.manifest),encoding='utf-8')
            temporary.replace(path)
        except (OSError,ValueError,KeyError,IndexError,TypeError):
            try:
                (self.directory/'manifest.failed').touch()
            except OSError:
                pass
        return self.manifest

    def image(self, champion):
        if not champion:
            return None
        manifest = self._manifest()
        if not manifest:
            return None
        identity = manifest['mapping'].get(key(champion))
        if not identity or not re.fullmatch(r'[A-Za-z0-9]+', identity):
            return None
        path = self.directory/f"{manifest['version']}_{identity}.png"
        try:
            if path.exists():
                data = path.read_bytes()
                if data.startswith(b'\x89PNG\r\n\x1a\n'):
                    return data
            failure = path.with_suffix('.failed')
            if failure.exists() and time.time() - failure.stat().st_mtime < 300:
                return None
            data = self.downloader(f"https://ddragon.leagueoflegends.com/cdn/{manifest['version']}/img/champion/{identity}.png")
            if not data.startswith(b'\x89PNG\r\n\x1a\n') or len(data) > 1024*1024:
                raise ValueError('Retrato PNG inválido')
            temporary = path.with_suffix('.tmp')
            temporary.write_bytes(data)
            temporary.replace(path)
            return data
        except (OSError,ValueError):
            try:
                path.with_suffix('.failed').touch()
            except OSError:
                pass
            return None
