"""Private editorial records and an explicit projection for published cards."""
from datetime import date
import re
import json
from urllib.parse import urlsplit

PATH = 'research/library.json'
PUBLICATION = 'https://markkondoskal.substack.com'


def initial():
    return {'version': 1, 'articles': [{
        'id': 'first-substack', 'kind': 'own', 'title': 'Welcome to StockAlerts Research',
        'url': PUBLICATION+'/p/first-substack', 'author': 'Mark Kondoskal',
        'publication': 'Substack', 'published_at': '', 'tickers': [],
        'summary': 'An introduction to my stock research, investment ideas, and the thinking behind StockAlerts.',
        'private_notes': '', 'published': True, 'featured': True}]}


def validate(document):
    if not isinstance(document, dict) or not isinstance(document.get('articles'), list):
        raise ValueError('Expected a research library')
    if len(document['articles']) > 200:
        raise ValueError('Maximum 200 articles per library')
    articles, ids = [], set()
    for raw in document['articles']:
        if not isinstance(raw, dict):
            raise ValueError('Invalid article')
        item = {}
        for field, limit in [('id',80),('title',180),('url',2000),('author',100),
                             ('publication',100),('summary',600),('private_notes',4000),('published_at',10)]:
            value = raw.get(field, '')
            if not isinstance(value, str) or len(value) > limit:
                raise ValueError(f'{field} exceeds its supported length or is not text')
            item[field] = value.strip()
        if not re.fullmatch(r'[A-Za-z0-9_-]{1,80}', item['id']) or item['id'] in ids:
            raise ValueError('Article IDs must be unique')
        ids.add(item['id'])
        if not item['title']:
            raise ValueError('An article title is required')
        try:
            url = urlsplit(item['url'])
            if url.scheme != 'https' or not url.hostname or url.username or url.password:
                raise ValueError('Use a public HTTPS article URL without embedded credentials')
            _ = url.port
        except ValueError:
            raise ValueError('Use a valid public HTTPS article URL')
        if item['published_at']:
            date.fromisoformat(item['published_at'])
        if raw.get('kind') not in ('own','reading'):
            raise ValueError('Choose My research or Reading list')
        item['kind'] = raw['kind']
        if item['kind'] == 'reading' and not item['author']:
            raise ValueError('Credit the original author for a reading-list article')
        tags = raw.get('tickers', [])
        if not isinstance(tags, list) or len(tags) > 10:
            raise ValueError('Use at most 10 ticker tags')
        from watchlist_rules import ticker_symbol
        item['tickers'] = sorted({ticker_symbol(tag) for tag in tags})
        for flag in ('published','featured'):
            if not isinstance(raw.get(flag,False),bool):
                raise ValueError('Visibility flags must be true or false')
            item[flag] = raw.get(flag,False)
        if item['featured'] and not item['published']:
            raise ValueError('A featured article must be published')
        articles.append(item)
    if sum(a['featured'] for a in articles) > 1:
        raise ValueError('Only one article can be featured')
    result = {'version': 1, 'articles': articles}
    if len(json.dumps(result, ensure_ascii=False).encode('utf-8')) > 900000:
        raise ValueError('Research library is too large; shorten notes or archive older items')
    return result


def public(document):
    clean = validate(document)
    allowed = {'id','kind','title','url','author','publication','published_at','tickers','summary','featured'}
    return {'publication_url': PUBLICATION, 'articles': [
        {key: value for key,value in item.items() if key in allowed}
        for item in clean['articles'] if item['published']]}
