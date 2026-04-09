import requests


class CloudSync:
    """Uploads browsing history records to Supabase REST API."""

    def __init__(self, get_config):
        self._get_config = get_config

    def sync(self, records):
        """
        Upload unsynced records to Supabase.
        records: list of (id, url, title, domain, visited_at) tuples.
        Returns (success: bool, message: str).
        """
        config = self._get_config()
        url = config.get('supabase_url', '').rstrip('/')
        key = config.get('supabase_key', '')

        if not url or not key:
            return False, 'Supabase not configured in settings'

        headers = {
            'apikey': key,
            'Authorization': f'Bearer {key}',
            'Content-Type': 'application/json',
            'Prefer': 'return=minimal',
        }

        payload = [
            {
                'url': r[1],
                'title': r[2],
                'domain': r[3],
                'visited_at': r[4],
                'is_flagged': bool(r[5]),
                'category': r[6],
                'reason': r[7],
                'severity': r[8],
            }
            for r in records
        ]

        try:
            resp = requests.post(
                f'{url}/rest/v1/browsing_history',
                headers=headers,
                json=payload,
                timeout=15,
            )
            if resp.status_code in (200, 201):
                return True, 'OK'
            return False, f'HTTP {resp.status_code}: {resp.text[:200]}'
        except Exception as e:
            return False, str(e)
