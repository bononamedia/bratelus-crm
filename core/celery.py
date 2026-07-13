import os
from celery import Celery
from celery.schedules import crontab

# Set the default Django settings module for the 'celery' program.
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')

# Initialize the Celery app
app = Celery('core')

# Read config from Django settings, the CELERY namespace means all 
# celery-related configuration keys should have a `CELERY_` prefix.
app.config_from_object('django.conf:settings', namespace='CELERY')

# Automatically discover tasks in all of your installed apps (like fsm/tasks.py)
app.autodiscover_tasks()

# ==========================================
# CELERY BEAT SCHEDULE
# ==========================================
app.conf.beat_schedule = {
    'flush-gps-locations-every-5-minutes': {
        'task': 'fsm.tasks.flush_gps_pings_buffer_to_db',
        'schedule': crontab(minute='*/5'), # Fires exactly every 5 minutes
    },
}