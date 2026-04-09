"""
Hybrid URL classifier:
  1. Rule-based lookup for known domains (instant, no API, no cost)
  2. Google Gemini 1.5 Flash free API for unknown domains
"""
import json
import os
import re

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

_gemini_model = None
_cache: dict = {}


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
        _gemini_model = genai.GenerativeModel('gemini-1.5-flash')
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


def _gemini_classify(url: str, title: str, domain: str) -> dict:
    model = _get_gemini_model()
    if model is None:
        return {'is_flagged': False, 'category': 'unclassified',
                'reason': 'Gemini key not set', 'severity': 'low'}
    try:
        resp = model.generate_content(
            _GEMINI_PROMPT.format(url=url, title=title, domain=domain)
        )
        text = resp.text.strip()
        if '```' in text:
            text = text.split('```')[1]
            if text.startswith('json'):
                text = text[4:]
        return json.loads(text.strip())
    except Exception as e:
        return {'is_flagged': False, 'category': 'unclassified',
                'reason': str(e)[:60], 'severity': 'low'}


# ── Public API ────────────────────────────────────────────────────────────
def classify(url: str, title: str = '', domain: str = '') -> dict:
    """
    Classify a URL. Checks rules first, falls back to Gemini for unknowns.
    Results cached per domain for the lifetime of the process.
    """
    cache_key = domain or url
    if cache_key in _cache:
        return _cache[cache_key]

    rule = _rule_lookup(domain)
    if rule:
        cat, reason, sev = rule
        result = {
            'is_flagged': cat != 'safe',
            'category': cat,
            'reason': reason,
            'severity': sev,
        }
    else:
        result = _gemini_classify(url, title, domain)

    _cache[cache_key] = result
    return result
