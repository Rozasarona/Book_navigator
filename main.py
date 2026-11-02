'''Service entry point for local runs and Coolify.'''
from __future__ import annotations
import argparse, json, logging, os
from pathlib import Path

ROOT = Path(__file__).resolve().parent

def load_env():
    path = ROOT / '.env'
    if not path.exists(): return
    for raw in path.read_text(encoding='utf-8').splitlines():
        line = raw.strip()
        if not line or line.startswith('#') or '=' not in line: continue
        key, value = line.split('=', 1)
        os.environ.setdefault(key.strip(), value.strip())

load_env()
logging.basicConfig(
    level=os.environ.get('LOG_LEVEL', 'INFO'),
    format='%(asctime)s %(levelname)s %(name)s: %(message)s'
)

import db
from collector.main import collect
from worker.main import process
from worker.recommend import create_profile, generate, link_child

def inspect_database():
    conn = db.connect(); db.init_schema(conn)
    tables = ['sources', 'books', 'audio_editions', 'book_analyses', 'profiles', 'recommendations', 'feedback']
    counts = {table: conn.execute('SELECT count(*) n FROM ' + table).fetchone()['n'] for table in tables}
    findings = [dict(row) for row in conn.execute(
        '''SELECT b.title,b.author,a.age_min,a.age_max,a.interest_tags_json,
        a.content_flags_json,a.enough_information,a.teaser
        FROM books b JOIN book_analyses a ON a.book_id=b.id ORDER BY a.id DESC LIMIT 10'''
    )]
    conn.close()
    print(json.dumps({'counts': counts, 'findings': findings}, ensure_ascii=False, indent=2))

def demo():
    collection = collect(offline=True)
    analysis = process(mode='heuristic')
    profile_id, code = create_profile(
        1001, 'Тестовый ребёнок', 8, ['приключения', 'дружба', 'юмор'],
        ['насилие', 'буллинг'], ''
    )
    link_child(code, 2001)
    recommendations = generate(profile_id)
    print(json.dumps({
        'collection': collection, 'analysis': analysis,
        'profile_id': profile_id, 'recommendation_ids': recommendations,
    }, ensure_ascii=False, indent=2))
    inspect_database()

def main():
    parser = argparse.ArgumentParser(description='Book Navigator')
    parser.add_argument('service', choices=['init', 'collector', 'worker', 'pipeline', 'bot', 'demo', 'inspect'])
    parser.add_argument('--offline', action='store_true', help='Use the bundled sample catalog')
    parser.add_argument('--heuristic', action='store_true', help='Do not call AITUNNEL')
    parser.add_argument('--reanalyze', action='store_true')
    args = parser.parse_args()
    if args.service == 'init': db.init_schema(); print('Database initialized')
    elif args.service == 'collector': print(db.json_dump(collect(args.offline)))
    elif args.service == 'worker':
        print(db.json_dump(process('heuristic' if args.heuristic else None, args.reanalyze)))
    elif args.service == 'pipeline':
        print(db.json_dump(collect(args.offline)))
        print(db.json_dump(process('heuristic' if args.heuristic or args.offline else None, args.reanalyze)))
        inspect_database()
    elif args.service == 'demo': demo()
    elif args.service == 'inspect': inspect_database()
    elif args.service == 'bot':
        from bot.main import main as run_bot
        run_bot()

if __name__ == '__main__':
    main()
