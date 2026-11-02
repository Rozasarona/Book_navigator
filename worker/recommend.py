'''Create safe weekly recommendation drafts for a child profile.'''
from __future__ import annotations
import json, secrets
from datetime import datetime, timedelta, timezone
import db

MSK = timezone(timedelta(hours=3))

def current_week_key(now=None):
    now = now or datetime.now(MSK)
    monday = now.date() - timedelta(days=now.weekday())
    return monday.isoformat()

def create_profile(parent_chat_id, child_name, age, interests, restrictions, other=''):
    age = int(age)
    if not 4 <= age <= 14: raise ValueError('Возраст должен быть от 4 до 14 лет')
    conn = db.connect(); db.init_schema(conn)
    code = secrets.token_hex(3).upper()
    row = conn.execute(
        '''INSERT INTO profiles(parent_chat_id,child_name,age,interests_json,
        restrictions_json,other_restrictions,link_code) VALUES (?,?,?,?,?,?,?) RETURNING id''',
        (int(parent_chat_id), child_name.strip(), age, db.json_dump(interests),
         db.json_dump(restrictions), other.strip(), code)
    ).fetchone()
    conn.commit(); conn.close()
    return int(row['id']), code

def link_child(code, child_chat_id):
    conn = db.connect(); db.init_schema(conn)
    row = conn.execute('SELECT id FROM profiles WHERE link_code=? AND active=1', (code.upper(),)).fetchone()
    if not row: conn.close(); return None
    conn.execute('UPDATE profiles SET child_chat_id=?,updated_at=CURRENT_TIMESTAMP WHERE id=?',
                 (int(child_chat_id), row['id']))
    conn.commit(); profile_id = int(row['id']); conn.close()
    return profile_id

def _load_candidates(conn):
    rows = conn.execute(
        '''SELECT b.*,a.id analysis_id,a.age_min analysis_age_min,a.age_max analysis_age_max,
        a.interest_tags_json,a.content_flags_json,a.safe_for_children,a.enough_information,
        a.teaser,a.summary,a.confidence
        FROM books b JOIN book_analyses a ON a.book_id=b.id
        WHERE a.id=(SELECT max(a2.id) FROM book_analyses a2 WHERE a2.book_id=b.id)
        AND a.safe_for_children=1 AND a.enough_information=1'''
    ).fetchall()
    return rows

def _best_edition(conn, book_id):
    return conn.execute(
        '''SELECT ae.*,s.name source_name FROM audio_editions ae JOIN sources s ON s.id=ae.source_id
        WHERE ae.book_id=? ORDER BY (ae.availability='available') DESC,
        COALESCE(ae.rating,0) DESC,ae.id DESC LIMIT 1''', (book_id,)
    ).fetchone()

def generate(profile_id, count=7, week_key=None):
    conn = db.connect(); db.init_schema(conn)
    profile = conn.execute('SELECT * FROM profiles WHERE id=? AND active=1', (profile_id,)).fetchone()
    if not profile: conn.close(); raise ValueError('Профиль не найден')
    interests = json.loads(profile['interests_json'])
    restrictions = set(json.loads(profile['restrictions_json']))
    other = [x for x in db.normalize_text(profile['other_restrictions']).split() if len(x) > 3]
    previous = {row['book_id'] for row in conn.execute(
        'SELECT DISTINCT book_id FROM recommendations WHERE profile_id=?', (profile_id,)
    )}
    candidates = []
    for book in _load_candidates(conn):
        if book['id'] in previous: continue
        age_min = book['analysis_age_min'] or 4; age_max = book['analysis_age_max'] or 14
        if not age_min <= profile['age'] <= age_max: continue
        flags = set(json.loads(book['content_flags_json']))
        if restrictions & flags: continue
        haystack = db.normalize_text(' '.join(filter(None, [
            book['title'], book['genre'], book['description'], book['summary'],
            ' '.join(json.loads(book['interest_tags_json']))
        ])))
        if other and any(token in haystack for token in other): continue
        matched = [interest for interest in interests if db.normalize_text(interest) in haystack]
        edition = _best_edition(conn, book['id'])
        score = 1 + len(matched) * 3 + float(book['confidence'] or 0)
        if edition and edition['availability'] == 'available': score += 1
        if edition and edition['rating']: score += min(float(edition['rating']), 5) / 5
        reason = 'Совпадает с интересами: ' + ', '.join(matched) if matched else 'Подходит по возрасту'
        candidates.append((score, book, edition, reason))
    candidates.sort(key=lambda value: (-value[0], value[1]['title']))
    week_key = week_key or current_week_key()
    created = []
    for score, book, edition, reason in candidates[:max(5, min(int(count), 7))]:
        row = conn.execute(
            '''INSERT INTO recommendations(profile_id,book_id,audio_edition_id,week_key,score,
            rationale,teaser) VALUES (?,?,?,?,?,?,?)
            ON CONFLICT(profile_id,book_id,week_key) DO UPDATE SET score=excluded.score,
            rationale=excluded.rationale RETURNING id''',
            (profile_id, book['id'], edition['id'] if edition else None, week_key, score,
             reason, book['teaser'] or book['summary'] or book['description'])
        ).fetchone()
        created.append(int(row['id']))
    conn.commit(); conn.close()
    return created

def details(conn, recommendation_id):
    return conn.execute(
        '''SELECT r.*,b.title,b.author,b.cover_url,ae.narrator,ae.duration_seconds,
        ae.audio_url,ae.product_url,ae.availability,ae.availability_note,s.name source_name,
        p.child_name,p.parent_chat_id,p.child_chat_id
        FROM recommendations r JOIN books b ON b.id=r.book_id
        JOIN profiles p ON p.id=r.profile_id
        LEFT JOIN audio_editions ae ON ae.id=r.audio_edition_id
        LEFT JOIN sources s ON s.id=ae.source_id WHERE r.id=?''', (recommendation_id,)
    ).fetchone()
