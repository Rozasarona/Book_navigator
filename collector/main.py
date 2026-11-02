'''Collect and normalize books from free public APIs.'''
from __future__ import annotations
import html, json, logging, re
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

import db
from collector.sources import SOURCE_DEFINITIONS
from data.sample_catalog import SAMPLE_BOOKS

LOG = logging.getLogger(__name__)
USER_AGENT = 'BookNavigator/0.1 educational project'

def fetch_json(url):
    req = Request(url, headers={'User-Agent': USER_AGENT, 'Accept': 'application/json'})
    with urlopen(req, timeout=30) as response:
        return json.loads(response.read().decode('utf-8'))

def clean_html(value):
    return html.unescape(re.sub(r'<[^>]+>', ' ', value or '')).strip()

def seed_sources(conn):
    for source in SOURCE_DEFINITIONS:
        conn.execute(
            '''INSERT INTO sources(name,kind,url,config_json,active) VALUES (?,?,?,?,?)
            ON CONFLICT(name) DO UPDATE SET kind=excluded.kind,url=excluded.url,
            config_json=excluded.config_json,active=excluded.active''',
            (source['name'], source['kind'], source.get('url'), db.json_dump(source['config']),
             int(source.get('active', True)))
        )
    conn.commit()

def read_sample(source):
    yield from SAMPLE_BOOKS

def read_google(source):
    config = json.loads(source['config_json'])
    for query in config.get('queries', ['детские книги']):
        params = {
            'q': query, 'langRestrict': 'ru', 'orderBy': 'newest',
            'maxResults': min(int(config.get('max_per_query', 20)), 40),
            'printType': 'books',
        }
        payload = fetch_json(source['url'] + '?' + urlencode(params))
        for volume in payload.get('items', []):
            info = volume.get('volumeInfo', {})
            ids = {x.get('type'): x.get('identifier') for x in info.get('industryIdentifiers', [])}
            yield {
                'external_id': volume.get('id'), 'title': info.get('title') or '',
                'author': ', '.join(info.get('authors', [])),
                'description': clean_html(info.get('description')),
                'genre': ', '.join(info.get('categories', [])),
                'language': info.get('language') or 'ru',
                'published_date': info.get('publishedDate'), 'publisher': info.get('publisher'),
                'isbn': ids.get('ISBN_13') or ids.get('ISBN_10'),
                'cover_url': info.get('imageLinks', {}).get('thumbnail'),
                'product_url': info.get('infoLink'), 'availability': 'unverified',
                'availability_note': 'Найдена книга; наличие аудиоверсии нужно проверить.',
                'rating': info.get('averageRating'), 'review_count': info.get('ratingsCount'),
                'raw': volume,
            }

def read_open_library(source):
    config = json.loads(source['config_json'])
    params = {
        'q': 'language:rus AND (subject:children OR subject:juvenile)',
        'sort': 'new', 'limit': min(int(config.get('limit', 40)), 100),
        'fields': 'key,title,author_name,first_publish_year,publisher,isbn,cover_i,subject,language,ratings_average,ratings_count',
    }
    payload = fetch_json(source['url'] + '?' + urlencode(params))
    for item in payload.get('docs', []):
        key = item.get('key') or ''
        yield {
            'external_id': key, 'title': item.get('title') or '',
            'author': ', '.join(item.get('author_name', [])),
            'description': None, 'genre': ', '.join(item.get('subject', [])[:8]),
            'language': 'ru', 'published_date': str(item.get('first_publish_year') or ''),
            'publisher': (item.get('publisher') or [None])[0],
            'isbn': (item.get('isbn') or [None])[0],
            'cover_url': 'https://covers.openlibrary.org/b/id/{}-M.jpg'.format(item.get('cover_i')) if item.get('cover_i') else None,
            'product_url': 'https://openlibrary.org' + key, 'availability': 'unverified',
            'availability_note': 'Библиографическая запись; аудиоверсия не подтверждена.',
            'rating': item.get('ratings_average'), 'review_count': item.get('ratings_count'),
            'raw': item,
        }

def read_librivox(source):
    config = json.loads(source['config_json'])
    url = source['url'] + '?' + urlencode({
        'format': 'json', 'extended': 1, 'coverart': 1,
        'limit': min(int(config.get('limit', 500)), 500), 'sort_order': 'desc',
    })
    for item in fetch_json(url).get('books', []):
        if (item.get('language') or '').lower() not in {'russian', 'русский'}:
            continue
        authors = []
        for author in item.get('authors', []):
            authors.append(' '.join(filter(None, [author.get('first_name'), author.get('last_name')])))
        genres = [genre.get('name', '') for genre in item.get('genres', [])]
        yield {
            'external_id': item.get('id'), 'title': item.get('title') or '',
            'author': ', '.join(authors), 'description': clean_html(item.get('description')),
            'genre': ', '.join(filter(None, genres)), 'language': 'ru',
            'published_date': item.get('copyright_year'),
            'cover_url': item.get('coverart_jpg'), 'narrator': None,
            'duration_seconds': int(item.get('totaltimesecs') or 0) or None,
            'audio_url': item.get('url_rss') or item.get('url_zip_file'),
            'product_url': item.get('url_librivox'), 'availability': 'available',
            'availability_note': 'Свободная аудиокнига LibriVox.', 'raw': item,
        }

READERS = {
    'sample': read_sample, 'google_books': read_google,
    'open_library': read_open_library, 'librivox': read_librivox,
}

def collect(offline=False):
    conn = db.connect()
    db.init_schema(conn)
    seed_sources(conn)
    run_id = db.start_run(conn, 'collector')
    saved = 0
    errors = []
    try:
        if offline:
            sources = conn.execute('SELECT * FROM sources WHERE kind=\'sample\' ORDER BY id').fetchall()
        else:
            sources = conn.execute('SELECT * FROM sources WHERE active=1 ORDER BY id').fetchall()
        for source in sources:
            reader = READERS.get(source['kind'])
            if not reader:
                errors.append('{}: неизвестный тип {}'.format(source['name'], source['kind']))
                continue
            try:
                for item in reader(source):
                    if not item.get('title'):
                        continue
                    book_id = db.upsert_book(conn, item)
                    db.upsert_audio_edition(conn, book_id, source['id'], item)
                    saved += 1
                conn.commit()
                LOG.info('Источник %s обработан', source['name'])
            except Exception as error:
                conn.rollback()
                errors.append('{}: {}'.format(source['name'], error))
                LOG.warning('Источник %s недоступен: %s', source['name'], error)
        note = f'сохранено записей: {saved}'
        if errors: note += '; ошибки: ' + ' | '.join(errors)
        db.finish_run(conn, run_id, saved, note)
        return {'saved': saved, 'errors': errors}
    except Exception as error:
        db.fail_run(conn, run_id, error)
        raise
    finally:
        conn.close()

def main():
    result = collect()
    print(db.json_dump(result))

if __name__ == '__main__':
    main()
