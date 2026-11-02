'''Free sources enabled for the MVP. Add another mapping to connect a source.'''

SOURCE_DEFINITIONS = [
    {
        'name': 'Google Books: детские книги',
        'kind': 'google_books',
        'url': 'https://www.googleapis.com/books/v1/volumes',
        'config': {
            'queries': ['детская литература', 'детское фэнтези', 'приключения для детей'],
            'max_per_query': 20,
        },
    },
    {
        'name': 'Open Library: children RU',
        'kind': 'open_library',
        'url': 'https://openlibrary.org/search.json',
        'config': {'limit': 40},
    },
    {
        'name': 'LibriVox: Russian',
        'kind': 'librivox',
        'url': 'https://librivox.org/api/feed/audiobooks',
        'config': {'limit': 500},
    },
    {
        'name': 'Демонстрационный каталог',
        'kind': 'sample',
        'url': None,
        'config': {}, 'active': False,
    },
]

