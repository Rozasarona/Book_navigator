import os, tempfile, unittest
from pathlib import Path

import db
from collector.main import collect
from worker.main import process
from worker.recommend import create_profile, generate, link_child

class PipelineTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        os.environ['DATABASE_PATH'] = str(Path(self.temp.name) / 'test.db')
        db.init_schema()

    def tearDown(self):
        self.temp.cleanup()

    def test_full_offline_pipeline_and_deduplication(self):
        first = collect(offline=True)
        self.assertEqual(first['saved'], 6)
        collect(offline=True)
        conn = db.connect()
        self.assertEqual(conn.execute('SELECT count(*) n FROM books').fetchone()['n'], 6)
        self.assertEqual(conn.execute('SELECT count(*) n FROM audio_editions').fetchone()['n'], 6)
        conn.close()

        result = process(mode='heuristic')
        self.assertEqual(result['processed'], 6)
        self.assertEqual(result['failed'], 0)

        profile_id, code = create_profile(
            101, 'Аня', 8, ['приключения', 'дружба'], ['насилие'], ''
        )
        self.assertEqual(link_child(code, 202), profile_id)
        recommendation_ids = generate(profile_id)
        self.assertGreaterEqual(len(recommendation_ids), 5)
        self.assertLessEqual(len(recommendation_ids), 7)

        conn = db.connect()
        titles = [row['title'] for row in conn.execute(
            '''SELECT b.title FROM recommendations r JOIN books b ON b.id=r.book_id
            WHERE r.profile_id=?''', (profile_id,)
        )]
        self.assertNotIn('Мио, мой Мио!', titles)
        self.assertTrue(all(row['teaser'] for row in conn.execute('SELECT teaser FROM recommendations')))
        conn.close()

    def test_profile_age_bounds(self):
        with self.assertRaises(ValueError):
            create_profile(1, 'Слишком маленький', 3, [], [], '')
        with self.assertRaises(ValueError):
            create_profile(1, 'Слишком взрослый', 15, [], [], '')

if __name__ == '__main__':
    unittest.main()
