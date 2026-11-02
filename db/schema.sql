PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS sources (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    kind TEXT NOT NULL,
    url TEXT,
    config_json TEXT NOT NULL DEFAULT '{}',
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    service TEXT NOT NULL,
    status TEXT NOT NULL,
    started_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    finished_at TEXT,
    items INTEGER NOT NULL DEFAULT 0,
    note TEXT
);

CREATE TABLE IF NOT EXISTS books (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    canonical_key TEXT NOT NULL UNIQUE,
    title TEXT NOT NULL,
    author TEXT,
    description TEXT,
    genre TEXT,
    age_min INTEGER,
    age_max INTEGER,
    language TEXT NOT NULL DEFAULT 'ru',
    published_date TEXT,
    publisher TEXT,
    isbn TEXT,
    cover_url TEXT,
    analysis_status TEXT NOT NULL DEFAULT 'new',
    collected_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_books_isbn ON books(isbn);
CREATE INDEX IF NOT EXISTS idx_books_status ON books(analysis_status);

CREATE TABLE IF NOT EXISTS audio_editions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    book_id INTEGER NOT NULL REFERENCES books(id) ON DELETE CASCADE,
    source_id INTEGER NOT NULL REFERENCES sources(id),
    external_id TEXT NOT NULL,
    narrator TEXT,
    duration_seconds INTEGER,
    audio_url TEXT,
    product_url TEXT,
    availability TEXT NOT NULL DEFAULT 'unverified',
    availability_note TEXT,
    rating REAL,
    review_count INTEGER,
    raw_json TEXT,
    collected_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(source_id, external_id)
);
CREATE INDEX IF NOT EXISTS idx_audio_book ON audio_editions(book_id);

CREATE TABLE IF NOT EXISTS reviews (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    book_id INTEGER NOT NULL REFERENCES books(id) ON DELETE CASCADE,
    source_id INTEGER REFERENCES sources(id),
    external_id TEXT,
    rating REAL,
    text TEXT,
    author_name TEXT,
    published_at TEXT,
    raw_json TEXT,
    UNIQUE(source_id, external_id)
);

CREATE TABLE IF NOT EXISTS book_analyses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    book_id INTEGER NOT NULL REFERENCES books(id) ON DELETE CASCADE,
    analyzer TEXT NOT NULL,
    model TEXT NOT NULL,
    prompt_version TEXT NOT NULL,
    age_min INTEGER,
    age_max INTEGER,
    interest_tags_json TEXT NOT NULL DEFAULT '[]',
    content_flags_json TEXT NOT NULL DEFAULT '[]',
    safe_for_children INTEGER NOT NULL,
    enough_information INTEGER NOT NULL,
    teaser TEXT,
    summary TEXT,
    confidence REAL,
    request_id TEXT,
    cost_rub REAL,
    raw_response_json TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(book_id, analyzer, model, prompt_version)
);

CREATE TABLE IF NOT EXISTS profiles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    parent_chat_id INTEGER NOT NULL,
    child_chat_id INTEGER,
    child_name TEXT NOT NULL,
    age INTEGER NOT NULL CHECK(age BETWEEN 4 AND 14),
    interests_json TEXT NOT NULL DEFAULT '[]',
    restrictions_json TEXT NOT NULL DEFAULT '[]',
    other_restrictions TEXT,
    link_code TEXT NOT NULL UNIQUE,
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_profiles_parent ON profiles(parent_chat_id);
CREATE INDEX IF NOT EXISTS idx_profiles_child ON profiles(child_chat_id);

CREATE TABLE IF NOT EXISTS recommendations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    profile_id INTEGER NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
    book_id INTEGER NOT NULL REFERENCES books(id),
    audio_edition_id INTEGER REFERENCES audio_editions(id),
    week_key TEXT NOT NULL,
    score REAL NOT NULL,
    rationale TEXT,
    teaser TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'draft',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    approved_at TEXT,
    sent_at TEXT,
    UNIQUE(profile_id, book_id, week_key)
);
CREATE INDEX IF NOT EXISTS idx_rec_profile_status ON recommendations(profile_id, status);

CREATE TABLE IF NOT EXISTS feedback (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    recommendation_id INTEGER NOT NULL REFERENCES recommendations(id) ON DELETE CASCADE,
    profile_id INTEGER NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
    actor_chat_id INTEGER NOT NULL,
    value TEXT NOT NULL CHECK(value IN (
        'liked', 'disliked', 'already_listened', 'content_mismatch', 'queue'
    )),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(recommendation_id, actor_chat_id)
);
