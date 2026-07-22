import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured


def _fernet():
    source = getattr(settings, 'EMAIL_CREDENTIAL_ENCRYPTION_KEY', '') or settings.SECRET_KEY
    key = base64.urlsafe_b64encode(hashlib.sha256(source.encode('utf-8')).digest())
    return Fernet(key)


def encrypt_secret(value):
    return _fernet().encrypt(value.encode('utf-8')).decode('ascii')


def decrypt_secret(value):
    try:
        return _fernet().decrypt(value.encode('ascii')).decode('utf-8')
    except InvalidToken as exc:
        raise ImproperlyConfigured(
            'The platform email password cannot be decrypted. Check the credential encryption key.'
        ) from exc
