'''Telegram bot with parent approval and child feedback.'''
from __future__ import annotations
import json, logging, os, time
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode
from urllib.request import Request, urlopen
import db
from worker.recommend import create_profile, details, generate, link_child

LOG = logging.getLogger(__name__)
MSK = timezone(timedelta(hours=3))
TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN', '')

def telegram(method, payload=None):
    if not TOKEN: raise RuntimeError('TELEGRAM_BOT_TOKEN не задан')
    data = {}
    for key, value in (payload or {}).items():
        data[key] = json.dumps(value, ensure_ascii=False) if isinstance(value, (dict, list)) else value
    request = Request(
        'https://api.telegram.org/bot{}/{}'.format(TOKEN, method),
        data=urlencode(data).encode() if data else None,
        headers={'Content-Type': 'application/x-www-form-urlencoded'}
    )
    with urlopen(request, timeout=70) as response:
        result = json.loads(response.read().decode())
    if not result.get('ok'): raise RuntimeError(result)
    return result['result']

def send(chat_id, text, keyboard=None):
    payload = {'chat_id': chat_id, 'text': text, 'disable_web_page_preview': False}
    if keyboard: payload['reply_markup'] = keyboard
    return telegram('sendMessage', payload)

def feedback_keyboard(rec_id):
    return {'inline_keyboard': [
        [{'text': '❤️ Понравилось', 'callback_data': f'fb:{rec_id}:liked'},
         {'text': '🎧 В очереди', 'callback_data': f'fb:{rec_id}:queue'}],
        [{'text': 'Уже слушал(а)', 'callback_data': f'fb:{rec_id}:already_listened'}],
        [{'text': 'Не понравилось', 'callback_data': f'fb:{rec_id}:disliked'},
         {'text': 'Не подходит', 'callback_data': f'fb:{rec_id}:content_mismatch'}],
    ]}

def format_book(row, for_parent=False):
    duration = ''
    if row['duration_seconds']:
        hours, rest = divmod(int(row['duration_seconds']), 3600)
        minutes = rest // 60
        duration = f'\n⏱ {hours} ч {minutes} мин' if hours else f'\n⏱ {minutes} мин'
    url = row['audio_url'] or row['product_url']
    warning = ''
    if row['availability'] != 'available':
        warning = '\n⚠️ Аудиоверсия не подтверждена — проверьте её в легальном каталоге.'
    source = '\nИсточник: {}'.format(row['source_name']) if row['source_name'] else ''
    commands = ''
    if for_parent:
        commands = '\n\n/approve {} · /reject {}\n/edit {} новый тизер'.format(
            row['id'], row['id'], row['id']
        )
    author = row['author'] or 'не указан'
    result = '📚 {}\nАвтор: {}{}\n\n{}\n\nПочему выбрали: {}'.format(
        row['title'], author, duration, row['teaser'], row['rationale']
    )
    return result + warning + source + ('\n🔗 ' + url if url else '') + commands

def send_draft(rec_id):
    conn = db.connect(); row = details(conn, rec_id); conn.close()
    if row: send(row['parent_chat_id'], format_book(row, True))

def approve(rec_id, parent_chat_id):
    conn = db.connect(); row = details(conn, rec_id)
    if not row or int(row['parent_chat_id']) != int(parent_chat_id):
        conn.close(); return 'Эта рекомендация недоступна.'
    conn.execute(
        '''UPDATE recommendations SET status='approved',approved_at=CURRENT_TIMESTAMP WHERE id=?''',
        (rec_id,)
    )
    if row['child_chat_id']:
        send(row['child_chat_id'], format_book(row), feedback_keyboard(rec_id))
        conn.execute(
            '''UPDATE recommendations SET status='sent',sent_at=CURRENT_TIMESTAMP WHERE id=?''',
            (rec_id,)
        )
        message = 'Одобрено и отправлено ребёнку.'
    else:
        message = 'Одобрено. Сначала ребёнок должен подключиться по коду.'
    conn.commit(); conn.close(); return message

HELP = '''Я подбираю детские аудиокниги для возраста 4–14 лет.

Родителю:
/profile Имя | возраст | интересы через запятую | ограничения через запятую | другое
/profiles — показать профили
/recommend ID — подготовить подборку сейчас
/approve ID, /reject ID, /edit ID новый тизер

Ребёнку:
/child КОД — связать профиль
/interests космос, животные — дополнить свои интересы'''

def split_list(value):
    return [item.strip().lower() for item in value.split(',') if item.strip()]

def handle_message(message):
    chat_id = message['chat']['id']; text = (message.get('text') or '').strip()
    if text in {'/start', '/help'}:
        send(chat_id, HELP); return
    command, _, args = text.partition(' ')
    if command == '/profile':
        parts = [part.strip() for part in args.split('|')]
        if len(parts) < 4:
            send(chat_id, 'Формат: /profile Имя | 8 | космос, приключения | страх, насилие | другое')
            return
        try:
            profile_id, code = create_profile(
                chat_id, parts[0], int(parts[1]), split_list(parts[2]), split_list(parts[3]),
                parts[4] if len(parts) > 4 else ''
            )
            send(chat_id, 'Профиль №{} создан. Код ребёнка: {}\nРебёнок отправляет: /child {}'.format(
                profile_id, code, code
            ))
        except Exception as error:
            send(chat_id, 'Не удалось создать профиль: ' + str(error))
        return
    if command == '/profiles':
        conn = db.connect()
        rows = conn.execute(
            'SELECT id,child_name,age,link_code,child_chat_id FROM profiles WHERE parent_chat_id=? AND active=1',
            (chat_id,)
        ).fetchall(); conn.close()
        if not rows: send(chat_id, 'Профилей пока нет.\n' + HELP); return
        lines = ['№{}: {}, {} лет, код {}, ребёнок {}'.format(
            row['id'], row['child_name'], row['age'], row['link_code'],
            'подключён' if row['child_chat_id'] else 'не подключён'
        ) for row in rows]
        send(chat_id, '\n'.join(lines)); return
    if command == '/child':
        profile_id = link_child(args.strip(), chat_id)
        send(chat_id, 'Профиль подключён. Жди одобренную подборку!' if profile_id else 'Код не найден.')
        return
    if command == '/interests':
        interests = split_list(args)
        conn = db.connect()
        rows = conn.execute('SELECT id,interests_json FROM profiles WHERE child_chat_id=?', (chat_id,)).fetchall()
        for row in rows:
            current = json.loads(row['interests_json'])
            conn.execute('UPDATE profiles SET interests_json=?,updated_at=CURRENT_TIMESTAMP WHERE id=?',
                         (db.json_dump(list(dict.fromkeys(current + interests))), row['id']))
        conn.commit(); conn.close()
        send(chat_id, 'Интересы обновлены.' if rows else 'Сначала подключись командой /child КОД.'); return
    if command == '/recommend':
        try:
            profile_id = int(args); conn = db.connect()
            owner = conn.execute('SELECT parent_chat_id FROM profiles WHERE id=?', (profile_id,)).fetchone()
            conn.close()
            if not owner or int(owner['parent_chat_id']) != int(chat_id): raise ValueError('профиль не найден')
            ids = generate(profile_id)
            send(chat_id, 'Подготовлено книг: {}. Проверьте каждую карточку.'.format(len(ids)))
            for rec_id in ids: send_draft(rec_id)
        except Exception as error:
            send(chat_id, 'Не удалось сделать подборку: ' + str(error))
        return
    if command == '/approve':
        try: send(chat_id, approve(int(args), chat_id))
        except Exception as error: send(chat_id, 'Ошибка: ' + str(error))
        return
    if command == '/reject':
        try:
            rec_id = int(args); conn = db.connect(); row = details(conn, rec_id)
            if not row or int(row['parent_chat_id']) != int(chat_id): raise ValueError('нет доступа')
            conn.execute('UPDATE recommendations SET status=\'rejected\' WHERE id=?', (rec_id,))
            conn.commit(); conn.close(); send(chat_id, 'Рекомендация отклонена.')
        except Exception as error: send(chat_id, 'Ошибка: ' + str(error))
        return
    if command == '/edit':
        rec_text, _, teaser = args.partition(' ')
        try:
            rec_id = int(rec_text); conn = db.connect(); row = details(conn, rec_id)
            if not teaser or not row or int(row['parent_chat_id']) != int(chat_id):
                raise ValueError('формат: /edit ID новый тизер')
            conn.execute('UPDATE recommendations SET teaser=? WHERE id=?', (teaser.strip(), rec_id))
            conn.commit(); conn.close(); send(chat_id, 'Тизер обновлён.')
        except Exception as error: send(chat_id, 'Ошибка: ' + str(error))
        return
    send(chat_id, 'Команда не распознана.\n' + HELP)

def handle_callback(callback):
    data = callback.get('data') or ''; chat_id = callback['from']['id']
    if not data.startswith('fb:'): return
    _, rec_text, value = data.split(':', 2); rec_id = int(rec_text)
    allowed = {'liked', 'disliked', 'already_listened', 'content_mismatch', 'queue'}
    conn = db.connect(); row = details(conn, rec_id)
    if not row or int(row['child_chat_id'] or 0) != int(chat_id) or value not in allowed:
        answer = 'Эта кнопка недоступна.'
    else:
        conn.execute(
            '''INSERT INTO feedback(recommendation_id,profile_id,actor_chat_id,value)
            VALUES (?,?,?,?) ON CONFLICT(recommendation_id,actor_chat_id)
            DO UPDATE SET value=excluded.value,created_at=CURRENT_TIMESTAMP''',
            (rec_id, row['profile_id'], chat_id, value)
        )
        conn.commit(); answer = 'Спасибо! Я учту это в следующих подборках.'
    conn.close()
    telegram('answerCallbackQuery', {'callback_query_id': callback['id'], 'text': answer})

def weekly_due():
    now = datetime.now(MSK)
    weekday = int(os.environ.get('WEEKLY_WEEKDAY', '6'))
    hour = int(os.environ.get('WEEKLY_HOUR_MSK', '12'))
    return now.weekday() == weekday and now.hour == hour

def run_weekly_once():
    week = (datetime.now(MSK).date() - timedelta(days=datetime.now(MSK).weekday())).isoformat()
    service = 'weekly:' + week
    conn = db.connect(); db.init_schema(conn)
    if conn.execute('SELECT 1 FROM runs WHERE service=? AND status=\'finished\'', (service,)).fetchone():
        conn.close(); return
    run_id = db.start_run(conn, service)
    try:
        from collector.main import collect
        from worker.main import process
        collect(offline=False)
        process()
        profiles = conn.execute('SELECT id FROM profiles WHERE active=1').fetchall()
        total = 0
        for profile in profiles:
            ids = generate(profile['id'], week_key=week); total += len(ids)
            for rec_id in ids: send_draft(rec_id)
        db.finish_run(conn, run_id, total, 'Еженедельные черновики отправлены родителям')
    except Exception as error:
        db.fail_run(conn, run_id, error); raise
    finally:
        conn.close()

def main():
    db.init_schema(); offset = 0; last_schedule_check = 0.0
    LOG.info('Telegram bot started')
    while True:
        try:
            updates = telegram('getUpdates', {'offset': offset, 'timeout': 50, 'allowed_updates': ['message', 'callback_query']})
            for update in updates:
                offset = update['update_id'] + 1
                if update.get('message'): handle_message(update['message'])
                if update.get('callback_query'): handle_callback(update['callback_query'])
            if time.monotonic() - last_schedule_check > 60:
                if weekly_due(): run_weekly_once()
                last_schedule_check = time.monotonic()
        except KeyboardInterrupt:
            return
        except Exception as error:
            LOG.exception('Bot loop error: %s', error); time.sleep(5)

if __name__ == '__main__':
    main()
