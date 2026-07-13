import os
import re

import requests


SPANISH_MARKERS = re.compile(
    r'\b(el|la|los|las|un|una|que|para|con|sin|trabajo|limpieza|terminado|puerta|cerrada|problema|necesita|gracias)\b|[¿¡ñáéíóú]',
    re.IGNORECASE,
)


def note_needs_translation(text):
    return bool(SPANISH_MARKERS.search(text or ''))


def translate_note_to_english(text):
    """Translate through a configured LibreTranslate-compatible endpoint."""
    if not note_needs_translation(text):
        return text, 'en', 'not_needed'

    endpoint = os.environ.get('FIELD_TRANSLATION_API_URL', '').strip()
    if not endpoint:
        return '', 'es', 'pending'

    payload = {'q': text, 'source': 'auto', 'target': 'en', 'format': 'text'}
    api_key = os.environ.get('FIELD_TRANSLATION_API_KEY', '').strip()
    if api_key:
        payload['api_key'] = api_key

    try:
        response = requests.post(endpoint, json=payload, timeout=15)
        response.raise_for_status()
        data = response.json()
        translated = data.get('translatedText') or data.get('translation') or ''
        if translated:
            return translated, data.get('detectedLanguage', 'es'), 'translated'
    except (requests.RequestException, ValueError):
        pass
    return '', 'es', 'failed'
