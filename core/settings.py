"""
Django settings for core project.
"""

import os
from pathlib import Path

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent

# ==========================================
# SECURITY & HOSTS (Reading from .env)
# ==========================================
SECRET_KEY = os.environ.get(
    'SECRET_KEY',
    'django-insecure-development-only-change-me',
)
DEBUG = os.environ.get('DEBUG', 'False').lower() == 'true'
ALLOWED_HOSTS = [
    host.strip()
    for host in os.environ.get(
        'ALLOWED_HOSTS',
        'bratelus.com,www.bratelus.com,app.bratelus.com,5.78.144.9,localhost,127.0.0.1',
    ).split(',')
    if host.strip()
]


# ==========================================
# APPLICATIONS & MIDDLEWARE
# ==========================================
INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'channels',
    
    'rest_framework',  # <--- ADD THIS RIGHT HERE
    
    # Custom Bratelus FSM/CRM Apps
    'organizations',
    'crm',
    'fsm',
    'finance',
    'chat',
    'storages',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',

    'core.middleware.ActiveOrganizationMiddleware',
]

ROOT_URLCONF = 'core.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'], # Or however yours is formatted
        'APP_DIRS': True,
        'OPTIONS': {
                'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                
                # --- BRATELUS GLOBAL VARIABLES ---
                    'core.context_processors.organization_context',
                    'chat.context_processors.chat_context',
            ],
        },
    },
]

WSGI_APPLICATION = 'core.wsgi.application'

# ==========================================
# CLOUDFLARE R2 (S3-COMPATIBLE) STORAGE
# =========================================

# You will replace these with your actual Cloudflare R2 credentials later
# For security, you should eventually move these to environment variables (.env)
AWS_ACCESS_KEY_ID = os.environ.get('R2_ACCESS_KEY_ID', 'your_access_key_here')
AWS_SECRET_ACCESS_KEY = os.environ.get('R2_SECRET_ACCESS_KEY', 'your_secret_key_here')
AWS_STORAGE_BUCKET_NAME = os.environ.get('R2_BUCKET_NAME', 'gps-teams-evidence')

# Cloudflare specific endpoint: https://<YOUR_CLOUDFLARE_ACCOUNT_ID>.r2.cloudflarestorage.com
AWS_S3_ENDPOINT_URL = os.environ.get('R2_ENDPOINT_URL', 'https://your-account-id.r2.cloudflarestorage.com')

# Tell Django to use this bucket for all User-Uploaded media (like photos)
DEFAULT_FILE_STORAGE = 'storages.backends.s3boto3.S3Boto3Storage'

# Prevent Django from overwriting files with the same name
AWS_S3_FILE_OVERWRITE = False


# ==========================================
# DATABASE (PostgreSQL inside Docker)
# ==========================================
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': 'bratelus_crm',
        'USER': 'crm_admin',
        'PASSWORD': os.environ.get('DB_PASSWORD'),
        'HOST': 'db',
        'PORT': '5432',
    }
}


# ==========================================
# PASSWORD VALIDATION & INT'L
# ==========================================
AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'America/New_York'
USE_I18N = True
USE_TZ = True


# ==========================================
# STATIC FILES
# ==========================================
STATIC_URL = 'static/'
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'
STATIC_ROOT = BASE_DIR / 'staticfiles'
STATICFILES_DIRS = [BASE_DIR / 'static']

LOGIN_REDIRECT_URL = '/dashboard/'
LOGOUT_REDIRECT_URL = '/'


# ==========================================
# ASYNC, CELERY & REDIS
# ==========================================
CELERY_BROKER_URL = os.environ.get('CELERY_BROKER_URL', 'redis://redis:6379/0')
CELERY_RESULT_BACKEND = os.environ.get('CELERY_BROKER_URL', 'redis://redis:6379/0')
CELERY_ACCEPT_CONTENT = ['json']
CELERY_TASK_SERIALIZER = 'json'

# Add the High-Speed Redis Cache for GPS Tracking
CACHES = {
    "default": {
        "BACKEND": "django_redis.cache.RedisCache",
        "LOCATION": "redis://redis:6379/1",
        "OPTIONS": {
            "CLIENT_CLASS": "django_redis.client.DefaultClient",
        }
    }
}

# Channels / WebSockets (for Daphne)
ASGI_APPLICATION = 'core.asgi.application'

CHANNEL_LAYERS = {
    'default': {
        'BACKEND': 'channels_redis.core.RedisChannelLayer',
        'CONFIG': {'hosts': [('redis', 6379)]},
    },
}

# Tell Django to trust form submissions coming from your actual domain
CSRF_TRUSTED_ORIGINS = [
    'https://bratelus.com',
    'https://www.bratelus.com',
    'https://app.bratelus.com',
]

# Tell Django it is sitting safely behind an Nginx proxy that is handling HTTPS
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')

STRIPE_SECRET_KEY = os.environ.get('STRIPE_SECRET_KEY', '')
STRIPE_WEBHOOK_SECRET = os.environ.get('STRIPE_WEBHOOK_SECRET', '')

PASSKEY_RP_ID = os.environ.get('PASSKEY_RP_ID', 'app.bratelus.com')
PASSKEY_ORIGIN = os.environ.get('PASSKEY_ORIGIN', 'https://app.bratelus.com')

CHAT_VAPID_PUBLIC_KEY = os.environ.get('CHAT_VAPID_PUBLIC_KEY', '')
CHAT_VAPID_PRIVATE_KEY = os.environ.get('CHAT_VAPID_PRIVATE_KEY', '/app/.vapid_private.pem')
CHAT_VAPID_SUBJECT = os.environ.get('CHAT_VAPID_SUBJECT', 'mailto:support@bratelus.com')

# Platform transactional email. Workspace email connections remain separate.
EMAIL_HOST = os.environ.get('EMAIL_HOST', '')
EMAIL_PORT = int(os.environ.get('EMAIL_PORT', '587'))
EMAIL_HOST_USER = os.environ.get('EMAIL_HOST_USER', '')
EMAIL_HOST_PASSWORD = os.environ.get('EMAIL_HOST_PASSWORD', '')
EMAIL_USE_TLS = os.environ.get('EMAIL_USE_TLS', 'true').lower() in ('1', 'true', 'yes')
EMAIL_TIMEOUT = 15
EMAIL_BACKEND = os.environ.get(
    'EMAIL_BACKEND',
    'django.core.mail.backends.smtp.EmailBackend' if EMAIL_HOST else 'django.core.mail.backends.console.EmailBackend',
)
DEFAULT_FROM_EMAIL = os.environ.get('DEFAULT_FROM_EMAIL', 'Bratelus <support@bratelus.com>')
SUPPORT_EMAIL = os.environ.get('SUPPORT_EMAIL', 'support@bratelus.com')
APP_BASE_URL = os.environ.get('APP_BASE_URL', 'https://app.bratelus.com')
