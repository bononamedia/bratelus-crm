from email.utils import formataddr

from django.conf import settings
from django.core import signing
from django.core.mail import get_connection
from django.core.exceptions import ImproperlyConfigured


EMAIL_VERIFICATION_SALT = 'bratelus-email-verification-v1'


def email_verification_token(user):
    return signing.dumps(
        {'user_id': user.pk, 'email': user.email.lower()},
        salt=EMAIL_VERIFICATION_SALT,
        compress=True,
    )


def read_email_verification_token(token, max_age):
    return signing.loads(token, salt=EMAIL_VERIFICATION_SALT, max_age=max_age)


def platform_email_delivery():
    """Return the active Bratelus SMTP connection and sender addresses."""
    from .models import PlatformEmailSettings

    config = PlatformEmailSettings.objects.first()
    if not config:
        return get_connection(), settings.DEFAULT_FROM_EMAIL, settings.SUPPORT_EMAIL
    if not config.is_active:
        raise ImproperlyConfigured('Platform transactional email is disabled in Superadmin.')

    connection = get_connection(
        backend='django.core.mail.backends.smtp.EmailBackend',
        host=config.smtp_host,
        port=config.smtp_port,
        username=config.smtp_username,
        password=config.get_smtp_password(),
        use_tls=config.use_tls,
        use_ssl=config.use_ssl,
        timeout=settings.EMAIL_TIMEOUT,
    )
    return connection, formataddr((config.display_name, config.from_email)), config.support_email
