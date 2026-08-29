"""
Hybrid URL classifier:
  1. Rule-based lookup for known domains (instant, no API, no cost)
  2. Google Gemini 1.5 Flash free API for unknown domains
"""
import json
import os
import re
from urllib.parse import urlparse, parse_qs, unquote_plus

# ── Rule-based domain table ───────────────────────────────────────────────
# Format: 'domain': ('category', 'reason', 'severity')
# is_flagged = True for everything except 'safe'
DOMAIN_RULES = {
    # ── Streaming ──
    'youtube.com':      ('streaming',   'YouTube video platform',        'medium'),
    'youtu.be':         ('streaming',   'YouTube short link',            'medium'),
    'twitch.tv':        ('streaming',   'Live gaming streams',           'medium'),
    'netflix.com':      ('streaming',   'Netflix',                       'low'),
    'disneyplus.com':   ('streaming',   'Disney+',                       'low'),
    'primevideo.com':   ('streaming',   'Amazon Prime Video',            'low'),
    'hotstar.com':      ('streaming',   'Hotstar streaming',             'low'),
    'crunchyroll.com':  ('streaming',   'Anime streaming',               'low'),

    # ── Gaming ──
    'roblox.com':           ('gaming', 'Roblox online games',            'medium'),
    'steam.com':            ('gaming', 'Steam gaming platform',          'medium'),
    'steampowered.com':     ('gaming', 'Steam gaming platform',          'medium'),
    'epicgames.com':        ('gaming', 'Epic Games store',               'medium'),
    'minecraft.net':        ('gaming', 'Minecraft',                      'medium'),
    'miniclip.com':         ('gaming', 'Browser games',                  'medium'),
    'friv.com':             ('gaming', 'Browser games',                  'medium'),
    'poki.com':             ('gaming', 'Browser games',                  'medium'),
    'coolmathgames.com':    ('gaming', 'Math and puzzle games',          'low'),
    'kongregate.com':       ('gaming', 'Browser games',                  'medium'),
    'addictinggames.com':   ('gaming', 'Browser games',                  'medium'),
    'itch.io':              ('gaming', 'Indie game platform',            'medium'),
    'gamesfreak.net':       ('gaming', 'Browser games',                  'medium'),
    'y8.com':               ('gaming', 'Browser games',                  'medium'),

    # ── Social Media ──
    'instagram.com':    ('social_media', 'Instagram',                    'medium'),
    'facebook.com':     ('social_media', 'Facebook',                     'medium'),
    'twitter.com':      ('social_media', 'Twitter/X',                    'medium'),
    'x.com':            ('social_media', 'Twitter/X',                    'medium'),
    'snapchat.com':     ('social_media', 'Snapchat',                     'high'),
    'tiktok.com':       ('social_media', 'TikTok short videos',          'high'),
    'discord.com':      ('social_media', 'Discord chat',                 'medium'),
    'reddit.com':       ('social_media', 'Reddit - unmoderated content', 'high'),
    'tumblr.com':       ('social_media', 'Tumblr - adult content risk',  'high'),
    'pinterest.com':    ('social_media', 'Pinterest image sharing',      'low'),
    'whatsapp.com':     ('social_media', 'WhatsApp messaging',           'low'),
    'telegram.org':     ('social_media', 'Telegram messaging',           'medium'),

    # ── Gambling ──
    'bet365.com':       ('gambling', 'Online gambling site',             'high'),
    'betway.com':       ('gambling', 'Online gambling site',             'high'),
    'draftkings.com':   ('gambling', 'Sports betting',                   'high'),
    'fanduel.com':      ('gambling', 'Sports betting',                   'high'),
    'pokerstars.com':   ('gambling', 'Online poker',                     'high'),

    # ── Safe / Educational ──
    'google.com':           ('safe', 'Google search',                    'low'),
    'bing.com':             ('safe', 'Bing search',                      'low'),
    'wikipedia.org':        ('safe', 'Wikipedia encyclopedia',           'low'),
    'khanacademy.org':      ('safe', 'Khan Academy education',           'low'),
    'stackoverflow.com':    ('safe', 'Programming Q&A',                  'low'),
    'github.com':           ('safe', 'Code repository',                  'low'),
    'britannica.com':       ('safe', 'Encyclopedia Britannica',          'low'),
    'duolingo.com':         ('safe', 'Language learning',                'low'),
    'coursera.org':         ('safe', 'Online courses',                   'low'),
}

# Domain fragments that immediately flag as adult/high-severity
_ADULT_KEYWORDS = [
    'porn', 'xxx', 'adult', r'\bsex\b', 'nude', 'erotic',
    'hentai', 'nsfw', 'onlyfans', 'fetish', 'escort',
]

# Search engines whose ?q= param must be evaluated separately
_SEARCH_DOMAINS = {'google.com', 'bing.com', 'duckduckgo.com', 'yahoo.com', 'yandex.com'}

# Keywords for raw search query text (broader than domain keywords)
_QUERY_ADULT_KEYWORDS = [
    r'\bporn\b', r'\bporno\b', r'\bxxx\b', r'\bnude\b', r'\bnudes\b',
    r'\bnaked\b', r'\bsex\b', r'\bsexed\b', r'\bsexual\b', r'\bsexually\b',
    r'\berotic\b', r'\bhentai\b', r'\bnsfw\b', r'\bonlyfans\b',
    r'\bfetish\b', r'\bboobs\b', r'\bvagina\b', r'\bpenis\b',
    r'\bfuck\b', r'\bfucking\b', r'\bbusty\b', r'\bmilf\b',
]


def _extract_search_query(url: str) -> str | None:
    """Extract the ?q= search query from a search engine URL."""
    try:
        qs = parse_qs(urlparse(url).query)
        raw = qs.get('q', [None])[0]
        return unquote_plus(raw) if raw else None
    except Exception:
        return None


def _classify_search_query(query: str, gemini: bool = True) -> dict | None:
    """
    Check a raw search query string for adult content.
    Returns a flagged result dict if adult, None if safe/unknown.
    Never cached — each query is independent.
    """
    for kw in _QUERY_ADULT_KEYWORDS:
        if re.search(kw, query, re.IGNORECASE):
            return {
                'is_flagged': True,
                'category': 'adult',
                'reason': 'Adult content in search query',
                'severity': 'high',
            }

    if not gemini:
        return None

    model = _get_gemini_model()
    if model is None:
        return None

    prompt = (
        'You are a content-safety classifier for a parental control app. Child is 13 years old.\n'
        'Is this web search query looking for adult or pornographic content?\n\n'
        f'Search query: {query}\n\n'
        'Reply ONLY with JSON: {"is_adult": true or false, "reason": "brief reason under 60 chars"}'
    )
    try:
        resp = model.generate_content(prompt)
        try:
            text = resp.text.strip()
        except Exception:
            # Gemini safety block on the query itself is itself an adult signal
            return {
                'is_flagged': True,
                'category': 'adult',
                'reason': 'Search query blocked by safety filter',
                'severity': 'high',
            }
        if '```' in text:
            text = text.split('```')[1]
            if text.startswith('json'):
                text = text[4:]
        data = json.loads(text.strip())
        if data.get('is_adult'):
            return {
                'is_flagged': True,
                'category': 'adult',
                'reason': data.get('reason', 'Adult search query')[:60],
                'severity': 'high',
            }
    except Exception:
        pass
    return None

_gemini_model = None
_cache: dict = {}

# ── Persistent domain cache ───────────────────────────────────────────────
# Saved next to the EXE so Gemini is called at most once per domain, ever.
if getattr(__import__('sys'), 'frozen', False):
    _CACHE_FILE = os.path.join(os.path.dirname(__import__('sys').executable), 'domain_cache.json')
else:
    _CACHE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'domain_cache.json')

def _load_cache():
    try:
        with open(_CACHE_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {}

def _save_cache():
    """
    Persist only confirmed-flagged verdicts to disk. A Gemini "safe" guess can
    be wrong (e.g. a generic-sounding domain judged with no page title) and
    shouldn't permanently whitelist a domain across restarts — only what's
    clearly flagged is safe to trust indefinitely.
    """
    try:
        persist = {k: v for k, v in _cache.items() if v.get('is_flagged')}
        with open(_CACHE_FILE, 'w', encoding='utf-8') as f:
            json.dump(persist, f)
    except Exception:
        pass

_cache = _load_cache()


# ── Helpers ───────────────────────────────────────────────────────────────
def _strip_www(domain: str) -> str:
    d = domain.lower()
    if d.startswith('www.'):
        d = d[4:]
    return d


def _adult_pattern_match(domain: str) -> bool:
    for kw in _ADULT_KEYWORDS:
        if re.search(kw, domain, re.IGNORECASE):
            return True
    return False


def _rule_lookup(domain: str):
    """Returns (category, reason, severity) or None."""
    d = _strip_www(domain)

    if _adult_pattern_match(d):
        return ('adult', 'Adult content detected in domain', 'high')

    # Exact match
    if d in DOMAIN_RULES:
        return DOMAIN_RULES[d]

    # Parent-domain match (e.g. sub.youtube.com → youtube.com)
    parts = d.split('.')
    for i in range(1, len(parts) - 1):
        parent = '.'.join(parts[i:])
        if parent in DOMAIN_RULES:
            return DOMAIN_RULES[parent]

    return None


# ── Gemini free API ───────────────────────────────────────────────────────
def _get_gemini_model():
    global _gemini_model
    if _gemini_model is not None:
        return _gemini_model
    key = os.environ.get('GEMINI_API_KEY', '')
    if not key:
        return None
    try:
        import google.generativeai as genai
        genai.configure(api_key=key)
        _gemini_model = genai.GenerativeModel('gemini-2.5-flash')
    except Exception as e:
        print(f'[classifier] Gemini init failed: {e}')
    return _gemini_model


_GEMINI_PROMPT = """\
You are a content-safety classifier for a parental control app. The child is 13 years old.
Decide if this website is appropriate for a 13-year-old.

URL: {url}
Title: {title}
Domain: {domain}

Reply ONLY with a JSON object — no extra text:
{{"is_flagged": true or false,
  "category": "safe" | "gaming" | "social_media" | "adult" | "violence" | "gambling" | "streaming" | "other",
  "reason": "brief reason under 60 characters",
  "severity": "low" | "medium" | "high"}}

Flag true for: adult/explicit content, graphic violence, gambling, heavy gaming, unmoderated social platforms.
severity=high: adult/explicit/gambling. severity=medium: gaming/social media. severity=low: borderline."""


def _gemini_classify(url: str, title: str, domain: str):
    """Returns a result dict, or None if rate-limited/errored (caller must not cache None)."""
    model = _get_gemini_model()
    if model is None:
        return {'is_flagged': False, 'category': 'unclassified',
                'reason': 'Gemini key not set', 'severity': 'low'}
    try:
        resp = model.generate_content(
            _GEMINI_PROMPT.format(url=url, title=title, domain=domain)
        )
        try:
            text = resp.text.strip()
        except Exception:
            # .text accessor failed — Gemini's safety filter blocked the response.
            # A safety block on a URL is itself a strong adult-content signal.
            return {'is_flagged': True, 'category': 'adult',
                    'reason': 'Blocked by Gemini safety filter', 'severity': 'high'}
        if '```' in text:
            text = text.split('```')[1]
            if text.startswith('json'):
                text = text[4:]
        return json.loads(text.strip())
    except Exception as e:
        err = str(e)
        if '429' in err or 'quota' in err.lower() or 'rate' in err.lower():
            return None  # Don't cache — retry next cycle
        return {'is_flagged': False, 'category': 'unclassified',
                'reason': err[:60], 'severity': 'low'}


# ── Public API ────────────────────────────────────────────────────────────
def classify(url: str, title: str = '', domain: str = '', gemini: bool = True) -> dict:
    """
    Classify a URL. Checks rules first, optionally falls back to Gemini.
    Pass gemini=False for the fast path (no API calls, unknown → unclassified).
    Rule-based lookups are deterministic and never cached (cheap to recompute).
    Gemini verdicts are cached per (domain, title) for the process lifetime —
    not per domain alone, since different pages on the same domain (e.g. a
    directory site) can have very different titles and very different content.
    """
    # For search engines, evaluate the query string — domain is "safe" but query might not be.
    if _strip_www(domain) in _SEARCH_DOMAINS:
        query = _extract_search_query(url)
        if query:
            flagged = _classify_search_query(query, gemini=gemini)
            if flagged:
                return flagged  # Don't cache — every query URL is different

    rule = _rule_lookup(domain)
    if rule:
        cat, reason, sev = rule
        return {
            'is_flagged': cat != 'safe',
            'category': cat,
            'reason': reason,
            'severity': sev,
        }

    if not gemini:
        return {'is_flagged': False, 'category': 'unclassified',
                'reason': '', 'severity': 'low'}

    cache_key = f'{domain or url}::{title}'
    if cache_key in _cache:
        return _cache[cache_key]

    result = _gemini_classify(url, title, domain)
    if result is None:
        # Rate-limited — don't cache, will be retried
        return {'is_flagged': False, 'category': 'unclassified',
                'reason': 'rate limited', 'severity': 'low'}

    _cache[cache_key] = result
    _save_cache()
    return result
