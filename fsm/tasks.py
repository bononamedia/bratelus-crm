import math
import os
import requests
from celery import shared_task
from django.core.mail import EmailMessage
from PIL import Image
from PIL.ExifTags import TAGS, GPSTAGS
from .models import (
    CompletionNotificationDelivery,
    CompletionNotificationSetting,
    FieldEvent,
    Job,
    JobEvidence,
)
from organizations.models import WorkspaceEmailConnection
from .translation import translate_note_to_english
import json
from django.core.cache import cache
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from .models import WorkerLocation

# --- Helper Functions for Coordinate Math ---
def get_decimal_from_dms(dms, ref):
    """Converts Degrees/Minutes/Seconds EXIF data into Decimal coordinates."""
    degrees = dms[0]
    minutes = dms[1]
    seconds = dms[2]
    decimal = float(degrees) + float(minutes)/60 + float(seconds)/3600
    if ref in ['S', 'W']:
        decimal = -decimal
    return decimal

def calculate_distance(lat1, lon1, lat2, lon2):
    """Haversine formula to calculate distance in meters between two GPS points."""
    R = 6371000 # Earth radius in meters
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)
    
    a = math.sin(delta_phi/2.0)**2 + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda/2.0)**2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))
    return R * c

# --- The Main Celery Task ---
@shared_task
def verify_photo_evidence(evidence_id):
    """
    Runs in the background. Opens the uploaded photo, extracts GPS data,
    and flags the database if the photo was taken > 100 meters from the property.
    """
    try:
        evidence = JobEvidence.objects.select_related('job__property').get(id=evidence_id)
        if evidence.media_type != 'photo':
            evidence.qc_notes = "Video evidence saved. GPS was verified from the field event."
            evidence.is_verified = True
            evidence.save(update_fields=['qc_notes', 'is_verified'])
            return
        
        # Open the image using Pillow (works seamlessly with S3 via Django Storage)
        image = Image.open(evidence.photo.open('rb'))
        exif_info = image.getexif()
        
        if not exif_info:
            evidence.qc_notes = "FAILED: No EXIF data found. Photo may be a screenshot or edited."
            evidence.is_verified = False
            evidence.save()
            return
            
        # Extract GPS Info
        gps_info = {}
        for key, value in exif_info.get_ifd(0x8825).items():
            decode = GPSTAGS.get(key, key)
            gps_info[decode] = value
            
        if 'GPSLatitude' not in gps_info or 'GPSLongitude' not in gps_info:
            evidence.qc_notes = "FAILED: Location services were disabled on the camera."
            evidence.is_verified = False
            evidence.save()
            return

        # Convert to Decimals
        photo_lat = get_decimal_from_dms(gps_info['GPSLatitude'], gps_info['GPSLatitudeRef'])
        photo_lng = get_decimal_from_dms(gps_info['GPSLongitude'], gps_info['GPSLongitudeRef'])
        
        # Save exact photo coordinates to the DB
        evidence.lat = photo_lat
        evidence.lng = photo_lng
        
        # Compare to Property Location
        expected_lat = evidence.job.property.location_lat
        expected_lng = evidence.job.property.location_lng
        
        if expected_lat and expected_lng:
            distance = calculate_distance(photo_lat, photo_lng, float(expected_lat), float(expected_lng))
            
            if distance <= 100: # 100 meters tolerance
                evidence.is_verified = True
                evidence.qc_notes = f"PASSED: Photo taken {int(distance)}m from target property."
            else:
                evidence.is_verified = False
                evidence.qc_notes = f"FLAGGED: Photo taken {int(distance)}m away from property!"
        else:
            evidence.is_verified = False
            evidence.qc_notes = "PENDING: Property has no coordinates set to verify against."

        evidence.save()

    except JobEvidence.DoesNotExist:
        pass


@shared_task
def translate_field_note(event_id):
    try:
        event = FieldEvent.objects.get(id=event_id, event_type='note_added')
    except FieldEvent.DoesNotExist:
        return
    translated, language, translation_status = translate_note_to_english(event.note_original)
    event.note_english = translated
    event.source_language = language
    event.translation_status = translation_status
    event.save(update_fields=['note_english', 'source_language', 'translation_status'])


def render_completion_template(template, job, contact):
    values = {
        'first_name': contact.first_name if contact else 'Customer',
        'service': job.title,
        'workspace_name': job.organization.name,
        'account_name': job.account.name,
    }
    rendered = template
    for key, value in values.items():
        rendered = rendered.replace('{{' + key + '}}', str(value or ''))
    return rendered


@shared_task
def send_completion_notifications(job_id):
    try:
        job = Job.objects.select_related('organization', 'account', 'completion_contact').get(id=job_id)
    except Job.DoesNotExist:
        return
    if job.completion_notification_method == 'none':
        return

    contact = job.completion_contact or job.account.contacts.order_by('-is_primary', 'id').first()
    setting, _ = CompletionNotificationSetting.objects.get_or_create(workspace=job.organization)
    message = render_completion_template(job.completion_message_override or setting.message_template, job, contact)
    subject = render_completion_template(setting.email_subject, job, contact)
    channels = ['email', 'sms'] if job.completion_notification_method == 'both' else [job.completion_notification_method]

    for channel in channels:
        recipient = ''
        if contact:
            recipient = contact.email if channel == 'email' else (contact.mobile or contact.phone)
        delivery, created = CompletionNotificationDelivery.objects.get_or_create(
            job=job,
            channel=channel,
            defaults={'contact': contact, 'recipient': recipient, 'subject': subject if channel == 'email' else '', 'message': message},
        )
        if not created and delivery.status == 'sent':
            continue
        delivery.contact = contact
        delivery.recipient = recipient
        delivery.message = message
        delivery.subject = subject if channel == 'email' else ''
        if not recipient:
            delivery.status = 'failed'
            delivery.error_message = f'The completion contact has no {channel} address.'
            delivery.save()
            continue

        try:
            if channel == 'email':
                mailbox = WorkspaceEmailConnection.objects.filter(workspace=job.organization, status='active').first()
                if not mailbox:
                    raise RuntimeError('No active workspace email connection is configured.')
                email = EmailMessage(
                    subject=subject,
                    body=message,
                    from_email=mailbox.from_email,
                    to=[recipient],
                    reply_to=[setting.reply_to_email or mailbox.from_email],
                )
                email.send(fail_silently=False)
                delivery.provider_reference = 'workspace-email'
            else:
                account_sid = os.environ.get('TWILIO_ACCOUNT_SID', '').strip()
                auth_token = os.environ.get('TWILIO_AUTH_TOKEN', '').strip()
                from_number = setting.sms_from_number or os.environ.get('TWILIO_FROM_NUMBER', '').strip()
                if not all([account_sid, auth_token, from_number]):
                    raise RuntimeError('Twilio credentials or workspace sender number are not configured.')
                response = requests.post(
                    f'https://api.twilio.com/2010-04-01/Accounts/{account_sid}/Messages.json',
                    data={'To': recipient, 'From': from_number, 'Body': message},
                    auth=(account_sid, auth_token),
                    timeout=20,
                )
                response.raise_for_status()
                delivery.provider_reference = response.json().get('sid', '')
            delivery.status = 'sent'
            delivery.sent_at = timezone.now()
            delivery.error_message = ''
        except (RuntimeError, requests.RequestException, ValueError, Exception) as exc:
            delivery.status = 'failed'
            delivery.error_message = str(exc)[:1000]
        delivery.save()

# ----------------------------------------------------------------------------
# Creat the Bulk Writer
# ============================================================================

@shared_task
def flush_gps_pings_buffer_to_db():
    """
    Periodic task that safely flushes cached GPS points from the 
    Redis queue into PostgreSQL using a high-performance bulk operation.
    """
    # 1. Connect directly to the underlying Redis instance behind Django's cache wrapper
    redis_client = cache.client.get_client()
    
    # 2. Extract all currently queued items in the list atomically
    # We rename the key temporarily or read all items up to the current length to prevent race conditions
    buffer_length = redis_client.llen("raw_gps_pings_buffer")
    if buffer_length == 0:
        return "Buffer is empty. No tracking points to write."

    # Pop 'buffer_length' number of items from the left side of the list
    pings_to_process = []
    for _ in range(buffer_length):
        ping_raw = redis_client.lpop("raw_gps_pings_buffer")
        if ping_raw:
            pings_to_process.append(json.loads(ping_raw.decode('utf-8')))

    if not pings_to_process:
        return "No clear data found in buffer."

    # 3. Parse data structures into memory-efficient Django Model instances
    location_instances = []
    for ping in pings_to_process:
        try:
            recorded_at = parse_datetime(ping.get('timestamp', '')) or timezone.now()
            if timezone.is_naive(recorded_at):
                recorded_at = timezone.make_aware(recorded_at)

            location_instances.append(
                WorkerLocation(
                    worker_id=ping['worker_id'],
                    lat=ping['latitude'],
                    lng=ping['longitude'],
                    timestamp=recorded_at,
                )
            )
        except KeyError:
            # Skip malformed data entries gracefully
            continue

    # 4. Perform a high-efficiency SQL Bulk Insert operation
    if location_instances:
        # bulk_create combines hundreds of individual inserts into a single database hit
        WorkerLocation.objects.bulk_create(location_instances, batch_size=500)
        
    return f"Successfully flushed {len(location_instances)} tracking points to PostgreSQL."
