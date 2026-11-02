'''Analyze normalized books with AITUNNEL or deterministic offline rules.'''
from __future__ import annotations
import json, logging, os, re
from urllib.request import Request, urlopen
import db

LOG = logging.getLogger(__name__)
PROMPT_VERSION = 'books-v2'
FLAGS = [
    'страх', 'насилие', 'смерть', 'буллинг', 'дискриминация',
    'романтика', 'религия', 'политика', 'болезни', 'зависимости',
]

PROMPT = '''Ты анализируешь детские книги для рекомендательного сервиса.
Опирайся только на переданные метаданные. Не придумывай сюжет и факты.
Если описания недостаточно для проверки содержания, enough_information=false.
Верни JSON: age_min и age_max в диапазоне 4-14; interest_tags — темы и интересы;
content_flags — только применимые значения из списка: {flags};
safe_for_children — подходит ли книга хотя бы части аудитории 4-14;
enough_information; teaser — 2 увлекательных предложения без спойлеров;
summary — нейтральное резюме; confidence — число 0..1.

Название: {title}
Автор: {author}
Жанр: {genre}
Описание: {description}
Возраст источника: {age_min}-{age_max}
'''

def parse_json_content(content):
    content = content.strip()
    if content.startswith('```'):
        content = re.sub(r'^```(?:json)?|```$', '', content, flags=re.I).strip()
    return json.loads(content)

def ask_aitunnel(book):
    api_key = os.environ.get('AITUNNEL_API_KEY')
    if not api_key:
        raise RuntimeError('AITUNNEL_API_KEY не задан')
    base = os.environ.get('AITUNNEL_BASE_URL', 'https://api.aitunnel.ru/v1').rstrip('/')
    model = os.environ.get('AITUNNEL_MODEL', 'auto')
    prompt = PROMPT.format(
        flags=', '.join(FLAGS), title=book['title'], author=book['author'] or 'не указан',
        genre=book['genre'] or 'не указан', description=(book['description'] or '')[:6000],
        age_min=book['age_min'] or 'не указан', age_max=book['age_max'] or 'не указан'
    )
    body = {
        'model': model, 'max_tokens': 1000,
        'messages': [{'role': 'user', 'content': prompt}],
        'response_format': {'type': 'json_object'},
    }
    request = Request(
        base + '/chat/completions', data=json.dumps(body, ensure_ascii=False).encode(),
        headers={'Authorization': 'Bearer ' + api_key, 'Content-Type': 'application/json'}
    )
    with urlopen(request, timeout=90) as response:
        payload = json.loads(response.read().decode('utf-8'))
    answer = parse_json_content(payload['choices'][0]['message']['content'])
    answer['_request_id'] = payload.get('id')
    answer['_model'] = payload.get('model') or model
    answer['_cost_rub'] = payload.get('usage', {}).get('cost_rub')
    answer['_raw'] = payload
    return answer

def analyze_heuristic(book):
    text = ' '.join(filter(None, [book['title'], book['genre'], book['description']])).lower()
    tag_map = {
        'приключения': ['приключ'], 'фэнтези': ['фэнтези', 'волшеб'],
        'дружба': ['друж', 'друз'], 'семья': ['семь'], 'юмор': ['юмор', 'смеш'],
        'школа': ['школ'], 'животные': ['животн'], 'космос': ['космос'],
    }
    tags = [tag for tag, stems in tag_map.items() if any(stem in text for stem in stems)]
    flag_map = {
        'страх': ['страш', 'злой', 'опасн'], 'насилие': ['борьб', 'битв', 'войн'],
        'смерть': ['смерт', 'погиб'], 'буллинг': ['травл', 'буллинг'],
        'болезни': ['болезн'],
    }
    flags = [flag for flag, stems in flag_map.items() if any(stem in text for stem in stems)]
    enough = len((book['description'] or '').strip()) >= 40
    teaser = (
        'Что произойдёт, если открыть историю «{}»? '.format(book['title']) +
        'Впереди герои, открытия и приключение, о котором лучше узнать без спойлеров.'
    )
    return {
        'age_min': book['age_min'] or 6, 'age_max': book['age_max'] or 12,
        'interest_tags': tags, 'content_flags': flags,
        'safe_for_children': True, 'enough_information': enough,
        'teaser': teaser, 'summary': book['description'] or '', 'confidence': 0.55,
        '_model': 'offline-rules', '_raw': {'mode': 'heuristic'},
    }

def normalize_answer(answer):
    age_min = max(4, min(14, int(answer.get('age_min') or 4)))
    age_max = max(age_min, min(14, int(answer.get('age_max') or 14)))
    flags = [value for value in answer.get('content_flags', []) if value in FLAGS]
    return {
        **answer, 'age_min': age_min, 'age_max': age_max,
        'interest_tags': list(dict.fromkeys(answer.get('interest_tags', [])))[:12],
        'content_flags': list(dict.fromkeys(flags)),
        'safe_for_children': bool(answer.get('safe_for_children')),
        'enough_information': bool(answer.get('enough_information')),
        'confidence': max(0.0, min(1.0, float(answer.get('confidence') or 0))),
    }

def save_analysis(conn, book_id, analyzer, answer):
    answer = normalize_answer(answer)
    model = answer.get('_model') or os.environ.get('AITUNNEL_MODEL', 'auto')
    conn.execute(
        '''INSERT INTO book_analyses(book_id,analyzer,model,prompt_version,age_min,age_max,
        interest_tags_json,content_flags_json,safe_for_children,enough_information,teaser,
        summary,confidence,request_id,cost_rub,raw_response_json)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(book_id,analyzer,model,prompt_version) DO UPDATE SET
        age_min=excluded.age_min,age_max=excluded.age_max,
        interest_tags_json=excluded.interest_tags_json,content_flags_json=excluded.content_flags_json,
        safe_for_children=excluded.safe_for_children,enough_information=excluded.enough_information,
        teaser=excluded.teaser,summary=excluded.summary,confidence=excluded.confidence,
        request_id=excluded.request_id,cost_rub=excluded.cost_rub,
        raw_response_json=excluded.raw_response_json,created_at=CURRENT_TIMESTAMP''',
        (book_id, analyzer, model, PROMPT_VERSION, answer['age_min'], answer['age_max'],
         db.json_dump(answer['interest_tags']), db.json_dump(answer['content_flags']),
         int(answer['safe_for_children']), int(answer['enough_information']), answer.get('teaser'),
         answer.get('summary'), answer['confidence'], answer.get('_request_id'),
         answer.get('_cost_rub'), db.json_dump(answer.get('_raw') or answer))
    )
    status = 'done' if answer['safe_for_children'] and answer['enough_information'] else 'excluded'
    conn.execute('UPDATE books SET analysis_status=? WHERE id=?', (status, book_id))
    return status

def process(mode=None, reanalyze=False, limit=None):
    mode = mode or os.environ.get('ANALYZER', 'aitunnel')
    if mode not in {'aitunnel', 'heuristic'}:
        raise ValueError('ANALYZER должен быть aitunnel или heuristic')
    conn = db.connect(); db.init_schema(conn)
    if reanalyze:
        conn.execute('UPDATE books SET analysis_status=\'new\'')
        conn.commit()
    query = 'SELECT * FROM books WHERE analysis_status IN (\'new\',\'failed\') ORDER BY id'
    params = ()
    if limit:
        query += ' LIMIT ?'; params = (int(limit),)
    books = conn.execute(query, params).fetchall()
    run_id = db.start_run(conn, 'worker')
    done = excluded = failed = 0
    try:
        for book in books:
            try:
                answer = ask_aitunnel(book) if mode == 'aitunnel' else analyze_heuristic(book)
                status = save_analysis(conn, book['id'], mode, answer)
                done += status == 'done'; excluded += status == 'excluded'
                conn.commit()
            except Exception as error:
                conn.rollback()
                conn.execute('UPDATE books SET analysis_status=\'failed\' WHERE id=?', (book['id'],))
                conn.commit(); failed += 1
                LOG.warning('Не удалось обработать книгу %s: %s', book['id'], error)
        result = {'processed': done + excluded, 'accepted': done, 'excluded': excluded, 'failed': failed}
        db.finish_run(conn, run_id, done + excluded, db.json_dump(result))
        return result
    except Exception as error:
        db.fail_run(conn, run_id, error)
        raise
    finally:
        conn.close()

def main():
    print(db.json_dump(process()))

if __name__ == '__main__':
    main()
