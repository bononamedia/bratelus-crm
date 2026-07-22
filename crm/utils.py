from urllib.parse import urlsplit, urlunsplit


def normalize_website(value):
    """Return a user-entered website as a canonical HTTPS URL."""
    value = (value or '').strip()
    if not value:
        return ''
    candidate = value if '://' in value else f'https://{value}'
    parsed = urlsplit(candidate)
    hostname = (parsed.hostname or '').lower().strip('.')
    if not hostname:
        return candidate
    if hostname.startswith('www.'):
        hostname = hostname[4:]
    try:
        port = f':{parsed.port}' if parsed.port else ''
    except ValueError:
        return candidate
    path = parsed.path.rstrip('/')
    return urlunsplit(('https', f'{hostname}{port}', path, parsed.query, ''))
