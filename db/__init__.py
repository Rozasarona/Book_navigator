'''SQLite storage shared by collector, analyzer and Telegram bot.'''
from __future__ import annotations
import hashlib, json, os, re, sqlite3, unicodedata
from pathlib import Path
from typing import Any
ROOT = Path(__file__).resolve().parents[1]
def database_path():
    path = Path(os.environ.get('DATABASE_PATH', 'data/book_navigator.db'))
    if not path.is_absolute(): path = ROOT / path
    path.parent.mkdir(parents=True, exist_ok=True)
    return path
def connect():
    conn = sqlite3.connect(database_path(), timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA foreign_keys=ON')
    conn.execute('PRAGMA journal_mode=WAL')
    return conn

def init_schema(conn=None):
    own = conn is None
    conn = conn or connect()
    conn.executescript((ROOT / 'db' / 'schema.sql').read_text(encoding='utf-8'))
    conn.commit()
    if own: conn.close()

def normalize_text(value):
    value = unicodedata.normalize('NFKC', value or '').lower().replace('ё', 'е')
    return re.sub(r'[^a-zа-я0-9]+', ' ', value).strip()

def canonical_key(title, author, isbn=None):
    if isbn:
        clean = re.sub(r'[^0-9xX]', '', isbn)
        if clean: return f'isbn:{clean.lower()}'
    raw = f'{normalize_text(title)}|{normalize_text(author)}'
    return 'book:' + hashlib.sha256(raw.encode()).hexdigest()[:24]

def json_dump(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True)

def start_run(conn, service):
    row = conn.execute(
        'INSERT INTO runs(service,status) VALUES (?,\'started\') RETURNING id', (service,)
    ).fetchone()
    conn.commit()
    return int(row['id'])

def finish_run(conn, run_id, items, note):
    conn.execute(
        '''UPDATE runs SET status='finished',finished_at=CURRENT_TIMESTAMP,
           items=?,note=? WHERE id=?''', (items, note, run_id)
    )
    conn.commit()

def fail_run(conn, run_id, error):
    conn.execute(
        '''UPDATE runs SET status='failed',finished_at=CURRENT_TIMESTAMP,note=? WHERE id=?''',
        (str(error)[:1000], run_id)
    )
    conn.commit()

def upsert_book(conn, item):
    key = canonical_key(item['title'], item.get('author'), item.get('isbn'))
    row = conn.execute('SELECT id FROM books WHERE canonical_key=?', (key,)).fetchone()
    values = (
        item['title'], item.get('author'), item.get('description'), item.get('genre'),
        item.get('age_min'), item.get('age_max'), item.get('language') or 'ru',
        item.get('published_date'), item.get('publisher'), item.get('isbn'),
        item.get('cover_url')
    )
    if row:
        book_id = int(row['id'])
        conn.execute(
            '''UPDATE books SET title=COALESCE(NULLIF(?,''),title),
            author=COALESCE(NULLIF(?,''),author),
            description=CASE WHEN length(COALESCE(?,''))>length(COALESCE(description,''))
                THEN ? ELSE description END,
            genre=COALESCE(NULLIF(?,''),genre),age_min=COALESCE(?,age_min),
            age_max=COALESCE(?,age_max),language=COALESCE(NULLIF(?,''),language),
            published_date=COALESCE(NULLIF(?,''),published_date),
            publisher=COALESCE(NULLIF(?,''),publisher),isbn=COALESCE(NULLIF(?,''),isbn),
            cover_url=COALESCE(NULLIF(?,''),cover_url),updated_at=CURRENT_TIMESTAMP
            WHERE id=?''',
            (values[0], values[1], values[2], values[2], *values[3:], book_id)
        )
        return book_id
    row = conn.execute(
        '''INSERT INTO books(canonical_key,title,author,description,genre,age_min,age_max,
        language,published_date,publisher,isbn,cover_url)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?) RETURNING id''', (key, *values)
    ).fetchone()
    return int(row['id'])

def upsert_audio_edition(conn, book_id, source_id, item):
    external_id = str(item.get('external_id') or hashlib.sha256(
        (item.get('product_url') or item['title']).encode()
    ).hexdigest()[:24])
    conn.execute(
        '''INSERT INTO audio_editions(book_id,source_id,external_id,narrator,duration_seconds,
        audio_url,product_url,availability,availability_note,rating,review_count,raw_json)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(source_id,external_id) DO UPDATE SET book_id=excluded.book_id,
        narrator=COALESCE(excluded.narrator,narrator),
        duration_seconds=COALESCE(excluded.duration_seconds,duration_seconds),
        audio_url=COALESCE(excluded.audio_url,audio_url),
        product_url=COALESCE(excluded.product_url,product_url),
        availability=excluded.availability,availability_note=excluded.availability_note,
        rating=COALESCE(excluded.rating,rating),review_count=COALESCE(excluded.review_count,review_count),
        raw_json=excluded.raw_json,updated_at=CURRENT_TIMESTAMP''',
        (book_id, source_id, external_id, item.get('narrator'), item.get('duration_seconds'),
         item.get('audio_url'), item.get('product_url'), item.get('availability') or 'unverified',
         item.get('availability_note'), item.get('rating'), item.get('review_count'),
         json_dump(item.get('raw') or item))
    )
    row = conn.execute(
        'SELECT id FROM audio_editions WHERE source_id=? AND external_id=?',
        (source_id, external_id)
    ).fetchone()
    return int(row['id'])
